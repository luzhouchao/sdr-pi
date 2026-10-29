"""Seeded framing mutations on the actual candidate supervisor and HTTP gateway."""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

TESTS=Path(__file__).parent
sys.path.insert(0,str(TESTS));sys.path.insert(0,str(TESTS.parent/'scripts'))
import test_amc_worker_supervisor as s3
import test_gpu_lease as s4


def corpus(seed):
    state=20260906;result=[]
    for index in range(256):
        state=(state*1664525+1013904223)&0xffffffff;position=state%len(seed)
        if index%4==0:value=seed[:position]
        elif index%4==1:value=seed[:position]+b'\0'+seed[position+1:]
        elif index%4==2:value=seed+b'\n{}'
        else:value=seed[:position]+bytes([state%128])+seed[position+1:]
        result.append(value)
    return result


class SupervisorFuzz(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=s3.LifecycleTests.asyncSetUp
    asyncTearDown=s3.LifecycleTests.asyncTearDown
    ready=s3.LifecycleTests.ready
    async def test_seeded_control_and_data_frames(self):
        cases=corpus(b'{"schema_version":1,"operation":"unsupported"}')
        for target in (self.service.socket,self.service.control_socket):
            for raw in cases:
                reader,writer=await asyncio.open_unix_connection(str(target),limit=s3.sup.FRAME)
                try:
                    writer.write(raw+b'\n');await writer.drain()
                    reply=await asyncio.wait_for(reader.readline(),2)
                    self.assertLessEqual(len(reply),s3.sup.FRAME)
                    self.assertEqual(json.loads(reply)['operation'],'error')
                finally:writer.close();await writer.wait_closed()
            self.assertEqual(self.service.metrics['submitted'],0)
            self.assertFalse(self.service.status()['recognizer_available'])
        print(json.dumps({'o1a_fuzz':'supervisor_control_and_data','cases_each':256,'seed':20260906,'sha256':hashlib.sha256(b'\0'.join(cases)).hexdigest()}))


class GatewayFuzz(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=s4.GatewayTests.asyncSetUp
    asyncTearDown=s4.GatewayTests.asyncTearDown
    async def test_seeded_http_frames(self):
        cases=corpus(b'GET /invalid HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\n\r\n')
        for raw in cases:
            reader,writer=await asyncio.open_connection('127.0.0.1',self.g.port)
            try:
                writer.write(raw+b'\r\n\r\n');await writer.drain()
                response=await asyncio.wait_for(reader.read(32768),2)
                self.assertLessEqual(len(response),32768)
                self.assertNotIn(b'200 Response',response)
            finally:writer.close();await writer.wait_closed()
        self.assertEqual(self.g.metrics['submitted'],0)
        print(json.dumps({'o1a_fuzz':'spark_http','cases':256,'seed':20260906,'sha256':hashlib.sha256(b'\0'.join(cases)).hexdigest()}))


if __name__=='__main__':unittest.main()
