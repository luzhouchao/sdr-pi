#!/usr/bin/env python3
"""S6b private Web/Runner/RX/Worker/Spark/browser acceptance; no production admission."""
if not __debug__:
    raise RuntimeError('optimized Python disables validation')
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import sqlite3
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[3]
SCRIPTS=Path(__file__).parent
spec=importlib.util.spec_from_file_location('s5_validation',SCRIPTS/'validate-runner-recognition.py')
s5=importlib.util.module_from_spec(spec);spec.loader.exec_module(s5)


async def validate(root):
    assert root.resolve()==root and root.parent==Path('/var/tmp/sdrharness-dev')
    assert root.name=='s6b-906a'
    assert not (root/'live-summary.json').exists()
    env={**os.environ,'TMPDIR':str(root/'tmp'),'PYTHONDONTWRITEBYTECODE':'1',
         'TRITON_CACHE_DIR':str(root/'triton'),'CUDA_CACHE_PATH':str(root/'cuda-cache')}
    procs=[];workers=set();paths=set();cases=[]
    generation=int(time.time()*1000)
    gateway_port,backend_port,web_port=s5.port(),s5.port(),s5.port()
    assert len({gateway_port,backend_port,web_port})==3
    runtime=root/'mamba';gate=root/'gate';base=f'http://127.0.0.1:{web_port}'
    controls=Path(f'/run/user/{os.getuid()}/sdrharness');controls.mkdir(mode=0o700,exist_ok=True)
    node_socket=controls/f'{root.name}-planner.sock';session_socket=controls/f'{root.name}-session.sock'
    assert not node_socket.exists() and not session_socket.exists()
    async def launch(name,args,environment=env):
        with (root/f'{name}.log').open('w') as output:
            proc=await asyncio.create_subprocess_exec(*map(str,args),env=environment,stdout=output,stderr=asyncio.subprocess.STDOUT)
        procs.append(proc);return proc
    async def ssh(command):
        p=await asyncio.create_subprocess_exec(*s5.rf.SSH,command,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:out,err=await asyncio.wait_for(p.communicate(),8)
        finally:
            if p.returncode is None:p.kill();await p.wait()
        assert p.returncode==0,err.decode()
        return out.decode()
    def http(route,method='GET',data=None):
        body=None if data is None else json.dumps(data).encode()
        request=urllib.request.Request(base+route,data=body,method=method,headers={'Content-Type':'application/json'})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=3) as response:
            raw=response.read(512*1024+1);assert len(raw)<=512*1024
            return json.loads(raw)
    async def health():return await s5.sup.exchange(runtime/'control.sock',dict(schema_version=1,operation='health'),1,s5.sup.FRAME)
    async def ready(kind):
        end=time.monotonic()+150
        while time.monotonic()<end:
            try:
                if kind=='mamba':
                    h=await health()
                    if h['fault']:raise RuntimeError(h['fault'])
                    if h['ready']:workers.add(h['worker_pid']);return h
                else:
                    status,h=await s5.gw.backend_http(gateway_port,key,'/health')
                    if status==200 and h['ready']:workers.add(h['worker_pid']);return h
            except (OSError,asyncio.TimeoutError):pass
            await asyncio.sleep(.05)
        raise RuntimeError(kind+' startup timeout')
    async def stop(proc):
        if proc.returncode is None:
            proc.terminate()
            try:await asyncio.wait_for(proc.wait(),45)
            except asyncio.TimeoutError:proc.kill();await proc.wait();raise
        assert proc.returncode==0,(proc.pid,proc.returncode)
    before=await ssh(s5.rf.STATE_COMMAND)
    s5.require_idle_radio(before,await ssh('netstat -nt 2>/dev/null; true'))
    daemon=(await ssh('pidof sdrd')).strip();assert len(daemon.split())==1
    audit=dict(schema_version=1,status='failed',generation=generation,maximum_rx_bytes=81920,
               initial_inspection_samples=4096,max_recognition_executions=2,maximum_model_spool_bytes=32768,
               free_bytes_before=shutil.disk_usage(root).free,radio_before=before,sdrd_pid=daemon,
               recognizer_available=False,locked_test_read=False,training=False,transmission=False,feature_directory=str(root))
    assert audit['free_bytes_before']>8*1024*1024
    print(json.dumps({k:v for k,v in audit.items() if k!='radio_before'}),flush=True)
    key=secrets.token_hex(32);key_path=root/'gateway-key';key_path.write_text(key);key_path.chmod(0o600)
    provider=dict(schema_version=1,api='openai-completions',base_url=f'http://127.0.0.1:{gateway_port}/v1',provider='spark-local',model='spark-x2.5-4b',api_key=key,context_window=32768,compression_threshold_percent=90)
    node_provider=root/'node-provider.json';node_provider.write_text(json.dumps(provider));node_provider.chmod(0o600)
    provider['initial_survey']=dict(mode='disabled',start_hz=70000000,stop_hz=6000000000,step_hz=8000000,dwell_ms=5,gain_db=50)
    provider['result_storage']=dict(save_iq=False)
    web_provider=root/'web-provider.json';web_provider.write_text(json.dumps(provider));web_provider.chmod(0o600)
    binary=root/'target/debug/sdr-agent';console=root/'target/debug/sdr-agent';web_binary=root/'target/debug/sdr-agent-web-console'
    webenv={**env,'SDR_WEB_LISTEN_HOST':'127.0.0.1','SDR_WEB_LISTEN_PORT':str(web_port),
        'SDR_WEB_STATE_PATH':str(root/'state.json'),'SDR_WEB_AGENT_BINARY':str(console),'SDR_WEB_REQUEST_PATH':str(root/'request.json'),
        'SDR_WEB_SESSION_SOCKET':str(session_socket),'SDR_WEB_SDRD_ADDRESS':'192.168.1.10:43110','SDR_WEB_PROVIDER_CONFIG_PATH':str(web_provider),
        'SDR_WEB_RESULT_DB_PATH':str(root/'results.sqlite3'),'SDR_WEB_CAPTURE_ROOT':str(root/'captures'),'SDR_WEB_CORPUS_ROOT':str(root/'corpus'),
        'SDR_WEB_ENGINEERING_RECOGNITION_ROOT':str(runtime),'SDR_WEB_RECOGNITION_AUDIT':str(root/'recognition-audit.jsonl')}
    async def start_web(tag):
        proc=await launch(tag,[web_binary],webenv)
        for _ in range(100):
            assert proc.returncode is None
            try:http('/api/state');return proc
            except OSError:await asyncio.sleep(.05)
        raise RuntimeError('Web startup timeout')
    try:
        print('starting private Worker, shared Spark gate and Node',flush=True)
        await launch('mamba',[sys.executable,SCRIPTS/'amc-worker-supervisor.py','--runtime-root',runtime,'--gpu-lease-root',gate,'--lifetime-seconds','1200','--max-batches','4','--max-restarts','3'])
        await launch('spark',[sys.executable,SCRIPTS/'spark-gpu-gateway.py','--runtime-root',root/'spark','--gpu-lease-root',gate,'--port',gateway_port,'--backend-port',backend_port,'--api-key-file',key_path,'--lifetime-seconds','1200','--max-requests','12'])
        nodeenv={**env,'SDR_PLANNER_BASE_URL':f'http://127.0.0.1:{gateway_port}/v1','SDR_PLANNER_API_KEY_FILE':str(key_path),'SDR_PLANNER_PROVIDER_CONFIG':str(node_provider),'SDR_PLANNER_PROVIDER':'spark-local','SDR_PLANNER_MODEL':'spark-x2.5-4b','SDR_PLANNER_SOCKET':str(node_socket),'SDR_SESSION_SOCKET':str(session_socket),'SDR_PLANNER_MAX_TOKENS':'512','SDR_PLANNER_TIMEOUT_MS':'60000','SDR_PLANNER_WEB_SEARCH_URL':''}
        await launch('node',['node',ROOT/'raspberry-pi/sdr-agent/planner-worker/src/main.mjs'],nodeenv)
        await asyncio.gather(ready('mamba'),ready('spark'))
        seed=dict(sweep_id=f's6b-seed-{generation}',session_generation=generation,frequencies=dict(kind='centers',centers_hz=[433920000]),sample_rate_hz=2100000,rf_bandwidth_hz=1500000,gain_db=50,settle_ms=100,frame_samples=4096,aggregate_frames=1,point_timeout_ms=1000,detection_threshold_db=6.)
        paths.add(f'/tmp/sdr-agent-dev/agx-sweep-{generation}-0')
        print(json.dumps(dict(seed_plan=seed,max_bytes=16384,stop_generation=generation,p201_directory=next(iter(paths)))),flush=True)
        proc=await asyncio.create_subprocess_exec(str(binary),'--mode','sweep','--sdrd','192.168.1.10:43110',env=env,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        procs.append(proc);out,err=await asyncio.wait_for(proc.communicate(json.dumps(seed).encode()),15)
        assert proc.returncode==0,err.decode()
        seed_report=json.loads(out);audit['seed_report']=seed_report;point=seed_report['points'][0]['spectral']
        request=dict(protocol_version=1,request_id=1,session_generation=generation+1,instruction='bounded S6b browser validation',state='idle',observation=dict(age_ms=0,health=dict(sdr_online=True,can_retune=True,can_capture_iq=True,recognizer_available=False,dropped_observations=0),candidates=[dict(id='s6b-live-candidate',center_hz=point['estimated_center_hz'],bandwidth_hz=point['occupied_bandwidth_hz'],peak_dbfs=point['peak_power_dbfs'],snr_db=point['measured_snr_db'],age_ms=0)]),limits=dict(min_freq_hz=70000000,max_freq_hz=6000000000,max_span_hz=5930000000,max_bandwidth_hz=2100000,max_dwell_ms=1000,max_iq_samples=4096,max_iq_bytes=32768,auto_approve_iq_bytes=32768,max_observation_age_ms=60000))
        (root/'request.json').write_text(json.dumps(request))
        web=await start_web('web-0');assert http('/api/recognition-results')==[]
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch(headless=True,env=env)
            try:
                page=await browser.new_page(viewport={'width':1440,'height':1000});errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                await page.goto(base,wait_until='domcontentloaded')
                await page.wait_for_function("view.state !== null && document.querySelector('.connection').classList.contains('online')")
                await page.locator('#new-session').click()
                await page.wait_for_function("view.active?.events.some(e=>e.text.includes('SDR Agent 已连接'))")
                session_id=http('/api/state')['active_session_id'];audit['application_session_id']=session_id
                async def send(command):
                    await page.locator('#command-input').fill(command)
                    await page.locator('#command-form button').click()
                async def wait_result(status,count):
                    await page.wait_for_function('(status)=>view.active?.observation?.recognition?.status===status',arg=status,timeout=45000)
                    await page.wait_for_function('view.active?.recognition_archive_id != null',timeout=5000)
                    records=http('/api/recognition-results');assert len(records)==count
                    current=next(r for r in records if r['id']==http('/api/state')['sessions'][0]['recognition_archive_id'])
                    assert current['origin']=='engineering_rx' and not current['production_result'] and not current['iq_retained']
                    await page.wait_for_function("(status)=>view.active?.model_input?.observation?.recognition?.status===status",arg=status,timeout=15000)
                    if status=='unavailable':
                        await page.wait_for_function("view.active?.events.some(e=>e.kind==='plan' && e.text.includes('保持'))",timeout=65000)
                    else:
                        await page.wait_for_function("view.active?.events.some(e=>(e.kind==='plan' && e.text.includes('保持') && e.timestamp_ms>=view.active.observation.recognition.observed_at_unix_ms) || (e.text.includes('request=4') && e.text.includes('没有提交下一步计划')))",timeout=65000)
                    current_session=next(s for s in http('/api/state')['sessions'] if s['id']==session_id)
                    audit.setdefault('feedback_outcomes',[]).append(dict(status=status,model_input=current_session['model_input'],events=[e for e in current_session['events'] if e['timestamp_ms']>=current['observation']['observed_at_unix_ms'] and (e['kind'] in ('plan','qwen') or '没有提交下一步计划' in e['text'])]))
                    return current
                print('browser approval -> real unavailable -> automatic Spark -> exact archive',flush=True)
                await send('/recognize s6b-live-candidate')
                await page.wait_for_function("view.active?.events.some(e=>e.text.includes('工程识别等待人工批准'))")
                assert http('/api/recognition-results')==[]
                await send('/approve');unavailable=await wait_result('unavailable',1)
                state=http('/api/state');session=next(s for s in state['sessions'] if s['id']==session_id)
                feedback=session['model_input'];assert feedback['observation']['recognition']==unavailable['observation']
                assert not s5.planner_has_internal_fields(feedback)
                audit['real_feedback']=feedback
                await page.locator('#current-recognition-open').click()
                await page.locator(f"#recognition-content[data-record-id='{unavailable['id']}']:visible").wait_for()
                assert '实收实验' in await page.locator('#recognition-origin').inner_text()
                assert '不是独立标签' in await page.locator('#recognition-meaning').inner_text()
                await page.screenshot(path=str(root/'real-unavailable.png'),full_page=True)
                cases.append('browser_approval_actual_rx_archive_and_automatic_feedback')
                await page.locator('#results-back').click();await asyncio.sleep(.3)
                print('browser real Worker failure -> error archive',flush=True)
                h=await ready('mamba');os.kill(h['worker_pid'],signal.SIGSTOP)
                await send('/recognize s6b-live-candidate');await asyncio.sleep(.3);await send('/approve')
                for _ in range(2500):
                    active=(await health())['active']
                    if active is not None:break
                    await asyncio.sleep(.01)
                assert active is not None
                os.kill(h['worker_pid'],signal.SIGKILL)
                error=await wait_result('error',2);await ready('mamba')
                audit['real_error']=error
                await page.locator('#current-recognition-open').click()
                await page.locator(f"#recognition-content[data-record-id='{error['id']}']:visible").wait_for()
                await page.screenshot(path=str(root/'real-error.png'),full_page=True)
                cases.append('actual_worker_failure_error_display')
                for name in ['Classified','Rejected']:
                    http('/api/recognition-results','POST',json.loads((root/f'{name}.json').read_text()))
                await page.locator('#recognition-refresh').click()
                for record in http('/api/recognition-results'):
                    await page.locator('#recognition-list button').filter(has_text=record['observation']['candidate_id']).filter(has_text={'unavailable':'不可用','error':'错误','classified':'已分类','rejected':'已拒识'}[record['observation']['status']]).click()
                    await page.wait_for_function('(status)=>document.querySelector("#recognition-status").textContent.includes(status)',arg=record['observation']['status'])
                    if record['origin']=='synthetic_fixture':assert '合成演示' in await page.locator('#recognition-origin').inner_text()
                await page.set_viewport_size({'width':390,'height':844})
                await page.screenshot(path=str(root/'four-states-mobile.png'),full_page=True)
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                cases.append('four_states_with_explicit_synthetic_positive_decisions')
                snapshot=http('/api/recognition-results')
                await stop(web);web=await start_web('web-1')
                assert http('/api/recognition-results')==snapshot
                await page.reload(wait_until='domcontentloaded')
                await page.wait_for_function("view.active?.events.filter(e=>e.text.includes('SDR Agent 已连接')).length>=2")
                # New prompt after restart must not inject or re-date the old recognition.
                await page.evaluate('showConsole()');await send('只返回 hold，不进行采集。')
                await page.wait_for_function('view.active?.model_input && !view.active.model_input.observation.recognition',timeout=65000)
                assert http('/api/recognition-results')==snapshot
                resumed=next(s for s in http('/api/state')['sessions'] if s['id']==session_id)['model_input']
                assert resumed['session_generation']>feedback['session_generation']
                assert not s5.planner_has_internal_fields(resumed)
                assert '/var/tmp/sdrharness-dev/' not in resumed['instruction']
                audit['resumed_request']=resumed
                cases.append('restart_preserves_exact_records_without_replaying_context')
                await page.locator('#sweep-results-entry').click();await page.locator('#archive-recognitions').click()
                page.once('dialog',lambda dialog:asyncio.create_task(dialog.dismiss()))
                await page.locator('#recognition-delete').click();assert len(http('/api/recognition-results'))==4
                for _ in range(4):
                    page.once('dialog',lambda dialog:asyncio.create_task(dialog.accept()))
                    await page.locator('#recognition-delete').click()
                    await asyncio.sleep(.15)
                assert http('/api/recognition-results')==[]
                await stop(web);web=await start_web('web-2')
                assert http('/api/recognition-results')==[]
                assert not errors,errors
                cases+=['browser_manual_delete_dismiss_confirm','deleted_rows_absent_after_second_restart','no_browser_errors']
            finally:await browser.close()
        assert not list((root/'captures').iterdir()) and not list((root/'corpus').iterdir())
        audit['status']='pass';audit['archive_before_delete']=snapshot
    except BaseException as error:
        audit['failure']=f'{type(error).__name__}: {error}'
        raise
    finally:
        # Web/Controller must finish joined stop before inference infrastructure exits.
        for p in reversed(procs):
            if p.returncode is None:
                p.terminate()
                try:await asyncio.wait_for(p.wait(),45)
                except asyncio.TimeoutError:p.kill();await p.wait()
        audit['cases']=cases;audit['worker_pids']=sorted(workers)
        for p in root.glob('web-*.log'):
            import re
            paths.update(re.findall(r'/tmp/sdr-agent-dev/(?:agx-sweep-\d+-\d+|agx-model-batch-\d+-\d+)',p.read_text(errors='replace')))
        # The runtime prints batch feature names without the P201 root prefix.
        if (root/'recognition-audit.jsonl').exists():
            for line in (root/'recognition-audit.jsonl').read_text().splitlines():
                event=json.loads(line)
                if event['phase']=='recognition_authorized':
                    g=event['session_generation'];q=event['request_id'];paths.add(f'/tmp/sdr-agent-dev/agx-sweep-{g}-0');paths.add(f'/tmp/sdr-agent-dev/agx-model-batch-{g}-{q}')
        audit['p201_directories']=sorted(paths);cleanup_errors=[]
        try:
            audit['radio_final']=await ssh(s5.rf.STATE_COMMAND)
            if not s5.rf.restored_state(before,audit['radio_final']):cleanup_errors.append('radio restoration mismatch')
            for path in paths:assert (await ssh(f'test ! -e {path} && echo absent')).strip()=='absent'
            assert (await ssh('pidof sdrd')).strip()==daemon
        except Exception as error:cleanup_errors.append(str(error))
        for path in [node_socket,session_socket]:
            if path.exists():
                import stat
                assert stat.S_ISSOCK(path.lstat().st_mode);path.unlink()
        audit['cleanup']={'process_exit_codes':[p.returncode for p in procs],'errors':cleanup_errors,'control_sockets_absent':True}
        if cleanup_errors:audit['status']='failed'
        (root/'live-summary.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False)+'\n')
        assert not cleanup_errors,cleanup_errors
    print('S6b actual browser closed-loop acceptance passed',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--feature-directory',type=Path,required=True)
    asyncio.run(validate(parser.parse_args().feature_directory))
