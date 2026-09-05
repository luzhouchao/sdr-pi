#!/usr/bin/env python3
"""Bounded real-Worker admission health validation on AGX; no SDR or datasets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
PYTHON = ROOT / 'local-assets/amc-eval/runtime/venv/bin/python'
WORKER = ROOT / 'jetson-agx/sdrharness/scripts/amc-mamba-worker.py'
PROFILE = ROOT / 'jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json'
ADMISSION = ROOT / 'jetson-agx/sdrharness/config/amc/rf-v1-recognizer-admission.candidate.json'


def raw_health(path, request):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(1)
        client.connect(str(path))
        client.sendall(json.dumps(request).encode() + b'\n')
        frame = bytearray()
        while not frame.endswith(b'\n') and len(frame) <= 16384:
            chunk = client.recv(16385 - len(frame))
            if not chunk:
                raise RuntimeError('Worker closed before newline')
            frame.extend(chunk)
        if len(frame) > 16384 or not frame.endswith(b'\n'):
            raise RuntimeError('invalid bounded health frame')
        return json.loads(frame)


def execute(args):
    feature = args.feature_directory
    if (feature.parent != Path('/var/tmp/sdrharness-dev') or not feature.is_absolute()
            or feature.is_symlink() or feature.resolve() != feature):
        raise ValueError('feature must be an exact direct child of /var/tmp/sdrharness-dev')
    feature.mkdir(mode=0o700, exist_ok=True)
    live = feature / 'admission-live'
    live.mkdir(mode=0o700)
    spool = live / 'iq'
    spool.mkdir(mode=0o700)
    sock = live / 'w.sock'
    def observe(admission=ADMISSION):
        response = subprocess.run([str(args.controller), '--mode', 'recognizer-health',
            '--recognizer-socket', str(sock), '--recognizer-admission', str(admission),
            '--request-id', '71001', '--session-generation', '20260905071'],
            capture_output=True, text=True, check=True, timeout=3)
        return json.loads(response.stdout)
    before = observe()
    assert not before['recognizer_available'] and before['reason'] == 'health_unavailable', before
    summary = {'schema_version': 1, 'schema_id': 'recognizer_admission_live_validation_v1',
               'controller_sha256': hashlib.sha256(args.controller.read_bytes()).hexdigest(),
               'admission_sha256': hashlib.sha256(ADMISSION.read_bytes()).hexdigest(),
               'feature_directory': str(feature), 'before_worker': before, 'workers': [],
               'rx_bytes': 0, 'iq_files_written': 0, 'dataset_opened': False,
               'locked_test_opened': False, 'production_recognizer_available': False}
    for number in range(2):
        print(json.dumps({'stage': 'loading_candidate_worker', 'instance': number + 1}), flush=True)
        with (live / f'worker-{number}.log').open('x') as log:
            process = subprocess.Popen([str(PYTHON), str(WORKER), '--rf-v1-profile', str(PROFILE),
                '--socket', str(sock), '--spool-root', str(spool), '--max-requests', '3' if number == 0 else '1'],
                stdout=log, stderr=subprocess.STDOUT, cwd=ROOT,
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'TMPDIR': str(live)})
        try:
            deadline = time.monotonic() + 120
            while not sock.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('candidate Worker startup failed')
                time.sleep(0.05)
            observation = observe()
            assert not observation['recognizer_available'] and observation['reason'] == 'candidate_not_admitted', observation
            assert observation['admission_sha256'] == summary['admission_sha256']
            record = {'controller_observation': observation}
            if number == 0:
                request = {'protocol_version': 1, 'operation': 'admission_health', 'request_id': 71002,
                           'session_generation': 20260905071, 'nonce': secrets.token_hex(32)}
                started = time.time_ns() // 1_000_000
                health = raw_health(sock, request)
                ended = time.time_ns() // 1_000_000
                assert all(health[k] == request[k] for k in ('request_id', 'session_generation', 'nonce'))
                assert started <= health['observed_at_unix_ms'] <= ended
                assert health['worker_instance_id'] == observation['worker_instance_id']
                assert health['identity'] == json.loads(ADMISSION.read_text())['identity']
                assert health['production_enabled'] is False
                malformed = raw_health(sock, {**request, 'production_enabled': True})
                assert malformed['status'] == 'error' and 'request_shape' in malformed['error']
                record.update(health=health, malformed_enable_request=malformed)
                forged = json.loads(ADMISSION.read_text())
                forged['status'] = 'admitted'
                forged_path = live / 'forged-admission.json'
                forged_path.write_text(json.dumps(forged))
                rejection = observe(forged_path)
                assert not rejection['recognizer_available'] and rejection['reason'] == 'admission_incomplete'
                record['status_toggle_rejected'] = rejection
            else:
                assert observation['worker_instance_id'] != summary['workers'][0]['controller_observation']['worker_instance_id']
            process.wait(timeout=10)
            assert process.returncode == 0 and not sock.exists() and not list(spool.iterdir())
            record['worker_stopped_socket_removed_spool_empty'] = True
            summary['workers'].append(record)
            print(json.dumps({'stage': 'candidate_health_verified', 'instance': number + 1,
                              'recognizer_available': False, 'reason': observation['reason']}), flush=True)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    summary['after_worker'] = observe()
    assert summary['after_worker']['reason'] == 'health_unavailable'
    summary['status'] = 'pass'
    output = live / 'summary.json'
    payload = json.dumps(summary, indent=2) + '\n'
    assert len(payload.encode()) < 65536
    output.write_text(payload)
    print(json.dumps({'status': 'pass', 'summary': str(output)}), flush=True)


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controller', required=True, type=Path)
    parser.add_argument('--feature-directory', required=True, type=Path)
    execute(parser.parse_args())
