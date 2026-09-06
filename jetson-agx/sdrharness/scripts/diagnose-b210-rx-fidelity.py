#!/usr/bin/env python3
"""Source-only RF fidelity preparation followed by bounded experimental inference."""
import argparse
import asyncio
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
FEATURE = Path('/var/tmp/sdrharness-dev/b210-fidelity-906e')
RATE, PERIOD, FIT_SAMPLES = 2100000, 4096, 7*4096


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS/filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


paired = module('fidelity_pair', 'compare-b210-source-received.py')
source_match = module('fidelity_source', 'analyze-b210-source-match.py')


def bandlimit(iq, half_width):
    iq = np.asarray(iq, dtype=np.complex128)
    if (iq.ndim != 1 or not iq.size or not np.isfinite(iq).all()
            or not np.isfinite(half_width) or not 0 < half_width < RATE/2):
        raise ValueError('bandlimit shape/range')
    bins = abs(np.fft.fftfreq(len(iq), 1/RATE)) <= half_width
    return np.fft.ifft(np.fft.fft(iq)*bins)


def correct_cfo(iq, frequency):
    iq = np.asarray(iq, dtype=np.complex128)
    if iq.ndim != 1 or not np.isfinite(iq).all() or not np.isfinite(frequency) or abs(frequency) >= RATE/2:
        raise ValueError('CFO shape/range')
    return iq*np.exp(-2j*np.pi*frequency*np.arange(len(iq))/RATE)


def coherence(reference, received):
    scale = float(np.vdot(reference, reference).real*np.vdot(received, received).real)
    return float(min(1., abs(np.vdot(reference, received))/np.sqrt(scale))) if scale > 0 else 0.


def fit_transfer(reference_period, received):
    reference_period = np.asarray(reference_period, dtype=np.complex128)
    received = np.asarray(received, dtype=np.complex128)
    if (reference_period.shape != (PERIOD,) or received.shape != (65535,)
            or not np.isfinite(reference_period).all() or not np.isfinite(received).all()
            or np.vdot(reference_period, reference_period).real <= 0):
        raise ValueError('fidelity input shape/power')
    reference = np.tile(reference_period, 16)[:len(received)]
    train_ref, train_rx = reference[:FIT_SAMPLES], received[:FIT_SAMPLES]
    gain = np.vdot(train_ref, train_rx)/np.vdot(train_ref, train_ref).real
    rows = []
    for start in range(FIT_SAMPLES, 15*PERIOD, PERIOD):
        x, y = reference[start:start+PERIOD], received[start:start+PERIOD]
        predicted = gain*x
        signal_power = float(np.vdot(predicted, predicted).real)
        residual = y-predicted
        rows.append(dict(complex_offset=start, coherence=coherence(x,y),
                         normalized_residual_power=(float(np.vdot(residual,residual).real/signal_power)
                                                    if signal_power > 1e-20 else None)))
    return dict(gain_real=float(gain.real), gain_imag=float(gain.imag),
                train_coherence=coherence(train_ref,train_rx), fit_samples=FIT_SAMPLES,
                heldout_windows=rows, heldout_median_coherence=float(np.median([r['coherence'] for r in rows])))


def power_partition(iq, half_width):
    spectrum = abs(np.fft.fft(iq))**2
    total = float(spectrum.sum())
    if not np.isfinite(total) or total <= 0:raise ValueError('nonfinite or zero received power')
    inside = float(spectrum[abs(np.fft.fftfreq(len(iq),1/RATE)) <= half_width].sum()/total)
    return dict(inside_fraction=inside, outside_fraction=1-inside,
                total_complex_power=float(np.mean(abs(iq)**2)))


def prepare(feature):
    originals, receipt = paired.prepare_inputs(feature)
    analysis = json.loads((feature/'source-matched-analysis.json').read_text())
    received, digest = source_match.read_iq(feature,'during-tx')
    assert digest == receipt['parent_iq_sha256']
    half_width = analysis['source_99_percent_half_width_hz']
    frequency = analysis['tone']['frequency_difference_hz']
    aligned = originals['source_receive_aligned'].astype(np.float64)
    reference = aligned[:,0]+1j*aligned[:,1]
    reference_band = bandlimit(reference,half_width)
    corrected = correct_cfo(received,frequency)
    paths = dict(received_raw=received, received_cfo=corrected,
                 received_band=bandlimit(received,half_width),
                 received_cfo_band=bandlimit(corrected,half_width))
    fits = {}
    for name, iq in paths.items():
        x = reference_band if name.endswith('band') else reference
        fits[name] = dict(direct=fit_transfer(x,iq), conjugate=fit_transfer(x.conj(),iq))
    def planar_pairs(iq):
        return np.asarray(np.stack((iq.real,iq.imag),axis=1),dtype='<f4')
    inputs = dict(source_aligned=originals['source_receive_aligned'], source_aligned_band=planar_pairs(reference_band))
    for name, iq in paths.items():inputs[name] = planar_pairs(iq[FIT_SAMPLES:FIT_SAMPLES+PERIOD])
    phase_fit = fits['received_cfo_band']['direct']
    phase_allowed = phase_fit['train_coherence'] >= .2
    if phase_allowed:
        phase = float(np.arctan2(phase_fit['gain_imag'],phase_fit['gain_real']))
        inputs['received_cfo_band_phase'] = planar_pairs(paths['received_cfo_band'][FIT_SAMPLES:FIT_SAMPLES+PERIOD]*np.exp(-1j*phase))
    else:phase = None
    assert len(inputs) <= 7
    tensors = {name:paired.normalize(iq) for name,iq in inputs.items()}
    assert paired.sha(tensors['received_raw'].tobytes()) == paired.sha(paired.normalize(originals['received_unmodified']).tobytes())
    details = dict(schema_id='b210_rx_fidelity_preparation_v1', source_receipt=receipt,
                   source_analysis_sha256=paired.sha((feature/'source-matched-analysis.json').read_bytes()),
                   cfo_hz=frequency, half_width_hz=half_width, source_lag=receipt['source_circular_lag'],
                   model_complex_offset=FIT_SAMPLES, raw_baseline_bytes_preserved=True,
                   method='tone CFO; source 99% band; first-seven-window scalar fit; fixed eighth-window inference',
                   residual_interpretation='noise plus interference plus model mismatch; not calibrated SNR',
                   phase_fit_threshold=.2, phase_variant_enabled=phase_allowed, estimated_phase_rad=phase,
                   phase_rotation_applied_rad=(-phase if phase is not None else None),
                   fits=fits, power_partitions={name:power_partition(iq,half_width) for name,iq in
                       [('source',reference),('rx_raw',received),('rx_cfo',corrected)]},
                   model_inputs={name:dict(sha256=paired.sha(data.tobytes()),bytes=data.nbytes) for name,data in tensors.items()},
                   recognizer_available=False, independent_labels=0, production_profile_compatible=False,
                   production_preprocess_changed=False)
    return details, tensors


def phase_drift(reference, received):
    """Supplementary source-referenced phase-rate estimate; never changes model inputs."""
    reference = np.asarray(reference,dtype=np.complex128)
    received = np.asarray(received,dtype=np.complex128)
    if reference.shape != (PERIOD,) or received.shape != (65535,):
        raise ValueError('phase diagnostic shape')
    denominator = float(np.vdot(reference,reference).real)
    if not np.isfinite(reference).all() or not np.isfinite(denominator) or denominator <= 0 or not np.isfinite(received).all():
        raise ValueError('phase diagnostic power')
    gains = np.array([np.vdot(reference,received[k*PERIOD:(k+1)*PERIOD])/denominator for k in range(15)])
    correlations = [coherence(reference,received[k*PERIOD:(k+1)*PERIOD]) for k in range(15)]
    result = dict(method='posthoc source-referenced phase rate; first seven windows only',
                  coefficient_coherence=correlations,fit_windows=7,heldout_windows=8,
                  phase_rate_alias_period_hz=RATE/PERIOD,applied_to_model_input=False,
                  identifiable=min(correlations[:7])>=.2)
    if not result['identifiable']:return result
    phases = np.unwrap(np.angle(gains))
    times = (np.arange(15)+.5)*PERIOD/RATE
    slope,intercept = np.linalg.lstsq(np.stack((times[:7],np.ones(7)),axis=1),phases[:7],rcond=None)[0]
    predicted = slope*times+intercept
    errors = np.angle(np.exp(1j*(phases-predicted)))
    result.update(residual_phase_rate_hz=float(slope/(2*np.pi)),window_times_s=times.tolist(),
                  unwrapped_phase_rad=phases.tolist(),predicted_phase_rad=predicted.tolist(),
                  fit_phase_rmse_rad=float(np.sqrt(np.mean(errors[:7]**2))),
                  heldout_phase_rmse_rad=float(np.sqrt(np.mean(errors[7:]**2))))
    return result


def supplement(feature):
    details,_ = prepare(feature)
    original,_ = paired.prepare_inputs(feature)
    iq,_ = source_match.read_iq(feature,'during-tx')
    aligned = original['source_receive_aligned']
    reference = bandlimit(aligned[:,0]+1j*aligned[:,1],details['half_width_hz'])
    received = bandlimit(correct_cfo(iq,details['cfo_hz']),details['half_width_hz'])
    value = phase_drift(reference,received)
    value['preparation_sha256'] = paired.sha((feature/'fidelity-prepared.json').read_bytes())
    with (feature/'fidelity-phase-supplement.json').open('x') as output:
        json.dump(value,output,indent=2);output.write('\n')
    print(json.dumps(value,indent=2))


def plot(feature, destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    details,tensors = prepare(feature)
    saved = json.loads((feature/'fidelity-prepared.json').read_text())
    for name,data in tensors.items():assert paired.sha(data.tobytes()) == saved['model_inputs'][name]['sha256']
    phase = json.loads((feature/'fidelity-phase-supplement.json').read_text())
    figure,axes = plt.subplots(3,1,figsize=(10,10),constrained_layout=True)
    envelope_stats = {}
    for name,label,color in [('source_aligned','Source aligned','#222222'),
                              ('received_raw','RX raw','#c44e52'),('received_cfo_band','RX CFO + band','#238b45')]:
        data = tensors[name].transpose(0,2,1).reshape(PERIOD,2).astype(np.float64)
        iq = data[:,0]+1j*data[:,1]
        envelope_stats[name] = dict(p05=float(np.quantile(abs(iq),.05)),median=float(np.median(abs(iq))),
                                    p95=float(np.quantile(abs(iq),.95)),dc_fraction=float(abs(iq.mean())))
        window = np.hanning(PERIOD)
        spectrum = abs(np.fft.fft(iq*window))**2/window.sum()**2
        axes[0].plot(np.fft.fftshift(np.fft.fftfreq(PERIOD,1/RATE))/1000,
                     np.fft.fftshift(10*np.log10(np.maximum(spectrum,1e-16))),label=label,color=color,lw=1)
        axes[1].plot(np.arange(512)/RATE*1000,abs(iq[:512]),label=label,color=color,lw=1)
    for edge in (-details['half_width_hz'],details['half_width_hz']):axes[0].axvline(edge/1000,color='gray',ls='--',lw=.8)
    axes[0].set(xlim=(-750,750),ylim=(-120,5),xlabel='Frequency offset (kHz)',ylabel='dB / FFT bin',
                title='RMS-normalized diagnostic model inputs (not absolute RF power)')
    axes[1].set(xlabel='Time within selected capture (ms)',ylabel='Normalized envelope',title='First 512 samples of fixed eighth capture window')
    if phase['identifiable']:
        times=np.asarray(phase['window_times_s'])*1000
        axes[2].plot(times[:7],phase['unwrapped_phase_rad'][:7],'o',label='Fit windows')
        axes[2].plot(times[7:],phase['unwrapped_phase_rad'][7:],'s',label='Later windows')
        axes[2].plot(times,phase['predicted_phase_rad'],'--',label='First-seven fit')
        axes[2].set_title('Source-referenced residual phase rate: %.2f Hz (not applied to model)'%phase['residual_phase_rate_hz'])
    axes[2].set(xlabel='Time from RX capture start (ms)',ylabel='Unwrapped phase (rad)')
    for axis in axes:axis.grid(alpha=.2);axis.legend(loc='best')
    figure.savefig(destination,dpi=150)
    plt.close(figure)
    print(json.dumps(dict(plot_input_hashes_verified=True,numpy_version=np.__version__,matplotlib_version=matplotlib.__version__,
                          fixed_selected_window_envelope=envelope_stats)))


async def infer(feature):
    preparation_path = feature/'fidelity-prepared.json'
    saved = json.loads(preparation_path.read_text())
    current, tensors = prepare(feature)
    assert current == saved, 'source-only preparation changed before inference'
    output = feature/'fidelity-inference.json'
    assert not output.exists()
    with (feature/'fidelity-inference-started.json').open('x') as marker:
        json.dump(dict(started_at_ns=time.time_ns(),maximum_experiment_windows=28),marker)
    receipt = dict(schema_id='b210_rx_fidelity_inference_v1', status='failed',
                   preparation_sha256=paired.sha(preparation_path.read_bytes()),
                   recognizer_available=False, independent_labels=0, production_profile_compatible=False,
                   result_semantics='offline_compensation_diagnostic_not_production_preprocess',
                   registered_maximum_windows=28, actual_experiment_windows=len(tensors)*4,
                   backend_warmup_windows=2, results={})
    from gpu_lease import GpuLease
    lease = GpuLease(feature/'fidelity-gate','mamba')
    token = None
    try:
        token = await lease.acquire(time.monotonic()+10,request='received-fidelity-comparison')
        worker = module('fidelity_worker','amc-mamba-worker.py')
        backend = worker.RfV1Backend(ROOT/'jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json')
        assert all(p.dtype == worker.torch.float32 for p in backend.model.parameters())
        receipt['identity'] = backend.admission_identity
        receipt['compute'] = 'cuda_fp16_autocast_fp32_weights'
        for name,data in tensors.items():
            logits,elapsed = [],0
            for window in data:
                value,timing = backend.classify_logits(np.ascontiguousarray(window))
                logits.append(value);elapsed += timing
            values = np.asarray(logits,dtype=np.float64)
            mean = values.mean(axis=0)
            probabilities = np.exp(mean-mean.max());probabilities /= probabilities.sum()
            numeric_id = int(probabilities.argmax())
            receipt['results'][name] = dict(numeric_id=numeric_id,window_numeric_ids=list(map(int,values.argmax(axis=1))),
                uncalibrated_probability=float(probabilities[numeric_id]),name_status='provisional',
                model_input_sha256=paired.sha(data.tobytes()),mean_logits_sha256=paired.sha(mean.astype('<f8').tobytes()),
                inference_us=elapsed,nominal_source_id_agreement=(numeric_id==0))
        receipt['status'] = 'comparison_completed'
    except BaseException as error:
        receipt['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        if token is not None:lease.release(token)
        receipt['gpu_lease'] = lease.metrics.copy();lease.close()
        output.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--infer',action='store_true',help='Recheck frozen source-only preparation before model loading')
    modes.add_argument('--phase-supplement',action='store_true',help='Posthoc phase-rate diagnostic; no model execution')
    modes.add_argument('--plot',type=Path,help='Plot existing results; requires matplotlib')
    args = parser.parse_args();feature = args.directory
    assert feature == FEATURE and feature.resolve() == feature
    def abort(signum,frame):raise RuntimeError(f'stop signal {signum}')
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,abort)
    if args.infer:asyncio.run(infer(feature))
    elif args.phase_supplement:supplement(feature)
    elif args.plot:plot(feature,args.plot)
    else:
        result,_ = prepare(feature)
        with (feature/'fidelity-prepared.json').open('x') as output:json.dump(result,output,indent=2);output.write('\n')
        print(json.dumps(result,indent=2))
