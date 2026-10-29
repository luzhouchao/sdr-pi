#!/usr/bin/env python3
"""Execute a registered RX-only complete/cancel/disconnect stream validation."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import rml2018a_campaign as c
from rml2018a_stream_frames import read_frame


def run(root):
    c.require(root.resolve() == root and root.parent == Path('/var/tmp/sdrharness-dev'), 'validation root')
    p = json.loads((root/'rx-validation-plan.json').read_text())
    binary = root/'cargo/debug/sdr-agent'
    c.require(c.file_hash(binary) == p['candidate_controller_sha256'] and p['maximum_new_tx_seconds'] == 0 and
              [(v['name'],v['samples'],v['maximum_bytes']) for v in p['cases']] ==
              [('complete',1048576,4194304),('cancel',8388608,33554432),('disconnect',8388608,33554432)], 'registered RX-only plan')
    spec = importlib.util.spec_from_file_location('stream_bg', Path(__file__).with_name('validate-p201-termination-background.py'))
    bg = importlib.util.module_from_spec(spec); spec.loader.exec_module(bg)
    baseline = json.loads((root/'before-deploy.json').read_text())
    reports = []
    def abort(sig, frame): raise RuntimeError(f'validation signal {sig}')
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM): signal.signal(sig, abort)
    signal.alarm(60)
    try:
        for ordinal, case in enumerate(p['cases']):
            bg.idle(); bg.restoration(baseline['radio'])
            dest = root/('rx-'+case['name']); dest.mkdir(mode=0o700)
            generation = p['generation_base']+ordinal
            plan = dict(session_generation=generation,sample_count=case['samples'],max_bytes=case['maximum_bytes'],
                        timeout_ms=10000,storage_directory=str(dest),reserve_bytes=256*1024**2)
            c.save(dest/'plan.json',plan)
            audit = dict(case=case,generation=generation,status='failed',bytes_received=0,events=0,started_ns=time.time_ns())
            child = None; requested = False
            try:
                with (dest/'controller.log').open('xb') as log, (dest/'raw.sigmf-data').open('xb') as raw, (dest/'events.jsonl').open('x') as events:
                    child = subprocess.Popen([str(binary),'--mode','stream-rx','--sdrd','192.168.1.10:43110',
                        '--request',str(dest/'plan.json')], stdout=subprocess.PIPE,stderr=log)
                    audit['pid'] = child.pid
                    while True:
                        try: header, data = read_frame(child.stdout)
                        except EOFError:
                            c.require(case['name']=='disconnect' and requested,'unexpected stream EOF'); break
                        c.require(header['generation']==generation,'stream generation')
                        record = dict(header,host_received_ns=time.time_ns(),host_mono_ns=time.monotonic_ns())
                        events.write(json.dumps(record)+'\n'); audit['events'] += 1
                        if header['event']=='rx_chunk':
                            c.require(header['sample_offset']*4 == audit['bytes_received'],'stream byte continuity')
                            raw.write(data); audit['bytes_received'] += len(data)
                            c.require(audit['bytes_received']<=case['maximum_bytes'],'stream total bound')
                            if not requested and case['name']!='complete':
                                requested = True; audit['stop_ns'] = time.time_ns()
                                if case['name']=='disconnect': child.terminate()
                                else:
                                    cancel = subprocess.run([str(binary),'--mode','cancel','--sdrd','192.168.1.10:43110',
                                        '--session-generation',str(generation)],capture_output=True,text=True,timeout=5)
                                    audit['cancel'] = dict(exit=cancel.returncode,stdout=cancel.stdout,stderr=cancel.stderr)
                                    c.require(cancel.returncode==0,'dedicated cancellation')
                        if header['event']=='rx_end': audit['end'] = header; break
                    raw.flush(); os.fsync(raw.fileno()); events.flush(); os.fsync(events.fileno())
                    audit['exit_code'] = child.wait(timeout=10)
                if case['name']=='complete':
                    c.require(audit['exit_code']==0 and audit['bytes_received']==case['maximum_bytes'] and
                              audit['end']['status']=='ok' and audit['end']['restored'],'complete stream')
                elif case['name']=='cancel':
                    c.require(audit['exit_code']!=0 and audit['end']['status']=='error' and audit['end']['restored'], 'cancelled/restored stream')
                bg.restoration(baseline['radio']); bg.idle()
                audit.update(status='verified',restored=True,finished_ns=time.time_ns(),raw_sha256=c.file_hash(dest/'raw.sigmf-data'))
                c.save(dest/'raw.sigmf-meta',{'global':{'core:datatype':'ci16_le','core:version':'1.2.5','core:sample_rate':2100000,
                    'core:description':'RX-only continuous transport validation; host timestamps in events.jsonl, no ADC timestamp'},
                    'captures':[{'core:sample_start':0,'core:frequency':2455000000}],'annotations':[]})
            except BaseException as error:
                audit['error'] = f'{type(error).__name__}: {error}'; raise
            finally:
                if child is not None and child.poll() is None:
                    child.terminate()
                    try: child.wait(timeout=10)
                    except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=5)
                c.save(dest/'audit.json',audit)
            reports.append(audit); print(json.dumps(audit),flush=True)
    finally:
        signal.alarm(0); c.save(root/'rx-validation.json',dict(cases=reports))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    run(parser.parse_args().root)
