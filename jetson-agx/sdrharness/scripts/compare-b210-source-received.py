#!/usr/bin/env python3
"""Bounded offline paired diagnostic; no RF, dataset access, production DTO or admission."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import time
import numpy as np

if not __debug__:
    raise RuntimeError('validation requires assertions')
SCRIPTS = Path(__file__).parent
ROOT = SCRIPTS.resolve().parents[2]
SOURCE_HASH = 'c95ac58c1fd91ef4da992622dbdf70a9bc5884d0941419083451473a052f534e'
OFFSET = 7 * 4096


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def sha(data):
    return hashlib.sha256(data).hexdigest()


def normalize(iq):
    iq = np.asarray(iq)
    if iq.shape != (4096, 2) or not np.isfinite(iq).all():
        raise ValueError('one finite 4096-complex-sample capture required')
    # Frozen RF-v1 shared-capture formula, byte-checked against its golden.
    # Do not invoke the study's other transforms: their DC-removal guards would
    # reject valid constant carriers even though RF-v1 explicitly preserves DC.
    raw = np.ascontiguousarray(iq.reshape(4, 1024, 2).transpose(0, 2, 1), dtype=np.float32)
    rms = np.sqrt(np.square(raw, dtype=np.float64).sum()/4096)
    if not np.isfinite(rms) or rms <= 0:
        raise ValueError('nonfinite or zero capture RMS')
    data = np.ascontiguousarray(raw.astype(np.float64)/rms, dtype=np.float32)
    assert data.shape == (4, 2, 1024) and data.dtype == np.float32
    assert abs(np.sqrt(np.square(data.astype(np.float64)).sum()/4096)-1) < 1e-6
    return data


def prepare_inputs(root):
    raw_tile = (root/'train-tile.fc32').read_bytes()
    plan = json.loads((root/'transmission-plan.json').read_text())
    analysis = json.loads((root/'source-matched-analysis.json').read_text())
    report = json.loads((root/'link-summary.json').read_text())
    assert sha(raw_tile) == plan['payload_sha256'] == SOURCE_HASH
    assert plan['split'] == 'train' and plan['locked_test_read'] is False
    assert plan['rows'] == [102400, 102401, 102403, 102404] and plan['class_id'] == 0
    assert report['rx_gain_db'] == 40 and report['rate_sps'] == 2100000
    assert report['bandwidth_hz'] == 1500000 and report['center_hz'] == 2440000000
    assert report['status'] == 'transport_completed_pending_signal_analysis'
    assert report['restoration_errors'] == [] and report['remote_tx_stopped']
    files = list((root/'during-tx').glob('*.sigmf-data'))
    assert len(files) == 1 and files[0].resolve().parent == root/'during-tx'
    raw = files[0].read_bytes()
    assert len(raw) == 65535*4 and sha(raw) == analysis['cases']['during-tx']['iq_sha256']
    lag = analysis['cases']['during-tx']['fixed_lag']
    assert type(lag) is int and 0 <= lag < 4096
    source = np.frombuffer(raw_tile, dtype='<f4').reshape(4096, 2)
    selected = raw[OFFSET*4:(OFFSET+4096)*4]
    received = np.frombuffer(selected, dtype='<i2').reshape(4096, 2)
    inputs = dict(source_original_order=source, source_receive_aligned=np.roll(source, lag, axis=0),
                  received_unmodified=received)
    receipt = dict(source_tile_sha256=sha(raw_tile), parent_iq_sha256=sha(raw),
                   received_slice_sha256=sha(selected), source_rows=plan['rows'],
                   source_nominal_class_id=0, dataset_nominal_snr_db=plan['dataset_nominal_snr_db'],
                   selected_complex_offset=OFFSET, source_circular_lag=lag,
                   alignment_chosen_before_model=True,
                   selected_source_diagnostic_correlation=analysis['cases']['during-tx']['later_eight_fixed_lag_correlations'][0],
                   control_assessment=analysis['engineering_controls'],
                   receiver=dict(gain_db=40, center_hz=2440000000, sample_rate_hz=2100000,
                                 rf_bandwidth_hz=1500000, parent_native_point=report['during_tx']['points'][0]),
                   spectral_snr_scope='parent 65535 samples; not AWGN SNR or exact selected-window SNR')
    return inputs, receipt


async def compare(root):
    assert root.resolve() == root and root == Path('/var/tmp/sdrharness-dev/b210-control-906b')
    output = root/'paired-comparison.json'
    assert not output.exists()
    inputs, receipt = prepare_inputs(root)
    tensors = {name: normalize(iq) for name, iq in inputs.items()}
    receipt.update(schema_id='b210_source_received_offline_pair_v1', status='failed',
                   recognizer_available=False, independent_labels=0, name_status='provisional',
                   result_semantics='offline_diagnostic_outside_runtime_rx_profile',
                   runtime_rx_profile_compatible=False, runtime_profile_gain_db=50,
                   model_preprocessing_modified=False, inference_windows=12, backend_warmup_windows=2,
                   digital_frequency_shift_applied_to_model_input=False, additional_filter_applied=False,
                   results={})
    from gpu_lease import GpuLease
    lease = GpuLease(root/'comparison-gate', 'mamba')
    token = None
    try:
        token = await lease.acquire(time.monotonic()+10, request='offline-source-received-pair')
        worker = module('paired_worker', 'amc-mamba-worker.py')
        backend = worker.RfV1Backend(ROOT/'jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json')
        assert all(p.dtype == worker.torch.float32 for p in backend.model.parameters())
        receipt['identity'] = backend.admission_identity
        receipt['compute'] = 'cuda_fp16_autocast_fp32_weights'
        for name, data in tensors.items():
            logits, timings = [], []
            for window in data:
                value, elapsed = backend.classify_logits(np.ascontiguousarray(window))
                logits.append(value);timings.append(elapsed)
            values = np.asarray(logits, dtype=np.float64)
            mean = values.mean(axis=0)
            probabilities = np.exp(mean-mean.max());probabilities /= probabilities.sum()
            numeric_id = int(probabilities.argmax())
            iq = inputs[name].astype(np.float64)
            rms = float(np.sqrt(np.square(iq).sum()/4096))
            receipt['results'][name] = dict(numeric_id=numeric_id,
                uncalibrated_probability=float(probabilities[numeric_id]),
                window_numeric_ids=list(map(int, values.argmax(axis=1))),
                mean_logits_sha256=sha(mean.astype('<f8').tobytes()),
                model_input_sha256=sha(data.astype('<f4').tobytes()),
                raw_complex_rms=rms, raw_units='adc_ci16' if name=='received_unmodified' else 'tx_fc32',
                raw_dc_fraction=float(np.linalg.norm(iq.mean(axis=0))/rms),
                inference_us=sum(timings), nominal_source_id_agreement=(numeric_id == 0))
        receipt['status'] = 'comparison_completed'
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
    asyncio.run(compare(args.directory))
