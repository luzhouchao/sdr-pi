#!/usr/bin/env python3
"""NX-only finite B210 engineering source. Waits for explicit GO on stdin."""
if not __debug__:
    raise RuntimeError('optimized Python would disable validation; refusing to run')

import argparse
import errno
import hashlib
import json
import os
import re
from pathlib import Path
import select
import signal
import subprocess
import time


def transmit(root):
    plan = json.loads((root / 'transmission-plan.json').read_text())
    version=plan.get('schema_version',1)
    if version == 5:
        from b210_multiclass_contract import validate
        assert validate(root) == plan
    center=2455000000 if version in (4,5) else 2440000000
    for key, value in dict(center_hz=center,rate_sps=2100000,bandwidth_hz=1500000,
                           tx_channel=0,tx_antenna='TX/RX',
                           split='train',locked_test_read=False).items():
        assert plan[key] == value, key
    configuration = (plan['tx_samples'], plan['tx_nominal_seconds'], plan['tx_gain_db'], plan['complex_peak'])
    if version in (2,3,4,5):
        assert plan['source_unit_samples']==1024 and plan['payload_bytes']==8192
        assert (version==5 or plan['rows']==[102400]) and plan['tx_unit_count']==20480 and plan['uhd_spb']==1024
        allowed=((20971520,10,70,0.2),(20971520,10,70,0.3)) if version==4 else ((20971520,10,70,0.2),)
        assert configuration in allowed, 'unregistered single-row transmission plan'
        spb=1024
    else:
        assert version==1 and plan['payload_bytes']==32768
        assert configuration in ((2100000, 1, 0, 0.1), (2100000, 1, 40, 0.1),
                                 (21000000, 10, 70, 0.2)), 'unregistered transmission plan'
        spb=10000
    offset=plan.get('tx_lo_offset_hz',0)
    if version==5:
        assert offset==250000 and plan['tx_requested_lo_hz']==2455250000
    elif version==4:
        assert type(offset) is int and offset==250000
        assert plan['tx_requested_lo_hz']==2455250000 and plan['diagnostic_contract']=='b210_2455_margin_v1'
        assert plan['parent_payload_sha256']=='c8e3d54629eb7dde75e6a49554090f570522e7b438d2602dce85a18cd1d771f9'
        assert plan['source_gain_multiplier']==(1. if plan['complex_peak']==.2 else 1.5)
    elif version==3:
        assert type(offset) is int and offset in (-250000,0,250000), 'unregistered LO offset'
        assert plan['tx_requested_lo_hz']==2440000000+offset
        assert plan['diagnostic_contract']=='b210_1024_lo_offset_v1'
    else:
        assert offset==0, 'LO offset requires version 3'
    payload = (root / 'train-tile.fc32').read_bytes()
    assert len(payload) == plan['payload_bytes'] and hashlib.sha256(payload).hexdigest() == plan['payload_sha256']
    fifo = root / 'tx.fc32.fifo'
    os.mkfifo(fifo, 0o600)
    child = None
    fd = None
    audit = dict(status='failed',payload_sha256=plan['payload_sha256'],bytes_written=0,
                 max_samples=plan['tx_samples'],rate_sps=2100000,nominal_seconds=plan['tx_nominal_seconds'])
    if version in (3,4,5):audit.update(tx_lo_offset_hz=offset,tx_requested_lo_hz=center+offset)
    if version in (4,5):audit.update(center_hz=center,complex_peak=plan['complex_peak'])
    if version==5:audit.update(case_id=plan['case_id'],class_id=plan['class_id'],rows=plan['rows'],source_iq_sha256=plan['source_iq_sha256'])
    # Signal handlers unwind finally; closing stdin before GO also aborts.
    def abort(signum, frame):
        raise RuntimeError('stop signal ' + str(signum))
    signal.signal(signal.SIGTERM, abort)
    signal.signal(signal.SIGINT, abort)
    try:
        args = ['/usr/lib/uhd/examples/tx_samples_from_file','--args','type=b200,serial=2508504',
                '--file',str(fifo),'--type','float','--spb',str(spb),'--rate','2100000',
                '--freq',str(center),'--gain',str(plan['tx_gain_db']),'--ant','TX/RX','--bw','1500000',
                '--channel','0','--subdev','A:A']
        if version in (3,4,5):args.extend(['--lo-offset',str(offset)])
        with (root / 'tx-uhd.log').open('x') as log:
            child = subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT)
        audit['child_pid'] = child.pid
        deadline = time.monotonic() + 40
        while fd is None:
            assert child.poll() is None, 'UHD exited before FIFO ready'
            assert time.monotonic() < deadline, 'UHD startup timeout'
            try:
                fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as error:
                if error.errno != errno.ENXIO:
                    raise
                time.sleep(.01)
        print(json.dumps(dict(event='ready',pid=os.getpid(),child_pid=child.pid)),flush=True)
        assert select.select([0], [], [], 20)[0], 'GO timeout'
        assert os.read(0, 128).strip() == b'GO', 'missing explicit GO'
        started = time.monotonic()
        audit['go_unix_ns'] = time.time_ns()
        print(json.dumps(dict(event='tx_start',go_unix_ns=audit['go_unix_ns'])),flush=True)
        total = plan['tx_samples'] * 8
        sent = 0
        while sent < total:
            assert time.monotonic() - started < plan['tx_nominal_seconds'] + 1, 'finite feed deadline exceeded'
            assert child.poll() is None, 'UHD exited during feed'
            payload_offset = sent % len(payload)
            chunk = payload[payload_offset:payload_offset + min(len(payload)-payload_offset, total-sent)]
            if select.select([], [fd], [], .02)[1]:
                try:
                    sent += os.write(fd, chunk)
                    audit['bytes_written'] = sent
                except BlockingIOError:
                    pass
        os.close(fd);fd = None
        audit['feed_seconds'] = time.monotonic() - started
        code = child.wait(timeout=5)
        assert code == 0, 'UHD failed'
        log_bytes = (root / 'tx-uhd.log').read_bytes()
        audit['uhd_log_sha256'] = hashlib.sha256(log_bytes).hexdigest()
        audit['uhd_async_markers'] = re.findall(r'(?m)^[US]+$', log_bytes.decode(errors='replace'))
        audit['status'] = 'sent'  # Bytes fed; RF delivery is independently checked at P201.
        print(json.dumps(audit),flush=True)
    finally:
        if fd is not None:
            os.close(fd)
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGINT)
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill();child.wait(timeout=2)
        audit['child_exit_code'] = None if child is None else child.returncode
        audit['child_stopped'] = child is None or child.poll() is not None
        fifo.unlink()
        (root / 'tx-summary.json').write_text(json.dumps(audit,indent=2)+'\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory', type=Path, required=True)
    a = p.parse_args()
    root = a.directory
    assert root.resolve() == root and root.parent == Path('/var/tmp/sdrharness-dev')
    transmit(root)


if __name__ == '__main__':
    main()
