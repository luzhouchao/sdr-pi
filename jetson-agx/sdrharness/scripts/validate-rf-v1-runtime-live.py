#!/usr/bin/env python3
"""Bounded RX1 RF-v1 runtime success/Worker-exit/capture-cancel validation.

No model evaluation, training, TX, persistent service changes or IQ retention.
The caller retains the bounded audit, then removes the exact feature directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / 'jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json'
WORKER = ROOT / 'jetson-agx/sdrharness/scripts/amc-mamba-worker.py'
PYTHON = ROOT / 'local-assets/amc-eval/runtime/venv/bin/python'
SSH = ['sshpass', '-f', '/home/jetson/.config/sdrharness/p201-root.password', 'ssh',
       '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=/home/jetson/.ssh/known_hosts',
       '-o', 'ConnectTimeout=5', 'root@192.168.1.10']
STATE_COMMAND = '''for p in /sys/bus/iio/devices/iio:device0/out_altvoltage0_RX_LO_frequency /sys/bus/iio/devices/iio:device0/in_voltage_sampling_frequency /sys/bus/iio/devices/iio:device0/in_voltage_rf_bandwidth /sys/bus/iio/devices/iio:device0/in_voltage0_gain_control_mode /sys/bus/iio/devices/iio:device0/in_voltage0_hardwaregain /sys/bus/iio/devices/iio:device0/in_voltage0_rf_port_select /sys/bus/iio/devices/iio:device*/scan_elements/*_en /sys/bus/iio/devices/iio:device*/buffer/enable; do if test -f "$p"; then echo "$p"; cat "$p"; fi; done'''


def run(args, payload=None, timeout=30):
    result = subprocess.run([str(v) for v in args], input=None if payload is None else json.dumps(payload),
                            text=True, capture_output=True, timeout=timeout, cwd=ROOT)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    return result.stdout


def restored_state(before, after):
    def parse(text):
        lines = text.splitlines()
        if len(lines) % 2:
            raise ValueError('incomplete radio snapshot')
        return dict(zip(lines[::2], lines[1::2]))
    original, current = parse(before), parse(after)
    mode = '/sys/bus/iio/devices/iio:device0/in_voltage0_gain_control_mode'
    gain = '/sys/bus/iio/devices/iio:device0/in_voltage0_hardwaregain'
    if original.get(mode) != current.get(mode):
        return False
    # Same rule as sdrd_iio.c verify_radio_state: manual gain is a saved
    # setting; in AGC mode hardwaregain is an autonomous measurement.
    if original.get(mode) in ('slow_attack', 'fast_attack', 'hybrid'):
        original.pop(gain, None)
        current.pop(gain, None)
    return original == current


def execute(args):
    feature = args.feature_directory
    if (not feature.is_absolute() or feature.parent != Path('/var/tmp/sdrharness-dev')
            or feature.is_symlink() or feature.resolve() != feature):
        raise ValueError('feature must be an exact direct child of /var/tmp/sdrharness-dev')
    feature.mkdir(mode=0o700, exist_ok=True)
    spool = feature / 'iq'
    spool.mkdir(mode=0o700)
    sock = feature / 'worker.sock'
    output = feature / 'live.json'
    if output.exists():
        raise ValueError('refusing to overwrite evidence')
    controller = [args.controller, '--repository-root', ROOT, '--sdrd', '192.168.1.10:43110']
    def ctl(mode, payload=None, extra=()):
        return json.loads(run([*controller, '--mode', mode, *extra], payload))
    with socket.create_connection(('192.168.1.10', 43110), 3):
        pass
    pids = run([*SSH, 'pidof sdrd']).split()
    if len(pids) != 1:
        raise ValueError('expected exactly one sdrd')
    before = run([*SSH, STATE_COMMAND])
    available = shutil.disk_usage(feature).free
    if available < 32768 + 1024 * 1024:
        raise ValueError('insufficient space for bounded spool and audit')
    audit = {'schema_id': 'rf_v1_runtime_live_v1', 'profile_sha256': hashlib.sha256(PROFILE.read_bytes()).hexdigest(),
             'controller_sha256': hashlib.sha256(args.controller.read_bytes()).hexdigest(),
             'feature_directory': str(feature), 'free_bytes_before': available,
             'total_rx_maximum_bytes': len(args.cases) * 2 * 4096 * 4, 'spool_maximum_bytes': 32768,
             'radio_before': before, 'sdrd_pid': pids[0], 'cases': [],
             'locked_test_opened': False, 'recognizer_available': False, 'label_truth': 'unknown'}
    print(json.dumps({k: v for k, v in audit.items() if k not in ('radio_before', 'cases')}), flush=True)
    assert ctl('observe')['healthy']
    base_generation = args.generation
    for number, case in enumerate(args.cases):
        worker = None
        capture = None
        generation = base_generation + number * 2
        request_id = 50001 + number * 10
        sweep_id = f'rf1-{generation}'
        p201_dirs = [f'/tmp/sdr-agent-dev/agx-sweep-{generation}-0',
                     f'/tmp/sdr-agent-dev/agx-model-batch-{generation + 1}-{request_id}']
        plan = {'sweep_id': sweep_id, 'session_generation': generation,
                'frequencies': {'kind': 'centers', 'centers_hz': [433920000]},
                'sample_rate_hz': 2100000, 'rf_bandwidth_hz': 1500000,
                'gain_db': 50, 'settle_ms': 100, 'frame_samples': 4096, 'aggregate_frames': 1,
                'point_timeout_ms': 1000, 'detection_threshold_db': 6.0}
        print(json.dumps({'case': case, 'plan': plan, 'maximum_rx_bytes': 32768,
                          'capture_samples': 4096, 'capture_max_ms': 1000, 'control_max_ms': 5000,
                          'model_max_ms': 4 * 5000, 'estimated_max_ms': 30000,
                          'agx_directory': str(feature), 'p201_directories': p201_dirs,
                          'stop': f'controller --mode cancel --session-generation {generation + 1}'}), flush=True)
        try:
            if case != 'capture_cancel':
                log = (feature / f'{case}-worker.log').open('x')
                worker = subprocess.Popen([str(PYTHON), str(WORKER), '--rf-v1-profile', str(PROFILE),
                    '--socket', str(sock), '--spool-root', str(spool), '--max-requests', '5' if case == 'success' else '2'],
                    stdout=log, stderr=subprocess.STDOUT, cwd=ROOT,
                    env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
                log.close()
                for _ in range(1200):
                    if sock.exists():
                        break
                    if worker.poll() is not None:
                        raise RuntimeError('worker failed to start')
                    time.sleep(0.1)
                health = json.loads(run([PYTHON, WORKER, '--probe-socket', sock, '--probe-timeout-ms', '1000']))
                assert health['model_sha256'] == 'a3c3e41ba9732171d65b023d7d9f1d334d88b7ca28be3d939b0536878c168054'
            inspection = ctl('sweep', plan)
            point = inspection['points'][0]
            spectral = point['spectral']
            candidate = {'id': 'rf-v1-runtime-unknown', 'center_hz': spectral['estimated_center_hz'],
                         'bandwidth_hz': spectral['occupied_bandwidth_hz'], 'peak_dbfs': spectral['peak_power_dbfs'],
                         'snr_db': spectral['measured_snr_db'], 'age_ms': 0}
            target = ctl('derive-recognition-target', {'candidate': candidate, 'report': inspection,
                         'observed_at_unix_ms': int(time.time() * 1000), 'inspection_gain_db': 50})
            command = [*controller, '--mode', 'recognize-batch-live', '--recognition-profile', PROFILE,
                       '--recognition-target', '-', '--request-id', str(request_id),
                       '--session-generation', str(generation + 1), '--recognizer-socket', sock,
                       '--recognizer-spool-root', spool]
            capture = subprocess.Popen([str(v) for v in command], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT)
            capture.stdin.write(json.dumps(target))
            capture.stdin.close()
            capture.stdin = None
            cancellation = None
            if case == 'capture_cancel':
                for _ in range(30):
                    try:
                        attempt = ctl('cancel', extra=('--session-generation', str(generation + 1)))
                    except RuntimeError as error:
                        if 'stale_or_missing_session' not in str(error):
                            raise
                        attempt = {'cancel_requested': False}
                    if attempt['cancel_requested']:
                        cancellation = attempt
                        break
                    if capture.poll() is not None:
                        break
                    time.sleep(0.01)
            stdout, stderr = capture.communicate(timeout=30)
            record = {'case': case, 'target': target, 'inspection_sequence': point['sequence'],
                      'exit_code': capture.returncode, 'capture_validation': stderr, 'cancel': cancellation}
            if case == 'success':
                assert capture.returncode == 0, stderr
                report = json.loads(stdout)
                assert report['mean_logit']['calibrated'] is False and report['transient_iq_removed']
                # Independent float64 aggregation, no model-generated truth.
                import math
                means = [sum(w['recognition']['rf_v1']['logits'][c] for w in report['windows']) / 4 for c in range(24)]
                assert max(abs(a-b) for a,b in zip(means, report['mean_logit']['mean_logits'])) < 1e-6
                exps = [math.exp(v - max(means)) for v in means]
                probs = [v / sum(exps) for v in exps]
                assert max(abs(a-b) for a,b in zip(probs, report['mean_logit']['probabilities'])) < 1e-7
                record['report'] = report
            elif case == 'worker_exit':
                assert capture.returncode != 0 and 'connect:' in stderr, stderr
            else:
                assert cancellation and capture.returncode != 0 and 'capture_failed_restored' in stderr, stderr
            if worker:
                worker.wait(timeout=10)
            assert not list(spool.iterdir()), 'spool leaked'
            after = run([*SSH, STATE_COMMAND])
            record['radio_after'] = after
            assert restored_state(before, after), 'saved radio state changed'
            assert ctl('observe')['healthy']
            # SDRD inline capture removes its exact derived directory itself.
            run([*SSH, ' ; '.join(f'test ! -e {p} || exit 1' for p in p201_dirs)])
            record.update(radio_restored=True, spool_empty=True, p201_transients_absent=True)
            audit['cases'].append(record)
            output.write_text(json.dumps(audit, indent=2) + '\n')
            print(json.dumps({'case': case, 'status': 'pass', 'spool_empty': True, 'radio_restored': True}), flush=True)
        finally:
            if capture and capture.poll() is None:
                try:
                    ctl('cancel', extra=('--session-generation', str(generation + 1)))
                except RuntimeError as error:
                    if 'stale_or_missing_session' not in str(error):
                        raise
                capture.terminate()
                capture.communicate(timeout=15)
            if worker and worker.poll() is None:
                worker.terminate()
                worker.wait(timeout=10)
    audit['status'] = 'pass'
    output.write_text(json.dumps(audit, indent=2) + '\n')
    print(json.dumps({'status': 'pass', 'audit': str(output)}), flush=True)


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feature-directory', type=Path, required=True)
    parser.add_argument('--controller', type=Path, required=True)
    parser.add_argument('--generation', type=int, required=True)
    parser.add_argument('--cases', nargs='+', choices=('success', 'worker_exit', 'capture_cancel'), default=['success', 'worker_exit', 'capture_cancel'])
    execute(parser.parse_args())
