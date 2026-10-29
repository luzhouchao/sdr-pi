#!/usr/bin/env python3
"""Read-only fixed-frequency guard phasors; no correction or model loading."""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import shutil
import signal
import time

import numpy as np

REPO = Path(__file__).resolve().parents[3]
PARENT = Path('/var/tmp/sdrharness-dev/rml2018a-leading-guard-20260916')
OUT = Path('/var/tmp/sdrharness-dev/rml2018a-lo-temporal-20260917')
RATE = 2100000
BLOCKS = (12, 24, 48, 96)


def read(p):
    return json.loads(Path(p).read_text())


def save(p, v):
    Path(p).write_text(json.dumps(v, indent=2, allow_nan=False) + '\n')


def digest(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def ahash(x):
    return hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest()


def phasors(z, frequency, starts):
    """Absolute local sample coordinates preserve inter-guard phase."""
    z = np.asarray(z, dtype=np.complex128)
    if not np.isfinite(z).all() or not np.isfinite(frequency):
        raise ValueError('finite input required')
    result = []
    for start in starts:
        if start < 0 or start + 384 > len(z):
            raise ValueError('complete guard required')
        for half in (0, 1):
            at = start + half * 192
            n = np.arange(at, at + 192)
            d = z[n] * np.exp(-2j * np.pi * frequency * n / RATE)
            mean = d.mean()
            se = []
            for size in BLOCKS:
                blocks = d.reshape(-1, size).mean(1)
                se.append(float(np.sqrt(np.sum(abs(blocks - mean)**2) /
                                        (len(blocks) * (len(blocks) - 1)))))
            result.append(dict(start=at, half=half, mean=[mean.real, mean.imag],
                               residual_power=float(np.mean(abs(d - mean)**2)), se=se))
    return result


def metrics(halves):
    """Curvature removes a constant residual frequency offset; no IQ correction."""
    a = np.array([complex(*h['mean']) for h in halves]).reshape(-1, 2)
    se = np.array([h['se'] for h in halves]).reshape(-1, 2, len(BLOCKS))
    amp = abs(a)
    if np.any(amp < 1e-10):
        return dict(identifiable=False)
    phase = np.unwrap(np.angle(a), axis=0)
    future = a[-3:]
    curvature = phase[-3] - 2 * phase[-2] + phase[-1]
    # SE is an empirical block statistic, not a calibrated confidence interval.
    sigma = se / amp[:, :, None]
    curv_se = np.sqrt(sigma[-3]**2 + 4 * sigma[-2]**2 + sigma[-1]**2)
    curvature_flags = (abs(curvature[:, None]) > 4 * curv_se).all(axis=0)
    same_sign = bool(curvature[0] * curvature[1] > 0)
    amp_change = amp[-1] - amp[-3]
    amp_se = np.sqrt(se[-1]**2 + se[-3]**2)
    amp_flags = (abs(amp_change[:, None]) > 4 * amp_se).all(axis=0)
    slope = (phase[-1] - phase[-3]) / (2 * 17920 / RATE * 2 * np.pi)
    result = dict(identifiable=True, future_phase_curvature_rad=curvature.tolist(),
                  curvature_empirical_se=curv_se.tolist(),
                  curvature_both_halves_4se=(curvature_flags & same_sign).tolist(),
                  future_endpoint_amplitude_change_fraction=(amp_change / amp[-3]).tolist(),
                  amplitude_both_halves_4se=(amp_flags & (amp_change[0] * amp_change[1] > 0)).tolist(),
                  residual_phase_slope_hz=slope.tolist(),
                  future_amplitude_range_fraction=(np.ptp(abs(future), axis=0) / abs(future).mean(0)).tolist())
    if len(a) == 4:
        result['preceding_to_first_future_phase_rad'] = (phase[1] - phase[0]).tolist()
        result['preceding_to_first_future_amplitude_fraction'] = ((amp[1] - amp[0]) / amp[0]).tolist()
    return result


def parents():
    audit = read(REPO / 'docs/evidence/RML2018A_LEADING_GUARD_2026-09-16.json')
    entries = {Path(x['path']).name: x for x in audit['files']}
    for name in ('rows.json', 'plan.json', 'frame-identities.json'):
        assert digest(PARENT / name) == entries[name]['sha256'], name
    plan = read(PARENT / 'plan.json')
    for item in plan['inputs']:
        st = Path(item['path']).stat()
        assert (st.st_size, st.st_mtime_ns) == (item['bytes'], item['mtime_ns'])
    frames = read(PARENT / 'frame-identities.json')
    for item in frames:
        assert digest(item['path']) == item['sha256'], item['path']
    rows = read(PARENT / 'rows.json')
    assert len(rows) == 2496 and len({r['source_row'] for r in rows}) == 2496
    assert len({(r['raw_path'], r['frame']) for r in rows}) == 2496
    return plan, rows, entries


def plan():
    OUT.mkdir(exist_ok=False)
    p, rows, entries = parents()
    value = dict(schema='fixed-frequency-lo-temporal-v1', rows=len(rows),
                 parent_files={n: entries[n] for n in ('rows.json', 'plan.json', 'frame-identities.json')},
                 inputs=p['inputs'], software_sha256=digest(__file__),
                 frequency='archived baseline guard frequency, fixed per context; no new search',
                 coordinates='baseline context origin: pilot-256; prepend192, demodulate in leading coordinates',
                 guards='three historical future guards; preceding only when previous spacing is exactly17920',
                 uncertainty='complex phasor block SE at12/24/48/96 samples;4SE descriptive screen in both halves with matching sign; not calibrated p-values',
                 metrics='phase second difference across3 future guards; endpoint amplitude change; phase slope is confounded with fixed frequency error',
                 limitation='shared frequency fit, adjacent correlated halves, possible shared ADC across nearby contexts; no independent replication or physical causality claim',
                 budget=dict(seconds=600, host_bytes=2*1024**3, output_bytes=64*1024**2,
                             context_bytes=2496*(65535+192)*4, free_bytes=shutil.disk_usage(OUT).free),
                 rf=False, predictions=0, source_payload_used=False, production_change=False)
    assert value['budget']['free_bytes'] > 1024**3
    save(OUT / 'plan.json', value)


def run():
    started = time.monotonic()
    p = read(OUT / 'plan.json')
    assert digest(__file__) == p['software_sha256']
    assert not (OUT / 'started.json').exists()
    save(OUT / 'started.json', dict(time_ns=time.time_ns()))
    signal.alarm(p['budget']['seconds'])
    _, rows, _ = parents()
    records = []
    cache = {}
    mapped_path = None
    checked_halves = 0
    max_mean_error = max_se_error = 0.
    for r in rows:
        if (OUT / 'STOP').exists():
            raise InterruptedError('STOP requested')
        if mapped_path != r['raw_path']:
            native = np.memmap(r['raw_path'], dtype='<i2', mode='r').reshape(-1, 2)
            mapped_path = r['raw_path']
            cache.clear()
        path = str(Path(r['frames']) / f"{r['frame']//64:03d}.json")
        if path not in cache:
            cache[path] = read(path)
        fr = cache[path][r['frame'] % 64]
        at = fr['marker_offset']
        iq = native[at-448:at-256+65535]
        assert iq.shape == (65535+192, 2)
        assert ahash(iq) == r['context_with_leading_sha256']
        assert ahash(iq[192:]) == r['sync']['context_sha256']
        g = fr['guard']['v1']
        assert g['guard_intervals'] == [[17728,18112],[35648,36032],[53568,53952]]
        has_pre = r['previous_spacing_samples'] == 17920 and r['frame'] > 0
        starts = ([0] if has_pre else []) + [17920, 35840, 53760]
        z = iq[:, 0].astype(float) + 1j*iq[:, 1].astype(float)
        halves = phasors(z, g['frequency_hz'], starts)
        rotation = np.exp(2j*np.pi*g['frequency_hz']*192/RATE)
        for current, old in zip(halves[-6:], fr['guard']['halves']):
            err = abs(complex(*current['mean'])*rotation - complex(*old['observed_amplitude']))
            se_err = abs(current['se'][1] - old['standard_error'])
            max_mean_error = max(max_mean_error, err)
            max_se_error = max(max_se_error, se_err)
            assert err < 1e-7 and se_err < 1e-7, 'archived phasor/SE reproduction'
            checked_halves += 1
        records.append(dict(index=r['index'], source_row=r['source_row'], raw_path=r['raw_path'],
                            frame=r['frame'], marker_offset=at, validation_only=True,
                            context_sha256=r['context_with_leading_sha256'], frequency_hz=g['frequency_hz'],
                            preceding_available=has_pre, unavailable_spacing=r['previous_spacing_samples'] if not has_pre else None,
                            halves=halves, metrics=metrics(halves)))
    assert len(records) == 2496
    save(OUT / 'rows.json', records)
    valid = [r for r in records if r['metrics']['identifiable']]
    def quant(key):
        return np.percentile([r['metrics'][key] for r in valid], [5,50,95], axis=0).tolist()
    summary = dict(rows=len(records), identifiable=len(valid), preceding_available=sum(r['preceding_available'] for r in records),
                   block_sizes=list(BLOCKS),
                   curvature_screen_counts=np.sum([r['metrics']['curvature_both_halves_4se'] for r in valid], axis=0).tolist(),
                   amplitude_screen_counts=np.sum([r['metrics']['amplitude_both_halves_4se'] for r in valid], axis=0).tolist(),
                   curvature_all_block_sizes=sum(all(r['metrics']['curvature_both_halves_4se']) for r in valid),
                   amplitude_all_block_sizes=sum(all(r['metrics']['amplitude_both_halves_4se']) for r in valid),
                   curvature_p05_p50_p95=quant('future_phase_curvature_rad'),
                   amplitude_range_p05_p50_p95=quant('future_amplitude_range_fraction'),
                   phase_slope_hz_p05_p50_p95=quant('residual_phase_slope_hz'),
                   archive_checks=dict(halves=checked_halves,max_mean_error=max_mean_error,max_se_error=max_se_error),
                   elapsed_seconds=time.monotonic()-started,
                   peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                   rf=0, predictions=0, production_change=False)
    assert summary['peak_rss_bytes'] < p['budget']['host_bytes']
    save(OUT / 'summary.json', summary)
    assert sum(f.stat().st_size for f in OUT.rglob('*') if f.is_file()) < p['budget']['output_bytes']
    signal.alarm(0)
    print(json.dumps(summary))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('plan', 'run'))
    args = parser.parse_args()
    {'plan': plan, 'run': run}[args.command]()
