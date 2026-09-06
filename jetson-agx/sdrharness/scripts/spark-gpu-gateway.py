#!/usr/bin/env python3
"""Finite candidate Spark gateway owning its llama child and shared GPU lease."""
import argparse
import asyncio
import ctypes
import fcntl
import json
import os
from pathlib import Path
import secrets
import signal
import stat
import time

from gpu_lease import GpuLease, LeaseError

MAX_BODY = 65536
MAX_RESPONSE = 2 * 1024 * 1024
LIBC = ctypes.CDLL(None, use_errno=True)


def require(ok, code):
    if not ok:
        raise ValueError(code)


def decode(data):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, 'duplicate_key')
            result[k] = v
        return result
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda _: require(False, 'nonfinite'))


async def headers(reader):
    raw = await reader.readuntil(b'\r\n\r\n')
    require(len(raw) <= 8192, 'headers_bound')
    lines = raw.decode('ascii').split('\r\n')
    fields = {}
    for line in lines[1:-2]:
        k, v = line.split(':', 1)
        k = k.lower()
        require(k not in fields, 'duplicate_header')
        fields[k] = v.strip()
    return lines[0], fields


async def backend_http(port, key, path, payload=None):
    reader, writer = await asyncio.open_connection('127.0.0.1', port, limit=8192)
    try:
        body = b'' if payload is None else json.dumps(payload, allow_nan=False).encode()
        method = 'GET' if payload is None else 'POST'
        writer.write((f'{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {key}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n').encode()+body)
        await writer.drain()
        first, fields = await headers(reader)
        require(first.startswith('HTTP/1.1 ') or first.startswith('HTTP/1.0 '), 'backend_protocol')
        status = int(first.split()[1])
        if fields.get('transfer-encoding') == 'chunked':
            data = bytearray()
            while True:
                line = await reader.readline()
                require(len(line) <= 32, 'chunk_header')
                size = int(line.strip(), 16)
                require(0 <= size <= MAX_RESPONSE-len(data), 'response_bound')
                if size == 0:
                    require(await reader.readexactly(2) == b'\r\n', 'chunk_end')
                    break
                data.extend(await reader.readexactly(size))
                require(await reader.readexactly(2) == b'\r\n', 'chunk_end')
        else:
            require('transfer-encoding' not in fields, 'encoding')
            size = int(fields['content-length'])
            require(0 <= size <= MAX_RESPONSE, 'response_bound')
            data = await reader.readexactly(size)
        return status, decode(data)
    finally:
        writer.close()
        await writer.wait_closed()


class Gateway:
    def __init__(self, root, gate_root, port, backend_port, key, binary, model,
                 lifetime=600, max_requests=32, timeout=120, command_factory=None):
        self.root, self.port, self.backend_port = root, port, backend_port
        self.key, self.binary, self.model = key, binary, model
        self.lifetime, self.max_requests, self.timeout = lifetime, max_requests, timeout
        self.command_factory = command_factory
        self.lease = GpuLease(gate_root, 'spark')
        self.token = None
        self.process = None
        self.instance = secrets.token_hex(32)
        self.worker_instance = None
        self.stopping = False
        self.active = False
        self.fault = None
        self.tasks = set()
        self.connections = 0
        self.metrics = dict(submitted=0, completed=0, cancelled=0, failed=0, busy=0, restarts=0)

    def initialize(self):
        require(self.root.is_absolute() and self.root.resolve() == self.root, 'runtime_path')
        self.root.mkdir(mode=0o700, exist_ok=True)
        m = self.root.lstat()
        require(stat.S_ISDIR(m.st_mode) and m.st_uid == os.geteuid() and m.st_mode & 0o077 == 0, 'runtime_permissions')
        self.lock = os.open(self.root/'gateway.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        m = os.fstat(self.lock)
        require(stat.S_ISREG(m.st_mode) and m.st_nlink == 1 and m.st_uid == os.geteuid() and m.st_mode & 0o077 == 0, 'lock_permissions')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # A private new backend key prevents accidental direct candidate calls.
        self.backend_key = secrets.token_hex(32)
        self.backend_key_file = self.root/'backend-key.txt'
        fd = os.open(self.backend_key_file, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as f:
            m = os.fstat(f.fileno())
            require(stat.S_ISREG(m.st_mode) and m.st_nlink == 1 and m.st_uid == os.geteuid() and m.st_mode & 0o077 == 0, 'key_metadata')
            os.ftruncate(f.fileno(), 0)
            f.write(self.backend_key)

    async def start_child(self):
        require(self.process is None and self.lease.held, 'startup_ownership')
        require(self.metrics['restarts'] < 4, 'restart_budget')
        parent = os.getpid()
        def child_setup():
            if LIBC.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent:
                os._exit(127)
        command = (self.command_factory(self.backend_port, self.backend_key) if self.command_factory else
                   [str(self.binary), '--model', str(self.model), '--alias', 'spark-x2.5-4b',
                    '--host', '127.0.0.1', '--port', str(self.backend_port), '--ctx-size', '32768',
                    '--parallel', '1', '--threads', '12', '--gpu-layers', 'all', '--flash-attn', 'on',
                    '--cache-type-k', 'f16', '--cache-type-v', 'f16', '--cache-ram', '256',
                    '--jinja', '--reasoning', 'auto',
                    '--reasoning-format', 'deepseek', '--api-key-file', str(self.backend_key_file), '--no-webui'])
        spawning = asyncio.create_task(asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True, pass_fds=(self.lock, self.lease.fd), preexec_fn=child_setup))
        try:
            self.process = await asyncio.shield(spawning)
        except asyncio.CancelledError:
            self.process = await spawning
            raise
        self.metrics['restarts'] += 1
        deadline = time.monotonic()+180
        while time.monotonic() < deadline:
            require(self.process.returncode is None, 'startup_exit')
            try:
                status, result = await asyncio.wait_for(backend_http(self.backend_port, self.backend_key, '/health'), .5)
                if status == 200 and result == {'status':'ok'}:
                    self.worker_instance = secrets.token_hex(32)
                    return
            except (OSError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(.05)
        raise TimeoutError('startup_deadline')

    async def kill_child(self):
        if self.process is not None:
            if self.process.returncode is None:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except asyncio.TimeoutError:
                self.fault = 'reap_failed'
                raise
            self.process = None
        self.worker_instance = None

    def release(self):
        if self.token is not None:
            self.lease.release(self.token)
            self.token = None

    def health(self):
        return dict(schema_version=1, instance_id=self.instance, worker_instance_id=self.worker_instance,
                    worker_pid=None if self.process is None else self.process.pid,
                    ready=bool(self.process and self.process.returncode is None and not self.stopping and self.fault is None),
                    fault=self.fault, recognizer_available=False, active=self.active, metrics=self.metrics,
                    gpu_held=self.lease.held, gpu_metrics=self.lease.metrics)

    async def completion(self, payload, disconnected):
        require(self.fault is None, 'gateway_fault')
        require(type(payload) is dict, 'payload')
        require(payload.get('model') == 'spark-x2.5-4b' and payload.get('n', 1) == 1, 'model_or_n')
        require(type(payload.get('messages')) is list and 1 <= len(payload['messages']) <= 128, 'messages')
        tokens = payload.get('max_completion_tokens', payload.get('max_tokens'))
        require(type(tokens) is int and 1 <= tokens <= 1024, 'token_bound')
        require(type(payload.get('stream', False)) is bool, 'stream')
        require(not ('max_tokens' in payload and 'max_completion_tokens' in payload), 'token_shape')
        self.metrics['submitted'] += 1
        require(self.metrics['submitted'] <= self.max_requests, 'request_budget')
        self.token = await self.lease.acquire(time.monotonic()+self.timeout,
                                             disconnected.done, str(self.metrics['submitted']))
        try:
            if self.process is not None and self.process.returncode is not None:
                await self.kill_child()
            if self.process is None:
                await self.start_child()
            require(not disconnected.done(), 'cancelled')
            forwarded = {**payload, 'stream':False}
            forwarded.pop('stream_options', None)
            status, result = await backend_http(self.backend_port, self.backend_key, '/v1/chat/completions', forwarded)
            require(status == 200 and type(result) is dict and len(result.get('choices', [])) == 1, 'backend_result')
            require(result['choices'][0].get('finish_reason') in ('stop','length','tool_calls'), 'backend_incomplete')
            require(not disconnected.done(), 'cancelled')
            self.metrics['completed'] += 1
            self.release()
            return result
        except BaseException:
            # Never treat an HTTP disconnect, task cancellation or deadline as
            # proof that CUDA generation stopped. Reap before releasing.
            await self.kill_child()
            self.release()
            raise

    async def reply(self, writer, status, result, stream=False):
        if stream:
            choice = result['choices'][0]
            chunk = {k:result[k] for k in ('id','created','model')}
            chunk.update(object='chat.completion.chunk', choices=[dict(index=0,delta=choice['message'],finish_reason=choice['finish_reason'])], usage=result.get('usage', {}))
            body = b'data: '+json.dumps(chunk).encode()+b'\n\ndata: [DONE]\n\n'
            mime = 'text/event-stream'
        else:
            body = json.dumps(result).encode()
            mime = 'application/json'
        writer.write(f'HTTP/1.1 {status} Response\r\nContent-Type: {mime}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode()+body)
        await asyncio.wait_for(writer.drain(), 1)

    async def handle(self, reader, writer):
        current = asyncio.current_task()
        self.tasks.add(current)
        self.connections += 1
        job = disconnect = None
        admitted = False
        try:
            require(self.connections <= 8 and not self.stopping, 'connections')
            first, fields = await asyncio.wait_for(headers(reader), 1)
            require(fields.get('authorization') == 'Bearer '+self.key, 'authorization')
            require('transfer-encoding' not in fields and 'expect' not in fields, 'request_encoding')
            if first == 'GET /health HTTP/1.1':
                await self.reply(writer, 200, self.health())
                return
            require(first == 'POST /v1/chat/completions HTTP/1.1', 'route')
            size = int(fields['content-length'])
            require(0 < size <= MAX_BODY, 'request_bound')
            payload = decode(await asyncio.wait_for(reader.readexactly(size), 1))
            if self.active:
                self.metrics['busy'] += 1
                await self.reply(writer, 429, {'error':{'message':'spark_busy'}})
                return
            self.active = admitted = True
            disconnect = asyncio.create_task(reader.read(1))
            job = asyncio.create_task(self.completion(payload, disconnect))
            done, _ = await asyncio.wait((job,disconnect), timeout=self.timeout, return_when=asyncio.FIRST_COMPLETED)
            if job not in done:
                self.metrics['cancelled' if disconnect in done else 'failed'] += 1
                job.cancel()
                await asyncio.gather(job, return_exceptions=True)
                if disconnect not in done:
                    await self.reply(writer, 504, {'error':{'message':'gpu_deadline'}})
                return
            result = await job
            await self.reply(writer, 200, result, payload.get('stream',False))
        except (OSError, ValueError, KeyError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, LeaseError):
            self.metrics['failed'] += 1
            if not writer.is_closing():
                try:
                    await self.reply(writer, 503, {'error':{'message':'gpu_request_failed'}})
                except OSError:
                    pass
        finally:
            if job is not None and not job.done():
                job.cancel()
                await asyncio.gather(job, return_exceptions=True)
            if disconnect is not None:
                disconnect.cancel()
            if admitted:
                self.active = False
            self.connections -= 1
            writer.close()
            self.tasks.discard(current)

    async def run(self):
        self.initialize()
        done = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, done.set)
        server = None
        try:
            self.token = await self.lease.acquire(time.monotonic()+180, done.is_set)
            startup = asyncio.create_task(self.start_child())
            stop = asyncio.create_task(done.wait())
            try:
                ready, _ = await asyncio.wait((startup,stop), return_when=asyncio.FIRST_COMPLETED)
                if startup not in ready:
                    startup.cancel()
                await startup
            finally:
                stop.cancel()
                if not startup.done():
                    startup.cancel()
                await asyncio.gather(startup, return_exceptions=True)
            self.release()
            server = await asyncio.start_server(self.handle, '127.0.0.1', self.port, limit=8192, backlog=8)
            try:
                await asyncio.wait_for(done.wait(), self.lifetime)
            except asyncio.TimeoutError:
                pass
        finally:
            self.stopping = True
            if server:
                server.close()
                await server.wait_closed()
            for task in list(self.tasks):
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            await self.kill_child()
            self.release()
            self.lease.close()
            os.close(self.lock)
            self.backend_key_file.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--gpu-lease-root', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--backend-port', type=int, required=True)
    parser.add_argument('--api-key-file', type=Path, required=True)
    parser.add_argument('--lifetime-seconds', type=int, default=600)
    parser.add_argument('--max-requests', type=int, default=32)
    args = parser.parse_args()
    require(1024 <= args.port <= 65535 and 1024 <= args.backend_port <= 65535 and args.port != args.backend_port, 'ports')
    require(1 <= args.lifetime_seconds <= 3600 and 1 <= args.max_requests <= 128, 'budgets')
    m = args.api_key_file.lstat()
    require(stat.S_ISREG(m.st_mode) and m.st_uid == os.geteuid() and m.st_mode & 0o077 == 0 and m.st_nlink == 1 and 16 <= m.st_size <= 128, 'key_file')
    key = args.api_key_file.read_text().strip()
    require(16 <= len(key) <= 128 and key.isascii() and key.isalnum(), 'key_format')
    os.umask(0o077)
    asyncio.run(Gateway(args.runtime_root, args.gpu_lease_root, args.port, args.backend_port, key,
                        Path('/home/jetson/Spark/runtime/llama.cpp/build/bin/llama-server'),
                        Path('/home/jetson/Spark/models/Spark-X2.5-4B.gguf'),
                        args.lifetime_seconds, args.max_requests).run())


if __name__ == '__main__':
    main()
