#!/usr/bin/env python3
"""Six fixed RX1 termination or antenna-return captures; no TX or model invocation."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

if not __debug__:
    raise RuntimeError('validation assertions required')
REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('termination_bg', Path(__file__).with_name('diagnose-b210-background.py'))
bg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bg)
ROOT = Path('/var/tmp/sdrharness-dev/p201-termination-20260909a')
BINARY = Path('/home/jetson/.local/lib/sdrharness/bin/sdr-agent')
STATE = bg.rf.STATE_COMMAND.replace(' /sys/bus/iio/devices/iio:device*/scan_elements',
    ' /sys/bus/iio/devices/iio:device0/in_voltage1_gain_control_mode'
    ' /sys/bus/iio/devices/iio:device0/in_voltage1_hardwaregain'
    ' /sys/bus/iio/devices/iio:device0/in_voltage1_rf_port_select'
    ' /sys/bus/iio/devices/iio:device*/scan_elements')
NX = ['ssh', '-F', '/home/jetson/.ssh/config', '-o', 'BatchMode=yes',
      '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=5', 'nx']


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def command(args, timeout=10):
    p = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f'command exit {p.returncode}: {p.stderr[-1000:]}')
    return p.stdout


def ssh(script):
    return command([*bg.rf.SSH, script])


def tx_preflight():
    assert command([*NX, 'hostname; whoami']).splitlines() == ['wheeltec', 'wheeltec']
    assert command([*NX, 'cat /sys/bus/usb/devices/2-1.2/serial']).strip() == '2508504'
    processes = command([*NX, 'ps -eo pid,comm,args'])
    matches = [line for line in processes.splitlines()
               if any(term in line.lower() for term in ('uhd', 'b210', 'tx_wave', 'gnuradio'))]
    assert not matches, 'possible transmitter process present'
    # No UHD initialization: inspect kernel ownership of the USB device only.
    command([*NX, 'sudo -n true && command -v fuser && test -c /dev/bus/usb/002/003'])
    holders = command([*NX, 'sudo -n fuser /dev/bus/usb/002/003 2>/dev/null || test "$?" -eq 1'])
    assert not holders.strip(), 'external SDR USB device is in use'
    return dict(host='wheeltec', user='wheeltec', usb_serial='2508504',
                matching_tx_processes=matches, usb_holder_pids=[],
                evidence='process and USB ownership checks; not an RF power measurement')


def idle():
    connections = ssh('netstat -nt 2>/dev/null')
    assert not any('ESTABLISHED' in line and any(f':{port} ' in line for port in (43110, 30431))
                   for line in connections.splitlines()), 'existing SDR connection; refuse capture'


def restoration(before):
    for _ in range(30):
        after = ssh(STATE)
        if after == before:
            return after
        time.sleep(.1)
    raise RuntimeError('both RX channels / scan masks / buffers not restored')


def compact_stats(raw):
    return {key: value for key, value in bg.stats(raw).items()
            if key not in ('raw_segments', 'filtered_segments')}


def acquire(condition):
    assert ROOT.resolve() == ROOT and not ROOT.exists()
    assert 'torch' not in sys.modules
    password = Path('/home/jetson/.config/sdrharness/p201-root.password')
    assert password.is_file() and not password.is_symlink() and password.stat().st_mode & 0o777 == 0o600
    ROOT.mkdir(mode=0o700)
    scratch = ROOT / 'scratch'
    scratch.mkdir(mode=0o700)
    os.environ.update(TMPDIR=str(scratch), XDG_CACHE_HOME=str(scratch), PYTHONDONTWRITEBYTECODE='1')
    available = shutil.disk_usage(ROOT).free
    assert available > 1572840 + 16 * 1024 * 1024
    generation = int(time.time() * 1000)
    plans = [dict(sweep_id=f'{condition}-{generation+i}', session_generation=generation+i,
        frequencies=dict(kind='centers', centers_hz=[2455000000]), sample_rate_hz=2100000,
        rf_bandwidth_hz=1500000, gain_db=40, settle_ms=500, frame_samples=65535,
        aggregate_frames=1, point_timeout_ms=1000, detection_threshold_db=12.) for i in range(6)]
    remote_paths = [f'/tmp/sdr-agent-dev/agx-sweep-{p["session_generation"]}-0' for p in plans]
    audit = dict(schema_id='p201_input_background_v2', status='preflight', input_condition=condition,
        base_head=command(['git', '-C', REPO, 'rev-parse', 'HEAD']).strip(),
        physical_connection=('operator confirmed original antenna returned to P201 RX1; external TX remains terminated and stopped'
            if condition == 'antenna-return' else 'operator confirmed 50-ohm load on P201 RX1 and previous external TX port'),
        root=str(ROOT), plans=plans, maximum_rx_bytes=1572840, free_bytes_before=available,
        capture_seconds_per_point=65535/2100000, expected_wall_seconds=40, overall_deadline_seconds=120,
        per_controller_deadline_seconds=15, inter_capture_delay_seconds=1,
        p201_transients=remote_paths, nx_transients=[], rows=[],
        stop='SIGINT/SIGTERM to runner; dedicated sdr-agent --mode cancel for active generation',
        controller_sha256=hashlib.sha256(BINARY.read_bytes()).hexdigest(),
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        filter_contract=bg.repair.filter_contract(), analysis_numpy=bg.np.__version__,
        model_windows=0, tx_operations=0, recognizer_available=False, independent_labels=0,
        historical_comparison_only=condition != 'antenna-return',
        comparison_design='sequential termination then antenna; not a bracketed antenna/termination/antenna experiment')
    if condition == 'antenna-return':
        inventory = REPO / 'docs/evidence/P201_TERMINATION_BACKGROUND_EVIDENCE_2026-09-09.json'
        parent = json.loads(inventory.read_text())
        for row in parent['files']:
            path = Path(row['path'])
            assert path.resolve() == path and not path.is_symlink()
            data = path.read_bytes()
            assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
        audit['parent_evidence'] = dict(path=str(inventory), sha256=hashlib.sha256(inventory.read_bytes()).hexdigest(),
                                        audit_path=str(Path(parent['root']) / 'audit.json'))
    save(ROOT / 'audit.json', audit)
    before = None
    try:
        audit['nx_before'] = tx_preflight()
        idle()
        daemon = ssh('pidof sdrd').split()
        assert len(daemon) == 1
        assert ssh(f'readlink /proc/{daemon[0]}/exe').strip() == '/sd/sdr-agent/current/sdrd'
        audit['daemon_pid'] = daemon[0]
        audit['daemon_sha256'] = ssh('sha256sum /sd/sdr-agent/current/sdrd').split()[0]
        if condition == 'antenna-return':
            parent_audit = json.loads(Path(audit['parent_evidence']['audit_path']).read_text())
            for key in ('daemon_sha256', 'controller_sha256', 'filter_contract', 'analysis_numpy'):
                assert audit[key] == parent_audit[key], f'comparison identity changed: {key}'
        audit['health_before'] = json.loads(command([BINARY, '--mode', 'health', '--sdrd', '192.168.1.10:43110']))
        assert audit['health_before']['healthy']
        before = ssh(STATE)
        state = dict(zip(before.splitlines()[::2], before.splitlines()[1::2]))
        assert len(before.splitlines()) % 2 == 0
        assert all(value == '0' for path, value in state.items() if path.endswith(('_en', '/enable')))
        assert all(state[f'/sys/bus/iio/devices/iio:device0/in_voltage{i}_gain_control_mode'] == 'manual' for i in (0, 1))
        audit['radio_before'] = before
        audit['status'] = 'running'
        save(ROOT / 'audit.json', audit)
        print(json.dumps({k: audit[k] for k in ('plans', 'maximum_rx_bytes', 'free_bytes_before', 'root', 'p201_transients', 'stop')}), flush=True)
        for index, plan in enumerate(plans):
            idle()
            assert ssh(STATE) == before
            assert shutil.disk_usage(ROOT).free > 262140 + 8 * 1024 * 1024
            remote = remote_paths[index]
            ssh(f'test ! -e {remote}')
            capture_root = ROOT / f'capture-{index:02d}'
            capture_root.mkdir(mode=0o700)
            save(capture_root / 'plan.json', plan)
            save(ROOT / 'active.json', dict(generation=plan['session_generation'], runner_pid=os.getpid()))
            started = time.time()
            p = subprocess.Popen([str(BINARY), '--mode', 'sweep', '--sdrd', '192.168.1.10:43110',
                '--sigmf-directory', str(capture_root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)
            try:
                out, err = p.communicate(json.dumps(plan), timeout=15)
                (capture_root / 'stderr.log').write_text(err)
                assert p.returncode == 0, err[-2000:]
                save(capture_root / 'report.json', json.loads(out))
                seal, raw = bg.native(capture_root, plan)
                audit['rows'].append(dict(index=index, started_unix=started, elapsed_seconds=time.time()-started,
                                         seal=seal, statistics=compact_stats(raw)))
            except BaseException:
                try:
                    audit['cancel'] = json.loads(command([BINARY, '--mode', 'cancel', '--sdrd',
                        '192.168.1.10:43110', '--session-generation', plan['session_generation']], timeout=6))
                finally:
                    if p.poll() is None:
                        p.terminate()
                        try:
                            p.communicate(timeout=3)
                        except subprocess.TimeoutExpired:
                            p.kill()
                            p.communicate(timeout=3)
                raise
            finally:
                restoration(before)
                ssh(f'test ! -e {remote}')
                save(ROOT / 'audit.json', audit)
            audit['rows'][-1]['radio_restored'] = True
            audit['rows'][-1]['p201_transient_absent'] = True
            print(json.dumps(audit['rows'][-1]), flush=True)
            if index < 5:
                time.sleep(1)
        audit['nx_after'] = tx_preflight()
        audit['status'] = 'completed'
    except BaseException as error:
        audit.update(status='failed', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        signal.alarm(0)
        try:
            if before is not None:
                audit['radio_after'] = restoration(before)
                audit['restored'] = audit['radio_after'] == before
                assert ssh('pidof sdrd').split() == [audit['daemon_pid']]
                assert ssh('sha256sum /sd/sdr-agent/current/sdrd').split()[0] == audit['daemon_sha256']
                audit['health_after'] = json.loads(command([BINARY, '--mode', 'health', '--sdrd', '192.168.1.10:43110']))
                for remote in remote_paths:
                    ssh(f'test ! -e {remote}')
                audit['all_p201_transients_absent'] = True
        finally:
            save(ROOT / 'audit.json', audit)


def verify():
    audit = json.loads((ROOT / 'audit.json').read_text())
    assert audit['status'] == 'completed' and len(audit['rows']) == 6
    assert audit['analysis_numpy'] == bg.np.__version__ and 'torch' not in sys.modules
    for index, row in enumerate(audit['rows']):
        seal, raw = bg.native(ROOT / f'capture-{index:02d}', audit['plans'][index])
        assert seal == row['seal'] and compact_stats(raw) == row['statistics']
        assert row['radio_restored'] and row['p201_transient_absent']
    assert audit['restored'] and audit['all_p201_transients_absent']
    print(json.dumps(dict(replay='passed', captures=6, rx_bytes=1572840, rf_operations=0, model_windows=0)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--acquire', action='store_true')
    choice.add_argument('--verify', action='store_true')
    parser.add_argument('--condition', choices=('termination', 'antenna-return'), default='termination')
    args = parser.parse_args()
    if args.condition == 'antenna-return':
        ROOT = Path('/var/tmp/sdrharness-dev/p201-antenna-return-20260909b')
    if args.verify:
        verify()
    else:
        def abort(signum, frame):
            raise RuntimeError(f'stop signal {signum}')
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
            signal.signal(sig, abort)
        signal.alarm(120)
        acquire(args.condition)
