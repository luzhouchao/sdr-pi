#!/usr/bin/env python3
"""Read-only IQ comparison with the historical FIR; no RF or model inference."""
import argparse
import importlib.util
import json
from pathlib import Path

import h5py
import numpy as np

import rml2018a_campaign as c


def coherence(x, y):
    return float(abs(np.vdot(x, y)) / max(np.linalg.norm(x)*np.linalg.norm(y), 1e-30))


def analyze(root):
    read = lambda p: json.loads(p.read_text())
    plan = read(root/'run-plan.json')
    dataset = Path(plan['source']['path'])
    c.require(dataset.stat().st_size == plan['source']['bytes'] and
              dataset.stat().st_mtime_ns == plan['source']['mtime_ns'], 'source identity')
    path = Path(__file__).with_name('repair-b210-lo-leakage.py')
    spec = importlib.util.spec_from_file_location('historical_filter', path)
    repair = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(repair)
    fir = repair.coefficients()
    c.require(c.digest(fir.astype('<f8').tobytes()) ==
              'd0e12014bedae088b71366497299adc3a1be0a45cf622e9cbb346d4ea0c8c8be', 'historical FIR identity')
    results = []
    # Fixed successful pilot set; no scan for favorable source rows or windows.
    for index in (4267, 4268, 22016):
        batch = root/f'batch-{index:07d}'
        audit = read(batch/'audit.json'); source = read(batch/'source.json')
        done = read(batch/'capture-complete.json')
        c.require(c.file_hash(batch/'audit.json') == done['audit_sha256'], 'audit seal')
        c.require(done['rows'] == source['rows'] == c.batch_rows(2555904, index), 'row identity')
        iq_path = Path(audit['seal']['iq_path'])
        c.require(c.file_hash(iq_path) == audit['seal']['iq_sha256'], 'native IQ hash')
        v = np.fromfile(iq_path, dtype='<i2').reshape(-1, 2)
        z = v[:, 0].astype(float) + 1j*v[:, 1]
        c.require(z.shape == (c.RX_SAMPLES,), 'native IQ shape')
        sync = audit['sync']; start = sync['payload_marker_offset'] + c.MARKER
        c.require(start >= 128 and start+24*1024 <= len(z)-128, 'full FIR halos')
        n = np.arange(len(z))
        rotation = np.exp(-2j*np.pi*sync['estimated_cfo_hz']*n/c.RATE +
                          1j*sync['phase_rotation_rad'])
        raw = (z*rotation)[start:start+24*1024].reshape(24, 1024)
        filtered = (repair.reject(z)*rotation[128:-128])[start-128:start+24*1024-128].reshape(24, 1024)
        # Independent FFT convolution checks the valid-filter coordinates.
        size = 1 << (len(z)+len(fir)-2).bit_length()
        fft = np.fft.ifft(np.fft.fft(z, size)*np.fft.fft(fir, size))[256:len(z)]
        c.require(np.max(abs(fft-repair.reject(z))) < 1e-9, 'FIR coordinate check')
        with h5py.File(dataset, 'r') as h5:
            iq = h5['X'][source['rows']]
        c.require(c.digest(iq.tobytes()) == source['original_iq_sha256'], 'source rows hash')
        reference = iq[..., 0].astype(float) + 1j*iq[..., 1]
        frame, scales = c.packet(iq, plan['run_id'], index)
        c.require(c.digest(frame.tobytes()) == audit['tx_plan']['payload_sha256'], 'original TX frame')
        # Preserve actual neighbors/guards, rather than treating each row as periodic.
        middle = repair.reject(np.tile(frame, 3))[len(frame)-128:2*len(frame)-128]
        filtered_source = middle[c.GUARD+c.MARKER:-c.GUARD].reshape(24, 1024)/scales[:, None]
        rows = []
        for k, row in enumerate(source['rows']):
            power = np.mean(abs(reference[k])**2)
            retention = float(np.mean(abs(filtered_source[k])**2)/power)
            distortion = float(np.mean(abs(filtered_source[k]-reference[k])**2)/power)
            rows.append(dict(row=row, raw_coherence=coherence(reference[k], raw[k]),
                filtered_coherence=coherence(reference[k], filtered[k]),
                filtered_to_filtered_coherence=coherence(filtered_source[k], filtered[k]),
                source_power_retention=retention, source_distortion_power=distortion,
                source_filter_eligible=retention >= .99 and distortion <= .01))
        spectrum = abs(np.fft.fft(z*np.hanning(len(z))))**2
        frequencies = np.fft.fftfreq(len(z), 1/c.RATE)
        peak = int(spectrum.argmax())
        results.append(dict(batch=index, audit_path=str(batch/'audit.json'),
            audit_sha256=done['audit_sha256'], iq_sha256=audit['seal']['iq_sha256'],
            request_id=audit['seal']['request_id'], session_generation=audit['seal']['session_generation'],
            source_iq_sha256=source['original_iq_sha256'], fixed_sync=sync, rows=rows,
            raw_coherence_mean=float(np.mean([x['raw_coherence'] for x in rows])),
            filtered_coherence_mean=float(np.mean([x['filtered_coherence'] for x in rows])),
            rx_power_removed_fraction=float(1-np.sum(abs(filtered)**2)/np.sum(abs(raw)**2)),
            dominant_baseband_hz=float(frequencies[peak]),
            peak_plus_minus_2khz_spectral_fraction=float(spectrum[abs(frequencies-frequencies[peak])<=2000].sum()/spectrum.sum())))
    return dict(schema='rml2018a-historical-filter-comparison-v1', root=str(root),
        run_id=plan['run_id'], parent_plan_sha256=c.file_hash(root/'run-plan.json'),
        script_sha256=c.file_hash(__file__), historical_filter_script_sha256=c.file_hash(path),
        filter_contract=repair.filter_contract(), new_rf_captures=0, model_inferences=0,
        recognizer_available=False, timing_refit=False, results=results,
        interpretation='Post-hoc engineering waveform comparison; no new accuracy claim or physical interferer identification.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.root), indent=2, allow_nan=False))
