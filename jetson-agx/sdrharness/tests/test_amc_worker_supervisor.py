"""S3 process, queue, deadline and ownership tests; no Torch/model/dataset."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import signal
import struct
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
SPEC=importlib.util.spec_from_file_location('supervisor',ROOT/'jetson-agx/sdrharness/scripts/amc-worker-supervisor.py')
sup=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(sup)

FAKE='''import json,os,secrets,socket,sys,time
from pathlib import Path
receipt=json.loads(Path(sys.argv[3]).read_text())
sock=socket.socket(socket.AF_UNIX);sock.bind(sys.argv[1]);sock.listen(1)
identity=secrets.token_hex(32);started=time.time_ns()//1000000
while True:
 c,_=sock.accept()
 with c:
  buf=b''
  while not buf.endswith(b'\\n'):
   chunk=c.recv(16384)
   if not chunk:break
   buf+=chunk
  if not buf:continue
  q=json.loads(buf)
  if q.get('operation')=='admission_health':
   r=dict(schema_version=1,schema_id='recognizer_health_v1',protocol_version=1,request_id=q['request_id'],session_generation=q['session_generation'],nonce=q['nonce'],worker_instance_id=identity,started_at_unix_ms=started,observed_at_unix_ms=time.time_ns()//1000000,status='ready',identity=receipt['identity'],admission_sha256=sys.argv[4],production_enabled=False)
  else:
   assert Path(q['iq']['storage']['path']).is_file()
   r=dict(protocol_version=1,request_id=q['request_id'],session_generation=q['session_generation'],status='ok',output=dict(candidate_id=q['candidate_id'],label='provisional:00',confidence=1/24,alternatives=[],backend=dict(runtime='synthetic',runtime_version='1',model_id=receipt['identity']['model_id'],model_sha256=receipt['identity']['checkpoint_sha256'],threads=1),timing=dict(map_us=1,preprocess_us=1,inference_us=1,total_us=3),rf_v1=dict(contract=q['rf_v1'],request_id=q['request_id'],session_generation=q['session_generation'],compute='cuda_fp16_autocast',logits=[0.0]*24)))
  c.sendall(json.dumps(r).encode()+b'\\n')
'''


def batch(service, request_id=10, generation=1, timeout=5000):
    filename=f'batch-{service.instance}-{generation}-{request_id}.f32'
    path=service.incoming/filename
    data=(struct.pack('<1024f',*([1.0]*1024))+struct.pack('<1024f',*([0.0]*1024)))*4
    path.write_bytes(data);path.chmod(0o600)
    requests=[]
    for i in range(4):
        c={k:service.receipt['identity'][k] for k in ('profile_sha256','preprocess_sha256','checkpoint_sha256')}
        c.update(batch_sha256=sup.digest(data),batch_request_id=request_id,source_sweep_id='synthetic-inspection',source_request_id=4,source_session_generation=generation,source_sequence=1,capture_request_id=5,capture_sequence=2,window_index=i)
        requests.append(dict(protocol_version=1,request_id=request_id+i,session_generation=generation,candidate_id='synthetic-candidate',max_latency_ms=5000,rf_v1=c,iq=dict(storage=dict(path=str(path),offset_bytes=i*8192,length_bytes=8192),sample_format='f32_le',layout='planar_iq',normalization='capture_unit_rms',samples_per_channel=1024,sample_rate_hz=2100000,center_hz=433920000)))
    return dict(schema_version=1,operation='submit',instance_id=service.instance,worker_instance_id=service.worker_id,request_id=request_id,session_generation=generation,timeout_ms=timeout,requests=requests)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='s3-')
        self.root=Path(self.tmp.name);self.root.chmod(0o700)
        fake=self.root/'fake.py';fake.write_text(FAKE)
        runtime=self.root/'runtime'
        self.service=sup.Supervisor(runtime,Path(sys.executable),max_restarts=8,startup_seconds=2,
            gpu_lease_root=self.root/'gate' if getattr(self,'use_gpu_lease',False) else None,
            command_factory=lambda socket,spool:[sys.executable,str(fake),str(socket),str(spool),str(sup.RECEIPT),sup.RECEIPT_HASH])
        self.service.initialize()
        self.server=await asyncio.start_unix_server(self.service.handle,path=str(self.service.socket),limit=sup.FRAME)
        self.control=await asyncio.start_unix_server(lambda r,w:self.service.handle(r,w,True),path=str(self.service.control_socket),limit=16384)
        self.task=asyncio.create_task(self.service.scheduler())
        await self.ready()

    async def ready(self):
        for _ in range(200):
            if self.service.health:return
            if self.task.done():await self.task
            await asyncio.sleep(.01)
        self.fail('worker startup timeout')

    async def asyncTearDown(self):
        self.service.stopping=True
        self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
        self.server.close();await self.server.wait_closed()
        self.control.close();await self.control.wait_closed()
        await self.service.kill_worker()
        for job in (self.service.active,self.service.pending):
            if job and not job.done.done():self.service.finish(job,'shutdown')
        if self.service.lock is not None:os.close(self.service.lock)
        if self.service.gpu_lease is not None:self.service.gpu_lease.close()
        self.tmp.cleanup()

    async def call(self,q):return await sup.exchange(self.service.socket,q,8,sup.FRAME)
    async def wait_active(self):
        for _ in range(100):
            if self.service.active:return
            await asyncio.sleep(.005)
        self.fail('no active batch')

    async def test_complete_four_windows_cleanup_and_replay(self):
        q=batch(self.service)
        r=await self.call(q)
        self.assertEqual(r['status'],'ok');self.assertEqual(len(r['outputs']),4)
        self.assertTrue(r['spool_removed']);self.assertFalse(list(self.service.owned.iterdir()))
        self.assertFalse(list(self.service.incoming.iterdir()))
        self.assertFalse(self.service.status()['recognizer_available'])
        self.assertEqual((await self.call(q))['code'],'replay')

    async def test_queue_one_cancel_queued_then_active_reaps_and_fences_generation(self):
        child=self.service.process.pid;old=self.service.worker_id
        os.kill(child,signal.SIGSTOP)
        first=batch(self.service,10);running=asyncio.create_task(self.call(first));await self.wait_active()
        second=batch(self.service,20);queued=asyncio.create_task(self.call(second));await asyncio.sleep(.03)
        self.assertEqual(self.service.status()['queue_depth'],1)
        self.assertEqual((await self.call(batch(self.service,30)))['code'],'busy')
        cancel={k:second[k] for k in ('schema_version','instance_id','worker_instance_id','request_id','session_generation')};cancel['operation']='cancel'
        reply=await self.call(cancel);self.assertEqual(reply['status'],'cancelled');await queued
        cancel.update(request_id=10)
        reply=await self.call(cancel);self.assertEqual(reply['status'],'cancelled');await running
        self.assertFalse(Path(f'/proc/{child}').exists());self.assertFalse(list(self.service.owned.iterdir()))
        await self.ready();self.assertNotEqual(old,self.service.worker_id)
        self.assertEqual((await self.call(cancel))['status'],'cancelled')
        self.assertEqual((await self.call(batch(self.service,40,generation=1)))['code'],'generation')
        self.assertEqual((await self.call(batch(self.service,50,generation=2)))['status'],'ok')

    async def test_queue_deadline_is_not_extended_by_active_inference(self):
        os.kill(self.service.process.pid,signal.SIGSTOP)
        running=asyncio.create_task(self.call(batch(self.service,10,timeout=1000)));await self.wait_active()
        started=asyncio.get_running_loop().time()
        result=await self.call(batch(self.service,20,timeout=50))
        self.assertEqual(result['status'],'deadline');self.assertLess(asyncio.get_running_loop().time()-started,.3)
        self.assertEqual((await running)['status'],'deadline');await self.ready()
        self.assertFalse(list(self.service.owned.iterdir()))

    async def test_disconnect_kills_active_worker_and_removes_spool(self):
        child=self.service.process.pid;os.kill(child,signal.SIGSTOP)
        q=batch(self.service)
        reader,writer=await asyncio.open_unix_connection(str(self.service.socket))
        writer.write(json.dumps(q).encode()+b'\n');await writer.drain();await self.wait_active()
        writer.close();await writer.wait_closed()
        for _ in range(200):
            if not (self.service.owned / Path(q['requests'][0]['iq']['storage']['path']).name).exists():break
            await asyncio.sleep(.01)
        self.assertFalse(Path(f'/proc/{child}').exists());self.assertFalse(list(self.service.owned.iterdir()))

    async def test_invalid_hash_shape_instance_and_mixed_source_never_owned(self):
        for i,fault in enumerate(('hash','source','offset','generation','instance','nan','duplicate')):
            q=batch(self.service,10+i*10)
            if fault=='hash':q['requests'][0]['rf_v1']['batch_sha256']='0'*64
            elif fault=='source':q['requests'][1]['rf_v1']['source_request_id']+=1
            elif fault=='offset':q['requests'][1]['iq']['storage']['offset_bytes']=0
            elif fault=='generation':q['requests'][1]['session_generation']+=1
            elif fault=='instance':q['instance_id']='0'*64
            elif fault=='nan':
                p=Path(q['requests'][0]['iq']['storage']['path']);data=p.read_bytes();p.write_bytes(struct.pack('<f',float('nan'))+data[4:])
            else:q['extra']='not_allowed'
            r=await self.call(q);self.assertEqual(r['operation'],'error',fault)
            self.assertFalse(list(self.service.owned.iterdir()))
        self.assertEqual(self.service.metrics['submitted'],0)

    async def test_control_socket_remains_responsive_when_data_peers_stall(self):
        clients=[]
        try:
            for _ in range(8):
                r,w=await asyncio.open_unix_connection(str(self.service.socket));clients.append(w)
            await asyncio.sleep(.02)
            h=await sup.exchange(self.service.control_socket,dict(schema_version=1,operation='health'),.25)
            self.assertEqual(h['instance_id'],self.service.instance)
        finally:
            for w in clients:w.close();await w.wait_closed()

    async def test_startup_cancellation_does_not_lose_child_ownership(self):
        from unittest.mock import patch
        other=sup.Supervisor(self.root/'starting',Path(sys.executable),command_factory=self.service.command_factory)
        other.initialize()
        created=asyncio.get_running_loop().create_future()
        original=asyncio.create_subprocess_exec
        async def delayed(*args,**kwargs):
            process=await original(*args,**kwargs)
            created.set_result(process)
            await asyncio.sleep(.05)
            return process
        try:
            with patch.object(asyncio,'create_subprocess_exec',delayed):
                task=asyncio.create_task(other.start_worker())
                process=await created
                task.cancel();await asyncio.gather(task,return_exceptions=True)
            self.assertIs(other.process,process)
            await other.kill_worker()
            self.assertIsNotNone(process.returncode)
        finally:
            await other.kill_worker()
            os.close(other.lock)

    async def test_duplicate_owner_and_unknown_spool_fail_closed(self):
        original=self.service.socket.stat().st_ino
        other=sup.Supervisor(self.service.root,Path(sys.executable))
        with self.assertRaises(BlockingIOError):other.initialize()
        self.assertEqual(original,self.service.socket.stat().st_ino)
        root=self.root/'untrusted';sup.private_directory(root);sup.private_directory(root/'incoming');sup.private_directory(root/'owned')
        target=self.root/'keep.txt';target.write_text('user data')
        (root/'incoming'/'unknown').symlink_to(target)
        other=sup.Supervisor(root,Path(sys.executable))
        try:
            with self.assertRaises(sup.ContractError):other.initialize()
            self.assertEqual(target.read_text(),'user data')
            self.assertTrue((root/'incoming'/'unknown').is_symlink())
        finally:
            if other.lock is not None:os.close(other.lock)

    async def test_supervisor_sigkill_kills_child_and_restart_cleans_spool(self):
        runtime=self.root/'restart'
        wrapper=self.root/'wrapper.py'
        wrapper.write_text("import asyncio,importlib.util,sys\nfrom pathlib import Path\nspec=importlib.util.spec_from_file_location('s',sys.argv[1]);s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)\nv=s.Supervisor(Path(sys.argv[2]),Path(sys.executable),startup_seconds=2,command_factory=lambda sock,spool:[sys.executable,sys.argv[3],str(sock),str(spool),str(s.RECEIPT),s.RECEIPT_HASH])\nasyncio.run(v.run(20))\n")
        command=[sys.executable,str(wrapper),str(ROOT/'jetson-agx/sdrharness/scripts/amc-worker-supervisor.py'),str(runtime),str(self.root/'fake.py')]
        async def start():
            proc=await asyncio.create_subprocess_exec(*command,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
            for _ in range(300):
                try:
                    h=await sup.exchange(runtime/'control.sock',dict(schema_version=1,operation='health'),.2)
                    if h['ready']:return proc,h
                except (OSError,asyncio.TimeoutError):pass
                self.assertIsNone(proc.returncode);await asyncio.sleep(.01)
            self.fail('subprocess readiness')
        proc,h=await start();second=None;request_task=None
        try:
            import types
            proxy=types.SimpleNamespace(instance=h['instance_id'],worker_id=h['worker_instance_id'],incoming=runtime/'incoming',receipt=self.service.receipt)
            q=batch(proxy)
            os.kill(h['worker_pid'],signal.SIGSTOP)
            request_task=asyncio.create_task(sup.exchange(runtime/'supervisor.sock',q,5,sup.FRAME))
            for _ in range(100):
                state=await sup.exchange(runtime/'control.sock',dict(schema_version=1,operation='health'),.2)
                if state['active'] is not None:break
                await asyncio.sleep(.01)
            self.assertIsNotNone(state['active'])
            # Also model a producer killed halfway through writing incoming IQ.
            partial=runtime/'incoming'/f"batch-{h['instance_id']}-1-20.f32"
            partial.write_bytes(b'partial');partial.chmod(0o600)
            proc.kill();await proc.wait()
            await asyncio.gather(request_task,return_exceptions=True)
            def child_dead():
                try:return Path(f"/proc/{h['worker_pid']}/stat").read_text().split()[2]=='Z'
                except FileNotFoundError:return True
            for _ in range(100):
                if child_dead():break
                await asyncio.sleep(.01)
            self.assertTrue(child_dead())
            second,new=await start()
            self.assertNotEqual(new['instance_id'],h['instance_id']);self.assertNotEqual(new['worker_instance_id'],h['worker_instance_id'])
            self.assertGreaterEqual(new['metrics']['removed'],2)
            self.assertFalse(list((runtime/'owned').iterdir()));self.assertFalse(list((runtime/'incoming').iterdir()))
            rejection=await sup.exchange(runtime/'supervisor.sock',q,1,sup.FRAME);self.assertEqual(rejection['code'],'instance')
        finally:
            if proc.returncode is None:proc.kill();await proc.wait()
            if second is not None:second.terminate();await asyncio.wait_for(second.wait(),5)

    async def test_crash_while_idle_restarts_and_changes_worker_identity(self):
        old=self.service.worker_id;os.kill(self.service.process.pid,signal.SIGKILL)
        for _ in range(200):
            if self.service.worker_id!=old and self.service.health:break
            await asyncio.sleep(.01)
        self.assertNotEqual(old,self.service.worker_id);self.assertEqual(self.service.metrics['crashes'],1)


if __name__=='__main__':unittest.main()
