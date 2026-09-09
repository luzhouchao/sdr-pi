#!/usr/bin/env python3
"""Finite 2.4-GHz antenna-background map using the installed RX-only Controller."""
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
spec = importlib.util.spec_from_file_location('map_base', Path(__file__).with_name('validate-p201-termination-background.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
np = base.bg.np
ROOT = Path('/var/tmp/sdrharness-dev/p201-background-map-20260909d')
CENTERS = [2400600000 + round(i * 82300000 / 69) for i in range(70)]
COUNT, RATE, BYTES = 65535, 2100000, 262140
MAX_BYTES = 225 * BYTES
save, ssh = base.save, base.ssh


def metrics(z, center):
    if z.shape != (COUNT,) or not np.isfinite(z).all():
        raise ValueError('complete finite 65535-sample window required')
    # Same 128-sample time resolution as previous diagnostics; no gain conversion.
    rms = np.array([np.sqrt(np.mean(abs(z[n:n+128])**2)) for n in range(0, COUNT, 128)])
    p50, p95, p99 = np.percentile(rms, [50, 95, 99])
    size = 1024
    blocks = z[:COUNT // size * size].reshape(-1, size)
    window = np.hanning(size)
    # Absolute ADC^2/Hz, no fitted source or RF-label inference. DC kept and separately marked.
    psd = abs(np.fft.fftshift(np.fft.fft(blocks * window, axis=1), axes=1))**2 / (RATE * np.sum(window**2))
    offsets = np.fft.fftshift(np.fft.fftfreq(size, 1/RATE))
    freq = center + offsets
    # Equal 25-kHz bands inside the central 80% of the analog passband.
    edges = np.arange(-600000, 600001, 25000)
    avg, peak = [], []
    for left, right in zip(edges[:-1], edges[1:]):
        band = (offsets >= left) & (offsets < right)
        avg.append(float(np.mean(psd[:, band])))
        peak.append(float(np.max(np.mean(psd[:, band], axis=1))))
    eligible = (abs(offsets) <= 600000) & (abs(offsets) >= 10000)
    mean_psd = psd.mean(axis=0)
    strongest = np.flatnonzero(eligible)[np.argmax(mean_psd[eligible])]
    return dict(raw_rms=dict(p50=float(p50), p95=float(p95), p99=float(p99), maximum=float(rms.max())),
                rms_128=rms.tolist(), observed_fraction_above_10x_median_power=float(np.mean(rms**2 > 10*p50**2)),
                relative_burst_line='10x this capture median power; descriptive, not calibrated occupancy',
                band_centers_hz=(center + (edges[:-1] + edges[1:])/2).tolist(),
                mean_psd_adc2_per_hz=avg, max_frame_psd_adc2_per_hz=peak,
                strongest_non_dc_hz=float(freq[strongest]), dc_exclusion_for_peak_hz=10000)


def native(root, plan):
    assert json.loads((root/'plan.json').read_text()) == plan
    report = json.loads((root/'report.json').read_text())
    centers = plan['frequencies']['centers_hz']
    assert report['backend'] == 'agx_iq_software_aggregate'
    assert report['sweep_id'] == plan['sweep_id'] and report['session_generation'] == plan['session_generation']
    assert len(report['points']) == len(centers)
    dataset = report['dataset']
    assert dataset['format'] == 'sigmf' and dataset['datatype'] == 'ci16_le' and dataset['bytes'] == len(centers)*BYTES
    data, meta = Path(dataset['data_path']), Path(dataset['metadata_path'])
    assert data.resolve() == data and meta.resolve() == meta and data.parent == meta.parent == root
    assert list(root.glob('*.sigmf-data')) == [data] and list(root.glob('*.sigmf-meta')) == [meta]
    raw = data.read_bytes()
    assert len(raw) == len(centers)*BYTES
    metadata = json.loads(meta.read_text())
    assert metadata['global']['core:sample_rate'] == RATE and metadata['global']['core:datatype'] == 'ci16_le'
    assert metadata['global']['sdrharness:sample_layout'] == 'interleaved_iq'
    expected_captures, rows = [], []
    previous_sequence = 0
    for i, (center, p) in enumerate(zip(centers, report['points'])):
        for key, value in dict(point_index=i, requested_center_hz=center, sample_rate_hz=RATE,
                rf_bandwidth_hz=1500000, captured_samples=COUNT, dropped_samples=0, overflow=False,
                clipped_samples=0, status_flags=0, session_generation=plan['session_generation']).items():
            assert p[key] == value, key
        assert abs(p['actual_center_hz']-center) <= 2 and p['rx_input'] == base.bg.live.RX_IDENTITY
        assert p['health'] == dict(healthy=True, flags=0, source='iio_adapter')
        assert p['timeout']['limit_ms'] == 1000 and not p['timeout']['timed_out']
        assert p['request_id'] > 0 and p['sequence'] > previous_sequence
        previous_sequence = p['sequence']
        expected_captures.append({'core:sample_start': i*COUNT, 'core:frequency': center,
            'sdrharness:point_index': i, 'sdrharness:rf_bandwidth_hz': 1500000, 'sdrharness:gain_db': 20})
        v = np.frombuffer(raw[i*BYTES:(i+1)*BYTES], dtype='<i2').reshape(-1, 2).astype(float)
        rows.append(dict(center_hz=center, request_id=p['request_id'], sequence=p['sequence'],
                         statistics=metrics(v[:, 0]+1j*v[:, 1], p['actual_center_hz'])))
    assert metadata['captures'] == expected_captures
    for key, value in dict(sample_rate_hz=RATE, rf_bandwidth_hz=1500000, gain_db=20,
                          settle_ms=500, frame_samples=COUNT, aggregate_frames=1, point_timeout_ms=1000).items():
        assert plan[key] == value, key
    return dict(hashes={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (data, meta, root/'plan.json', root/'report.json')}, rows=rows)


def select(sweeps):
    assert len(sweeps) == 3 and all(len(s['rows']) == 70 for s in sweeps)
    ranking = []
    for c in CENTERS:
        rows = [next(r for r in s['rows'] if r['center_hz'] == c) for s in sweeps]
        score = float(np.median([r['statistics']['raw_rms']['p95'] for r in rows]))
        ranking.append(dict(center_hz=c, median_round_p95_rms=score))
    ranking.sort(key=lambda r: (-r['median_round_p95_rms'], r['center_hz']))
    chosen = [2455000000]
    for row in ranking:
        if all(abs(row['center_hz']-c) >= 4000000 for c in chosen):
            chosen.append(row['center_hz'])
        if len(chosen) == 5:
            break
    assert len(chosen) == 5
    return dict(centers_hz=chosen, ranking=ranking,
                rule='2455MHz anchor plus four strongest median-round raw p95 RMS; >=4MHz separation')


def acquire():
    assert ROOT.resolve() == ROOT and not ROOT.exists() and 'torch' not in sys.modules
    ROOT.mkdir(mode=0o700)
    (ROOT/'scratch').mkdir(mode=0o700)
    os.environ.update(TMPDIR=str(ROOT/'scratch'), XDG_CACHE_HOME=str(ROOT/'scratch'))
    assert shutil.disk_usage(ROOT).free > MAX_BYTES + 64*1024*1024
    generation = int(time.time()*1000)
    audit = dict(schema_id='p201_background_map_v1', status='preflight', physical_input='operator confirmed RX1 antenna; external TX terminated and stopped',
        base_head=base.command(['git', '-C', base.REPO, 'rev-parse', 'HEAD']).strip(),
        centers_hz=CENTERS, max_points=225, max_bytes=MAX_BYTES, free_bytes=shutil.disk_usage(ROOT).free,
        overall_deadline_seconds=1200, survey_call_deadline_seconds=300, focus_call_deadline_seconds=15,
        estimated_wall_seconds=300, point_capture_deadline_ms=1000, sample_seconds=COUNT/RATE,
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        controller_sha256=hashlib.sha256(base.BINARY.read_bytes()).hexdigest(), numpy=np.__version__,
        tx_operations=0, model_windows=0, recognizer_available=False, independent_labels=0, sweeps=[])
    before = None
    save(ROOT/'audit.json', audit)
    try:
        audit['nx_before'] = base.tx_preflight()
        base.idle()
        pids = ssh('pidof sdrd').split(); assert len(pids) == 1
        assert ssh(f'readlink /proc/{pids[0]}/exe').strip() == '/sd/sdr-agent/current/sdrd'
        audit['daemon_pid'] = pids[0]
        audit['daemon_sha256'] = ssh('sha256sum /sd/sdr-agent/current/sdrd').split()[0]
        audit['health_before'] = json.loads(base.command([base.BINARY, '--mode', 'health', '--sdrd', '192.168.1.10:43110']))
        before = ssh(base.STATE)
        lines = before.splitlines(); assert len(lines) % 2 == 0
        state = dict(zip(lines[::2], lines[1::2]))
        assert all(v == '0' for p,v in state.items() if p.endswith(('_en', '/enable')))
        assert all(state[f'/sys/bus/iio/devices/iio:device0/in_voltage{i}_gain_control_mode'] == 'manual' for i in (0,1))
        audit.update(radio_before=before, status='running')
        def capture(centers, phase, round_index):
            index = len(audit['sweeps']); gen = generation+index
            root = ROOT/f'capture-{index:02d}'; root.mkdir(mode=0o700)
            plan = dict(sweep_id=f'background-map-{gen}', session_generation=gen,
                frequencies=dict(kind='centers', centers_hz=centers), sample_rate_hz=RATE,
                rf_bandwidth_hz=1500000, gain_db=20, settle_ms=500, frame_samples=COUNT,
                aggregate_frames=1, point_timeout_ms=1000, detection_threshold_db=12.)
            remote = [f'/tmp/sdr-agent-dev/agx-sweep-{gen}-{i}' for i in range(len(centers))]
            base.idle(); assert ssh(base.STATE) == before
            assert shutil.disk_usage(ROOT).free > len(centers)*BYTES+16*1024*1024
            save(root/'plan.json', plan)
            audit['active'] = dict(runner_pid=os.getpid(), generation=gen, p201_paths=remote)
            audit.setdefault('all_p201_paths', []).extend(remote)
            save(ROOT/'audit.json', audit)
            print(json.dumps(dict(phase=phase, round=round_index, plan=plan, max_bytes=len(centers)*BYTES,
                free_bytes=shutil.disk_usage(ROOT).free, agx_root=str(root), p201_paths=remote,
                stop=f'{base.BINARY} --mode cancel --sdrd 192.168.1.10:43110 --session-generation {gen}')), flush=True)
            p = subprocess.Popen([str(base.BINARY), '--mode', 'sweep', '--sdrd', '192.168.1.10:43110',
                '--sigmf-directory', str(root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            started = time.time()
            try:
                out, err = p.communicate(json.dumps(plan), timeout=300 if phase=='survey' else 15)
                (root/'stderr.log').write_text(err)
                assert p.returncode == 0, err[-2000:]
                save(root/'report.json', json.loads(out))
                result = native(root, plan)
                audit['sweeps'].append(dict(index=index, phase=phase, round=round_index, started_unix=started,
                    elapsed_seconds=time.time()-started, **result))
            except BaseException:
                try:
                    audit['cancel'] = json.loads(base.command([base.BINARY, '--mode', 'cancel', '--sdrd',
                        '192.168.1.10:43110', '--session-generation', gen], timeout=6))
                finally:
                    if p.poll() is None:
                        p.terminate()
                        try: p.communicate(timeout=3)
                        except subprocess.TimeoutExpired: p.kill(); p.communicate(timeout=3)
                raise
            finally:
                base.restoration(before)
                ssh(' && '.join(f'test ! -e {x}' for x in remote))
                save(ROOT/'audit.json', audit)
            audit['sweeps'][-1].update(restored=True, remote_absent=True)
            print(json.dumps(dict(completed=index, phase=phase, points=len(centers), elapsed=audit['sweeps'][-1]['elapsed_seconds'])), flush=True)
        for round_index in range(3): capture(CENTERS, 'survey', round_index)
        audit['selection'] = select(audit['sweeps'])
        save(ROOT/'audit.json', audit)
        for round_index in range(3):
            for center in audit['selection']['centers_hz']: capture([center], 'focus', round_index)
        audit['nx_after'] = base.tx_preflight()
        audit['status'] = 'completed'
    except BaseException as error:
        audit.update(status='failed', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        signal.alarm(0)
        try:
            if before is not None:
                audit['radio_after'] = base.restoration(before)
                assert ssh('pidof sdrd').split() == [audit['daemon_pid']]
                assert ssh('sha256sum /sd/sdr-agent/current/sdrd').split()[0] == audit['daemon_sha256']
                audit['health_after'] = json.loads(base.command([base.BINARY, '--mode', 'health', '--sdrd', '192.168.1.10:43110']))
                audit['restored'] = True
        except BaseException as error:
            audit.update(status='failed', restoration_error=str(error)); raise
        finally: save(ROOT/'audit.json', audit)


def verify():
    audit = json.loads((ROOT/'audit.json').read_text())
    assert audit['status']=='completed' and audit['restored'] and len(audit['sweeps'])==18
    assert audit['numpy']==np.__version__ and 'torch' not in sys.modules
    for s in audit['sweeps']:
        root=ROOT/f'capture-{s["index"]:02d}'
        result=native(root, json.loads((root/'plan.json').read_text()))
        assert result['hashes']==s['hashes'] and result['rows']==s['rows']
        assert s['restored'] and s['remote_absent']
    assert select(audit['sweeps'][:3])==audit['selection']
    print('225-point data, selection and exact numerical replay passed; no RF or model calls')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument('--acquire', action='store_true'); g.add_argument('--verify', action='store_true')
    args=parser.parse_args()
    if args.verify: verify()
    else:
        def abort(signum, frame): raise RuntimeError(f'stop signal {signum}')
        for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM): signal.signal(sig,abort)
        signal.alarm(1200)
        acquire()
