#!/usr/bin/env python3
"""Bounded RF-v1 batch supervisor. No model runtime is imported in this process."""
import argparse
import asyncio
import ctypes
from collections import deque
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import stat
import struct
import time

LIBC = ctypes.CDLL(None, use_errno=True)
ROOT = Path(__file__).resolve().parents[3]
WORKER = ROOT / 'jetson-agx/sdrharness/scripts/amc-mamba-worker.py'
PROFILE = ROOT / 'jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json'
RECEIPT = ROOT / 'jetson-agx/sdrharness/config/amc/rf-v1-recognizer-admission.candidate.json'
RECEIPT_HASH = '3c802706d35852e4e1ee45b3db2285b0790a7deac331b8c948c4aa6fc1147b83'
FRAME = 65536
SPOOL_BYTES = 32768
BATCH_NAME = re.compile(r'^batch-[a-f0-9]{64}-[1-9][0-9]{0,19}-[1-9][0-9]{0,19}\.f32$')


class ContractError(Exception):
    pass


def require(ok, code):
    if not ok:
        raise ContractError(code)


def exact(value, keys):
    require(type(value) is dict and set(value) == set(keys.split()), 'shape')


def positive(value):
    return type(value) is int and 0 < value < 2**64


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_key')
        result[key] = value
    return result


def decode(data):
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda _: require(False, 'nonfinite'))


def private_directory(path):
    require(path.is_absolute() and path.resolve() == path, 'runtime_path')
    path.mkdir(mode=0o700, exist_ok=True)
    m = path.lstat()
    require(stat.S_ISDIR(m.st_mode) and m.st_uid == os.geteuid() and m.st_mode & 0o077 == 0, 'runtime_permissions')


def spool_metadata(path, complete=True):
    m = path.lstat()
    require(stat.S_ISREG(m.st_mode) and m.st_uid == os.geteuid()
            and m.st_mode & 0o077 == 0 and m.st_nlink == 1 and (m.st_size == SPOOL_BYTES if complete else 0 <= m.st_size <= SPOOL_BYTES), 'spool_metadata')
    return m


def remove_spool(path, identity=None, complete=True):
    if not path.exists() and not path.is_symlink():
        return
    m = spool_metadata(path, complete)
    if identity is not None:
        require((m.st_dev, m.st_ino) == identity, 'spool_identity')
    path.unlink()


async def exchange(path, payload, timeout, limit=16384):
    async def work():
        reader, writer = await asyncio.open_unix_connection(str(path), limit=limit)
        try:
            data = json.dumps(payload, allow_nan=False, separators=(',', ':')).encode() + b'\n'
            require(len(data) <= limit, 'frame_size')
            writer.write(data)
            await writer.drain()
            response = await reader.readline()
            require(response.endswith(b'\n') and len(response) <= limit, 'truncated_frame')
            return decode(response)
        finally:
            writer.close()
            await writer.wait_closed()
    return await asyncio.wait_for(work(), timeout)


class Job:
    def __init__(self, request, path, identity, accepted):
        self.request = request
        self.key = (request['session_generation'], request['request_id'])
        self.path, self.identity = path, identity
        self.accepted = accepted
        self.deadline = self.accepted + request['timeout_ms'] / 1000
        self.done = asyncio.get_running_loop().create_future()
        self.cancel = asyncio.Event()
        self.window = None
        self.expiry = None


class Supervisor:
    def __init__(self, runtime, python, max_batches=128, max_restarts=4, startup_seconds=120,
                 command_factory=None):
        self.root, self.python = runtime, python
        self.incoming, self.owned = runtime / 'incoming', runtime / 'owned'
        self.socket, self.worker_socket = runtime / 'supervisor.sock', runtime / 'worker.sock'
        self.control_socket = runtime / 'control.sock'
        self.instance = secrets.token_hex(32)
        self.process = None
        self.health = None
        self.worker_id = None
        self.lock = None
        self.active = None
        self.pending = None
        self.wakeup = asyncio.Event()
        self.stopping = False
        self.fault = None
        self.highwater = (0, 0)
        self.minimum_generation = 1
        self.recent = deque(maxlen=8)
        self.connections = 0
        self.control_connections = 0
        self.max_batches, self.max_restarts = max_batches, max_restarts
        self.startup_seconds = startup_seconds
        self.command_factory = command_factory
        data = RECEIPT.read_bytes()
        require(digest(data) == RECEIPT_HASH, 'receipt_hash')
        self.receipt = decode(data)
        self.metrics = dict(submitted=0, completed=0, busy=0, cancelled=0, expired=0,
                            failed=0, crashes=0, restarts=0, removed=0, queue_wait_us=0,
                            total_us=0, connection_drops=0)

    def initialize(self):
        private_directory(self.root)
        lock_path = self.root / 'supervisor.lock'
        self.lock = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        m = os.fstat(self.lock)
        require(stat.S_ISREG(m.st_mode) and m.st_uid == os.geteuid() and m.st_mode & 0o077 == 0 and m.st_nlink == 1, 'lock_permissions')
        # Child inherits the lock: a killed parent cannot race a still-live CUDA child.
        started = time.monotonic()
        try:
            while True:
                try:
                    fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    # A responsive owner is a duplicate, never a takeover. After
                    # SIGKILL, GPU teardown may briefly retain the inherited fd.
                    owner_alive = False
                    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as probe:
                        probe.settimeout(.02)
                        try:
                            probe.connect(str(self.control_socket))
                            owner_alive = True
                        except OSError:
                            pass
                    if owner_alive or time.monotonic()-started >= 3:
                        raise
                    time.sleep(.025)
        except OSError:
            os.close(self.lock)
            self.lock = None
            raise
        self.metrics['lock_wait_us'] = int((time.monotonic()-started)*1000000)
        for directory in (self.incoming, self.owned):
            private_directory(directory)
            entries = list(directory.iterdir())
            require(len(entries) <= 16, 'orphan_bound')
            for path in entries:
                require(BATCH_NAME.fullmatch(path.name), 'unknown_spool')
                spool_metadata(path, complete=False)
            for path in entries:
                remove_spool(path, complete=False)
                self.metrics['removed'] += 1
        for path in (self.socket, self.control_socket, self.worker_socket):
            if path.exists() or path.is_symlink():
                require(stat.S_ISSOCK(path.lstat().st_mode), 'socket_type')
                path.unlink()

    async def start_worker(self):
        require(self.process is None, 'worker_already_owned')
        require(self.metrics['restarts'] <= self.max_restarts, 'restart_budget')
        parent = os.getpid()

        def child_setup():
            # Linux parent-death signal plus the inherited flock closes supervisor SIGKILL races.
            if LIBC.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent:
                os._exit(127)

        command = (self.command_factory(self.worker_socket, self.owned) if self.command_factory else
                   [str(self.python), str(WORKER), '--rf-v1-profile', str(PROFILE),
                    '--socket', str(self.worker_socket), '--spool-root', str(self.owned),
                    '--max-requests', str(self.max_batches * 4 + 16)])
        spawning = asyncio.create_task(asyncio.create_subprocess_exec(
            *command, cwd=ROOT, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True, pass_fds=(self.lock,), preexec_fn=child_setup))
        try:
            self.process = await asyncio.shield(spawning)
        except asyncio.CancelledError:
            # Shutdown must retain the PID even if cancellation lands between
            # fork/exec and create_subprocess_exec returning the process object.
            self.process = await spawning
            raise
        deadline = time.monotonic() + self.startup_seconds
        while not self.stopping:
            require(self.process.returncode is None, 'startup_exit')
            require(time.monotonic() < deadline, 'startup_deadline')
            q = dict(protocol_version=1, operation='admission_health', request_id=1,
                     session_generation=max(1, self.minimum_generation), nonce=secrets.token_hex(32))
            try:
                h = await exchange(self.worker_socket, q, .25)
            except (OSError, asyncio.TimeoutError):
                await asyncio.sleep(.025)
                continue
            exact(h, 'schema_version schema_id protocol_version request_id session_generation nonce worker_instance_id started_at_unix_ms observed_at_unix_ms status identity admission_sha256 production_enabled')
            require(all(h[k] == q[k] for k in ('protocol_version', 'request_id', 'session_generation', 'nonce'))
                    and h['schema_version'] == 1 and h['schema_id'] == 'recognizer_health_v1'
                    and h['status'] == 'ready' and h['identity'] == self.receipt['identity']
                    and h['admission_sha256'] == RECEIPT_HASH and h['production_enabled'] is False
                    and re.fullmatch('[a-f0-9]{64}', h['worker_instance_id']) is not None
                    and abs(h['observed_at_unix_ms'] - time.time_ns() // 1000000) <= 1000, 'worker_health')
            self.health, self.worker_id = h, h['worker_instance_id']
            return
        raise ContractError('stopping')

    async def kill_worker(self):
        self.health = None
        if self.process is not None:
            if self.process.returncode is None:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            await asyncio.wait_for(self.process.wait(), 2)
            self.process = None
        if self.worker_socket.exists():
            require(stat.S_ISSOCK(self.worker_socket.lstat().st_mode), 'worker_socket_type')
            self.worker_socket.unlink()

    def status(self):
        return dict(schema_version=1, operation='health', instance_id=self.instance,
                    worker_instance_id=self.worker_id, ready=bool(self.health and not self.fault and not self.stopping and self.metrics['submitted'] < self.max_batches),
                    recognizer_available=False, minimum_generation=self.minimum_generation,
                    active=None if self.active is None else dict(request_id=self.active.key[1], session_generation=self.active.key[0], window=self.active.window),
                    queue_depth=int(self.pending is not None), queue_capacity=1,
                    worker_pid=None if self.process is None else self.process.pid,
                    fault=self.fault, metrics=dict(self.metrics))

    def validate_submit(self, q):
        exact(q, 'schema_version operation instance_id worker_instance_id request_id session_generation timeout_ms requests')
        require(type(q['schema_version']) is int and q['schema_version'] == 1 and q['operation'] == 'submit', 'protocol')
        require(q['instance_id'] == self.instance and q['worker_instance_id'] == self.worker_id, 'instance')
        require(self.health is not None and self.fault is None and not self.stopping, 'unavailable')
        require(positive(q['request_id']) and positive(q['session_generation'])
                and q['session_generation'] >= self.minimum_generation, 'generation')
        key = (q['session_generation'], q['request_id'])
        require(key > self.highwater, 'replay')
        require(type(q['timeout_ms']) is int and 50 <= q['timeout_ms'] <= 5000, 'deadline')
        require(type(q['requests']) is list and len(q['requests']) == 4, 'windows')
        filename = f'batch-{self.instance}-{key[0]}-{key[1]}.f32'
        source = self.incoming / filename
        first = None
        for i, r in enumerate(q['requests']):
            exact(r, 'protocol_version request_id session_generation candidate_id iq max_latency_ms rf_v1')
            exact(r['iq'], 'storage sample_format layout normalization samples_per_channel sample_rate_hz center_hz')
            iq, c = r['iq'], r['rf_v1']
            exact(iq['storage'], 'path offset_bytes length_bytes')
            exact(c, 'profile_sha256 preprocess_sha256 checkpoint_sha256 batch_sha256 batch_request_id source_sweep_id source_request_id source_session_generation source_sequence capture_request_id capture_sequence window_index')
            require(type(r['protocol_version']) is int and r['protocol_version'] == 1 and positive(r['request_id']) and positive(r['session_generation']) and r['request_id'] == key[1] + i < 2**64
                    and r['session_generation'] == key[0] and type(r['max_latency_ms']) is int and r['max_latency_ms'] == 5000
                    and isinstance(r['candidate_id'], str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', r['candidate_id']) is not None
                    and iq['sample_format'] == 'f32_le' and iq['layout'] == 'planar_iq'
                    and iq['normalization'] == 'capture_unit_rms' and iq['samples_per_channel'] == 1024
                    and type(iq['samples_per_channel']) is int and type(iq['sample_rate_hz']) is int and iq['sample_rate_hz'] == 2100000 and type(iq['center_hz']) is int and 70000000 <= iq['center_hz'] <= 6000000000
                    and iq['storage'] == dict(path=str(source), offset_bytes=i * 8192, length_bytes=8192)
                    and type(iq['storage']['offset_bytes']) is int and type(iq['storage']['length_bytes']) is int
                    and type(c['window_index']) is int and c['window_index'] == i and positive(c['batch_request_id']) and c['batch_request_id'] == key[1], 'window_contract')
            for name in ('profile_sha256', 'preprocess_sha256', 'checkpoint_sha256'):
                require(c[name] == self.receipt['identity'][name], 'identity')
            require(isinstance(c['batch_sha256'], str) and re.fullmatch('[a-f0-9]{64}', c['batch_sha256']), 'batch_hash')
            for name in ('source_request_id', 'source_session_generation', 'source_sequence', 'capture_request_id', 'capture_sequence'):
                require(positive(c[name]), 'source')
            require(isinstance(c['source_sweep_id'], str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', c['source_sweep_id']), 'source')
            comparable = (r['candidate_id'], iq['center_hz'], {k: v for k, v in c.items() if k != 'window_index'})
            if first is None:
                first = comparable
            require(first == comparable, 'mixed_batch')
        m = spool_metadata(source)
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            actual = os.fstat(fd)
            require((m.st_dev, m.st_ino) == (actual.st_dev, actual.st_ino), 'spool_race')
            data = os.read(fd, SPOOL_BYTES + 1)
        finally:
            os.close(fd)
        require(len(data) == SPOOL_BYTES and digest(data) == q['requests'][0]['rf_v1']['batch_sha256'], 'iq_hash')
        values = [v[0] for v in struct.iter_unpack('<f', data)]
        require(all(math.isfinite(v) for v in values) and abs(math.sqrt(sum(v*v for v in values)/4096)-1) <= 1e-6, 'iq_rms')
        return source, (m.st_dev, m.st_ino)

    def submit(self, q):
        accepted = time.monotonic()
        source, identity = self.validate_submit(q)
        if self.pending is not None or (self.active and q['session_generation'] != self.active.key[0]):
            self.metrics['busy'] += 1
            raise ContractError('busy')
        require(self.metrics['submitted'] < self.max_batches, 'batch_budget')
        target = self.owned / source.name
        require(not target.exists(), 'spool_collision')
        source.rename(target)
        job = Job(q, target, identity, accepted)
        self.highwater = job.key
        self.pending = job
        self.metrics['submitted'] += 1
        self.wakeup.set()
        job.expiry = asyncio.create_task(self.expire_pending(job))
        return job

    async def expire_pending(self, job):
        await asyncio.sleep(max(0,job.deadline-time.monotonic()))
        if self.pending is job:
            self.pending = None
            self.finish(job,'deadline')

    def finish(self, job, status, outputs=None):
        try:
            remove_spool(job.path, job.identity)
        except (OSError, ContractError):
            self.fault = 'cleanup_failed'
            self.health = None
            raise
        if job.expiry is not None and job.expiry is not asyncio.current_task():
            job.expiry.cancel()
        self.metrics['removed'] += 1
        self.metrics[{'ok':'completed', 'cancelled':'cancelled', 'deadline':'expired'}.get(status, 'failed')] += 1
        self.metrics['total_us'] += int((time.monotonic()-job.accepted)*1000000)
        reply = dict(schema_version=1, operation='submit', instance_id=self.instance,
                     worker_instance_id=job.request['worker_instance_id'], request_id=job.key[1],
                     session_generation=job.key[0], status=status, spool_removed=True,
                     outputs=outputs if status == 'ok' else [])
        self.recent.append({**reply,'outputs':[]})
        if not job.done.done():
            job.done.set_result(reply)

    async def cancel_job(self, job):
        if job is self.pending:
            self.pending = None
            self.finish(job, 'cancelled')
        else:
            job.cancel.set()
        return await asyncio.wait_for(asyncio.shield(job.done), 3)

    async def dispatch(self, q):
        if q.get('operation') == 'health':
            exact(q, 'schema_version operation')
            require(type(q['schema_version']) is int and q['schema_version'] == 1, 'protocol')
            return self.status()
        if q.get('operation') == 'cancel':
            exact(q, 'schema_version operation instance_id worker_instance_id request_id session_generation')
            require(type(q['schema_version']) is int and q['schema_version'] == 1 and q['instance_id'] == self.instance, 'instance')
            require(positive(q['request_id']) and positive(q['session_generation']) and type(q['worker_instance_id']) is str and re.fullmatch('[a-f0-9]{64}',q['worker_instance_id']), 'cancel_identity')
            matches = [j for j in (self.active, self.pending) if j and j.key == (q['session_generation'], q['request_id'])
                       and j.request['worker_instance_id'] == q['worker_instance_id']]
            if not matches:
                cached = [r for r in self.recent if all(r[k]==q[k] for k in ('instance_id','worker_instance_id','request_id','session_generation'))]
                require(len(cached)==1,'not_active')
                return {**cached[0],'operation':'cancel'}
            require(len(matches) == 1, 'not_active')
            result = await self.cancel_job(matches[0])
            return {**result, 'operation':'cancel', 'outputs':[]}
        raise ContractError('operation')

    async def handle(self, reader, writer, control=False):
        if (self.control_connections >= 4 if control else self.connections >= 8):
            self.metrics['connection_drops'] += 1
            writer.close()
            return
        if control:
            self.control_connections += 1
        else:
            self.connections += 1
        job = None
        eof_task = None
        try:
            data = await asyncio.wait_for(reader.readline(), 1)
            require(len(data) <= FRAME and data.endswith(b'\n'), 'frame')
            q = decode(data)
            require(type(q) is dict, 'shape')
            if q.get('operation') == 'submit':
                require(not control, 'control_only')
                job = self.submit(q)
                eof_task = asyncio.create_task(reader.read(1))
                done, _ = await asyncio.wait([job.done, eof_task], return_when=asyncio.FIRST_COMPLETED)
                if eof_task in done and not job.done.done():
                    await self.cancel_job(job)
                    return
                reply = await job.done
            else:
                reply = await self.dispatch(q)
            payload = json.dumps(reply, allow_nan=False, separators=(',', ':')).encode()+b'\n'
            require(len(payload) <= FRAME, 'reply_bound')
            writer.write(payload)
            await asyncio.wait_for(writer.drain(), 1)
        except (ContractError, ValueError, OSError, asyncio.TimeoutError) as error:
            if job is not None and not job.done.done():
                job.cancel.set()
            if not writer.is_closing():
                writer.write(json.dumps(dict(schema_version=1, operation='error', code=str(error)[:64])).encode()+b'\n')
                try:
                    await asyncio.wait_for(writer.drain(), .25)
                except (OSError, asyncio.TimeoutError):
                    pass
        finally:
            if eof_task is not None:
                eof_task.cancel()
            writer.close()
            if control:
                self.control_connections -= 1
            else:
                self.connections -= 1

    async def scheduler(self):
        while not self.stopping:
            if self.health is None:
                try:
                    await self.start_worker()
                except (ContractError, OSError, asyncio.TimeoutError, ValueError) as error:
                    await self.kill_worker()
                    self.fault = str(error)[:64]
                    return
            if self.pending is None:
                self.wakeup.clear()
                try:
                    await asyncio.wait_for(self.wakeup.wait(), .05)
                except asyncio.TimeoutError:
                    if self.process and self.process.returncode is not None:
                        await self.invalidate('worker_exit')
                continue
            job, self.pending = self.pending, None
            self.active = job
            self.metrics['queue_wait_us'] += int((time.monotonic()-job.accepted)*1000000)
            status, outputs = 'ok', []
            try:
                for i, request in enumerate(job.request['requests']):
                    job.window = i
                    require(time.monotonic() < job.deadline, 'deadline')
                    require(not job.cancel.is_set(), 'cancelled')
                    request = {**request, 'iq':{**request['iq'], 'storage':{**request['iq']['storage'], 'path':str(job.path)}}}
                    inference = asyncio.create_task(exchange(self.worker_socket, request, max(.001,job.deadline-time.monotonic())))
                    cancellation = asyncio.create_task(job.cancel.wait())
                    try:
                        done, _ = await asyncio.wait([inference,cancellation], return_when=asyncio.FIRST_COMPLETED)
                        require(cancellation not in done, 'cancelled')
                        reply = await inference
                    finally:
                        inference.cancel()
                        cancellation.cancel()
                        await asyncio.gather(inference,cancellation,return_exceptions=True)
                    require(time.monotonic() < job.deadline and not job.cancel.is_set(), 'deadline' if not job.cancel.is_set() else 'cancelled')
                    require(reply.get('status') == 'ok' and reply.get('request_id') == request['request_id'] and reply.get('session_generation') == job.key[0], 'worker_response')
                    out = reply.get('output', {})
                    require(out.get('candidate_id') == request['candidate_id'] and out.get('rf_v1', {}).get('contract') == request['rf_v1'], 'worker_correlation')
                    exact(out,'candidate_id label confidence alternatives backend timing rf_v1')
                    exact(out['rf_v1'],'contract request_id session_generation compute logits')
                    exact(out['backend'],'runtime runtime_version model_id model_sha256 threads')
                    exact(out['timing'],'map_us preprocess_us inference_us total_us')
                    logits=out['rf_v1']['logits']
                    require(out['rf_v1']['request_id']==request['request_id'] and out['rf_v1']['session_generation']==job.key[0]
                            and out['rf_v1']['compute']=='cuda_fp16_autocast' and type(logits) is list and len(logits)==24
                            and all(type(v) in (int,float) and math.isfinite(v) for v in logits)
                            and out['backend']['model_id']==self.receipt['identity']['model_id']
                            and out['backend']['model_sha256']==self.receipt['identity']['checkpoint_sha256']
                            and type(out['backend']['threads']) is int and 1<=out['backend']['threads']<=4
                            and all(type(v) is int and 0<=v<=5000000 for v in out['timing'].values())
                            and sum(out['timing'][k] for k in ('map_us','preprocess_us','inference_us'))<=out['timing']['total_us']
                            and type(out['alternatives']) is list and len(out['alternatives'])<=8
                            and type(out['confidence']) in (int,float) and math.isfinite(out['confidence']) and 0<=out['confidence']<=1,'worker_output')
                    top = max(range(24),key=lambda k:logits[k])
                    probabilities = [math.exp(v-logits[top]) for v in logits]
                    total=sum(probabilities)
                    require(out['label']==f'provisional:{top:02}' and abs(out['confidence']-probabilities[top]/total)<1e-6,'worker_prediction')
                    seen={out['label']}
                    for alt in out['alternatives']:
                        exact(alt,'label confidence')
                        require(type(alt['label']) is str and re.fullmatch(r'provisional:[0-9]{2}',alt['label']) and alt['label'] not in seen,'worker_alternative')
                        index=int(alt['label'].split(':')[1])
                        require(index<24 and type(alt['confidence']) in (int,float) and math.isfinite(alt['confidence']) and abs(alt['confidence']-probabilities[index]/total)<1e-6,'worker_alternative')
                        seen.add(alt['label'])
                    outputs.append(out)
            except asyncio.TimeoutError:
                status = 'deadline'
            except (ContractError, OSError, ValueError) as error:
                status = str(error) if str(error) in ('cancelled', 'deadline') else 'worker_error'
            if status != 'ok':
                await self.invalidate(status, finish_active=False)
            self.finish(job, status, outputs)
            self.active = None

    async def invalidate(self, reason, finish_active=True):
        # No success/cancel acknowledgment until the child is reaped and its spool removed.
        await self.kill_worker()
        self.minimum_generation = max(self.minimum_generation, self.highwater[0]+1)
        self.metrics['restarts'] += 1
        if reason not in ('cancelled','deadline'):
            self.metrics['crashes'] += 1
        if self.pending:
            self.finish(self.pending, 'worker_restarted')
            self.pending = None
        if finish_active and self.active:
            self.finish(self.active, 'worker_error')
            self.active = None
        await asyncio.sleep(.05)

    async def run(self, lifetime_seconds):
        self.initialize()
        server = await asyncio.start_unix_server(self.handle, path=str(self.socket), backlog=8, limit=FRAME)
        control = await asyncio.start_unix_server(lambda r,w:self.handle(r,w,True), path=str(self.control_socket), backlog=4, limit=16384)
        os.chmod(self.control_socket, 0o600)
        os.chmod(self.socket, 0o600)
        self.server = server
        task = asyncio.create_task(self.scheduler())
        def failed(future):
            if not future.cancelled() and future.exception() is not None:
                self.fault = 'scheduler_failure'
                self.health = None
                asyncio.create_task(self.kill_worker())
        task.add_done_callback(failed)
        done = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, done.set)
        try:
            await asyncio.wait_for(done.wait(), lifetime_seconds)
        except asyncio.TimeoutError:
            pass
        finally:
            self.stopping = True
            server.close()
            control.close()
            await server.wait_closed()
            await control.wait_closed()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await self.kill_worker()
            for job in (self.pending,self.active):
                if job and not job.done.done():
                    self.finish(job,'shutdown')
            for path in (self.socket,self.control_socket):
                if path.exists():
                    path.unlink()
            os.close(self.lock)
            self.lock = None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root',type=Path,required=True)
    parser.add_argument('--worker-python',type=Path,default=ROOT/'local-assets/amc-eval/runtime/venv/bin/python')
    parser.add_argument('--max-batches',type=int,default=128)
    parser.add_argument('--max-restarts',type=int,default=4)
    parser.add_argument('--lifetime-seconds',type=int,default=600)
    args=parser.parse_args()
    require(1 <= args.max_batches <= 10000 and 0 <= args.max_restarts <= 16 and 1 <= args.lifetime_seconds <= 3600,'budget')
    os.umask(0o077)
    asyncio.run(Supervisor(args.runtime_root,args.worker_python,args.max_batches,args.max_restarts).run(args.lifetime_seconds))


if __name__=='__main__':
    main()
