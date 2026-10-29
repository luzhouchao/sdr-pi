"""Reproducible four-dataset RRC channel simulation, never an RF result."""
import argparse
import hashlib
import json
import resource
import time
from pathlib import Path
import numpy as np
from amc_dataset_contract import read_selected
import amc_rrc_transport as r

REPO = Path(__file__).resolve().parents[3]
PARENT = REPO/'docs/evidence/AMC_SOURCE_STORE_2026-09-26.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--uniform', action='store_true', help='common payload selected by --payload and sourceZ18 for all four')
    parser.add_argument('--payload',type=int,choices=[2048,16384],default=16384)
    args = parser.parse_args()
    root = args.output
    r.c.require(root.is_absolute() and root.resolve() == root and
                root.is_relative_to(Path('/var/tmp/sdrharness-dev')) and not root.exists(),
                'new isolated validation directory')
    root.mkdir(parents=True)
    parent = json.loads(PARENT.read_text())
    selection = parent['source_selection']
    old = parent['rml2018a_comparison']
    value = old['results']['18' if args.uniform else '30']['contract']
    split = REPO/'local-assets/amc-eval/splits/server-seed42-20260914/RML2018a_split_seed42_tr700_val150_te150.npz'
    r.c.require(hashlib.sha256(split.read_bytes()).hexdigest() == old['split_sha256'], '2018 split SHA')
    with np.load(split) as f:
        r.c.require(set(value['source_rows']) <= set(f['val']), '2018 fixed validation membership')
    selection['rml2018a'] = dict(contract=value, source_path=old['source_path'],
        source_bytes=old['source_bytes'], splits=[dict(path=str(split), seed=42, sha256=old['split_sha256'])],
        selection_reason='fixed32/class seed42 rows from prior FFT screen', source_z=18 if args.uniform else 30)
    frame_payload = args.payload if args.uniform else None
    plan = dict(scope='offline channel simulation; no radio/model/training', selection_seed=20260926,
                source_selection=selection, transport=r.contract(frame_payload),
                cfo_hz=1373., phase_rad=.41, lo_relative_amplitude=.08,
                lo_frequency_delta_from_nominal_hz=1.37, noise_component_std=.0002,
                adc_counts_per_unit=2000, initial_rf_samples=317, trailing_rf_samples=700,
                guard_max_relative_rms_error=.02, required_synchronized_fraction=1.,
                required_guard_applied_fraction=1., input_chunks_rf_samples=131099,
                maximum_adc_samples=r.MAX_CAPTURE,
                source_sha_basis='parent complete source audit; per-selected-IQ SHA rechecked, 2018 whole SHA historical')
    (root/'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2)+'\n')
    result = dict(parent_sha256=hashlib.sha256(PARENT.read_bytes()).hexdigest(), datasets={}, status='running')
    for dataset, entry in selection.items():
        started = time.monotonic()
        contract = entry['contract']
        x, actual = read_selected(entry['source_path'], dataset, np.array(contract['source_rows']),
                                  contract['class_names'], contract['source_sha256'])
        r.c.require(actual == contract, 'source metadata identity')
        digest = hashlib.sha256(x.tobytes()).hexdigest()
        if 'selected_iq_sha256' in entry:
            r.c.require(digest == entry['selected_iq_sha256'], 'selected original IQ hash')
        run_id = 'rrc-four-dataset-'+dataset+'-20260926'
        tx, txinfo = r.transmit(x, run_id, frame_payload_samples=frame_payload)
        frequency = np.fft.fftfreq(len(tx), 1/r.c.RATE)
        power = abs(np.fft.fft(tx))**2
        inside = (abs(frequency)<=700000)&(abs(frequency-250000)<=700000)
        outside = float(power[~inside].sum()/power.sum())
        z = np.r_[np.zeros(317), tx, np.zeros(700)]
        n = np.arange(len(z))
        rng = np.random.default_rng(20260926)
        z *= np.exp(2j*np.pi*1373*n/r.c.RATE+.41j)
        z += .08*np.exp(2j*np.pi*(250000+1373+1.37)*n/r.c.RATE+.2j)
        z += .0002*(rng.normal(size=len(z))+1j*rng.normal(size=len(z)))
        adc = np.rint(2000*np.stack((z.real, z.imag), axis=1))
        r.c.require(max(abs(adc).ravel())<32767, 'simulated ADC clipping')
        adc = adc.astype('<i2')
        decoder = r.Decoder(run_id, x.shape[1], len(x), frame_payload_samples=frame_payload)
        for start in range(0, len(adc), 131099):
            decoder.feed(adc[start:start+131099])
        decoder.feed(np.empty(0, complex), final=True)
        decoded = decoder.result()
        reference = x/np.sqrt(np.mean(abs(x)**2, axis=1))[:, None]
        metrics = {}
        for tag in ('raw', 'guard'):
            y = decoded['inputs'][tag][:,0]+1j*decoded['inputs'][tag][:,1]
            errors = np.sqrt(np.mean(abs(y-reference)**2, axis=1))
            metrics[tag] = dict(valid=int(decoded['masks'][tag].sum()),
                max_relative_rms_error=float(np.nanmax(errors)) if np.isfinite(errors).any() else None,
                median_relative_rms_error=float(np.nanmedian(errors)) if np.isfinite(errors).any() else None,
                row_relative_rms_error=[float(v) if np.isfinite(v) else None for v in errors],
                inputs_sha256=hashlib.sha256(decoded['inputs'][tag].tobytes()).hexdigest())
        applied = sum(f.get('guard',{}).get('status')=='applied' for f in decoded['frames'])
        per_frame = frame_payload//x.shape[1] if args.uniform else 16
        expected_starts = np.array([317+(i//per_frame)*4*(1536+per_frame*x.shape[1])+5120+(i%per_frame)*4*x.shape[1] for i in range(len(x))])
        correct_offsets = bool(np.array_equal(expected_starts, decoded['sample_starts']))
        passed = (metrics['guard']['valid']==len(x) and metrics['guard']['max_relative_rms_error']<=.02
                  and applied==(len(x)+per_frame-1)//per_frame and correct_offsets and outside<.01)
        record = dict(rows=len(x), native_samples=x.shape[1], selected_iq_sha256=digest,
            tx=txinfo, whole_tx_outside_fraction=outside, simulated_adc_sha256=hashlib.sha256(adc.tobytes()).hexdigest(),
            adc_samples=len(adc), metrics=metrics, applied_frames=applied, exact_adc_lineage=correct_offsets,
            frames=decoded['frames'], missing_frames=decoded['missing_frames'], passed=bool(passed),
            elapsed_seconds=time.monotonic()-started,
            process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
        result['datasets'][dataset] = record
        (root/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
        print(dataset, 'passed', passed, 'valid', metrics['guard']['valid'], 'guard frames', applied,
              'max error', metrics['guard']['max_relative_rms_error'], flush=True)
    result['status'] = 'passed' if all(v['passed'] for v in result['datasets'].values()) else 'failed'
    (root/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    return 0 if result['status']=='passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
