#!/usr/bin/env python3
"""Preregistered known-source complex-bias counterfactuals; no production compensation."""
import argparse
import asyncio
import json
from pathlib import Path
import signal
import time
import numpy as np
import importlib.util

if not __debug__:raise RuntimeError('validation requires assertions')
SCRIPTS=Path(__file__).parent
ROOT=SCRIPTS.resolve().parents[2]
FEATURE=Path('/var/tmp/sdrharness-dev/b210-affine-906f')
PERIOD,FIT_SAMPLES,RATE=4096,7*4096,2100000


def module(name,file):
    spec=importlib.util.spec_from_file_location(name,SCRIPTS/file)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


fidelity=module('affine_fidelity','diagnose-b210-rx-fidelity.py')
paired=fidelity.paired


def pair(z):return [float(z.real),float(z.imag)]
def complex_value(v):return complex(v[0],v[1])
def iq(z):return np.asarray(np.stack((z.real,z.imag),axis=1),dtype='<f4')


def fit_affine(reference,received):
    x=np.asarray(reference,dtype=np.complex128);y=np.asarray(received,dtype=np.complex128)
    if x.shape!=(FIT_SAMPLES,) or y.shape!=x.shape or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('affine fitting requires exactly seven finite windows')
    matrix=np.column_stack((x,np.ones(FIT_SAMPLES)))
    condition=float(np.linalg.cond(matrix))
    if not np.isfinite(condition) or condition>1000:raise ValueError('unidentifiable affine reference')
    coefficients,_,rank,_=np.linalg.lstsq(matrix,y,rcond=None)
    h,b=coefficients
    if rank!=2 or not np.isfinite(coefficients).all() or abs(h)<=1e-6:raise ValueError('unidentifiable affine gain')
    h0=np.vdot(x,y)/np.vdot(x,x).real
    return dict(gain=pair(h),bias=pair(b),gain_only=pair(h0),condition=condition,fit_samples=FIT_SAMPLES,
                bias_to_source_rms=float(abs(b)/(abs(h)*np.sqrt(np.mean(abs(x)**2)))))


def estimate(raw,source,tone_cfo,half_width):
    # Slice BEFORE FFT/mixing/lag/phase/gain estimation: no later samples can
    # influence coefficients through circular FFT filtering.
    raw=np.asarray(raw,dtype=np.complex128);source=np.asarray(source,dtype=np.complex128)
    if raw.shape!=(65535,) or source.shape!=(PERIOD,) or not np.isfinite(raw).all() or not np.isfinite(source).all():
        raise ValueError('affine source/capture shape')
    prefix=fidelity.bandlimit(fidelity.correct_cfo(raw[:FIT_SAMPLES],tone_cfo),half_width)
    reference=fidelity.bandlimit(source,half_width)
    target=abs(reference)-np.mean(abs(reference))
    envelopes=abs(prefix.reshape(7,PERIOD));envelopes-=envelopes.mean(axis=1,keepdims=True)
    norms=np.sqrt((envelopes**2).sum(axis=1)*(target**2).sum())
    if np.any(norms<=0):raise ValueError('degenerate source envelope')
    correlations=np.fft.ifft(np.fft.fft(envelopes,axis=1)*np.fft.fft(target).conj(),axis=1).real/norms[:,None]
    lag=int(np.median(correlations.argmax(axis=1)))
    reference=np.roll(reference,lag)
    phases=[];coherences=[]
    for k in range(7):
        y=prefix[k*PERIOD:(k+1)*PERIOD]
        phases.append(float(np.angle(np.vdot(reference,y))))
        coherences.append(fidelity.coherence(reference,y))
    times=(np.arange(7)+.5)*PERIOD/RATE
    slope,intercept=np.linalg.lstsq(np.column_stack((times,np.ones(7))),np.unwrap(phases),rcond=None)[0]
    rmse=float(np.sqrt(np.mean((np.unwrap(phases)-(slope*times+intercept))**2)))
    residual=float(slope/(2*np.pi))
    allowed=min(coherences)>=.2 and rmse<=.2 and abs(residual)<=200
    result=dict(method='prefix-only source-referenced lag, residual phase-rate and affine fit',
                parameter_complex_samples=FIT_SAMPLES,lag=lag,phase_window_coherence=coherences,
                phase_fit_rmse_rad=rmse,residual_frequency_hz=residual,residual_gate_passed=allowed,
                phase_alias_period_hz=RATE/PERIOD,affine=None)
    if allowed:
        corrected=fidelity.correct_cfo(prefix,residual)
        try:result['affine']=fit_affine(np.tile(reference,7),corrected)
        except ValueError as error:result['affine_unavailable_reason']=str(error)
    return result,reference


def heldout(reference,received,coefficients):
    x=np.tile(reference,16)[:len(received)]
    h,b,h0=(complex_value(coefficients[k]) for k in ('gain','bias','gain_only'))
    rows=[]
    for start in range(FIT_SAMPLES,15*PERIOD,PERIOD):
        target=x[start:start+PERIOD];actual=received[start:start+PERIOD]
        power=float(np.mean(abs(actual)**2))
        if not power>0:raise ValueError('zero heldout received power')
        rows.append(dict(complex_offset=start,
                         gain_only_residual_fraction=float(np.mean(abs(actual-h0*target)**2)/power),
                         affine_residual_fraction=float(np.mean(abs(actual-h*target-b)**2)/power),
                         centered_coherence=fidelity.coherence(target-target.mean(),actual-actual.mean())))
    return rows


def prepare(feature,exploratory_source_failure=False):
    originals,receipt=paired.prepare_inputs(feature)
    analysis=json.loads((feature/'source-matched-analysis.json').read_text())
    raw,digest=fidelity.source_match.read_iq(feature,'during-tx')
    assert digest==receipt['parent_iq_sha256']
    original=originals['source_original_order'].astype(np.float64)
    source=original[:,0]+1j*original[:,1]
    cfo=analysis['tone']['frequency_difference_hz'];width=analysis['source_99_percent_half_width_hz']
    estimates,reference=estimate(raw,source,cfo,width)
    source_pass=analysis['engineering_controls']['passed']
    if exploratory_source_failure and source_pass:raise ValueError('exploratory override is only for a recorded failed source gate')
    tone_band=fidelity.bandlimit(fidelity.correct_cfo(raw,cfo),width)
    selected=slice(FIT_SAMPLES,FIT_SAMPLES+PERIOD)
    inputs=dict(source_band=iq(reference),received_raw=originals['received_unmodified'],received_tone_band=iq(tone_band[selected]))
    validation=[]
    if (source_pass or exploratory_source_failure) and estimates['residual_gate_passed']:
        corrected=fidelity.correct_cfo(tone_band,estimates['residual_frequency_hz'])
        inputs['received_residual_band']=iq(corrected[selected])
        if estimates['affine'] is not None:
            h=complex_value(estimates['affine']['gain']);b=complex_value(estimates['affine']['bias'])
            inputs['source_gain_phase']=iq(h*reference)
            inputs['source_with_bias']=iq(h*reference+b)
            inputs['received_debiased']=iq(corrected[selected]-b)
            validation=heldout(reference,corrected,estimates['affine'])
    order=['source_band','source_gain_phase','source_with_bias','received_raw','received_tone_band','received_residual_band','received_debiased']
    inputs={name:inputs[name] for name in order if name in inputs}
    tensors={name:paired.normalize(value) for name,value in inputs.items()}
    assert len(tensors)<=7
    details=dict(schema_id='b210_affine_preparation_v1',source_receipt=receipt,source_control_passed=source_pass,
                 tone_cfo_hz=cfo,source_half_width_hz=width,estimates=estimates,heldout_validation=validation,
                 model_complex_offset=FIT_SAMPLES,model_parameters_fitted_from_raw_prefix_only=True,
                 model_inputs={name:dict(sha256=paired.sha(data.tobytes()),bytes=data.nbytes) for name,data in tensors.items()},
                 envelope={name:dict(p05=float(np.quantile(np.linalg.norm(data,axis=1),.05)),
                                    p95=float(np.quantile(np.linalg.norm(data,axis=1),.95)))
                           for name,data in ((k,t.transpose(0,2,1).reshape(PERIOD,2)) for k,t in tensors.items())},
                 recognizer_available=False,independent_labels=0,production_profile_compatible=False,
                 interpretation='known-source channel diagnostic; never remove the source genuine mean as if it were bias')
    if exploratory_source_failure:
        details['source_gate_failure_exploration']=True
        details['original_failed_preparation_sha256']=paired.sha((feature/'affine-prepared.json').read_bytes())
        details['qualified_bidirectional_validation']=False
    return details,tensors


def plot(feature,destination,exploratory_source_failure):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    current,tensors=prepare(feature,exploratory_source_failure)
    prefix='affine-exploratory' if exploratory_source_failure else 'affine'
    inference=json.loads((feature/(prefix+'-inference.json')).read_text())
    for name,data in tensors.items():assert paired.sha(data.tobytes())==inference['results'][name]['model_input_sha256']
    figure,axes=plt.subplots(3,1,figsize=(11,9),constrained_layout=True)
    def envelope(name):
        data=tensors[name].transpose(0,2,1).reshape(PERIOD,2).astype(np.float64)
        return np.linalg.norm(data,axis=1)
    times=np.arange(PERIOD)/RATE*1000
    for name,label,color in [('source_band','Source','#333333'),('source_with_bias','Source + fitted bias','#e69f00'),
                             ('received_residual_band','RX before bias removal','#b2182b')]:
        if name in tensors:axes[0].plot(times,envelope(name),label=label,color=color,lw=.9,alpha=.85)
    for name,label,color in [('source_band','Source','#333333'),('received_debiased','RX after bias removal','#1b9e77')]:
        if name in tensors:axes[1].plot(times,envelope(name),label=label,color=color,lw=.9,alpha=.85)
    axes[0].set_title('Fixed eighth capture window: RMS-normalized envelopes')
    for axis in axes[:2]:
        axis.set(xlabel='Time within capture (ms)',ylabel='Envelope')
        for k in (1,2,3):axis.axvline(k*1024/RATE*1000,color='gray',ls='--',lw=.5)
    rows=current['heldout_validation']
    if rows:
        axes[2].plot(range(8,16),[r['gain_only_residual_fraction'] for r in rows],'o-',label='Gain-only fit')
        axes[2].plot(range(8,16),[r['affine_residual_fraction'] for r in rows],'s-',label='Gain + complex bias fit')
    axes[2].set(xlabel='Later capture window',ylabel='Residual / received power',title='All coefficients fixed from first seven raw windows')
    for axis in axes:axis.grid(alpha=.2);axis.legend(loc='best')
    figure.suptitle('Posthoc exploration: original source-envelope gate FAILED' if exploratory_source_failure else 'Known-source affine diagnostic')
    figure.savefig(destination,dpi=150);plt.close(figure)
    print(json.dumps(dict(all_model_input_hashes_verified=True,numpy_version=np.__version__,matplotlib_version=matplotlib.__version__,
                          source_control_passed=current['source_control_passed'],qualified_bidirectional_validation=inference['qualified_bidirectional_validation'])))


async def infer(feature,exploratory_source_failure=False,*,prepare_function=None,prefix_override=None):
    current,tensors=(prepare_function or prepare)(feature,exploratory_source_failure)
    prefix=prefix_override or ('affine-exploratory' if exploratory_source_failure else 'affine')
    assert prefix in ('affine','affine-exploratory','v4-affine')
    assert len(tensors)<=7, 'registered model-window budget'
    preparation_path=feature/(prefix+'-prepared.json')
    assert current==json.loads(preparation_path.read_text()),'prepared inputs changed'
    output=feature/(prefix+'-inference.json');assert not output.exists()
    with (feature/'affine-inference-started.json').open('x') as marker:json.dump(dict(started_at_ns=time.time_ns(),maximum_windows=28),marker)
    receipt=dict(schema_id='b210_affine_inference_v1',status='failed',preparation_sha256=paired.sha(preparation_path.read_bytes()),
                 actual_experiment_windows=len(tensors)*4,maximum_experiment_windows=28,backend_warmup_windows=2,
                 source_control_passed=current['source_control_passed'],source_gate_failure_exploration=exploratory_source_failure,
                 qualified_bidirectional_validation=(current['source_control_passed'] and len(tensors)==7),
                 recognizer_available=False,independent_labels=0,production_profile_compatible=False,
                 result_semantics='known-source bidirectional bias diagnostic; not production classification',results={})
    from gpu_lease import GpuLease
    lease=GpuLease(feature/'affine-gate','mamba');token=None
    try:
        token=await lease.acquire(time.monotonic()+10,request='source-received-affine-comparison')
        worker=module('affine_worker','amc-mamba-worker.py')
        backend=worker.RfV1Backend(ROOT/'jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json')
        assert all(p.dtype==worker.torch.float32 for p in backend.model.parameters())
        receipt['identity']=backend.admission_identity;receipt['compute']='cuda_fp16_autocast_fp32_weights'
        for name,data in tensors.items():
            logits=[];elapsed=0
            for window in data:
                values,timing=backend.classify_logits(np.ascontiguousarray(window));logits.append(values);elapsed+=timing
            values=np.asarray(logits,dtype=np.float64);mean=values.mean(axis=0)
            probabilities=np.exp(mean-mean.max());probabilities/=probabilities.sum();numeric_id=int(probabilities.argmax())
            receipt['results'][name]=dict(numeric_id=numeric_id,window_numeric_ids=list(map(int,values.argmax(axis=1))),
                                         uncalibrated_probability=float(probabilities[numeric_id]),name_status='provisional',
                                         mean_logits_sha256=paired.sha(mean.astype('<f8').tobytes()),
                                         model_input_sha256=paired.sha(data.tobytes()),inference_us=elapsed,
                                         nominal_source_id_agreement=(numeric_id==0))
        receipt['status']='comparison_completed'
    except BaseException as error:receipt['failure']=f'{type(error).__name__}: {error}';raise
    finally:
        if token is not None:lease.release(token)
        receipt['gpu_lease']=lease.metrics.copy();lease.close()
        output.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--infer',action='store_true')
    modes.add_argument('--plot',type=Path)
    parser.add_argument('--exploratory-source-failure',action='store_true',help='Explicit posthoc exploration; failed source gate remains failed')
    args=parser.parse_args()
    assert args.directory==FEATURE and args.directory.resolve()==args.directory
    def abort(signum,frame):raise RuntimeError(f'stop signal {signum}')
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,abort)
    if args.infer:asyncio.run(infer(args.directory,args.exploratory_source_failure))
    elif args.plot:plot(args.directory,args.plot,args.exploratory_source_failure)
    else:
        details,_=prepare(args.directory,args.exploratory_source_failure)
        name='affine-exploratory-prepared.json' if args.exploratory_source_failure else 'affine-prepared.json'
        with (args.directory/name).open('x') as output:json.dump(details,output,indent=2);output.write('\n')
        print(json.dumps(details,indent=2))
