#!/usr/bin/env python3
"""Ask the configured real model for a monitor plan; no SDR execution or credential copies."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

REPO=Path(__file__).resolve().parents[3]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--controller',type=Path,required=True)
    args=parser.parse_args()
    root=args.root.resolve()
    assert root==args.root and root.parent==Path('/var/tmp/sdrharness-dev') and not root.exists()
    root.mkdir(mode=0o700)
    (root/'durable').mkdir(mode=0o700)
    socket_root=Path(f'/run/user/{os.getuid()}/sdr-agent')
    socket_root.mkdir(mode=0o700,parents=True,exist_ok=True)
    planner=socket_root/f'monitor-real-{os.getpid()}-p.sock'
    session=socket_root/f'monitor-real-{os.getpid()}-s.sock'
    assert not planner.exists() and not session.exists()
    env={**os.environ,'SDR_DURABLE_STATE_DIR':str(root/'durable'),'TMPDIR':str(root),
         'SDR_PLANNER_BASE_URL':'http://127.0.0.1:1/v1','SDR_PLANNER_API_KEY':'',
         'SDR_PLANNER_API_KEY_FILE':'','SDR_PLANNER_PROVIDER_CONFIG':'/var/lib/sdrharness/web-console/provider.json',
         'SDR_PLANNER_SOCKET':str(planner),'SDR_SESSION_SOCKET':str(session),
         'SDR_PLANNER_WEB_SEARCH_URL':'','SDR_PLANNER_TIMEOUT_MS':'90000'}
    child=subprocess.Popen(['/home/jetson/.local/bin/node',str(REPO/'src/agent/planner-worker/src/main.mjs')],
                           env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if planner.exists():break
            if child.poll() is not None:raise RuntimeError('isolated Planner exited')
            time.sleep(.1)
        else:raise RuntimeError('Planner startup timeout')
        request=json.loads((REPO/'deploy/agx/config/request.json').read_text())
        request['instruction']='在2455到2456 MHz监测两轮，每轮结束等待1秒，谱峰高于噪声15 dB时网页告警。总预算最多2个动作、90秒和65536字节。'
        request['observation']['health'].update(sdr_online=True,can_retune=True,can_capture_iq=True)
        result=subprocess.run([str(args.controller),'--mode','plan','--socket',str(planner),'--timeout-ms','110000'],
                              input=json.dumps(request),text=True,capture_output=True,timeout=115)
        if result.returncode:raise RuntimeError('real Planner did not produce a validated plan: '+result.stderr[:300])
        action=json.loads(result.stdout)['action']
        print(json.dumps({'kind':action['kind'],'target_sweeps':action.get('target_sweeps'),
                          'monitor_threshold_db':action.get('monitor_threshold_db'),
                          'monitor_interval_secs':action.get('monitor_interval_secs'),
                          'max_steps':action.get('max_steps'),'max_seconds':action.get('max_seconds'),
                          'max_iq_bytes':action.get('max_iq_bytes'),'rf':False},ensure_ascii=False),flush=True)
        assert action['kind']=='start_task' and action['target_sweeps']==2
        assert action['monitor_threshold_db']==15 and action['monitor_interval_secs']==1
        assert action['max_steps']==2 and action['max_seconds']<=90 and action['max_iq_bytes']<=65536
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGTERM)
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        for path in (planner,session):
            if path.exists():path.unlink()


if __name__=='__main__':main()
