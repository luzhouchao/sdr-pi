#!/usr/bin/env python3
"""Finite isolated RX1/RX2 candidate validation; always restore the installed daemon."""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import time

spec = importlib.util.spec_from_file_location('port_rf', Path(__file__).with_name('validate-rf-v1-runtime-live.py'))
rf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rf)
STATE = rf.STATE_COMMAND.replace(' /sys/bus/iio/devices/iio:device*/scan_elements',
    ' /sys/bus/iio/devices/iio:device0/in_voltage1_gain_control_mode'
    ' /sys/bus/iio/devices/iio:device0/in_voltage1_hardwaregain'
    ' /sys/bus/iio/devices/iio:device0/in_voltage1_rf_port_select'
    ' /sys/bus/iio/devices/iio:device*/scan_elements')


def command(args, payload=None, timeout=20):
    r = subprocess.run(list(map(str, args)), input=payload, capture_output=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(r.stderr.decode(errors='replace')[-1500:])
    return r.stdout


def ssh(script, payload=None):
    return command([*rf.SSH, script], payload).decode()


class Wire:
    def __init__(self):
        self.socket = socket.create_connection(('192.168.1.10', 43110), 3)
        self.socket.settimeout(8)
        self.file = self.socket.makefile('rb')
        self.request = 0

    def send(self, text, status='ok'):
        self.request += 1
        name, _, args = text.partition(' ')
        self.socket.sendall(f'SDRD/1 {name} {self.request} {args}\n'.encode())
        raw = self.file.readline(384 * 1024 + 1)
        assert len(raw) <= 384 * 1024 and raw.endswith(b'\n')
        row = json.loads(raw)
        assert row['request_id'] == self.request and row['schema_version'] == 1
        assert row['status'] == status, row
        return row

    def close(self):
        self.file.close()
        self.socket.close()


def execute(binary, root):
    password = Path('/home/jetson/.config/sdrharness/p201-root.password')
    assert password.is_file() and not password.is_symlink() and stat.S_IMODE(password.stat().st_mode) == 0o600
    assert root.resolve() == root and root.parent == Path('/var/tmp/sdrharness-dev') and root.is_dir()
    assert all(c.isalnum() or c == '-' for c in root.name)
    assert binary.resolve() == binary and binary.is_file()
    remote = '/tmp/sdr-agent-dev/' + root.name
    candidate = remote + '/sdrd'
    audit_path = root / 'port-live.json'
    assert not audit_path.exists()
    maximum = 2 * (65535 + 65535 + 4096) * 4
    assert shutil.disk_usage(root).free > maximum + 16 * 1024 * 1024
    budget = dict(ports=['RX1', 'RX2'], center_hz=2455000000, rate_sps=2100000,
                  bandwidth_hz=1500000, gain_db=40, settle_ms=500,
                  cases_per_port=['65535 success', '65535 forced 1ms timeout', '4096 recovery', 'disconnect restoration'],
                  maximum_rx_bytes=maximum, maximum_capture_calls=6, estimated_seconds=60,
                  agx_directory=str(root), p201_directory=remote, free_bytes=shutil.disk_usage(root).free,
                  stop='SIGINT/SIGTERM to this script; active session STOP_SESSION and candidate shutdown; installed daemon restored',
                  tx_operations=0, model_windows=0, antenna='operator reports new 2.4/5GHz antenna on RX2')
    print(json.dumps(budget), flush=True)
    before = ssh(STATE)
    values = dict(zip(before.splitlines()[::2], before.splitlines()[1::2]))
    assert all(v == '0' for p, v in values.items() if p.endswith('_en') or p.endswith('/enable'))
    assert all(values[f'/sys/bus/iio/devices/iio:device0/in_voltage{i}_gain_control_mode'] == 'manual' for i in (0, 1))
    original_pid = ssh('pidof sdrd').split()
    assert len(original_pid) == 1
    assert ssh(f'readlink /proc/{original_pid[0]}/exe').strip() == '/sd/sdr-agent/current/sdrd'
    old_hash = ssh('sha256sum /sd/sdr-agent/current/sdrd').split()[0]
    config = ssh('cat /sd/sdr-agent/current/sdrd.conf')
    assert 'rx_input=' not in config
    timer_active = subprocess.run(['systemctl', 'is-active', '--quiet', 'sdrharness-p201-sdrd-recovery.timer']).returncode == 0
    audit = dict(budget=budget, radio_before=before, original_pid=original_pid,
                 installed_sha256=old_hash, candidate_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                 cases=[], status='running', recognizer_available=False, deployed=False)
    wire = None
    generation = 0
    candidate_pid = None
    stopped = False
    staged = False
    timer_stopped = False
    try:
        command(['sudo', '-n', 'systemctl', 'stop', 'sdrharness-p201-sdrd-recovery.timer', 'sdrharness-p201-sdrd-recovery.service'])
        timer_stopped = True
        # Existing user/Controller sessions must be idle before taking ownership.
        connections = ssh('netstat -nt')
        assert not any(':43110 ' in l and 'ESTABLISHED' in l for l in connections.splitlines())
        ssh(f'test ! -e {remote} && mkdir -m 700 {remote}')
        staged = True
        ssh(f'cat > {candidate} && chmod 700 {candidate}', binary.read_bytes())
        assert ssh(f'sha256sum {candidate}').split()[0] == audit['candidate_sha256']
        stopped = True
        ssh('/etc/init.d/S60sdrd stop')
        for _ in range(30):
            if not ssh('pidof sdrd; true').strip():
                break
            time.sleep(.1)
        assert not ssh('pidof sdrd; true').strip()
        assert ':43110 ' not in ssh('netstat -lnt')
        for port in ('RX1', 'RX2'):
            cfg = config + '\nrx_input=' + port + '\n'
            ssh(f'cat > {remote}/{port}.conf', cfg.encode())
            for mode in ('--check-config', '--probe', '--probe-radio'):
                audit.setdefault('probes', []).append(dict(port=port, mode=mode,
                    output=ssh(f'{candidate} --config {remote}/{port}.conf {mode}')))
            ssh(f'{candidate} --config {remote}/{port}.conf --serve >{remote}/{port}.log 2>&1 </dev/null &')
            for _ in range(30):
                pids = ssh('pidof sdrd; true').split()
                if len(pids) == 1 and ':43110 ' in ssh('netstat -lnt'):
                    break
                time.sleep(.1)
            assert len(pids) == 1
            candidate_pid = pids[0]
            assert ssh(f'readlink /proc/{candidate_pid}/exe').strip() == candidate
            wire = Wire()
            health = wire.send('HEALTH')
            caps = wire.send('CAPABILITIES')
            identity = caps['rx_input']
            assert identity['verified'] and identity['front_panel_port'] == port
            assert identity['logical_channel'] == ('RX0' if port == 'RX1' else 'RX1')
            assert identity['phy_channel'] == ('voltage0' if port == 'RX1' else 'voltage1')
            assert identity['scan_i_channel'] == ('voltage0' if port == 'RX1' else 'voltage2')
            assert identity['scan_q_channel'] == ('voltage1' if port == 'RX1' else 'voltage3')
            assert caps['software_summary'] == (port == 'RX1') and caps['raw_iq_capture']
            assert health['healthy']
            for index, (samples, limit) in enumerate(((65535, 1000), (65535, 1), (4096, 1000))):
                generation = int(time.time() * 1000)
                assert wire.send(f'START_SESSION {generation}')['rx_input'] == identity
                assert wire.send(f'APPLY_PROFILE {generation} 2455000000 2100000 1500000 manual 40 1')['rx_input'] == identity
                time.sleep(.5)
                feature = f'{root.name}-{port.lower()}-{index}'
                row = wire.send(f'CAPTURE_IQ_INLINE {generation} {samples} {samples * 4} {feature} {limit}', 'error' if limit == 1 else 'ok')
                if limit == 1:
                    assert row['error'] == 'capture_failed_restored' and row['timeout']['timed_out']
                    assert 'iq_base64' not in row and row['health']['healthy'] is False
                else:
                    iq = base64.b64decode(row.pop('iq_base64'), validate=True)
                    assert len(iq) == samples * 4 and row['samples_captured'] == samples
                    assert row['rx_input'] == identity and row['health']['healthy'] and not row['overflow'] and row['dropped_samples'] == 0
                    import struct
                    pairs = list(struct.iter_unpack('<hh', iq))
                    row['iq_sha256'] = hashlib.sha256(iq).hexdigest()
                    row['component_range'] = [min(min(x) for x in pairs), max(max(x) for x in pairs)]
                    row['rms_adc'] = (sum(i*i + q*q for i,q in pairs) / samples) ** .5
                    assert row['rms_adc'] > 0 and -2048 <= row['component_range'][0] <= row['component_range'][1] <= 2047
                    # libiio enables channels in its context at APPLY_PROFILE;
                    # sysfs scan bits are materialized when the buffer is created.
                    active_state = ssh(STATE)
                    active = dict(zip(active_state.splitlines()[::2], active_state.splitlines()[1::2]))
                    for i in range(4):
                        assert active[f'/sys/bus/iio/devices/iio:device3/scan_elements/in_voltage{i}_en'] == str(int(i // 2 == int(port == 'RX2')))
                    row['active_radio_state'] = active_state
                    assert wire.send(f'STOP_SESSION {generation}')['restored']
                assert ssh(STATE) == before
                ssh(f'test ! -e /tmp/sdr-agent-dev/{feature}')
                audit['cases'].append(dict(port=port, kind='timeout' if limit == 1 else 'success', response=row, restored=True))
                generation = 0
            generation = int(time.time() * 1000)
            wire.send(f'START_SESSION {generation}')
            wire.send(f'APPLY_PROFILE {generation} 2455000000 2100000 1500000 manual 40 1')
            wire.close()
            wire = None
            for _ in range(30):
                if ssh(STATE) == before:
                    break
                time.sleep(.1)
            assert ssh(STATE) == before
            audit['cases'].append(dict(port=port, kind='disconnect', restored=True))
            generation = 0
            ssh(f'kill -TERM {candidate_pid}')
            for _ in range(30):
                if not ssh('pidof sdrd; true').strip():
                    break
                time.sleep(.1)
            assert not ssh('pidof sdrd; true').strip()
            candidate_pid = None
            audit.setdefault('daemon_logs', {})[port] = ssh(f'cat {remote}/{port}.log')
        audit['status'] = 'passed'
    finally:
        try:
            if wire:
                try:
                    if generation:
                        wire.send(f'STOP_SESSION {generation}')
                except Exception:
                    pass
                wire.close()
            if stopped:
                pids = ssh('pidof sdrd; true').split()
                original_running = False
                for pid in pids:
                    executable = ssh(f'readlink /proc/{pid}/exe').strip()
                    assert executable in (candidate, '/sd/sdr-agent/current/sdrd')
                    if executable == candidate:
                        ssh(f'kill -TERM {pid}')
                    else:
                        original_running = True
                for _ in range(40):
                    if original_running or not ssh('pidof sdrd; true').strip():
                        break
                    time.sleep(.1)
                assert original_running or not ssh('pidof sdrd; true').strip()
                assert ssh(STATE) == before
                if not original_running:
                    ssh('/etc/init.d/S60sdrd start')
                assert len(ssh('pidof sdrd').split()) == 1
                assert ssh('sha256sum /sd/sdr-agent/current/sdrd').split()[0] == old_hash
            audit['radio_after'] = ssh(STATE)
            audit['restored'] = audit['radio_after'] == before
            if staged:
                # Only the files this runner created; rmdir fails if anything else exists.
                ssh(f'rm -f {candidate} {remote}/RX1.conf {remote}/RX2.conf {remote}/RX1.log {remote}/RX2.log; rmdir {remote}; test ! -e {remote}')
                audit['remote_staging_removed'] = True
        except BaseException as error:
            audit['cleanup_error'] = f'{type(error).__name__}: {error}'
            raise
        finally:
            if timer_stopped and timer_active:
                command(['sudo', '-n', 'systemctl', 'start', 'sdrharness-p201-sdrd-recovery.timer'])
            audit_path.write_text(json.dumps(audit, indent=2) + '\n')
    assert audit['restored']
    print('RX1/RX2 candidate validation passed; installed daemon and both RX states restored.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--feature-directory', required=True, type=Path)
    args = parser.parse_args()
    def interrupt(signum, frame):
        raise KeyboardInterrupt(f'signal {signum}')
    signal.signal(signal.SIGTERM, interrupt)
    execute(args.binary, args.feature_directory)
