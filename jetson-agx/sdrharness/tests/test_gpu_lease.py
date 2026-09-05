"""S4a OS lease and owned Spark gateway fault tests, no model or datasets."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
from gpu_lease import GpuLease, LeaseError
spec = importlib.util.spec_from_file_location('gateway', SCRIPTS/'spark-gpu-gateway.py')
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)

FAKE = r'''
import json,sys,time
from http.server import HTTPServer,BaseHTTPRequestHandler
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send(self,value):
  data=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_GET(self):self.send({'status':'ok'})
 def do_POST(self):
  q=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  if q['messages'][0]['content']=='block':time.sleep(60)
  self.send(dict(id='test',created=1,model='spark-x2.5-4b',choices=[dict(index=0,message=dict(role='assistant',content='ok'),finish_reason='stop')],usage=dict(prompt_tokens=1,completion_tokens=1,total_tokens=2)))
HTTPServer(('127.0.0.1',int(sys.argv[1])),Handler).serve_forever()
'''


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def request(content='ok'):
    return dict(model='spark-x2.5-4b',messages=[dict(role='user',content=content)],max_tokens=16)


class LeaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='s4a-')
        self.root = Path(self.tmp.name)
        self.a = GpuLease(self.root/'gate','spark')
        self.b = GpuLease(self.root/'gate','mamba')

    async def asyncTearDown(self):
        self.a.close();self.b.close();self.tmp.cleanup()

    async def test_serialization_deadline_cancel_and_stale_token(self):
        token = await self.a.acquire(time.monotonic()+1)
        with self.assertRaisesRegex(LeaseError,'deadline'):
            await self.b.acquire(time.monotonic()+.025)
        with self.assertRaisesRegex(LeaseError,'cancelled'):
            await self.b.acquire(time.monotonic()+1,lambda:True)
        with self.assertRaisesRegex(LeaseError,'stale'):
            self.a.release(('wrong',1))
        self.a.release(token)
        other = await self.b.acquire(time.monotonic()+1)
        self.b.release(other)
        newer = await self.a.acquire(time.monotonic()+1)
        with self.assertRaisesRegex(LeaseError,'stale'):
            self.a.release(token)
        self.a.release(newer)

    async def test_inherited_fd_prevents_release_on_owner_exit(self):
        # The child owns a duplicate of the SAME open description, not a new flock.
        token = await self.a.acquire(time.monotonic()+1)
        proc = await asyncio.create_subprocess_exec(sys.executable,'-c','import time;time.sleep(30)',pass_fds=(self.a.fd,))
        try:
            os.close(self.a.fd)
            self.a.fd = os.open('/dev/null',os.O_RDONLY)
            with self.assertRaisesRegex(LeaseError,'deadline'):
                await self.b.acquire(time.monotonic()+.03)
            proc.kill();await proc.wait()
            other = await self.b.acquire(time.monotonic()+1)
            self.b.release(other)
        finally:
            if proc.returncode is None:proc.kill();await proc.wait()

    async def test_symlink_hardlink_permissions_and_replaced_inode(self):
        self.a.path.unlink();self.a.path.symlink_to('/dev/null')
        with self.assertRaises(LeaseError):await self.a.acquire(time.monotonic()+1)
        with self.assertRaises(OSError):GpuLease(self.root/'gate','spark')
        self.a.path.unlink();self.a.path.write_bytes(b'');self.a.path.chmod(0o644)
        with self.assertRaises(LeaseError):GpuLease(self.root/'gate','spark')
        self.a.path.chmod(0o600);os.link(self.a.path,self.root/'link')
        with self.assertRaises(LeaseError):GpuLease(self.root/'gate','spark')


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='s4g-')
        self.root = Path(self.tmp.name)
        self.g = gateway.Gateway(self.root/'spark',self.root/'gate',port(),port(),'a'*32,Path('/none'),Path('/none'),timeout=.3,
            command_factory=lambda p,k:[sys.executable,'-c',FAKE,str(p)])
        self.g.initialize()
        self.g.token = await self.g.lease.acquire(time.monotonic()+1)
        await self.g.start_child();self.g.release()
        self.server = await asyncio.start_server(self.g.handle,'127.0.0.1',self.g.port,limit=8192)
        self.other = GpuLease(self.root/'gate','mamba')

    async def asyncTearDown(self):
        self.server.close();await self.server.wait_closed()
        for t in list(self.g.tasks):t.cancel()
        await asyncio.gather(*self.g.tasks,return_exceptions=True)
        await self.g.kill_child();self.g.release();self.g.lease.close()
        os.close(self.g.lock);self.other.close();self.tmp.cleanup()

    async def client(self,body):
        reader,writer=await asyncio.open_connection('127.0.0.1',self.g.port)
        data=json.dumps(body).encode()
        writer.write(f'POST /v1/chat/completions HTTP/1.1\r\nAuthorization: Bearer {self.g.key}\r\nContent-Length: {len(data)}\r\n\r\n'.encode()+data)
        await writer.drain()
        return reader,writer

    async def settled(self):
        for _ in range(200):
            if not self.g.active:return
            await asyncio.sleep(.005)
        self.fail('request remained active')

    async def test_success_buffered_sse_and_bounded_input(self):
        for stream in (False,True):
            status,result=await gateway.backend_http(self.g.port,self.g.key,'/v1/chat/completions',request()) if not stream else (None,None)
            if not stream:self.assertEqual(status,200);self.assertEqual(result['choices'][0]['message']['content'],'ok')
            else:
                r,w=await self.client({**request(),'stream':True})
                data=await r.read();self.assertIn(b'data: [DONE]',data);w.close();await w.wait_closed()
        self.assertFalse(self.g.lease.held)
        status,_=await gateway.backend_http(self.g.port,self.g.key,'/v1/chat/completions',{**request(),'max_tokens':1025})
        self.assertEqual(status,503)

    async def test_cancel_waiter_does_not_unlock_other_owner(self):
        token=await self.other.acquire(time.monotonic()+1)
        pid=self.g.process.pid
        r,w=await self.client(request());await asyncio.sleep(.03)
        w.close();await w.wait_closed();await self.settled()
        self.assertTrue(self.other.held);self.assertEqual(self.g.process.pid,pid)
        self.assertIsNone(self.g.process.returncode)
        self.other.release(token)

    async def test_disconnect_reaps_active_backend_then_next_owner(self):
        pid=self.g.process.pid
        r,w=await self.client(request('block'));await asyncio.sleep(.04)
        self.assertTrue(self.g.lease.held)
        w.close();await w.wait_closed();await self.settled()
        self.assertIsNone(self.g.process);self.assertFalse(Path(f'/proc/{pid}').exists())
        token=await self.other.acquire(time.monotonic()+1);self.other.release(token)
        status,result=await gateway.backend_http(self.g.port,self.g.key,'/v1/chat/completions',request())
        self.assertEqual(status,200);self.assertNotEqual(self.g.process.pid,pid)

    async def test_active_deadline_and_busy_release_after_reap(self):
        pid=self.g.process.pid
        r,w=await self.client(request('block'));await asyncio.sleep(.03)
        status,_=await gateway.backend_http(self.g.port,self.g.key,'/v1/chat/completions',request())
        self.assertEqual(status,429)
        data=await asyncio.wait_for(r.read(),2);self.assertIn(b'504',data)
        w.close();await w.wait_closed();await self.settled()
        self.assertFalse(Path(f'/proc/{pid}').exists())
        token=await self.other.acquire(time.monotonic()+1);self.other.release(token)

    async def test_startup_cancel_retains_inherited_owner_until_reap(self):
        await self.g.kill_child()
        self.g.token=await self.g.lease.acquire(time.monotonic()+1)
        original=asyncio.create_subprocess_exec
        created=asyncio.Event()
        async def delayed(*args,**kwargs):
            process=await original(*args,**kwargs)
            created.set()
            await asyncio.sleep(.03)
            return process
        with patch.object(asyncio,'create_subprocess_exec',new=delayed):
            task=asyncio.create_task(self.g.start_child())
            await created.wait();task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertIsNotNone(self.g.process)
        self.assertTrue(self.g.lease.held)
        await self.g.kill_child();self.g.release()
        token=await self.other.acquire(time.monotonic()+1);self.other.release(token)

    async def test_reap_failure_keeps_gate_and_health_closed(self):
        self.g.token=await self.g.lease.acquire(time.monotonic()+1)
        with patch.object(self.g.process,'wait',new=AsyncMock(side_effect=asyncio.TimeoutError)):
            with self.assertRaises(asyncio.TimeoutError):await self.g.kill_child()
        self.assertTrue(self.g.lease.held)
        self.assertFalse(self.g.health()['ready'])
        self.assertEqual(self.g.health()['fault'],'reap_failed')
        with self.assertRaisesRegex(LeaseError,'deadline'):
            await self.other.acquire(time.monotonic()+.02)
        await self.g.kill_child();self.g.release()

    async def test_child_crash_releases_and_stale_output_absent(self):
        r,w=await self.client(request('block'));await asyncio.sleep(.03)
        self.g.process.kill()
        data=await asyncio.wait_for(r.read(),2)
        self.assertIn(b'503',data);self.assertNotIn(b'choices',data)
        w.close();await w.wait_closed();await self.settled()
        token=await self.other.acquire(time.monotonic()+1);self.other.release(token)


import test_amc_worker_supervisor as s3


class GatedMambaTests(s3.LifecycleTests):
    use_gpu_lease = True

    async def test_gpu_wait_cancel_preserves_spark_owner(self):
        other = GpuLease(self.root/'gate','spark')
        try:
            token = await other.acquire(time.monotonic()+1)
            q = s3.batch(self.service)
            running = asyncio.create_task(self.call(q))
            await self.wait_active()
            ack = await self.service.cancel_job(self.service.active)
            self.assertEqual(ack['status'],'cancelled')
            self.assertTrue(other.held)
            self.assertEqual((await running)['status'],'cancelled')
            other.release(token)
            await self.ready()
            q = s3.batch(self.service,request_id=20,generation=2)
            self.assertEqual((await self.call(q))['status'],'ok')
        finally:
            other.close()

    async def test_whole_batch_lease_not_four_independent_windows(self):
        before = self.service.gpu_lease.metrics['acquired']
        q = s3.batch(self.service)
        self.assertEqual((await self.call(q))['status'],'ok')
        self.assertEqual(self.service.gpu_lease.metrics['acquired'],before+1)
        self.assertFalse(self.service.gpu_lease.held)


if __name__=='__main__':unittest.main()
