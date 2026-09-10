#!/usr/bin/env python3
"""NX finite packet source. No RF until an exact GO line arrives on stdin."""
import argparse
import errno
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import time

from rml2018a_campaign import file_hash, require, save, validate_tx


def transmit(root):
    require(root.is_absolute() and root.resolve() == root and root.is_dir(), 'root path')
    require((root/'tx-plan.json').stat().st_size < 16384, 'plan bound')
    require((root/'packet.fc32').stat().st_size <= 26112*8, 'packet bound')
    plan = json.loads((root/'tx-plan.json').read_text())
    payload = (root/'packet.fc32').read_bytes()
    validate_tx(plan, payload)
    with (root/'tx-started.json').open('x') as f:
        json.dump(dict(pid=os.getpid(), run_id=plan['run_id'], batch=plan['batch']), f)
    fifo = root/'packet.fifo'
    os.mkfifo(fifo, 0o600)
    child = None
    fd = None
    audit = dict(status='failed', bytes_written=0, batch=plan['batch'],
                 payload_sha256=plan['payload_sha256'], requested_tx_samples=plan['tx_samples'])

    def abort(sig, frame):
        raise RuntimeError(f'TX stop signal {sig}')

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(sig, abort)
    signal.alarm(55)
    try:
        args = ['/usr/lib/uhd/examples/tx_samples_from_file', '--args', 'type=b200,serial=2508504',
                '--file', str(fifo), '--type', 'float', '--spb', '1024', '--rate', '2100000',
                '--freq', '433920000', '--gain', '70', '--ant', 'TX/RX', '--bw', '1500000',
                '--channel', '0', '--subdev', 'A:A', '--lo-offset', '250000']
        with (root/'tx-uhd.log').open('x') as log:
            child = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
        audit['child_pid'] = child.pid
        end = time.monotonic() + 30
        while fd is None:
            require(child.poll() is None and time.monotonic() < end, 'UHD startup failed')
            try:
                fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as e:
                if e.errno != errno.ENXIO:
                    raise
                time.sleep(.01)
        print(json.dumps(dict(event='ready', pid=os.getpid(), child_pid=child.pid,
                              batch=plan['batch'], payload_sha256=plan['payload_sha256'])), flush=True)
        require(select.select([0], [], [], 10)[0], 'GO deadline')
        require(os.read(0, 128) == b'GO\n', 'explicit GO required')
        audit['go_unix_ns'] = time.time_ns()
        print(json.dumps(dict(event='tx_start', batch=plan['batch'])), flush=True)
        end = time.monotonic() + plan['max_seconds'] + 2
        maximum = plan['tx_samples'] * 8
        while audit['bytes_written'] < maximum:
            require(child.poll() is None and time.monotonic() < end, 'finite TX feed deadline')
            at = audit['bytes_written'] % len(payload)
            chunk = payload[at:at+min(len(payload)-at, maximum-audit['bytes_written'])]
            if select.select([], [fd], [], .02)[1]:
                try:
                    audit['bytes_written'] += os.write(fd, chunk)
                except BlockingIOError:
                    pass
        os.close(fd); fd = None
        require(child.wait(timeout=5) == 0, 'UHD exit failure')
        audit['status'] = 'fed_complete'  # Independent RX marker checks prove delivery.
    except BaseException as e:
        audit['error'] = f'{type(e).__name__}: {e}'
        raise
    finally:
        signal.alarm(0)
        if fd is not None:
            os.close(fd)
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGINT)
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=2)
        audit['child_exit_code'] = None if child is None else child.returncode
        audit['child_stopped'] = child is None or child.poll() is not None
        if (root/'tx-uhd.log').exists():
            audit['uhd_log_sha256'] = file_hash(root/'tx-uhd.log')
        fifo.unlink(missing_ok=True)
        save(root/'tx-summary.json', audit)
    print(json.dumps(dict(event='finished', **audit)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    transmit(parser.parse_args().directory)
