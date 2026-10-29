"""Cross-process GPU inference lease, inherited by an owned model child.

Never unlink/replace the lock file. Only release after synchronous completion
or confirmed child reaping. A supervisor SIGKILL retains the lock in its child
until parent-death SIGKILL has closed the last inherited descriptor.
"""
import asyncio
import fcntl
import json
import os
from pathlib import Path
import secrets
import stat
import time


class LeaseError(Exception):
    pass


class GpuLease:
    def __init__(self, root: Path, owner: str):
        if not root.is_absolute() or root.resolve() != root or owner not in ('spark', 'mamba'):
            raise LeaseError('lease_identity')
        root.mkdir(mode=0o700, exist_ok=True)
        m = root.lstat()
        if not stat.S_ISDIR(m.st_mode) or m.st_uid != os.geteuid() or m.st_mode & 0o077:
            raise LeaseError('lease_directory')
        self.path = root / 'inference.lock'
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        m = os.fstat(self.fd)
        if not stat.S_ISREG(m.st_mode) or m.st_nlink != 1 or m.st_uid != os.geteuid() or m.st_mode & 0o077:
            os.close(self.fd)
            raise LeaseError('lease_file')
        self.identity = (m.st_dev, m.st_ino)
        self.owner, self.instance = owner, secrets.token_hex(16)
        self.held = False
        self.serial = 0
        self.metrics = dict(acquired=0, released=0, wait_us=0, held_us=0, cancelled=0, expired=0)
        self.started = None
        self.events = []

    def check(self):
        m = self.path.lstat()
        if (m.st_dev, m.st_ino) != self.identity or not stat.S_ISREG(m.st_mode):
            raise LeaseError('lease_replaced')

    async def acquire(self, deadline, cancelled=lambda: False, request='startup'):
        if self.held:
            raise LeaseError('lease_reentrant')
        started = time.monotonic_ns()
        while True:
            if cancelled():
                self.metrics['cancelled'] += 1
                raise LeaseError('cancelled')
            if time.monotonic() >= deadline:
                self.metrics['expired'] += 1
                raise LeaseError('deadline')
            self.check()
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(.005)
        self.held = True
        self.started = time.monotonic_ns()
        self.serial += 1
        self.metrics['acquired'] += 1
        self.metrics['wait_us'] += (self.started-started)//1000
        self.event('acquire', request)
        return (self.instance, self.serial)

    def event(self, kind, request):
        event = dict(event=kind, owner=self.owner, instance=self.instance,
                     serial=self.serial, request=str(request)[:96], monotonic_ns=time.monotonic_ns())
        self.events.append(event)
        self.events = self.events[-32:]
        # Bounded caller lifetime; metadata only, no prompt/IQ/model result.
        print(json.dumps({'gpu_lease':event}), flush=True)

    def release(self, token):
        if not self.held or token != (self.instance, self.serial):
            raise LeaseError('lease_stale_release')
        self.check()
        self.event('release', '')
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        self.held = False
        self.metrics['released'] += 1
        self.metrics['held_us'] += (time.monotonic_ns()-self.started)//1000

    def close(self):
        # Closing while a child remains alive deliberately leaves its inherited
        # lock intact. Callers must reap their child before ordinary close.
        os.close(self.fd)
