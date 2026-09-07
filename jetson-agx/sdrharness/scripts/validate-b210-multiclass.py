#!/usr/bin/env python3
"""Preregistered train-only 24-class source/RX diagnostic, never admission."""
if not __debug__:
    raise RuntimeError('validation assertions required')

import argparse
import asyncio
from contextlib import contextmanager, ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import zipfile

import h5py
import numpy as np
import b210_multiclass_contract as contract
import importlib.util

SCRIPTS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('multi_repair', SCRIPTS / 'repair-b210-lo-leakage.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)
lo, live = repair.lo, repair.live
ports = live.affine.module('multi_ports', 'validate-sdrd-rx-ports.py')
ROOT = Path('/var/tmp/sdrharness-dev/b210-multiclass-907u')
REPO = live.affine.ROOT
MANIFEST = REPO / 'jetson-agx/sdrharness/config/amc/b210-multiclass-907u.json'
PHASES = ('baseline', 'during-tx', 'after-tx')
sha = lambda raw: hashlib.sha256(raw).hexdigest()
save = lo.save


def feature(tag):
    assert tag in {f'r{r}c{c:02}' for r in range(3) for c in range(24)} | {f'tone{r}' for r in range(3)}
    return ROOT.parent / f'b210-multi-{tag}-907u'


def train_member(split):
    with zipfile.ZipFile(split) as archive:
        train = np.load(io.BytesIO(archive.read('train.npy')), allow_pickle=False)
    assert train.ndim == 1 and train.dtype.kind in 'iu'
    assert sha(np.asarray(train, dtype='<i8').tobytes()) == contract.TRAIN_SHA256
    return train


def select_rows(train):
    selected = {}
    for c in range(24):
        rows = train[(train >= (c * 26 + 25) * 4096) & (train < (c + 1) * 26 * 4096)]
        assert len(set(map(int, rows))) == len(rows) and len(rows) >= 3
        chosen = sorted(map(int, rows), key=lambda row: sha(f'b210-multiclass-907u:row:{row}'.encode()))[:3]
        for r, row in enumerate(chosen):
            selected[r, c] = row
    return [(r, c, selected[r, c]) for r in range(3) for c in
            sorted(range(24), key=lambda c: sha(f'b210-multiclass-907u:order:{r}:{c}'.encode()))]


def read_selected(dataset, selection):
    rows = sorted(row for _, _, row in selection)
    assert len(rows) == len(set(rows)) == 72
    with h5py.File(dataset, 'r') as h5:
        iq = np.asarray(h5['X'][rows], dtype='<f4')
        labels = np.asarray(h5['Y'][rows])
        snr = np.asarray(h5['Z'][rows]).reshape(-1)
    assert iq.shape == (72, 1024, 2) and np.isfinite(iq).all()
    assert labels.shape == (72, 24) and (snr == 30).all()
    classes = {row: c for _, c, row in selection}
    assert np.array_equal(labels, np.eye(24)[[classes[row] for row in rows]])
    return dict(zip(rows, iq))


def complex_iq(iq):
    return iq[..., 0].astype(float) + 1j * iq[..., 1].astype(float)


def fir_eligible(retention):
    return bool(retention['power_fraction'] >= .99 and retention['normalized_distortion_power'] <= .01)


def export():
    assert ROOT.resolve() == ROOT and ROOT.is_dir() and not MANIFEST.exists()
    pinned = live.document(REPO / 'jetson-agx/sdrharness/config/amc/rf-preprocess-v1-selection-plan.json')['pinned_inputs']
    dataset = REPO / pinned['dataset']['path']
    assert dataset.stat().st_size == pinned['dataset']['bytes']
    selection = select_rows(train_member(REPO / pinned['split']['path']))
    samples = read_selected(dataset, selection)
    cases = []
    for r, c, row in selection:
        tag = f'r{r}c{c:02}'
        root = feature(tag)
        root.mkdir(mode=0o700)
        iq = samples[row]
        scale = .2 / float(abs(complex_iq(iq)).max())
        payload = np.asarray(iq * scale, dtype='<f4').tobytes()
        retention = repair.source_retention(complex_iq(iq))
        plan = dict(schema_version=5, diagnostic_contract=contract.CONTRACT,
                    case_id=tag, round=r, class_id=c, rows=[row], split='train',
                    train_member_sha256=contract.TRAIN_SHA256, dataset_path=str(dataset),
                    dataset_identity=pinned['dataset'], name_status='provisional', dataset_nominal_snr_db=30,
                    source_iq_sha256=sha(iq.tobytes()), payload_sha256=sha(payload),
                    payload_bytes=8192, amplitude_scale=scale, complex_peak=.2,
                    center_hz=2455000000, rate_sps=2100000, bandwidth_hz=1500000,
                    tx_gain_db=70, tx_samples=20971520, tx_nominal_seconds=10,
                    tx_channel=0, tx_antenna='TX/RX', source_unit_samples=1024, tx_unit_count=20480,
                    uhd_spb=1024, tx_lo_offset_hz=250000, tx_requested_lo_hz=2455250000,
                    locked_test_read=False, recognizer_available=False,
                    receiver_label='unknown; source association is diagnostic, not independent annotation',
                    physical_dataset_sample_rate_known=False, source_retention=retention,
                    fir_diagnostic_eligible=fir_eligible(retention))
        (root / 'source-original.fc32').write_bytes(iq.tobytes())
        (root / 'train-tile.fc32').write_bytes(payload)
        save(root / 'transmission-plan.json', plan)
        cases.append(plan)
    for r in range(3):
        feature(f'tone{r}').mkdir(mode=0o700)
    manifest = dict(schema_id=contract.CONTRACT, cases=cases,
                    selection='sha256-ranked train-only +30dB rows; no model-based selection',
                    max_rx_bytes=58981500, max_tx_samples=1584949440, max_nominal_tx_seconds=750,
                    max_model_windows=1152, max_warmup_windows=2, max_wall_seconds=7200,
                    independent_labels=0, recognizer_available=False,
                    antenna='operator confirmed new dual-band antenna on P201 RX1')
    save(MANIFEST, manifest)
    os.link(MANIFEST, ROOT / 'multiclass-manifest.json')
    for plan in cases:
        os.link(MANIFEST, feature(plan['case_id']) / 'multiclass-manifest.json')
    print(json.dumps(dict(manifest_sha256=sha(MANIFEST.read_bytes()), cases=72,
                         fir_eligible=sum(p['fir_diagnostic_eligible'] for p in cases))), flush=True)


def manifest():
    assert sha(MANIFEST.read_bytes()) == contract.MANIFEST_SHA256
    return live.document(MANIFEST)


def validate_source(root):
    p = contract.validate(root)
    raw = live.read(root / 'source-original.fc32')
    assert len(raw) == 8192 and sha(raw) == p['source_iq_sha256']
    iq = np.frombuffer(raw, dtype='<f4').reshape(1024, 2)
    assert sha(np.asarray(iq * p['amplitude_scale'], dtype='<f4').tobytes()) == p['payload_sha256']
    assert repair.source_retention(complex_iq(iq)) == p['source_retention']
    return p


def checked_command(args, timeout=40):
    return subprocess.run(list(map(str, args)), check=True, capture_output=True, text=True, timeout=timeout).stdout


def seal_capture(root, plan):
    seal = live.validate_capture_root(root, 'rml', single_source_sha256=plan['payload_sha256'],
                                     expected_center_hz=2455000000)
    tx = live.document(root / 'tx-summary.json')
    for key in ('case_id', 'class_id', 'rows', 'source_iq_sha256', 'tx_lo_offset_hz', 'tx_requested_lo_hz'):
        assert tx[key] == plan[key], key
    log = live.read(root / 'tx-uhd.log').decode()
    for label, wanted in [('Setting TX LO Offset', .25), ('Actual TX Freq', 2455.),
                          ('Actual TX Rate', 2.1), ('Actual TX Bandwidth', 1.5), ('Actual TX Gain', 70.)]:
        values = re.findall(re.escape(label) + r': ([\d.+-]+)', log)
        assert len(values) == 1 and abs(float(values[0]) - wanted) < 1e-6, label
    return seal


def remote_cleanup(root):
    # Only known private files. Any unexpected file prevents directory removal.
    names = ('transmission-plan.json', 'train-tile.fc32', 'multiclass-manifest.json',
             'b210-finite-train-tx.py', 'b210_multiclass_contract.py', 'tx-summary.json', 'tx-uhd.log')
    code = ('from pathlib import Path; import shutil; r=Path(' + repr(str(root)) + '); '
            'assert r.resolve()==r and r.parent==Path("/var/tmp/sdrharness-dev"); '
            'assert not (r/"tx.fc32.fifo").exists(); '
            'assert {p.name for p in r.iterdir()} <= set(' + repr(names) + '); '
            '[p.unlink() for p in r.iterdir()]; r.rmdir(); assert not r.exists()')
    checked_command([*lo.NX, 'python3 -c ' + shlex.quote(code)])


def acquire(binary):
    matrix = manifest()
    for p in matrix['cases']:
        validate_source(feature(p['case_id']))
    free = shutil.disk_usage(ROOT).free
    assert free > matrix['max_rx_bytes'] + 1024 ** 3
    password = Path('/home/jetson/.config/sdrharness/p201-root.password')
    assert password.is_file() and not password.is_symlink() and password.stat().st_mode & 0o777 == 0o600
    wire = ports.Wire()
    try:
        hello = wire.send('HELLO')
        health = wire.send('HEALTH')
        wire.send('QUIT')
    finally:
        wire.close()
    before = ports.ssh(ports.STATE)
    pid = ports.ssh('pidof sdrd').strip()
    assert len(pid.split()) == 1
    deployed = ports.ssh('sha256sum /sd/sdr-agent/current/sdrd').split()[0]
    assert deployed == '83a661a892b8ab71de3f4e7d64064c9c65030623dc7245eb3d3a1420a696ba4f'
    receipt = dict(manifest_sha256=contract.MANIFEST_SHA256, max_rx_bytes=matrix['max_rx_bytes'],
                   free_bytes=free, started_unix_ns=time.time_ns(), radio_before=before,
                   sdrd_pid=pid, sdrd_sha256=deployed, hello=hello, health=health,
                   controller_sha256=sha(binary.read_bytes()), results={}, remote_removed=[], status='failed')
    save(ROOT / 'matrix-started.json', {k: v for k, v in receipt.items() if k != 'results'})
    print(json.dumps(dict(event='matrix_plan', max_rx_bytes=matrix['max_rx_bytes'],
                         free_bytes=free, root=str(ROOT), estimated_minutes=35, max_seconds=7200)), flush=True)
    started = time.monotonic()
    staged = None
    active = None
    stopping = False
    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        if active is not None and active.poll() is None:
            active.send_signal(signal.SIGTERM)  # timeout forwards to restoring RX/TX owner
    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        for r in range(3):
            tags = [f'tone{r}'] + [p['case_id'] for p in matrix['cases'] if p['round'] == r]
            for tag in tags:
                assert not stopping and time.monotonic() - started < 7000, 'matrix stopped/deadline'
                root = feature(tag)
                tone = tag.startswith('tone')
                assert not (root / 'link-started.json').exists(), 'attempt already consumed'
                entry = dict(status='attempted_failed')
                receipt['results'][tag] = entry
                checked_command([*lo.NX, 'mkdir -m 700 ' + shlex.quote(str(root))])
                staged = root
                if not tone:
                    files = [root / n for n in ('transmission-plan.json', 'train-tile.fc32', 'multiclass-manifest.json')]
                    files += [SCRIPTS / n for n in ('b210-finite-train-tx.py', 'b210_multiclass_contract.py')]
                    checked_command(['scp', '-F', '/home/jetson/.ssh/config', *files, f'nx:{root}/'])
                    # Both local and NX validate pinned matrix/payload before hardware startup.
                    checked_command([*lo.NX, f'cd {root} && PYTHONDONTWRITEBYTECODE=1 python3 -c ' +
                                     shlex.quote('from pathlib import Path; import b210_multiclass_contract as c; c.validate(Path.cwd())')])
                args = ['timeout', '--signal=TERM', '--kill-after=20s', '180s', 'python3',
                        SCRIPTS / 'validate-b210-p201-link.py', '--directory', root,
                        '--controller', binary, '--mode', 'tone' if tone else 'rml',
                        '--rx-gain-db', '40', '--center-hz', '2455000000']
                with (root / 'runner.log').open('x') as log:
                    active = subprocess.Popen(list(map(str, args)), stdout=log, stderr=subprocess.STDOUT)
                    active.wait(timeout=205)
                    result = active
                    active = None
                if not tone:
                    for name in ('tx-summary.json', 'tx-uhd.log'):
                        checked_command(['scp', '-F', '/home/jetson/.ssh/config', f'nx:{root}/{name}', root / name])
                summary = live.document(root / 'link-summary.json')
                assert not summary['restoration_errors'] and summary.get('remote_tx_stopped'), 'stop/restoration failed'
                checked_command([*lo.NX, live.link_tool.remote_absence_command(root, None, None)])
                remote_cleanup(root)
                staged = None
                receipt['remote_removed'].append(str(root))
                assert ports.ssh(ports.STATE) == before and ports.ssh('pidof sdrd').strip() == pid
                # Failed transport stays in the full denominator; no automatic repeat.
                entry.update(returncode=result.returncode, status='failed')
                if result.returncode == 0:
                    try:
                        entry['seal'] = (live.validate_capture_root(root, 'tone', expected_center_hz=2455000000)
                                         if tone else seal_capture(root, contract.validate(root)))
                        entry['status'] = 'transport_valid'
                    except (ValueError, AssertionError) as error:
                        entry['validation_error'] = str(error)
                if tone:
                    assert entry['status'] == 'transport_valid', 'tone transport failed'
                    entry['metrics'] = live.match.tone_metrics(root)
                    entry['assessment'] = live.match.assess_tone(entry['metrics'])
                    assert entry['assessment']['passed'], 'tone gate failed'
                print(json.dumps(dict(event='completed', case=tag, status=entry['status'],
                                      completed=len(receipt['results']), total=75)), flush=True)
        receipt['status'] = 'matrix_completed'
    except BaseException as error:
        receipt['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if active is not None and active.poll() is None:
            active.send_signal(signal.SIGTERM)
            try:
                active.wait(timeout=25)
            except subprocess.TimeoutExpired:
                active.kill()
                active.wait(timeout=5)
        if staged is not None:
            try:
                checked_command([*lo.NX, live.link_tool.remote_absence_command(staged, None, None)])
                remote_cleanup(staged)
                receipt['remote_removed'].append(str(staged))
            except Exception as error:
                receipt['cleanup_failure'] = str(error)
        receipt['radio_after'] = ports.ssh(ports.STATE)
        receipt['restored'] = receipt['radio_after'] == before and ports.ssh('pidof sdrd').strip() == pid
        receipt['elapsed_seconds'] = time.monotonic() - started
        save(ROOT / 'acquisition.json', receipt)


def normalize(z):
    return live.affine.paired.normalize(np.column_stack((z.real, z.imag)))


def inputs_for(p, entry):
    root = feature(p['case_id'])
    validate_source(root)
    source = complex_iq(np.frombuffer(live.read(root / 'source-original.fc32'), dtype='<f4').reshape(1024, 2))
    tensors = {'source_original': normalize(np.tile(source, 4))}
    captures = None
    if entry and entry['status'] == 'transport_valid':
        assert seal_capture(root, p) == entry['seal']
        captures = {tag: live.match.read_iq(root, tag)[0] for tag in PHASES}
        tensors['received_raw'] = normalize(captures['during-tx'][32768:36864])
    if p['fir_diagnostic_eligible']:
        tensors['source_filtered'] = normalize(repair.reject(np.tile(source, 6))[1024-128:5120-128])
        if captures is not None:
            tensors['received_filtered'] = normalize(repair.reject(captures['during-tx'])[32768-128:36864-128])
    return source, captures, tensors


def prepare():
    acquisition = live.document(ROOT / 'acquisition.json')
    report = dict(manifest_sha256=contract.MANIFEST_SHA256, acquisition_sha256=sha(live.read(ROOT / 'acquisition.json')),
                  cases={}, model_inputs={}, recognizer_available=False, independent_labels=0,
                  production_profile_compatible=False, result_semantics='uncalibrated diagnostic predictions')
    tensors = {}
    for p in manifest()['cases']:
        tag = p['case_id']
        entry = acquisition['results'].get(tag)
        source, captures, data = inputs_for(p, entry)
        case = dict(class_id=p['class_id'], row=p['rows'][0],
                    transport_status='not_attempted' if entry is None else entry['status'],
                    fir_eligible=p['fir_diagnostic_eligible'], source_retention=p['source_retention'],
                    qualification_passed=False)
        if captures is not None:
            power = lambda z: float(np.mean(abs(z[32768:36864]) ** 2))
            case['raw_stopped_power_margins_db'] = {phase: float(10*np.log10(max(power(captures['during-tx']), 1e-30) /
                                                         max(power(captures[phase]), 1e-30))) for phase in ('baseline', 'after-tx')}
            case['tx_evidence'] = live.document(feature(tag) / 'tx-summary.json')
            tone = acquisition['results'][f'tone{p["round"]}']
            try:
                details, _ = repair.evaluate(source, captures, tone['metrics']['frequency_difference_hz'], 250000)
                case['association'] = {k: v for k, v in details.items() if k not in ('pointwise', 'segments', 'heldout_blocks')}
                case['alignment'] = details['pointwise']['alignment']
                case['qualification_passed'] = bool(p['fir_diagnostic_eligible'] and details['model_control_passed'])
            except (ValueError, AssertionError, np.linalg.LinAlgError) as error:
                case['association_unavailable'] = f'{type(error).__name__}: {error}'
        report['cases'][tag] = case
        for name, array in data.items():
            key = tag + '/' + name
            tensors[key] = array
            report['model_inputs'][key] = sha(array.tobytes())
    return report, tensors


@contextmanager
def idle_spark_pause(*, evidence_root=ROOT):
    """Installed Spark predates the shared gate; pause only an idle, identified PID."""
    assert evidence_root.resolve() == evidence_root and evidence_root.parent == Path('/var/tmp/sdrharness-dev')
    assert evidence_root.is_dir()
    import urllib.request
    pid = int(checked_command(['systemctl', 'show', 'spark-x25.service', '-p', 'MainPID', '--value']).strip())
    proc = Path('/proc') / str(pid)
    assert pid > 1 and (proc / 'cmdline').read_bytes().split(b'\0')[0] == b'/home/jetson/Spark/runtime/llama.cpp/build/bin/llama-server'
    key = Path('/home/jetson/Spark/config/api-key.txt').read_text().strip()
    request = urllib.request.Request('http://127.0.0.1:8010/slots', headers={'Authorization': 'Bearer ' + key})
    with urllib.request.urlopen(request, timeout=3) as response:
        slots = json.load(response)
    assert slots and all(slot['is_processing'] is False for slot in slots), 'Spark is busy'
    start = (proc / 'stat').read_text().split()[21]
    audit = dict(pid=pid, start_ticks=start, idle_slots=len(slots), resumed=False,
                 mechanism='SIGSTOP idle installed Spark; feature-private Mamba lease', started_ns=time.time_ns())
    # Independent bounded restore if this diagnostic owner is killed unexpectedly.
    code = ('import os,signal,sys,time; from pathlib import Path; time.sleep(700); '
            'p=Path("/proc")/sys.argv[1]; '
            'os.kill(int(sys.argv[1]),signal.SIGCONT) if p.exists() and '
            '(p/"stat").read_text().split()[21]==sys.argv[2] else None')
    watchdog = subprocess.Popen([sys.executable, '-c', code, str(pid), start], start_new_session=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        os.kill(pid, signal.SIGSTOP)
        deadline = time.monotonic() + 3
        while (proc / 'stat').read_text().split()[2] != 'T':
            assert time.monotonic() < deadline, 'Spark pause timeout'
            time.sleep(.01)
        audit['pause_confirmed'] = True
        yield
    finally:
        assert (proc / 'stat').read_text().split()[21] == start, 'Spark PID identity changed'
        os.kill(pid, signal.SIGCONT)
        deadline = time.monotonic() + 3
        while (proc / 'stat').read_text().split()[2] == 'T':
            assert time.monotonic() < deadline, 'Spark resume timeout'
            time.sleep(.01)
        audit.update(resumed=True, finished_ns=time.time_ns())
        watchdog.terminate()
        watchdog.wait(timeout=3)
        audit['restore_watchdog_stopped'] = watchdog.returncode is not None
        save(evidence_root / 'gpu-isolation.json', audit)


async def infer():
    report, tensors = prepare()
    assert report == live.document(ROOT / 'prepared.json')
    assert len(tensors) <= 288
    save(ROOT / 'inference-started.json', dict(planned_windows=4*len(tensors), warmup_windows=2,
                                            prepared_sha256=sha(live.read(ROOT / 'prepared.json'))))
    from gpu_lease import GpuLease
    lease = GpuLease(ROOT / 'gpu-gate', 'mamba')
    token = None
    isolation = ExitStack()
    receipt = dict(status='failed', results={}, model_windows=0, warmup_windows=0,
                   recognizer_available=False, independent_labels=0, uncalibrated=True)
    try:
        token = await lease.acquire(time.monotonic()+10, request='b210-24class-diagnostic')
        isolation.enter_context(idle_spark_pause())
        worker = live.affine.module('multi_worker', 'amc-mamba-worker.py')
        backend = worker.RfV1Backend(REPO / 'jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json')
        assert all(p.dtype == worker.torch.float32 for p in backend.model.parameters())
        receipt.update(identity=backend.admission_identity, compute='cuda_fp16_autocast_fp32_weights', warmup_windows=2)
        deadline = time.monotonic() + 600
        for key, data in tensors.items():
            assert time.monotonic() < deadline, 'inference deadline'
            logits, elapsed = [], 0
            for window in data:
                values, timing = backend.classify_logits(np.ascontiguousarray(window))
                logits.append(values)
                elapsed += timing
                receipt['model_windows'] += 1
            values = np.asarray(logits, dtype=np.float64)
            assert values.shape == (4, 24) and np.isfinite(values).all()
            mean = values.mean(axis=0)
            receipt['results'][key] = dict(numeric_id=int(mean.argmax()), window_numeric_ids=values.argmax(axis=1).tolist(),
                logits=values.tolist(), mean_logits=mean.tolist(), name_status='provisional', inference_us=elapsed,
                input_sha256=sha(data.tobytes()), uncalibrated=True)
            if key.endswith('received_raw'):
                print(json.dumps(dict(event='inferred', case=key, numeric_id=int(mean.argmax()))), flush=True)
        receipt['status'] = 'comparison_completed'
    except BaseException as error:
        receipt['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        if token is not None:
            lease.release(token)
        receipt['gpu_lease'] = lease.metrics.copy()
        lease.close()
        try:
            isolation.close()
        finally:
            save(ROOT / 'inference.json', receipt)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--export', action='store_true')
    group.add_argument('--acquire', type=Path)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--infer', action='store_true')
    args = parser.parse_args()
    if args.export:
        export()
    elif args.acquire:
        acquire(args.acquire)
    elif args.prepare:
        save(ROOT / 'prepared.json', prepare()[0])
    else:
        def abort(signum, frame):
            raise InterruptedError(f'stop signal {signum}')
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, abort)
        asyncio.run(infer())
