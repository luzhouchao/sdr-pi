#!/usr/bin/env python3
"""Finite S3 validation with real RF-v1 CUDA Worker and one synthetic replay file."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
SCRIPT=Path(__file__).with_name('amc-worker-supervisor.py')
SPEC=importlib.util.spec_from_file_location('supervisor',SCRIPT)
sup=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(sup)


def dead(pid):
    try:return Path(f'/proc/{pid}/stat').read_text().split()[2]=='Z'
    except FileNotFoundError:return True


async def validate(feature,controller):
    require=lambda ok: sup.require(ok,'validation_assertion')
    require(feature.is_absolute() and feature.parent==Path('/var/tmp/sdrharness-dev') and feature.resolve()==feature)
    runtime=feature/'live';model=feature/'model.f32';fixture=json.loads((feature/'replay.json').read_text())
    require(model.stat().st_size==32768 and hashlib.sha256(model.read_bytes()).hexdigest()==fixture['batch']['model_bytes_sha256'])
    env={**os.environ,'TMPDIR':str(feature/'tmp'),'PYTHONDONTWRITEBYTECODE':'1',
         'TRITON_CACHE_DIR':str(feature/'triton'),'CUDA_CACHE_PATH':str(feature/'cuda-cache')}
    report={'schema_version':1,'schema_id':'worker_supervisor_s3_live_validation','synthetic_input':True,
            'rx_bytes':0,'locked_test_read':False,'recognizer_available':False,
            'model_bytes':32768,'model_bytes_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
            'controller_sha256':hashlib.sha256(controller.read_bytes()).hexdigest(),'stages':[]}
    workers=set();processes=[]
    async def control(q):return await sup.exchange(runtime/'control.sock',q,3,sup.FRAME)
    async def health():return await control(dict(schema_version=1,operation='health'))
    async def ready(different=None):
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            if processes and processes[-1].returncode is not None:
                raise RuntimeError(f'supervisor exited during readiness: {processes[-1].returncode}')
            try:
                h=await health()
                if h['fault']:raise RuntimeError(h['fault'])
                if h['ready'] and h['worker_instance_id']!=different:
                    workers.add(h['worker_pid']);return h
            except (OSError,asyncio.TimeoutError):pass
            await asyncio.sleep(.05)
        raise RuntimeError('live readiness timeout')
    async def start():
        log=(feature/f'supervisor-{len(processes)}.log').open('w')
        process=await asyncio.create_subprocess_exec(sys.executable,str(SCRIPT),'--runtime-root',str(runtime),'--max-batches','16','--max-restarts','4','--lifetime-seconds','600',env=env,stdout=log,stderr=asyncio.subprocess.STDOUT)
        log.close();processes.append(process)
        return process,await ready()
    def envelope(h,request_id,generation,timeout=5000):
        b=fixture['batch'];path=runtime/'incoming'/f"batch-{h['instance_id']}-{generation}-{request_id}.f32"
        path.write_bytes(model.read_bytes());path.chmod(0o600)
        requests=[]
        for i in range(4):
            c={k:b[k] for k in ('profile_sha256','preprocess_sha256','source_sweep_id','source_request_id','source_session_generation','source_sequence')}
            c.update(checkpoint_sha256=sup.decode(sup.RECEIPT.read_bytes())['identity']['checkpoint_sha256'],batch_sha256=b['model_bytes_sha256'],batch_request_id=request_id,capture_request_id=b['capture']['sdrd_request_id'],capture_sequence=b['capture']['sequence'],window_index=i)
            requests.append(dict(protocol_version=1,request_id=request_id+i,session_generation=generation,candidate_id=b['candidate_id'],max_latency_ms=5000,rf_v1=c,iq=dict(storage=dict(path=str(path),offset_bytes=i*8192,length_bytes=8192),sample_format='f32_le',layout='planar_iq',normalization='capture_unit_rms',samples_per_channel=1024,sample_rate_hz=2100000,center_hz=b['center_hz'])))
        return dict(schema_version=1,operation='submit',instance_id=h['instance_id'],worker_instance_id=h['worker_instance_id'],request_id=request_id,session_generation=generation,timeout_ms=timeout,requests=requests)
    async def submit(q):return await sup.exchange(runtime/'supervisor.sock',q,8,sup.FRAME)
    async def active():
        for _ in range(100):
            h=await health()
            if h['active'] is not None:return h
            await asyncio.sleep(.01)
        raise RuntimeError('no active live batch')
    async def native(mode,request=None):
        args=[str(controller),'--mode',mode,'--recognizer-supervisor-root',str(runtime)]
        if request is not None:
            p=feature/'native-request.json';p.write_text(json.dumps(request));p.chmod(0o600)
            args+=['--request',str(p)]
        if mode=='recognize-supervised-replay':args+=['--recognition-profile',str(sup.PROFILE),'--recognizer-spool-root',str(feature),'--repository-root',str(ROOT)]
        proc=await asyncio.create_subprocess_exec(*args,env=env,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        stdout,stderr=await asyncio.wait_for(proc.communicate(),12)
        require(proc.returncode==0)
        return json.loads(stdout)
    async def success(generation):
        replay=json.loads(json.dumps(fixture));replay['batch']['session_generation']=generation;replay['batch']['capture']['session_generation']=generation
        result=await native('recognize-supervised-replay',replay)
        require(result['synthetic_input'] and result['result']['observation']['status']=='unavailable'
                and result['result']['observation']['calibration_status']=='uncalibrated')
        require(not list((runtime/'owned').iterdir()) and not list((runtime/'incoming').iterdir()))
        return dict(result_status=result['result']['observation']['status'],windows=len(result['result']['experimental_batch']['windows']),timing=result['result']['observation']['timing'])
    try:
        print('loading first finite real RF-v1 Worker',flush=True)
        proc,h=await start()
        native_health=await native('recognizer-supervisor-health');require(native_health['instance_id']==h['instance_id'] and not native_health['recognizer_available'])
        report['stages'].append({'stage':'native_success',**await success(100),'health':await health()})
        print('real batch success; checking bounded queue/deadline',flush=True)
        old=h['worker_instance_id'];pid=h['worker_pid'];os.kill(pid,signal.SIGSTOP)
        running=asyncio.create_task(submit(envelope(h,100,101,1000)));await active()
        queued=envelope(h,110,101,100);start_time=time.monotonic();waiting=asyncio.create_task(submit(queued))
        await asyncio.sleep(.02)
        overflow=envelope(h,120,101,100);busy=await submit(overflow)
        require(busy['operation']=='error' and busy['code']=='busy')
        Path(overflow['requests'][0]['iq']['storage']['path']).unlink()
        qreply=await waiting
        require(qreply['status']=='deadline' and qreply['spool_removed'] and time.monotonic()-start_time<.5)
        r=await running;require(r['status']=='deadline' and r['spool_removed'] and dead(pid))
        h=await ready(old)
        report['stages'].append({'stage':'deadline_and_restart','active_status':r['status'],'queued_status':qreply['status'],'busy_rejected':True,'health':h})
        report['stages'].append({'stage':'success_after_deadline',**await success(102)})
        print('deadline cleanup passed; checking native cancellation',flush=True)
        old=h['worker_instance_id'];pid=h['worker_pid'];os.kill(pid,signal.SIGSTOP)
        q=envelope(h,200,103);running=asyncio.create_task(submit(q));await active()
        cancel={k:q[k] for k in ('schema_version','instance_id','worker_instance_id','request_id','session_generation')};cancel['operation']='cancel'
        pending=envelope(h,210,103);waiting=asyncio.create_task(submit(pending));await asyncio.sleep(.02)
        queued_cancel={**cancel,'request_id':210}
        queued_ack=await native('recognizer-supervisor-cancel',queued_cancel);queued_reply=await waiting
        require(queued_ack['status']=='cancelled' and queued_reply['spool_removed'] and not dead(pid))
        ack=await native('recognizer-supervisor-cancel',cancel);r=await running
        require(ack['status']=='cancelled' and ack['spool_removed'] and r['status']=='cancelled' and dead(pid))
        h=await ready(old)
        require((await native('recognizer-supervisor-cancel',cancel))['status']=='cancelled')
        report['stages'].append({'stage':'native_cancel_confirmed','health':h})
        print('cancel cleanup passed; checking supervisor SIGKILL and restart',flush=True)
        pid=h['worker_pid'];os.kill(pid,signal.SIGSTOP)
        q=envelope(h,300,104);running=asyncio.create_task(submit(q));await active()
        partial=runtime/'incoming'/f"batch-{h['instance_id']}-104-310.f32";partial.write_bytes(b'partial');partial.chmod(0o600)
        old_service=h['instance_id'];proc.kill();await proc.wait();await asyncio.gather(running,return_exceptions=True)
        for _ in range(100):
            if dead(pid):break
            await asyncio.sleep(.02)
        require(dead(pid))
        proc,h=await start();require(h['instance_id']!=old_service and h['metrics']['removed']>=2)
        stale=await submit(q);require(stale['operation']=='error' and stale['code']=='instance')
        report['stages'].append({'stage':'supervisor_restart_cleanup','health':h,'stale_instance_rejected':True})
        report['stages'].append({'stage':'native_success_after_supervisor_restart',**await success(105),'health':await health()})
        report['status']='pass'
    finally:
        for proc in processes:
            if proc.returncode is None:
                proc.terminate()
                try:await asyncio.wait_for(proc.wait(),10)
                except asyncio.TimeoutError:proc.kill();await proc.wait();raise
        require(all(dead(pid) for pid in workers))
    require(not (runtime/'supervisor.sock').exists() and not (runtime/'worker.sock').exists() and not (runtime/'control.sock').exists())
    require(not list((runtime/'owned').iterdir()) and not list((runtime/'incoming').iterdir()))
    report['cleanup']={'worker_pids':sorted(workers),'workers_dead':True,'sockets_removed':True,'incoming_and_owned_empty':True,'supervisor_exit_codes':[p.returncode for p in processes]}
    (feature/'live-summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print('S3 finite real-Worker validation passed',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--feature-directory',type=Path,required=True);parser.add_argument('--controller',type=Path,required=True);args=parser.parse_args()
    asyncio.run(validate(args.feature_directory,args.controller))


if __name__=='__main__':main()
