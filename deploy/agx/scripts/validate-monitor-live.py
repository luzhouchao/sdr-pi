#!/usr/bin/env python3
"""Two-sweep RX-only isolated monitoring acceptance; uses a deterministic model upstream."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[3]
SSH = ['sshpass','-f','/home/jetson/.config/sdrharness/p201-root.password','ssh',
       '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile=/home/jetson/.ssh/known_hosts',
       '-o','ConnectTimeout=5','root@192.168.1.10']
STATE = '''for p in /sys/bus/iio/devices/iio:device0/out_altvoltage0_RX_LO_frequency /sys/bus/iio/devices/iio:device0/in_voltage_sampling_frequency /sys/bus/iio/devices/iio:device0/in_voltage_rf_bandwidth /sys/bus/iio/devices/iio:device0/in_voltage0_gain_control_mode /sys/bus/iio/devices/iio:device0/in_voltage0_hardwaregain /sys/bus/iio/devices/iio:device0/in_voltage0_rf_port_select /sys/bus/iio/devices/iio:device0/in_voltage1_gain_control_mode /sys/bus/iio/devices/iio:device0/in_voltage1_hardwaregain /sys/bus/iio/devices/iio:device0/in_voltage1_rf_port_select /sys/bus/iio/devices/iio:device*/scan_elements/*_en /sys/bus/iio/devices/iio:device*/buffer/enable; do if test -f "$p"; then echo "$p"; cat "$p"; fi; done'''


def remote(command):
    return subprocess.run([*SSH,command],check=True,text=True,capture_output=True,timeout=8).stdout


def radio_state():
    lines=remote(STATE).splitlines()
    if len(lines)%2: raise RuntimeError('incomplete P201 snapshot')
    return dict(zip(lines[::2],lines[1::2]))


def idle():
    connections=remote("netstat -nt 2>/dev/null | grep -E ':(43110|30431).*ESTABLISHED' || true")
    if connections.strip(): raise RuntimeError('P201 has an active control or IIO connection')
    pids=remote('pidof sdrd').split()
    if len(pids)!=1: raise RuntimeError('expected exactly one sdrd')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--controller',type=Path,required=True)
    parser.add_argument('--web',type=Path,required=True)
    args=parser.parse_args()
    root=args.root.resolve()
    assert root==args.root and root.parent==Path('/var/tmp/sdrharness-dev') and not root.exists()
    assert args.controller.is_file() and args.web.is_file()
    assert subprocess.run(['stat','-c','%a','/home/jetson/.config/sdrharness/p201-root.password'],capture_output=True,text=True,check=True).stdout.strip()=='600'
    if subprocess.run(['systemctl','is-active','--quiet','sdrharness-web.service']).returncode:
        raise RuntimeError('production Web must initially be running')
    idle(); baseline=radio_state()
    if len(baseline)<19 or any(v!='0' for k,v in baseline.items() if k.endswith('/enable') or k.endswith('_en')):
        raise RuntimeError('P201 baseline incomplete or RX buffer busy')
    root.mkdir(mode=0o700)
    free=shutil.disk_usage(root).free
    if free<128*1024*1024: raise RuntimeError('insufficient AGX free space')
    socket_root=Path(f'/run/user/{os.getuid()}/sdr-agent')
    socket_root.mkdir(mode=0o700,parents=True,exist_ok=True)
    socket_prefix=f'monitor-live-{os.getpid()}'
    planner_socket=socket_root/f'{socket_prefix}-p.sock';session_socket=socket_root/f'{socket_prefix}-s.sock'
    if planner_socket.exists() or session_socket.exists(): raise RuntimeError('test socket already exists')
    plan={'frequency_hz':[2455000000,2456000000], 'sample_rate_hz':10000000,'bandwidth_hz':10000000,
          'gain_db':20,'settle_ms':20,'points_per_sweep':2,'samples_per_point':4096,'point_timeout_ms':250,
          'sweeps':2,'max_steps':2,'max_duration_seconds':90,'max_iq_bytes':65536,'expected_iq_bytes':65536,
          'interval_after_sweep_seconds':1,'script_deadline_seconds':120,'free_bytes':free,
          'agx_capture_root':str(root/'captures'),'p201_paths':'recorded before task submission',
          'stop':'POST /api/sessions/monitor-live/command with /stop; terminate isolated Web on timeout',
          'upstream':'deterministic test model; no transmit'}
    (root/'plan.json').write_text(json.dumps(plan,indent=2))
    task={'action':'start_task','mission':'在2455–2456MHz监测两轮，间隔至少一秒，谱峰高于噪声15dB时网页告警',
          'target_sweeps':2,'max_steps':2,'max_seconds':90,'max_iq_bytes':65536,
          'min_freq_hz':2455000000,'max_freq_hz':2456000000,'monitor_threshold_db':15,'monitor_interval_secs':1}
    scan={'action':'survey_band','start_hz':2455000000,'stop_hz':2456000000,'step_hz':1000000,
          'sample_rate_hz':10000000,'rf_bandwidth_hz':10000000,'dwell_ms':20}
    actions=[task,scan,scan]
    class Upstream(BaseHTTPRequestHandler):
        calls=0
        def log_message(self,*_): pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length','0')))
            index=Upstream.calls;Upstream.calls+=1
            action=actions[index] if index<len(actions) else {'action':'hold','reason':'test limit reached'}
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            def event(value): self.wfile.write(('data: '+json.dumps(value)+'\n\n').encode())
            event({'id':'chat_test','object':'chat.completion.chunk','model':'test-model','choices':[{'index':0,'delta':{'role':'assistant','tool_calls':[{'index':0,'id':'call_test','type':'function','function':{'name':'submit_plan','arguments':json.dumps(action)}}]},'finish_reason':None}]})
            event({'id':'chat_test','object':'chat.completion.chunk','model':'test-model','choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}]})
            self.wfile.write(b'data: [DONE]\n\n')
    upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
    threading.Thread(target=upstream.serve_forever,daemon=True).start()
    with socket.socket() as s: s.bind(('127.0.0.1',0));web_port=s.getsockname()[1]
    url=f'http://127.0.0.1:{web_port}'
    req=json.loads((REPO/'deploy/agx/config/request.json').read_text())
    req['limits'].update(min_freq_hz=2455000000,max_freq_hz=2456000000,max_span_hz=1000000,max_bandwidth_hz=10000000,max_dwell_ms=20,max_iq_samples=8192,max_iq_bytes=32768,auto_approve_iq_bytes=32768)
    (root/'request.json').write_text(json.dumps(req))
    state={'controller_generation':0,'active_session_id':'monitor-live','sessions':[{'id':'monitor-live','title':'隔离监测验收',
           'created_at_ms':1,'last_used_at_ms':1,'generation':1,'status':'stored','compacted_summary':'',
           'summary_pending':False,'events_since_compaction':0,'initial_survey_status':'skipped','save_iq':True,'events':[]}]}
    (root/'state.json').write_text(json.dumps(state))
    def api(path,body=None):
        data=None if body is None else json.dumps(body).encode()
        with urlopen(Request(url+path,data=data,headers={'Content-Type':'application/json'}),timeout=5) as response:return json.load(response)
    planner=None;web=None;stopped_production=False;requested_stop=False;p201_paths=[]
    old_handler=signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(RuntimeError('validation terminated')))
    try:
        subprocess.run(['sudo','-n','systemctl','stop','sdrharness-web.service'],check=True,timeout=55)
        stopped_production=True
        idle()
        if radio_state()!=baseline: raise RuntimeError('P201 changed before test')
        env={**os.environ,'TMPDIR':str(root),'SDR_DURABLE_STATE_DIR':str(root/'durable'),
             'SDR_PLANNER_BASE_URL':f'http://127.0.0.1:{upstream.server_port}/v1','SDR_PLANNER_API':'openai-completions',
             'SDR_PLANNER_API_KEY':'validation-only','SDR_PLANNER_API_KEY_FILE':'','SDR_PLANNER_PROVIDER':'sdk-test',
             'SDR_PLANNER_MODEL':'test-model','SDR_PLANNER_PROVIDER_CONFIG':str(root/'absent-provider'),
             'SDR_PLANNER_WEB_SEARCH_URL':'','SDR_PLANNER_SOCKET':str(planner_socket),'SDR_SESSION_SOCKET':str(session_socket)}
        (root/'durable').mkdir(mode=0o700)
        planner=subprocess.Popen(['/home/jetson/.local/bin/node',str(REPO/'src/agent/planner-worker/src/main.mjs')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            if session_socket.exists(): break
            if planner.poll() is not None: raise RuntimeError('isolated Planner exited')
            time.sleep(.1)
        else: raise RuntimeError('isolated Planner socket timeout')
        env.update(SDR_WEB_LISTEN_HOST='127.0.0.1',SDR_WEB_LISTEN_PORT=str(web_port),SDR_WEB_STATE_PATH=str(root/'state.json'),
            SDR_WEB_AGENT_BINARY=str(args.controller),SDR_WEB_REQUEST_PATH=str(root/'request.json'),SDR_WEB_PROVIDER_CONFIG_PATH=str(root/'absent-web-provider'),
            SDR_WEB_RESULT_DB_PATH=str(root/'results.sqlite3'),SDR_WEB_CAPTURE_ROOT=str(root/'captures'),SDR_WEB_CORPUS_ROOT=str(root/'corpus'),
            SDR_WEB_SDRD_ADDRESS='192.168.1.10:43110',SDR_WEB_SESSION_SOCKET=str(session_socket),SDR_WEB_PLANNER_SOCKET=str(planner_socket),
            SDR_DURABLE_CONTROLLER_DIR=str(root/'ledger'))
        (root/'ledger').mkdir(mode=0o700)
        web=subprocess.Popen([str(args.web)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(150):
            try:
                current=api('/api/state');session=current['sessions'][0]
                if session['status']=='connected' and current['controller_generation']>0: break
            except (URLError,TimeoutError): pass
            if web.poll() is not None: raise RuntimeError('isolated Web exited')
            time.sleep(.1)
        else: raise RuntimeError('isolated Controller did not connect')
        generation=current['controller_generation']+1
        p201_paths=[f'/tmp/sdr-agent-dev/agx-sweep-{generation}-{i}' for i in range(2)]
        if remote(' && '.join('test ! -e '+p for p in p201_paths)+' && echo clean').strip()!='clean':raise RuntimeError('P201 feature paths already exist')
        plan['p201_paths']=p201_paths;plan['session_generation']=generation
        (root/'plan.json').write_text(json.dumps(plan,indent=2))
        print(json.dumps(plan,ensure_ascii=False),flush=True)
        api('/api/sessions/monitor-live/command',{'command':'在2455到2456 MHz监测两轮，间隔一秒，谱峰高于噪声15 dB时网页告警。'})
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            current=api('/api/state');session=current['sessions'][0];results=api('/api/results')
            if len(results)==2 and any('任务目标已完成' in e.get('text','') for e in session['events']):break
            if any('sdr_agent_error=' in e.get('text','') for e in session['events']):
                raise RuntimeError('isolated Controller reported an error before completion')
            if web.poll() is not None or planner.poll() is not None:raise RuntimeError('isolated process exited')
            time.sleep(.2)
        else:raise RuntimeError('monitor task deadline expired')
        assert session.get('monitor_threshold_db')==15 and len(results)==2 and Upstream.calls==3
        assert all(r['point_count']==2 and r['iq_bytes']==32768 for r in results)
        assert abs(results[0]['created_at_ms']-results[1]['created_at_ms'])>=1000
        report=api('/api/monitoring?session_id=monitor-live')
        assert report['threshold_db']==15 and len(report['groups'])==2
        assert all(g['observations']==2 for g in report['groups'])
        detail=api(f"/api/results/{results[0]['id']}/spectrogram/0")
        assert detail['center_hz']==2455000000 and detail['samples']==4096 and len(detail['grid_db'])<=64
        api('/api/sessions/monitor-live/command',{'command':'/stop'});requested_stop=True
        print(json.dumps({'status':'pass','results':len(results),'points':4,'iq_bytes':65536,'groups':len(report['groups']),
                          'alerts':len(report['alerts']),'threshold_db':15,'fake_model':True,'spectrogram':True}),flush=True)
    finally:
        signal.signal(signal.SIGTERM,old_handler)
        if web and web.poll() is None:
            if not requested_stop:
                try: api('/api/sessions/monitor-live/command',{'command':'/stop'})
                except Exception: pass
            web.send_signal(signal.SIGTERM)
            try: web.wait(timeout=20)
            except subprocess.TimeoutExpired: web.kill();web.wait(timeout=5)
        if planner and planner.poll() is None:
            planner.send_signal(signal.SIGTERM)
            try: planner.wait(timeout=10)
            except subprocess.TimeoutExpired: planner.kill();planner.wait(timeout=5)
        upstream.shutdown();upstream.server_close()
        for path in (planner_socket,session_socket):
            if path.exists(): path.unlink()
        try:
            for _ in range(30):
                try:
                    idle()
                    if radio_state()==baseline: break
                except Exception: pass
                time.sleep(.2)
            else: raise RuntimeError('P201 state did not restore')
            if p201_paths and remote(' && '.join('test ! -e '+p for p in p201_paths)+' && echo clean').strip()!='clean':
                raise RuntimeError('P201 temporary path remains')
            print(json.dumps({'p201_restored':True,'radio_fields':len(baseline),'temporary_paths_absent':True}),flush=True)
        finally:
            if stopped_production:
                subprocess.run(['sudo','-n','systemctl','start','sdrharness-web.service'],check=True,timeout=55)


if __name__=='__main__':main()
