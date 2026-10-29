#!/usr/bin/env python3
"""Fixed historical FIR replay; optional bounded engineering inference, never RF."""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import time

import h5py
import numpy as np

import rml2018a_campaign as c


def coherence(x, y):
    return float(abs(np.vdot(x, y)) / max(np.linalg.norm(x)*np.linalg.norm(y), 1e-30))


def validate_indices(indices):
    c.require(1 <= len(indices) <= 3 and len(set(indices)) == len(indices) and
              all(type(i) is int and 0 <= i < 106496 for i in indices), 'bounded unique batches')


def load_runner():
    spec=importlib.util.spec_from_file_location('filter_campaign_runner',Path(__file__).with_name('rml2018a-rf-campaign.py'))
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    return runner


def prepare(root, indices=(4267, 4268, 22016)):
    validate_indices(indices)
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
    results = []; tensors = {}
    # Fixed successful pilot set; no scan for favorable source rows or windows.
    for index in indices:
        batch = root/f'batch-{index:07d}'
        audit = read(batch/'audit.json'); source = read(batch/'source.json')
        done = read(batch/'capture-complete.json')
        c.require(c.file_hash(batch/'audit.json') == done['audit_sha256'], 'audit seal')
        c.require(audit['status'] == done['status'] == 'synchronized' and audit['restored'], 'restored synchronized batch')
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
            c.require(h5['Y'][source['rows']].argmax(axis=1).tolist()==source['class_ids'], 'source labels')
            if 'source_snr_db' in source:
                c.require(h5['Z'][source['rows']].ravel().tolist()==source['source_snr_db'], 'source Z')
        c.require(c.digest(iq.tobytes()) == source['original_iq_sha256'], 'source rows hash')
        reference = iq[..., 0].astype(float) + 1j*iq[..., 1]
        frame, scales = c.packet(iq, plan['run_id'], index)
        c.require(c.digest(frame.tobytes()) == audit['tx_plan']['payload_sha256'], 'original TX frame')
        # Preserve actual neighbors/guards, rather than treating each row as periodic.
        middle = repair.reject(np.tile(frame, 3))[len(frame)-128:2*len(frame)-128]
        filtered_source = middle[c.GUARD+c.MARKER:-c.GUARD].reshape(24, 1024)/scales[:, None]
        rows = []
        tensors[index] = dict(source_original=reference, source_filtered=filtered_source,
                              received_raw=raw, received_filtered=filtered)
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
    report = dict(schema='rml2018a-historical-filter-comparison-v2', root=str(root),
        run_id=plan['run_id'], parent_plan_sha256=c.file_hash(root/'run-plan.json'),
        script_sha256=c.file_hash(__file__), historical_filter_script_sha256=c.file_hash(path),
        filter_contract=repair.filter_contract(), new_rf_captures=0, model_inferences=0,
        recognizer_available=False, timing_refit=False, results=results,
        all_sources_filter_eligible=all(x['source_filter_eligible'] for b in results for x in b['rows']),
        input_hashes={str(i): {tag: c.digest(np.ascontiguousarray(z,dtype='<c16').tobytes())
                      for tag,z in parts.items()} for i,parts in tensors.items()},
        filtered_rx_sinr_db=None,
        filtered_rx_sinr_reason='filter changes source noise allocation; original Z cannot calibrate filtered SINR',
        interpretation='Post-hoc engineering waveform comparison; no new accuracy claim or physical interferer identification.')
    return report, tensors


def analyze(root, indices=(4267, 4268, 22016)):
    return prepare(root, indices)[0]


DIAGNOSTIC_VARIANTS = ('received_raw', 'received_filtered', 'filtered_raw_rms',
    'source_scaled', 'source_original', 'filtered_phase_only', 'filtered_offset_only',
    'filtered_phase_offset', 'filtered_cfo_only', 'filtered_phase_cfo')
COMPONENT_VARIANTS = ('source_original', 'received_filtered', 'removed_only',
    'source_with_removed', 'amplitude_error_only', 'phase_error_only',
    'source_with_fitted_offset', 'affine_reference')


def affine_fit(x, y):
    xc=x-x.mean();yc=y-y.mean();energy=float(np.vdot(xc,xc).real)
    c.require(energy > 1e-20, 'diagnostic centered source energy')
    gain=np.vdot(xc,yc)/energy
    return gain, y.mean()-gain*x.mean(), energy


def diagnostic_variants(source, filtered_source, raw, filtered):
    """Known-source counterfactuals, never a deployable receiver or SINR estimator."""
    x=np.asarray(filtered_source,dtype=np.complex128);y=np.asarray(filtered,dtype=np.complex128)
    c.require(x.shape==y.shape==(1024,) and np.isfinite(x).all() and np.isfinite(y).all(), 'diagnostic window')
    gain,offset,_=affine_fit(x,y)
    phase=float(np.angle(gain))
    # Eight fixed 128-sample fits. Weight only by source energy, never predictions.
    fits=[affine_fit(x[j:j+128],y[j:j+128]) for j in range(0,1024,128)]
    times=np.arange(8)*128+63.5
    weights=np.sqrt([fit[2] for fit in fits])
    phases=np.unwrap(np.angle([fit[0] for fit in fits]))
    slope,intercept=np.polyfit(times,phases,1,w=weights)
    hz=float(slope*c.RATE/(2*np.pi))
    valid=bool(np.isfinite(hz) and abs(hz)<=5000)
    applied_slope=float(slope) if valid else 0.
    frequency_corrected=y*np.exp(-1j*applied_slope*np.arange(1024))
    corrected_gain,_,_=affine_fit(x,frequency_corrected)
    ratio=float(np.sqrt(np.mean(abs(y)**2)/np.mean(abs(raw)**2)))
    norm=c.normalize_window
    inputs=dict(received_raw=norm(raw),received_filtered=norm(y),
        filtered_raw_rms=np.ascontiguousarray(norm(y)*ratio,dtype=np.float32),
        source_scaled=np.ascontiguousarray(norm(source)*ratio,dtype=np.float32),
        source_original=norm(source),filtered_phase_only=norm(y*np.exp(-1j*phase)),
        filtered_offset_only=norm(y-offset),filtered_phase_offset=norm((y-offset)*np.exp(-1j*phase)),
        filtered_cfo_only=norm(frequency_corrected),
        filtered_phase_cfo=norm(frequency_corrected*np.exp(-1j*np.angle(corrected_gain))))
    diagnostic=dict(source_assisted=True,phase_deg=float(np.degrees(phase)),
        gain=[float(gain.real),float(gain.imag)],offset=[float(offset.real),float(offset.imag)],
        offset_over_filtered_rms=float(abs(offset)/np.sqrt(np.mean(abs(y)**2))),
        filtered_over_raw_rms=ratio,residual_cfo_hz=hz,cfo_fit_valid=valid,
        cfo_phase_fit_rms_rad=float(np.sqrt(np.average((phases-(slope*times+intercept))**2,weights=weights**2))),
        correction_applied_hz=hz if valid else 0.)
    return inputs,diagnostic


def component_variants(source, filtered_source, raw, filtered):
    """Oracle component swaps isolate waveform sensitivity; never production inputs."""
    x=np.asarray(filtered_source,dtype=np.complex128);y=np.asarray(filtered,dtype=np.complex128)
    gain,offset,_=affine_fit(x,y)
    c.require(abs(gain)>1e-12, 'diagnostic nonzero gain')
    corrected=(y-offset)/gain;removed=raw-y;norm=c.normalize_window
    inputs=dict(source_original=norm(source),received_filtered=norm(y),removed_only=norm(removed),
        source_with_removed=norm(gain*x+removed),
        amplitude_error_only=norm(abs(corrected)*np.exp(1j*np.angle(x))),
        phase_error_only=norm(abs(x)*np.exp(1j*np.angle(corrected))),
        source_with_fitted_offset=norm(x+offset/gain),affine_reference=norm(gain*x+offset))
    return inputs,dict(source_assisted=True,gain=[float(gain.real),float(gain.imag)],
        offset=[float(offset.real),float(offset.imag)],
        removed_power_over_raw=float(np.mean(abs(removed)**2)/np.mean(abs(raw)**2)),
        interpretation='FIR complement is not a pure interferer; amplitude/phase swaps use the known source, including its noisy near-zero phase.')


def prepare_diagnostic(root, indices, *, components=False):
    report,arrays=prepare(root,indices);tensors={}
    tags=COMPONENT_VARIANTS if components else DIAGNOSTIC_VARIANTS
    for index,parts in arrays.items():
        rows=[];tensors[index]={tag:[] for tag in tags}
        for k in range(24):
            variants,metrics=(component_variants if components else diagnostic_variants)(parts['source_original'][k],parts['source_filtered'][k],
                                                parts['received_raw'][k],parts['received_filtered'][k])
            rows.append(metrics)
            for tag,value in variants.items():tensors[index][tag].append(value)
        for tag in tensors[index]:tensors[index][tag]=np.stack(tensors[index][tag])
        next(b for b in report['results'] if b['batch']==index)['diagnostic_fits']=rows
    report.update(diagnostic_variants=list(tags),
        diagnostic_input_hashes={str(i):{tag:c.digest(values.tobytes()) for tag,values in parts.items()} for i,parts in tensors.items()},
        interpretation='Known-source diagnostic counterfactuals only; not independent accuracy, deployable correction, or physical SINR.')
    return report,tensors


def infer(root, output, indices, *, diagnose=False, components=False):
    validate_indices(indices)
    diagnose=diagnose or components
    tags=COMPONENT_VARIANTS if components else DIAGNOSTIC_VARIANTS
    # Separate derived root: never modify the sealed parent campaign or select rows by prediction.
    c.require(output.resolve() == output and output.parent == Path('/var/tmp/sdrharness-dev') and
              output.name.startswith('rml-filter-') and not output.exists(), 'new derived root required')
    runner=load_runner()
    plan=runner.load_plan(root)
    c.require(shutil.disk_usage(output.parent).free > 64*1024*1024, 'derived output disk reserve')
    output.mkdir(mode=0o700)
    scratch=output/'scratch';scratch.mkdir(mode=0o700)
    os.environ.update(TMPDIR=str(scratch),XDG_CACHE_HOME=str(scratch),PYTHONDONTWRITEBYTECODE='1')
    c.save(output/'plan.json',dict(parent=str(root),parent_plan_sha256=c.file_hash(root/'run-plan.json'),
        batches=list(indices),maximum_model_windows=len(indices)*24*(len(tags) if diagnose else 4),warmup_windows=2,
        deadline_seconds=650,new_rf_captures=0,recognizer_available=False,
        filter='fixed257-tap175kHz Kaiser8, historical coefficient hash enforced',
        gate='all registered source rows retain >=99% power with <=1% distortion; otherwise skip entire inference',
        selection='all registered rows and fixed variants; invalid raw SINR rows remain in denominators',
        diagnostic_variants=list(tags) if diagnose else None,
        source_assisted_diagnostic=diagnose,
        diagnostic_method=('known-source affine fit; fixed FIR complement and samplewise envelope/phase swaps; no parameter search'
            if components else '8 fixed128-point affine fits; source-energy-weighted unwrapped phase slope; abs<=5kHz else recorded no-op' if diagnose else None),
        runner_sha256=c.file_hash(__file__)))
    report,tensors=prepare_diagnostic(root,indices,components=components) if diagnose else prepare(root,indices)
    c.save(output/'prepared.json',report)
    receipt=dict(status='skipped_source_filter_gate',rows=[],model_windows=0,warmup_windows=0,
        prepared_sha256=c.file_hash(output/'prepared.json'),recognizer_available=False,
        profile_sha256=plan['profile_sha256'],label_map_sha256=plan['label_map_sha256'],
        semantics='single1024 window engineering comparison on registered batches only; not independent admission',
        name_status='provisional',filtered_rx_sinr_db=None,
        source_assisted_diagnostic=diagnose,
        filtered_rx_sinr_reason=report['filtered_rx_sinr_reason'])
    if not report['all_sources_filter_eligible']:
        c.save(output/'inference.json',receipt);return receipt
    multi=runner.module('filter_multi','validate-b210-multiclass.py')
    from gpu_lease import GpuLease
    lease=GpuLease(scratch/'gpu-gate','mamba');token=None
    receipt['status']='failed'
    try:
        token=asyncio.run(lease.acquire(time.monotonic()+10,request='rml-fixed-filter-comparison'))
        with multi.idle_spark_pause(evidence_root=output):
            worker=runner.module('filter_model','amc-mamba-worker.py')
            backend=worker.RfV1Backend(runner.PROFILE)
            c.require(all(p.dtype==worker.torch.float32 for p in backend.model.parameters()), 'FP32 weights')
            receipt.update(model_identity=backend.admission_identity,warmup_windows=2,
                           compute='cuda_fp16_autocast_fp32_weights')
            deadline=time.monotonic()+580
            for index,parts in tensors.items():
                batch=root/f'batch-{index:07d}';source=runner.document(batch/'source.json')
                audit=runner.document(batch/'audit.json')
                _,seal=runner.native_check(batch,runner.document(batch/'rx-plan.json'))
                c.require(seal==audit['seal'], 'native capture seal')
                for k,row in enumerate(source['rows']):
                    entry=dict(row=row,batch=index,true_id=source['class_ids'][k],
                        source_snr_db=source['source_snr_db'][k],raw_receive_quality=audit['receive_quality'][k],predictions={})
                    for tag,values in parts.items():
                        c.require(time.monotonic()<deadline, 'inference deadline')
                        tensor=values[k] if diagnose else c.normalize_window(values[k])
                        logits,us=backend.classify_logits(tensor)
                        c.require(np.asarray(logits).shape==(24,) and np.isfinite(logits).all(), 'finite logits')
                        entry['predictions'][tag]=dict(id=int(np.argmax(logits)),logits=logits,
                            input_sha256=c.digest(tensor.tobytes()),inference_us=us)
                        receipt['model_windows']+=1
                    receipt['rows'].append(entry)
                print(json.dumps(dict(event='filter_inferred',batch=index,rows=24)),flush=True)
            del backend
        tags=tuple(next(iter(tensors.values())))
        receipt['summary']={tag:dict(rows=len(receipt['rows']),correct=sum(
            x['predictions'][tag]['id']==x['true_id'] for x in receipt['rows'])) for tag in tags}
        receipt['status']='comparison_completed'
    except BaseException as error:
        receipt['error']=f'{type(error).__name__}: {error}';raise
    finally:
        if token is not None:lease.release(token)
        receipt['gpu_lease']=lease.metrics.copy();lease.close()
        c.save(output/'inference.json',receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--batches',nargs='+',type=int,default=[4267,4268,22016])
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--infer-output',type=Path,help='optional new derived root for all-row four-variant inference')
    modes.add_argument('--diagnose-output',type=Path,help='known-source phase/CFO/offset/scale diagnostic, never production correction')
    modes.add_argument('--components-output',type=Path,help='known-source component swaps after scalar diagnostics; never production correction')
    args = parser.parse_args()
    if args.infer_output or args.diagnose_output or args.components_output:
        def abort(sig, frame):raise RuntimeError(f'filter comparison stopped by signal {sig}')
        for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(sig,abort)
        signal.alarm(650)
        try:
            result=infer(args.root,args.infer_output or args.diagnose_output or args.components_output,tuple(args.batches),
                         diagnose=bool(args.diagnose_output),components=bool(args.components_output))
            print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2,allow_nan=False))
        finally:signal.alarm(0)
    else:print(json.dumps(analyze(args.root,tuple(args.batches)), indent=2, allow_nan=False))
