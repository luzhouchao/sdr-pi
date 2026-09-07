#!/usr/bin/env python3
"""Seven preregistered source perturbations; no RF, new dataset rows or production decisions."""
import argparse
import asyncio
import importlib.util
import json
import math
from pathlib import Path
import shutil
import signal
import time
import numpy as np

if not __debug__:
    raise RuntimeError('validation requires assertions')
SCRIPTS = Path(__file__).parent
ROOT = SCRIPTS.resolve().parents[2]
AUDIT_PATH = ROOT/'docs/evidence/B210_P201_RX40_PAIRED_AUDIT_2026-09-06.json'
AUDIT_HASH = '1d3c01a3f26e3661295b2a72facd87d3d72d1510bb279e1afd3344fbbc84b432'
FEATURE = Path('/var/tmp/sdrharness-dev/b210-source-sensitivity-906d')
RATE = 2100000
SEED = 20260906


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS/filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


paired = module('source_pair', 'compare-b210-source-received.py')


def pinned_json(path, digest):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 65536:
        raise ValueError('bounded regular evidence file required')
    raw = path.read_bytes()
    if paired.sha(raw) != digest:
        raise ValueError('historical evidence hash mismatch')
    return json.loads(raw)


def variants(source, lag, frequency):
    source = np.asarray(source)
    if (source.shape != (4096, 2) or not np.isfinite(source).all()
            or type(lag) is not int or not 0 <= lag < 4096
            or not math.isfinite(frequency) or not 0 < frequency < RATE/2):
        raise ValueError('source, lag or frequency shape')
    aligned = np.roll(source, lag, axis=0).astype(np.float64)
    z = aligned[:, 0] + 1j*aligned[:, 1]
    power = float(np.mean(abs(z)**2))
    if power <= 0:
        raise ValueError('zero source power')
    def iq(values):
        return np.asarray(np.stack((values.real, values.imag), axis=1), dtype='<f4')
    phase = 2*np.pi*frequency*np.arange(4096)/RATE
    noise = np.random.Generator(np.random.PCG64(SEED)).normal(size=(4096, 2))
    noise /= np.sqrt(np.square(noise).sum()/4096)
    result = {
        'source_original': np.asarray(source, dtype='<f4').copy(),
        'source_aligned': np.asarray(aligned, dtype='<f4'),
        'aligned_cfo_positive': iq(z*np.exp(1j*phase)),
        'aligned_cfo_negative': iq(z*np.exp(-1j*phase)),
        'aligned_phase90': iq(z*1j),
    }
    metadata = {
        'source_original': dict(impairment='none', circular_lag=0),
        'source_aligned': dict(impairment='none', circular_lag=lag),
        'aligned_cfo_positive': dict(impairment='cfo', frequency_hz=frequency, initial_phase_rad=0),
        'aligned_cfo_negative': dict(impairment='cfo', frequency_hz=-frequency, initial_phase_rad=0),
        'aligned_phase90': dict(impairment='constant_phase', phase_rad=float(np.pi/2)),
    }
    for db in (20, 10):
        name = f'aligned_awgn{db}'
        result[name] = np.asarray(aligned + noise*np.sqrt(power/10**(db/10)), dtype='<f4')
        residual = result[name].astype(np.float64)-aligned
        actual_db = float(10*np.log10(power/(np.square(residual).sum()/4096)))
        assert abs(actual_db-db) < 1e-5
        metadata[name] = dict(impairment='added_awgn', seed=SEED, requested_component_ratio_db=db,
                              actual_component_ratio_db=actual_db, total_snr_known=False)
    assert len(result) == 7
    return result, metadata


def prepare(feature):
    historical = pinned_json(AUDIT_PATH, AUDIT_HASH)
    raw = (feature/'train-tile.fc32').read_bytes()
    export = json.loads((feature/'transmission-plan.json').read_text())
    assert len(raw) == 32768 and paired.sha(raw) == export['payload_sha256'] == paired.SOURCE_HASH
    assert export['rows'] == [102400, 102401, 102403, 102404]
    assert export['split'] == 'train' and export['locked_test_read'] is False
    assert export['class_id'] == 0 and export['dataset_nominal_snr_db'] == 30
    lag = historical['paired_comparison']['source_circular_lag']
    frequency = historical['source_analysis']['tone']['frequency_difference_hz']
    inputs, metadata = variants(np.frombuffer(raw, dtype='<f4').reshape(4096, 2), lag, frequency)
    tensors = {name: paired.normalize(iq) for name, iq in inputs.items()}
    for name, previous in [('source_original', 'source_original_order'), ('source_aligned', 'source_receive_aligned')]:
        assert paired.sha(tensors[name].tobytes()) == historical['paired_comparison']['results'][previous]['model_input_sha256']
    return inputs, metadata, tensors, historical, export


async def run(feature):
    assert feature == FEATURE and feature.resolve() == feature
    output = feature/'source-sensitivity.json'
    assert not output.exists()
    with (feature/'inference-started.json').open('x') as marker:
        json.dump(dict(started_at_unix_ns=time.time_ns(), max_experiment_windows=28, rf_operations=0), marker)
    inputs, metadata, tensors, historical, export = prepare(feature)
    assert shutil.disk_usage(feature).free > 8*1024*1024
    receipt = dict(schema_id='b210_source_sensitivity_v1', status='failed', rf_operations=0,
                   historical_audit_sha256=AUDIT_HASH, historical_receive_result_recomputed=False,
                   source_tile_sha256=export['payload_sha256'], source_rows=export['rows'], source_split='train',
                   source_nominal_id=0, dataset_nominal_snr_db=30, source_phase_start_is_synthetic=True,
                   current_frequency_measured=False, independent_labels=0, recognizer_available=False,
                   production_preprocess_changed=False, production_profile_compatible=False,
                   model_precision_experiment=False, interpretation='single_source_synthetic_sensitivity_not_RF_causal_proof',
                   registered_experiment_windows=28, backend_warmup_windows=2, results={})
    from gpu_lease import GpuLease
    lease = GpuLease(feature/'gpu-gate', 'mamba')
    token = None
    try:
        token = await lease.acquire(time.monotonic()+10, request='source-impairment-sensitivity')
        worker = module('sensitivity_worker', 'amc-mamba-worker.py')
        backend = worker.RfV1Backend(ROOT/'jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json')
        assert all(p.dtype == worker.torch.float32 for p in backend.model.parameters())
        assert backend.admission_identity == historical['paired_comparison']['identity']
        receipt['identity'] = backend.admission_identity
        receipt['compute'] = 'cuda_fp16_autocast_fp32_weights'
        receipt['case_order'] = list(inputs)
        for name, data in tensors.items():
            logits, elapsed = [], 0
            for window in data:
                values, timing = backend.classify_logits(np.ascontiguousarray(window))
                logits.append(values);elapsed += timing
            values = np.asarray(logits, dtype=np.float64)
            assert values.shape == (4, 24) and np.isfinite(values).all()
            mean = values.mean(axis=0)
            probabilities = np.exp(mean-mean.max());probabilities /= probabilities.sum()
            iq = inputs[name].astype(np.float64)
            rms = float(np.sqrt(np.square(iq).sum()/4096))
            numeric_id = int(probabilities.argmax())
            row = dict(perturbation=metadata[name], numeric_id=numeric_id, name_status='provisional',
                       window_numeric_ids=list(map(int, values.argmax(axis=1))),
                       uncalibrated_probability=float(probabilities[numeric_id]),
                       nominal_source_id_agreement=(numeric_id == 0), inference_us=elapsed,
                       raw_input_sha256=paired.sha(inputs[name].tobytes()), model_input_sha256=paired.sha(data.tobytes()),
                       mean_logits_sha256=paired.sha(mean.astype('<f8').tobytes()),
                       raw_complex_rms=rms, raw_dc_fraction=float(np.linalg.norm(iq.mean(axis=0))/rms))
            if name in ('source_original', 'source_aligned'):
                previous = 'source_original_order' if name == 'source_original' else 'source_receive_aligned'
                row['historical_mean_logits_reproduced'] = row['mean_logits_sha256'] == historical['paired_comparison']['results'][previous]['mean_logits_sha256']
            receipt['results'][name] = row
        receipt['status'] = 'sensitivity_comparison_completed'
    except BaseException as error:
        receipt['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        if token is not None:lease.release(token)
        receipt['gpu_lease'] = lease.metrics.copy()
        lease.close()
        output.write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    def abort(signum, frame):
        raise RuntimeError(f'stop signal {signum}')
    for sig in (signal.SIGTERM, signal.SIGINT):signal.signal(sig, abort)
    asyncio.run(run(args.directory))
