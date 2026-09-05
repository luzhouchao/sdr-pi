#!/usr/bin/env python3
"""S4a finite real Spark BF16 / RF-v1 Mamba serialization and failure validation."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
SCRIPTS=Path(__file__).parent


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


sup=module('sup',SCRIPTS/'amc-worker-supervisor.py')
gw=module('gw',SCRIPTS/'spark-gpu-gateway.py')


def unused_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


def dead(pid):
    try:return Path(f'/proc/{pid}/stat').read_text().split()[2]=='Z'
    except FileNotFoundError:return True


async def validate(feature,controller):
    assert feature.is_absolute() and feature.resolve()==feature and feature.parent==Path('/var/tmp/sdrharness-dev')
    fixture=json.loads((feature/'replay.json').read_text());data=(feature/'model.f32').read_bytes()
    assert len(data)==32768 and hashlib.sha256(data).hexdigest()==fixture['batch']['model_bytes_sha256']
    gate=feature/'gate';runtime=feature/'mamba';spark_root=feature/'spark'
    key=secrets.token_hex(32);keyfile=feature/'gateway-key.txt';keyfile.write_text(key);keyfile.chmod(0o600)
    port,backend_port=unused_port(),unused_port();assert port!=backend_port
    env={**os.environ,'TMPDIR':str(feature/'tmp'),'PYTHONDONTWRITEBYTECODE':'1','TRITON_CACHE_DIR':str(feature/'triton'),'CUDA_CACHE_PATH':str(feature/'cuda-cache')}
    processes=[];pids=set();stages=[];background=set();logfiles=[]
    def task(coro):
        result=asyncio.create_task(coro);background.add(result);return result
    async def launch(kind):
        logfile=feature/f'{kind}-{len(processes)}.log';logfiles.append(logfile)
        with logfile.open('w') as log:
            command=([sys.executable,str(SCRIPTS/'amc-worker-supervisor.py'),'--runtime-root',str(runtime),'--gpu-lease-root',str(gate),'--max-batches','24','--max-restarts','4','--lifetime-seconds','600'] if kind=='mamba' else
                     [sys.executable,str(SCRIPTS/'spark-gpu-gateway.py'),'--runtime-root',str(spark_root),'--gpu-lease-root',str(gate),'--port',str(port),'--backend-port',str(backend_port),'--api-key-file',str(keyfile),'--lifetime-seconds','600','--max-requests','24'])
            proc=await asyncio.create_subprocess_exec(*command,env=env,stdout=log,stderr=asyncio.subprocess.STDOUT)
        processes.append(proc);return proc
    async def mh():return await sup.exchange(runtime/'control.sock',dict(schema_version=1,operation='health'),1,sup.FRAME)
    async def sh():
        status,h=await asyncio.wait_for(gw.backend_http(port,key,'/health'),1);assert status==200;return h
    async def ready(which):
        deadline=time.monotonic()+190
        while time.monotonic()<deadline:
            try:
                h=await (mh() if which=='mamba' else sh())
                if h.get('fault'):raise RuntimeError(h['fault'])
                if h['ready']:
                    pids.add(h['worker_pid']);return h
            except (OSError,asyncio.TimeoutError):pass
            await asyncio.sleep(.05)
        raise RuntimeError(which+' startup timeout')
    async def held(which):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            h=await (mh() if which=='mamba' else sh())
            if h.get('gpu_held',h.get('metrics',{}).get('gpu_held',0)):return h
            await asyncio.sleep(.005)
        raise RuntimeError(which+' did not acquire')
    async def node():
        proc=await asyncio.create_subprocess_exec('node',str(ROOT/'raspberry-pi/sdr-agent/planner-worker/scripts/validate-gpu-planner.mjs'),str(port),str(keyfile),env=env,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            out,err=await asyncio.wait_for(proc.communicate(),125)
            if proc.returncode:raise RuntimeError(err.decode()[-1500:])
            return json.loads(out)
        finally:
            if proc.returncode is None:proc.kill();await proc.wait()
    async def native(generation):
        value=json.loads(json.dumps(fixture));value['batch']['session_generation']=generation;value['batch']['capture']['session_generation']=generation
        path=feature/f'replay-{generation}.json';path.write_text(json.dumps(value))
        proc=await asyncio.create_subprocess_exec(str(controller),'--mode','recognize-supervised-replay','--recognizer-supervisor-root',str(runtime),'--recognition-profile',str(sup.PROFILE),'--recognizer-spool-root',str(feature),'--repository-root',str(ROOT),'--request',str(path),env=env,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            out,err=await asyncio.wait_for(proc.communicate(),12)
            if proc.returncode:raise RuntimeError(err.decode()[-1000:])
            result=json.loads(out)['result'];assert result['observation']['status']=='unavailable'
            return dict(status='unavailable',windows=len(result['experimental_batch']['windows']))
        finally:
            if proc.returncode is None:proc.kill();await proc.wait()
    def envelope(h,rid,gen,timeout=5000):
        b=fixture['batch'];path=runtime/'incoming'/f"batch-{h['instance_id']}-{gen}-{rid}.f32"
        path.write_bytes(data);path.chmod(0o600);requests=[]
        for i in range(4):
            c={k:b[k] for k in ('profile_sha256','preprocess_sha256','source_sweep_id','source_request_id','source_session_generation','source_sequence')}
            c.update(checkpoint_sha256=sup.decode(sup.RECEIPT.read_bytes())['identity']['checkpoint_sha256'],batch_sha256=b['model_bytes_sha256'],batch_request_id=rid,capture_request_id=b['capture']['sdrd_request_id'],capture_sequence=b['capture']['sequence'],window_index=i)
            requests.append(dict(protocol_version=1,request_id=rid+i,session_generation=gen,candidate_id=b['candidate_id'],max_latency_ms=5000,rf_v1=c,iq=dict(storage=dict(path=str(path),offset_bytes=i*8192,length_bytes=8192),sample_format='f32_le',layout='planar_iq',normalization='capture_unit_rms',samples_per_channel=1024,sample_rate_hz=2100000,center_hz=b['center_hz'])))
        return dict(schema_version=1,operation='submit',instance_id=h['instance_id'],worker_instance_id=h['worker_instance_id'],request_id=rid,session_generation=gen,timeout_ms=timeout,requests=requests)
    async def submit(q):return await sup.exchange(runtime/'supervisor.sock',q,8,sup.FRAME)
    async def spark_wire():
        reader,writer=await asyncio.open_connection('127.0.0.1',port)
        payload=dict(model='spark-x2.5-4b',messages=[dict(role='user',content='Count from one to twenty.')],max_tokens=32,chat_template_kwargs=dict(enable_thinking=False))
        body=json.dumps(payload).encode();writer.write(f'POST /v1/chat/completions HTTP/1.1\r\nAuthorization: Bearer {key}\r\nContent-Length: {len(body)}\r\n\r\n'.encode()+body);await writer.drain()
        return reader,writer
    try:
        print('starting isolated Spark and Mamba with shared startup lease',flush=True)
        sp=await launch('spark');mp=await launch('mamba')
        s,m=await asyncio.gather(ready('spark'),ready('mamba'))
        stages.append(dict(stage='resident_startup',spark=s,mamba=m))
        print('validating actual Node Spark -> native Mamba -> Node Spark',flush=True)
        stages.append(dict(stage='spark_mamba_spark',first=await node(),mamba=await native(100),second=await node()))
        assert (await sh())['worker_pid']==s['worker_pid'] and (await mh())['worker_pid']==m['worker_pid']
        print('checking concurrent Spark request and Mamba lease wait',flush=True)
        r,w=await spark_wire();await held('spark');waiting=task(native(101))
        reply=await asyncio.wait_for(r.read(),15);w.close();await w.wait_closed();assert b'200 Response' in reply
        stages.append(dict(stage='concurrent_serialized',mamba=await waiting))
        print('checking Mamba cancel before waiting Planner can run',flush=True)
        m=await mh();pid=m['worker_pid'];os.kill(pid,signal.SIGSTOP)
        q=envelope(m,200,102);running=task(submit(q));await held('mamba');planner=task(node());await asyncio.sleep(.05)
        assert not planner.done() and not (await sh())['gpu_held']
        cancel={k:q[k] for k in ('schema_version','instance_id','worker_instance_id','request_id','session_generation')};cancel['operation']='cancel'
        ack=await sup.exchange(runtime/'control.sock',cancel,3,sup.FRAME)
        assert ack['status']=='cancelled' and dead(pid) and (await running)['status']=='cancelled'
        stages.append(dict(stage='mamba_cancel_releases_to_planner',planner=await planner,worker_dead=True))
        m=await ready('mamba')
        print('checking Spark disconnect before waiting Mamba can run',flush=True)
        s=await sh();pid=s['worker_pid'];os.kill(pid,signal.SIGSTOP)
        r,w=await spark_wire();await held('spark');waiting=task(native(104));await asyncio.sleep(.05)
        assert not waiting.done() and not (await mh())['metrics']['gpu_held']
        w.close();await w.wait_closed();result=await waiting;assert dead(pid)
        stages.append(dict(stage='spark_cancel_releases_to_mamba',mamba=result,worker_dead=True))
        stages.append(dict(stage='spark_recovery',planner=await node()))
        s=await ready('spark')
        print('checking Spark supervisor SIGKILL with inherited GPU lock',flush=True)
        pid=s['worker_pid'];os.kill(pid,signal.SIGSTOP)
        r,w=await spark_wire();await held('spark');waiting=task(native(105));await asyncio.sleep(.05)
        sp.kill();await sp.wait();w.close();await w.wait_closed()
        stages.append(dict(stage='spark_parent_death',mamba=await waiting,worker_dead=dead(pid)));assert dead(pid)
        # Wait actual lock teardown before restarting, never delete lock files.
        await asyncio.sleep(.05)
        sp=await launch('spark');s=await ready('spark')
        print('checking Mamba supervisor SIGKILL before next Planner',flush=True)
        m=await mh();pid=m['worker_pid'];os.kill(pid,signal.SIGSTOP)
        running=task(submit(envelope(m,300,106)));await held('mamba');planner=task(node());await asyncio.sleep(.05)
        mp.kill();await mp.wait();await asyncio.gather(running,return_exceptions=True)
        stages.append(dict(stage='mamba_parent_death',planner=await planner,worker_dead=dead(pid)));assert dead(pid)
        mp=await launch('mamba');m=await ready('mamba')
        stages.append(dict(stage='final_recovery',mamba=await native(110),planner=await node(),mamba_health=await mh(),spark_health=await sh()))
    finally:
        for t in background:
            if not t.done():t.cancel()
        await asyncio.gather(*background,return_exceptions=True)
        for p in processes:
            if p.returncode is None:
                p.terminate()
                try:await asyncio.wait_for(p.wait(),12)
                except asyncio.TimeoutError:p.kill();await p.wait()
        assert all(dead(pid) for pid in pids)
    assert not list((runtime/'incoming').iterdir()) and not list((runtime/'owned').iterdir())
    assert not any((runtime/n).exists() for n in ('supervisor.sock','control.sock','worker.sock'))
    events=[]
    for path in logfiles:
        for line in path.read_text().splitlines():
            if line.startswith('{"gpu_lease":'):events.append(json.loads(line)['gpu_lease'])
    events.sort(key=lambda e:e['monotonic_ns'])
    # Killed owners intentionally have no release event. Their inherited flock
    # can only be acquired after the last model-child descriptor has closed.
    open_lease=None;killed_intervals=0;intervals=0
    for event in events:
        identity=(event['instance'],event['serial'])
        if event['event']=='acquire':
            if open_lease is not None:
                killed_intervals+=1
            open_lease=identity;intervals+=1
        else:
            assert identity==open_lease, 'out-of-order or overlapping explicit releases'
            open_lease=None
    assert open_lease is None and killed_intervals==2
    report=dict(schema_version=1,status='pass',synthetic_input=True,rx_bytes=0,locked_test_read=False,recognizer_available=False,
                stages=stages,lease_events=events,lease_intervals=intervals,parent_death_intervals=killed_intervals,
                cleanup=dict(worker_pids=sorted(pids),workers_dead=True,supervisor_exit_codes=[p.returncode for p in processes],spools_empty=True,sockets_absent=True,ports=[port,backend_port]),
                model_bytes_sha256=hashlib.sha256(data).hexdigest(),controller_sha256=hashlib.sha256(controller.read_bytes()).hexdigest())
    (feature/'live-summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print('S4a real GPU lease validation passed',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--feature-directory',type=Path,required=True);p.add_argument('--controller',type=Path,required=True);a=p.parse_args();asyncio.run(validate(a.feature_directory,a.controller))


if __name__=='__main__':main()
