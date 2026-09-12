#!/usr/bin/env python3
"""Read-only posthoc guard diagnosis; never admits a rejected correction."""
import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

import rml2018a_campaign as c
import rml2018a_lo_cancellation as lo
import rml2018a_pilot_timing as timing
import rml2018a_guard_tone as guard_tone

REMAINING_CASES = (17664, 35414, 62038, 97536)


def tone_parts(values, start, frequency):
    """Descriptive coherent/noncoherent split at the already frozen LO frequency."""
    z = np.asarray(values, dtype=complex)
    c.require(z.shape == (192,) and np.isfinite(z).all() and
              type(start) is int and start >= 0 and np.isfinite(frequency), 'finite tone split')
    carrier = np.exp(2j*np.pi*frequency*np.arange(start, start+192)/c.RATE)
    amplitude = np.mean(z/carrier)
    total = float(np.mean(abs(z)**2))
    coherent = float(abs(amplitude)**2)
    return dict(total_counts2=total, coherent_at_frozen_lo_counts2=coherent,
                noncoherent_counts2=float(np.mean(abs(z-amplitude*carrier)**2)),
                coherent_fraction=coherent/total if total else 0.)


def neighborhoods(residual, intervals):
    """All complete 192-point windows around each guard/pilot, without ranking."""
    z = np.asarray(residual, dtype=complex)
    c.require(z.shape == (c.RX_SAMPLES,) and np.isfinite(z).all(), 'finite native residual')
    window = np.hanning(192)
    result = []
    for start, stop in intervals:
        marker = stop+64
        rows = []
        for at in range(marker-640, marker+1280-191, 64):
            if at < 0 or at+192 > len(z):
                continue
            v = z[at:at+192]
            spectrum = np.fft.fftshift(abs(np.fft.fft(v*window))**2)/(192*np.sum(window**2))
            rows.append(dict(start=at, stop=at+192, power_counts2=float(np.mean(abs(v)**2)),
                             spectrum_bin_power_counts2=spectrum.tolist()))
        result.append(dict(marker=marker, guard_interval=[start, stop], windows=rows))
    return result


def stats(values):
    z = np.asarray(values, dtype=complex)
    c.require(z.shape == (192,) and np.isfinite(z).all(), 'finite 192-sample guard half')
    power = float(np.mean(abs(z)**2))
    w = np.hanning(len(z))
    spectrum = abs(np.fft.fft(z*w))**2
    frequency = np.fft.fftfreq(len(z), 1/c.RATE)
    bands = [(0, 100000), (100000, 350000), (350000, 700000), (700000, 1050001)]
    # Integrated Hann periodogram; Parseval checked separately in tests.
    band_power = [float(spectrum[(abs(frequency) >= a) & (abs(frequency) < b)].sum()
                        / (len(z)*np.sum(w*w))) for a, b in bands]
    fine = abs(np.fft.fft(z*w, 16384))**2
    peak = float(np.fft.fftfreq(16384, 1/c.RATE)[fine.argmax()])
    amplitude = np.mean(z*np.exp(-2j*np.pi*peak*np.arange(len(z))/c.RATE))
    return dict(power_counts2=power, blocks64_power_counts2=[float(np.mean(abs(v)**2))
        for v in z.reshape(3, 64)], spectrum_band_power_counts2=band_power,
        spectrum_peak_hz=peak, peak_tone_projection_fraction=float(abs(amplitude)**2/power) if power else 0.)


def compatible(a, b):
    """Only tolerate scalar floating roundoff when replaying a sealed DSP record."""
    if isinstance(a, dict):
        return isinstance(b, dict) and a.keys() == b.keys() and all(compatible(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(compatible(x, y) for x, y in zip(a, b))
    if isinstance(a, float):
        return isinstance(b, (float, int)) and bool(np.isclose(a, b, rtol=1e-12, atol=1e-12))
    return a == b


def analyze(prepared_path, inventory_path):
    inventory = json.loads(inventory_path.read_text())
    expected = {f['path']: f for root in inventory['retained_roots'] for f in root['files']}
    accessed = {}

    def verify(path):
        path = Path(path)
        item = expected[str(path)]
        c.require(path.is_file() and path.stat().st_size == item['bytes'] and
                  c.file_hash(path) == item['sha256'], 'sealed parent mismatch: '+str(path))
        accessed[str(path)] = item
        return path

    def document(path):
        return json.loads(verify(path).read_text())

    prepared = document(prepared_path)
    remaining = prepared['schema'] == 'rml2018a-remaining-high-snr-comparison-v1'
    root = Path(prepared['parent'])
    plan = document(root/'run-plan.json')
    c.require(c.file_hash(root/'run-plan.json') == prepared['parent_plan_sha256'] and
              plan['run_id'] == prepared['run_id'], 'parent plan identity')
    for name in ('rml2018a_lo_cancellation.py', 'rml2018a_pilot_timing.py', 'rml2018a_guard_tone.py') if remaining else ('rml2018a_lo_cancellation.py', 'rml2018a_pilot_timing.py'):
        c.require(c.file_hash(Path(__file__).with_name(name)) == prepared['software'][name], 'parent DSP software')
    spec = importlib.util.spec_from_file_location('guard_native', Path(__file__).with_name('rml2018a-rf-campaign.py'))
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    results = []
    expected_batches = c.RML_REMAINING_BATCHES if remaining else c.RML_TIMING_BATCHES
    c.require([v['batch'] for v in prepared['results']] == list(expected_batches), 'bounded parent batches')
    for parent in prepared['results']:
        if remaining and parent['batch'] not in REMAINING_CASES:
            continue
        batch = parent['batch']; d = root/f'batch-{batch:07d}'
        audit = document(d/'audit.json'); report = document(d/'report.json')
        complete = document(d/'capture-complete.json'); rx_plan = document(d/'rx-plan.json')
        source = document(d/'source.json')
        verify(report['dataset']['data_path']); verify(report['dataset']['metadata_path'])
        verify(d/'tx-uhd.log')
        raw, seal = runner.native_check(d, rx_plan)
        c.require(seal == audit['seal'] == parent['seal'] and audit['restored'] and
                  c.file_hash(d/'audit.json') == complete['audit_sha256'] == parent['parent_audit_sha256'] and
                  source['rows'] == complete['rows'], 'native seal and source association')
        _, sync = c.synchronize(raw, prepared['run_id'], batch, 24)
        c.require(compatible(sync, parent['sync']) and compatible(sync, audit['sync']), 'original sync')
        returned, info = lo.cancel(raw, sync)
        c.require(compatible(info, parent['lo_cancellation']), 'original cancellation replay')
        if info['status'] == 'skipped':
            c.require(np.array_equal(returned, raw), 'rejection must preserve IQ')
        # Candidate residual is diagnostic even when cancellation was rejected.
        # Never compute SINR/model predictions or export corrected IQ here.
        n = np.arange(len(raw))
        residual = raw-complex(info['amplitude_real'], info['amplitude_imag'])*np.exp(
            2j*np.pi*info['frequency_hz']*n/c.RATE)
        guards = []
        for start, stop in info['guard_intervals']:
            guards.append(dict(start=start, stop=stop, start_ms=start/c.RATE*1000,
                training=stats(residual[start:start+192]), heldout=stats(residual[start+192:stop])))
        if remaining:
            returned, guard_info = guard_tone.cancel(raw, sync)
            c.require(compatible(guard_info, parent['guard_correction']), 'original guard decision replay')
            if guard_info['status'] == 'skipped':
                c.require(np.array_equal(returned, raw), 'guard rejection preserves IQ')
            tx = document(d/'tx-summary.json')
            c.require(tx['uhd_log_sha256'] == c.file_hash(d/'tx-uhd.log'), 'TX log identity')
            for g in guards:
                for kind, at in (('training', g['start']), ('heldout', g['start']+192)):
                    g[kind]['tone_parts'] = tone_parts(residual[at:at+192], at, info['frequency_hz'])
            begin = sync['payload_marker_offset']+c.MARKER
            results.append(dict(batch=batch, class_name=parent['class_name'], source_rows=source['rows'],
                seal=seal, selected_payload_interval=[begin, begin+24*1024],
                original_guard_status=guard_info['status'], original_guard_reason=guard_info['reason'],
                frozen_lo_frequency_hz=info['frequency_hz'], original_halves=guard_info['halves'],
                guards=guards, neighborhoods=neighborhoods(residual, info['guard_intervals']),
                tx={k:tx[k] for k in ('status','bytes_written','requested_tx_samples','go_unix_ns','child_exit_code','child_stopped','uhd_log_sha256')},
                uhd_tail_markers=parent['uhd_tail_markers']))
            continue
        # Inspect pilot fits only; discard the returned payload immediately.
        _, pilot = timing.correct(residual, sync, prepared['run_id'], batch)
        pilot.pop('output_sha256', None)
        pilot['diagnostic_only'] = True
        pilot['adopts_rejected_lo'] = False
        begin = sync['payload_marker_offset']+c.MARKER
        results.append(dict(batch=batch, class_name=parent['class_name'], source_rows=source['rows'],
            seal=seal, selected_payload_interval=[begin, begin+24*1024],
            original_lo_status=info['status'], original_lo_reason=info['reason'],
            original_holdout_suppression_db=info['heldout_suppression_db'], guards=guards,
            pilot_candidate_diagnostic=pilot, uhd_tail_markers=parent['uhd_tail_markers']))
    tx_comparison = []
    if remaining:
        for parent in prepared['results']:
            d = root/f"batch-{parent['batch']:07d}"
            tx = document(d/'tx-summary.json')
            log = verify(d/'tx-uhd.log').read_text()
            tail = log.split('Done!')[-1].strip()
            c.require(tail == parent['uhd_tail_markers'] and
                      tx['uhd_log_sha256'] == c.file_hash(d/'tx-uhd.log'), 'TX tail identity')
            tx_comparison.append(dict(batch=parent['batch'], class_name=parent['class_name'],
                guard_status=parent['guard_correction']['status'], uhd_tail=tail,
                feed_status=tx['status'], child_exit_code=tx['child_exit_code']))
    return dict(schema='rml2018a-remaining-guard-anomaly-posthoc-v1' if remaining else 'rml2018a-guard-anomaly-posthoc-v1', posthoc=True,
        rf_operations=0, source_iq_reads=0, model_windows=0, admitted_correction_changes=0,
        parent_inventory_sha256=c.file_hash(inventory_path), run_id=prepared['run_id'],
        software={name:c.file_hash(Path(__file__).with_name(name)) for name in
            ('diagnose-rml2018a-guard-anomaly.py', 'rml2018a_campaign.py', 'rml2018a-rf-campaign.py',
             'rml2018a_lo_cancellation.py', 'rml2018a_pilot_timing.py', 'rml2018a_guard_tone.py')},
        numpy_version=np.__version__, parent_files=list(accessed.values()), results=results,
        tx_comparison=tx_comparison,
        spectrum_absolute_bands_hz=[[0,100000],[100000,350000],[350000,700000],[700000,1050001]],
        limitations=['posthoc descriptive statistics, no new acceptance threshold',
            'candidate residual of rejected LO is never admitted as received SINR or model input',
            'pilot fits cannot establish sample continuity between pilots',
            'untimestamped UHD tail markers cannot localize events in native RX samples',
            'broad residual does not identify Wi-Fi, receiver noise, or transport as physical source'])


def plot(report, destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    if report['schema'] == 'rml2018a-remaining-guard-anomaly-posthoc-v1':
        fig, axes = plt.subplots(4, 3, figsize=(13, 12), constrained_layout=True)
        for row, case in enumerate(report['results']):
            for col, item in enumerate(case['neighborhoods']):
                ax = axes[row, col]; windows = item['windows']
                values = np.asarray([v['spectrum_bin_power_counts2'] for v in windows]).T
                times = [(v['start']+96-item['marker'])/c.RATE*1e6 for v in windows]
                frequencies = np.fft.fftshift(np.fft.fftfreq(192, 1/c.RATE))/1000
                mesh = ax.pcolormesh(times, frequencies, 10*np.log10(np.maximum(values, 1e-12)),
                                     shading='nearest', vmin=-25, vmax=30, cmap='viridis')
                for point in (-448, -64, 0, 1024):
                    ax.axvline(point/c.RATE*1e6, color='white', ls=':', lw=.7)
                ax.set(title=f"{case['class_name']} guard {col+1} @ {item['marker']/c.RATE*1000:.2f} ms",
                       xlabel='Time from pilot start (us)', ylabel='Baseband frequency (kHz)')
        fig.colorbar(mesh, ax=axes, label='Candidate residual bin power (dB counts squared)')
        fig.suptitle('Fixed-LO candidate residual; rejected corrections remain rejected\n192-point Hann / 64-point hop; pilot and payload energy is not background noise')
        fig.savefig(destination, dpi=140); plt.close(fig)
        return
    fig, axes = plt.subplots(2, 4, figsize=(14, 7), constrained_layout=True)
    for ax, case in zip(axes.flat, report['results']):
        for i, guard in enumerate(case['guards']):
            y = guard['training']['blocks64_power_counts2']+guard['heldout']['blocks64_power_counts2']
            ax.plot(np.arange(6)*64+32, y, 'o-', label=f'Guard {i+1} @ {guard["start_ms"]:.2f} ms')
        ax.axvline(192, color='gray', ls=':')
        ax.set(title=case['class_name'], xlabel='Samples within guard interior', ylabel='Residual power (counts squared)',
               yscale='log', ylim=(1, 60))
        ax.grid(alpha=.2); ax.legend(fontsize=7)
    fig.suptitle('Posthoc candidate LO residual: left = training; right = heldout\nOriginal gates unchanged; no rejected correction admitted')
    fig.savefig(destination, dpi=140); plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--inventory', type=Path)
    parser.add_argument('--plot-only', action='store_true', help='Plot saved analysis with a plotting Python environment')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    c.require(args.output.is_absolute() and args.output.parent == Path('/var/tmp/sdrharness-dev') and
              args.output.name.startswith('rml-guard-anomaly-'), 'diagnostic output root')
    if args.plot_only:
        c.require(not (args.output/'guard-residual.png').exists(), 'new plot required')
        plot(json.loads((args.output/'analysis.json').read_text()), args.output/'guard-residual.png')
    else:
        c.require(args.prepared is not None and args.inventory is not None, 'prepared and inventory required')
        c.require(not args.output.exists(), 'new output required')
        result = analyze(args.prepared, args.inventory)
        args.output.mkdir(mode=0o700)
        c.save(args.output/'analysis.json', result)
        print(json.dumps(dict(status='complete', batches=len(result['results']), rf_operations=0, model_windows=0)))
