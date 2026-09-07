#!/usr/bin/env python3
"""Prefix-only counterfactuals for the sealed multiclass pilot; no RF or dataset access."""
if not __debug__:
    raise RuntimeError('validation assertions required')
import argparse
import asyncio
from contextlib import ExitStack
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import time

import numpy as np

SCRIPTS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('residual_multi', SCRIPTS/'validate-b210-multiclass.py')
multi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(multi)
point, repair = multi.repair.lo.point, multi.repair
ROOT = Path('/var/tmp/sdrharness-dev/b210-residual-907v')
REPO = multi.REPO
OLD_AUDIT = REPO/'docs/evidence/B210_MULTICLASS_AUDIT_2026-09-07.json'
AUDIT = REPO/'docs/evidence/B210_RESIDUAL_AUDIT_2026-09-07.json'
CLASSES = (5, 11, 13, 19)
BAD = ('r0c05', 'r0c11', 'r1c13', 'r2c19')
START, COUNT, FIT, RATE = 32768, 65535, 16384, 2100000
KINDS = ('source_original', 'received_filtered', 'source_shifted', 'source_phase',
         'source_carrier', 'source_affine', 'received_cfo', 'received_cfo_phase', 'received_affine')
sha = multi.sha
save = multi.save


def verify_parent():
    inventory = multi.live.document(REPO/'docs/evidence/B210_MULTICLASS_EVIDENCE_2026-09-07.json')
    expected = {p['path'] for p in inventory['files']}
    assert {str(p) for r in inventory['roots'] for p in Path(r).rglob('*') if p.is_file()} == expected
    for row in inventory['files']:
        raw = multi.live.read(Path(row['path']))
        assert len(raw) == row['bytes'] and sha(raw) == row['sha256']
    return dict(inventory_sha256=sha((REPO/'docs/evidence/B210_MULTICLASS_EVIDENCE_2026-09-07.json').read_bytes()),
                audit_sha256=sha(OLD_AUDIT.read_bytes()), files=len(expected))


def centered_width(source):
    z = np.asarray(source, dtype=np.complex128)
    if z.shape != (1024,) or not np.isfinite(z).all():
        raise ValueError('finite 1024 source required')
    p = float(np.mean(abs(z)**2))
    ac = float(np.mean(abs(z-z.mean())**2))
    if p <= 0 or ac <= p*1e-12:
        raise ValueError('no identifiable centered modulation energy')
    total = multi.live.match.source_bandwidth(z)
    centered = multi.live.match.source_bandwidth(z-z.mean())
    return dict(total_99_width_hz=total, centered_99_width_hz=centered,
                diagnostic_width_hz=max(3000, centered), dc_power_fraction=float(abs(z.mean())**2/p),
                applied_to_model_iq=False, original_gate_revised=False)


def estimate(source, raw, tone_cfo, width):
    if np.shape(source) != (1024,) or np.shape(raw) != (COUNT,) or not np.isfinite(raw).all():
        raise ValueError('complete source and capture required')
    if not np.isfinite(source).all() or not np.isfinite([tone_cfo, width]).all() or not 0 < width < RATE/2:
        raise ValueError('finite source, CFO and positive band required')
    fit = point.alignment(source, raw[:FIT], tone_cfo, width)
    if not fit['usable']:
        return dict(alignment=fit, available=False), None
    matrix = point.design_matrix(source, fit, (0,), FIT)
    try:
        coefficients, metrics = point.solve_channel(matrix, raw[:FIT], True)
    except ValueError as error:
        return dict(alignment=fit, available=False, reason=str(error)), None
    if abs(coefficients[0]) <= 1e-12:
        return dict(alignment=fit, available=False, reason='zero channel gain'), None
    return dict(alignment=fit, available=True, channel=metrics, fit_samples=FIT), coefficients


def block(z):
    # A valid symmetric FIR retains both real neighboring halos, never wraps RX.
    return repair.reject(z)[START-128:START+4096-128]


def transforms(source, raw, fit, coefficients):
    n = np.arange(COUNT)
    reference = source[(n-fit['lag']) % 1024]
    carrier = np.exp(2j*np.pi*fit['total_frequency_hz']*n/RATE)
    h, b, d = coefficients
    received = block(raw)
    rotation = carrier[START:START+4096]
    initial = carrier[START]
    predicted = (h*reference+b)*carrier+d
    bias = b*carrier+d
    output = dict(source_original=np.tile(source, 4), received_filtered=received,
                  source_shifted=block(reference), source_phase=block(h*reference*initial),
                  source_carrier=block(h*reference*carrier), source_affine=block(predicted),
                  received_cfo=received/rotation, received_cfo_phase=received/rotation/h,
                  received_affine=block(raw-bias)/rotation/h)
    assert set(output) == set(KINDS)
    assert all(z.shape == (4096,) and np.isfinite(z).all() for z in output.values())
    power = float(np.mean(abs(received)**2))
    diagnostics = dict(fixed_block_source_only_residual_fraction=float(np.mean(abs(received-output['source_carrier'])**2)/power),
                       fixed_block_affine_residual_fraction=float(np.mean(abs(received-output['source_affine'])**2)/power),
                       extra_bias_to_source_rms=float(np.sqrt(np.mean(abs(block(bias))**2)/np.mean(abs(output['source_carrier'])**2))),
                       source_true_mean_preserved=True, corrected_capture_start=START,
                       initial_phase_rad=float(np.angle(h*initial)))
    return output, diagnostics


def prepare():
    parent = verify_parent()
    old = multi.live.document(OLD_AUDIT)
    acquisition = multi.live.document(multi.ROOT/'acquisition.json')
    report = dict(schema_id='b210_multiclass_residual_v1', parent=parent, cases={}, strong_dc={}, model_inputs={},
                  recognizer_available=False, independent_labels=0, new_rf_operations=0, dataset_reads=0,
                  interpretation='posthoc known-source counterfactuals; not deployable blind correction')
    tensors = {}
    for p in multi.manifest()['cases']:
        c, tag = p['class_id'], p['case_id']
        if c not in (*CLASSES, 17, 18):
            continue
        source, captures, baseline = multi.inputs_for(p, acquisition['results'][tag])
        tone = acquisition['results'][f'tone{p["round"]}']['metrics']['frequency_difference_hz']
        raw = captures['during-tx']
        width = multi.live.match.source_bandwidth(source)
        if c in (17, 18):
            diag = centered_width(source)
            result, coeff = estimate(source, raw, tone, diag['diagnostic_width_hz'])
            diag['prefix_fit'] = result
            if coeff is not None:
                _, metrics = transforms(source, raw, result['alignment'], coeff)
                diag['heldout_diagnostics'] = metrics
            report['strong_dc'][tag] = diag
            continue
        case = dict(class_id=c, original_error_target=tag in BAD,
                    original_qualification_passed=old['analysis']['cases'][tag]['qualification_passed'])
        result, coeff = estimate(source, raw, tone, width)
        case['estimate'] = result
        data = {k: baseline[k] for k in ('source_original', 'received_filtered')}
        if coeff is not None:
            arrays, metrics = transforms(source, raw, result['alignment'], coeff)
            data = {name: multi.normalize(z) for name, z in arrays.items()}
            case['heldout_diagnostics'] = metrics
        for kind in ('source_original', 'received_filtered'):
            assert sha(data[kind].tobytes()) == old['inference']['results'][tag+'/'+kind]['input_sha256']
        report['cases'][tag] = case
        for kind, tensor in data.items():
            key = tag+'/'+kind
            tensors[key] = tensor
            report['model_inputs'][key] = sha(tensor.tobytes())
    assert len(report['cases']) == 12 and len(report['strong_dc']) == 6 and len(tensors) <= 108
    return report, tensors


async def infer():
    report, tensors = prepare()
    assert report == multi.live.document(ROOT/'prepared.json')
    save(ROOT/'inference-started.json', dict(max_windows=432, planned_windows=len(tensors)*4, max_warmup=2))
    from gpu_lease import GpuLease
    lease = GpuLease(ROOT/'gpu-gate', 'mamba')
    token = None
    isolation = ExitStack()
    receipt = dict(status='failed', results={}, model_windows=0, warmup_windows=0,
                   recognizer_available=False, independent_labels=0, uncalibrated=True)
    try:
        token = await lease.acquire(time.monotonic()+10, request='b210-residual-diagnostic')
        isolation.enter_context(multi.idle_spark_pause(evidence_root=ROOT))
        worker = multi.live.affine.module('residual_worker', 'amc-mamba-worker.py')
        backend = worker.RfV1Backend(REPO/'jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json')
        assert all(p.dtype == worker.torch.float32 for p in backend.model.parameters())
        receipt.update(identity=backend.admission_identity, warmup_windows=2)
        end = time.monotonic()+600
        old = multi.live.document(OLD_AUDIT)['inference']['results']
        for key, data in tensors.items():
            assert time.monotonic() < end
            values, elapsed = [], 0
            for window in data:
                logits, timing = backend.classify_logits(np.ascontiguousarray(window))
                values.append(logits)
                elapsed += timing
                receipt['model_windows'] += 1
            logits = np.asarray(values, dtype=np.float64)
            assert logits.shape == (4, 24) and np.isfinite(logits).all()
            result = dict(numeric_id=int(logits.mean(axis=0).argmax()), window_numeric_ids=logits.argmax(axis=1).tolist(),
                          logits=logits.tolist(), mean_logits=logits.mean(axis=0).tolist(), input_sha256=sha(data.tobytes()),
                          name_status='provisional', inference_us=elapsed)
            if key in old:
                result['baseline_logits_max_abs_difference'] = float(np.max(abs(logits-np.asarray(old[key]['logits']))))
                result['baseline_numeric_id_equal'] = result['numeric_id'] == old[key]['numeric_id']
            receipt['results'][key] = result
        receipt['status'] = 'completed'
    except BaseException as error:
        receipt['failure'] = str(error)
        raise
    finally:
        try:
            if token is not None:
                lease.release(token)
            receipt['gpu_lease'] = lease.metrics.copy()
            lease.close()
        finally:
            try:
                isolation.close()
            finally:
                save(ROOT/'inference.json', receipt)


def verify():
    audit = multi.live.document(AUDIT)
    report, tensors = prepare()
    assert report == audit['analysis']
    assert set(tensors) == set(audit['inference']['results'])
    for key, value in tensors.items():
        result = audit['inference']['results'][key]
        assert sha(value.tobytes()) == result['input_sha256']
        logits = np.asarray(result['logits'], dtype=float)
        assert logits.mean(axis=0).tolist() == result['mean_logits']
        assert int(logits.mean(axis=0).argmax()) == result['numeric_id']
    assert pointwise()[0] == audit['pointwise']
    print(json.dumps(dict(replay='passed', parent_files=report['parent']['files'], model_reexecuted=False, new_rf=0)))


def pointwise():
    """逐点显示用前段参数对齐后的完整固定块；不将后验显示重新送模型。"""
    old = multi.live.document(multi.ROOT/'acquisition.json')
    preparation = multi.live.document(ROOT/'prepared.json') if (ROOT/'prepared.json').exists() else multi.live.document(AUDIT)['analysis']
    arrays, metrics = {}, {}
    for p in multi.manifest()['cases']:
        tag = p['case_id']
        if p['class_id'] not in CLASSES:
            continue
        source, captures, _ = multi.inputs_for(p, old['results'][tag])
        detail = preparation['cases'][tag]['estimate']
        coeff = np.array([complex(*v) for v in detail['channel']['coefficients']])
        output, _ = transforms(source, captures['during-tx'], detail['alignment'], coeff)
        # 共用源RMS显示幅度，不能各自缩放后把幅度误差藏掉。
        scale = np.sqrt(np.mean(abs(output['source_shifted'])**2))
        x, y = output['source_shifted']/scale, output['received_affine']/scale
        error = y-x
        arrays[tag+'_source'] = x
        arrays[tag+'_received'] = y
        windows = []
        for start in range(0, 4096, 1024):
            xx, yy = x[start:start+1024], y[start:start+1024]
            xc, yc = xx-xx.mean(), yy-yy.mean()
            gain = np.vdot(xc, yc)/np.vdot(xc, xc).real
            residual = yc-gain*xc
            windows.append(dict(start=START+start,
                coherence=multi.live.affine.fidelity.coherence(xc, yc),
                local_gain_magnitude=float(abs(gain)), local_phase_rad=float(np.angle(gain)),
                residual_after_local_scalar_fraction=float(np.mean(abs(residual)**2)/np.mean(abs(yc)**2))))
        metrics[tag] = dict(source_sha256=sha(x.astype('<c16').tobytes()), received_sha256=sha(y.astype('<c16').tobytes()),
                           point_count=4096, display_zoom_first_points=192, source_rms_scale=float(scale),
                           error_rms=float(np.sqrt(np.mean(abs(error)**2))),
                           error_p50=float(np.quantile(abs(error), .5)), error_p95=float(np.quantile(abs(error), .95)),
                           error_max=float(abs(error).max()), windows=windows,
                           local_scalar_fitted_for_description_only=True, new_model_windows=0)
    return metrics, arrays


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--infer', action='store_true')
    group.add_argument('--verify', action='store_true')
    group.add_argument('--pointwise', action='store_true')
    args = parser.parse_args()
    def stop(signum, frame):
        raise InterruptedError(f'signal {signum}')
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)
    if args.prepare:
        save(ROOT/'prepared.json', prepare()[0])
    elif args.infer:
        asyncio.run(infer())
    elif args.pointwise:
        metrics, arrays = pointwise()
        save(ROOT/'pointwise.json', metrics)
        np.savez(ROOT/'pointwise-display.npz', **arrays)
    else:
        verify()
