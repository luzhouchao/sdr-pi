#!/usr/bin/env python3
"""Known narrowband engineering source: LO separation and fixed FIR rejection."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import time
import signal
import numpy as np

if not __debug__:raise RuntimeError('validation assertions required')
SCRIPTS=Path(__file__).parent
spec=importlib.util.spec_from_file_location('reject_lo',SCRIPTS/'diagnose-b210-lo-offset.py')
lo=importlib.util.module_from_spec(spec);spec.loader.exec_module(lo)
point,live=lo.point,lo.live
ROOT=Path('/var/tmp/sdrharness-dev/b210-reject-907m')
CASES=(('zero',0),('fix1',250000),('fix2',250000))
MODEL_START=32768
HALO=128

def feature(tag):return ROOT.parent/f'b210-reject-{tag}-907m'

def coefficients():
    n=np.arange(257)-HALO
    taps=2*175000/point.RATE*np.sinc(2*175000/point.RATE*n)*np.kaiser(257,8.)
    return taps/taps.sum()

def reject(z):
    """No source fitting, DC removal, resampling or circular/zero-padded output."""
    z=np.asarray(z,dtype=np.complex128)
    if z.ndim!=1 or len(z)<257 or not np.isfinite(z).all():raise ValueError('finite IQ with both FIR halos required')
    return np.convolve(z,coefficients(),mode='valid')

def source_retention(source):
    z=np.asarray(source,dtype=np.complex128)
    if z.shape!=(1024,) or not np.isfinite(z).all() or point.rms(z)==0:raise ValueError('finite nonzero 1024 source required')
    filtered=reject(np.tile(z,3))[1024-HALO:2048-HALO]
    return dict(power_fraction=point.rms(filtered)**2/point.rms(z)**2,
                normalized_distortion_power=point.rms(filtered-z)**2/point.rms(z)**2,
                complex_mean_error=abs(complex(filtered.mean()-z.mean())))

def filter_contract():
    taps=coefficients();f=np.fft.rfftfreq(131072,1/point.RATE);response=abs(np.fft.rfft(taps,131072))
    return dict(schema_id='b210_separated_lo_fixed_fir_v1',sample_rate_hz=point.RATE,tx_lo_offset_hz=250000,
                taps=257,cutoff_hz=175000,kaiser_beta=8.,raw_halo_samples=HALO,
                coefficients_sha256=lo.hashlib.sha256(taps.astype('<f8').tobytes()).hexdigest(),
                passband_max_amplitude_error=float(max(abs(response[f<=140000]-1))),
                stopband_max_db=float(20*np.log10(max(response[f>=210000]))),
                source_mean_preserved=True,production_enabled=False)

def window_metrics(raw,filtered,predicted,controls,start):
    # All arrays refer to the same original capture offset; filter removes halos.
    sl=slice(start-HALO,start+4096-HALO);y=filtered[sl];p=predicted[sl]
    if len(y)!=4096 or len(p)!=4096:raise ValueError('complete fixed evaluation block required')
    coherences=[live.affine.fidelity.coherence(x-x.mean(),z-z.mean()) for x,z in zip(p.reshape(4,1024),y.reshape(4,1024))]
    power=point.rms(y)**2
    residual=point.rms(y-p)**2/max(power,1e-30)
    margins={tag:float(10*np.log10(max(power,1e-30)/max(point.rms(z[sl])**2,1e-30))) for tag,z in controls.items()}
    return dict(raw_start=start,samples=4096,centered_coherences=coherences,residual_power_fraction=residual,
                stopped_power_margins_db=margins,passed=bool(min(coherences)>=.9 and residual<=.2 and min(margins.values())>=10))

def evaluate(source,captures,tone_cfo,offset):
    raw=captures['during-tx'];controls={k:captures[k] for k in ('baseline','after-tx')}
    report,arrays=point.compare(source,raw,controls,tone_cfo,live.match.source_bandwidth(source))
    result=dict(pointwise=report,filter_contract=filter_contract(),source_retention=source_retention(source),model_control_passed=False)
    if arrays is None:return result,{}
    fit=report['alignment'];h=complex(*report['models']['scalar_robust']['coefficients'][0])
    n=np.arange(point.COUNT);reference=source[(n-fit['lag'])%1024]
    prediction=h*reference*np.exp(2j*np.pi*fit['total_frequency_hz']*n/point.RATE)
    filtered={tag:reject(z) for tag,z in captures.items()};predicted=reject(prediction)
    y=filtered['during-tx'];stopped={k:filtered[k] for k in controls}
    # Hann spectrum of the same prefix interior before and after the FIR.
    size=point.FIT-2*HALO;f=np.fft.fftfreq(size,1/point.RATE);mask=abs(f-(fit['total_frequency_hz']+offset))<=500
    def line_power(z):return float((abs(np.fft.fft(z*np.hanning(size)))**2)[mask].sum())
    before=line_power(raw[HALO:point.FIT-HALO]);after=line_power(y[:size])
    suppression=float(10*np.log10(max(before,1e-30)/max(after,1e-30)))
    result.update(lo_band_suppression_db=suppression,valid_raw_interval=[HALO,point.COUNT-HALO],
                  leakage_repair_passed=bool(offset==250000 and suppression>=40 and result['source_retention']['power_fraction']>=.99),
                  heldout_blocks=[window_metrics(raw,y,predicted,stopped,start) for start in range(17408,62464,4096)])
    selected=window_metrics(raw,y,predicted,stopped,MODEL_START)
    result['fixed_model_block']=selected
    result['model_control_passed']=bool(selected['passed'] and (offset==0 or result['leakage_repair_passed']))
    result['segments']=[dict(raw_start=start,samples=min(128,point.COUNT-HALO-start),
                            raw_rms=point.rms(raw[start:min(start+128,point.COUNT-HALO)]),
                            filtered_rms=point.rms(y[start-HALO:min(start+128,point.COUNT-HALO)-HALO]),
                            gain_only_residual_rms=point.rms((y-predicted)[start-HALO:min(start+128,point.COUNT-HALO)-HALO]))
                        for start in range(HALO,point.COUNT-HALO,128)]
    inputs={}
    if result['model_control_passed']:
        source_filtered=reject(np.tile(source,point.COUNT//1024+2))[MODEL_START-HALO:MODEL_START+4096-HALO]
        # Apply only the already-fixed integer lag to source controls. RF carrier/gain
        # estimates never enter the model inputs or the rejection transform.
        source_filtered=np.roll(source_filtered,fit['lag'])
        inputs=dict(source_original=reference[MODEL_START:MODEL_START+4096],source_filtered=source_filtered,
                    received_raw=raw[MODEL_START:MODEL_START+4096],received_filtered=y[MODEL_START-HALO:MODEL_START+4096-HALO])
        inputs={name:live.affine.paired.normalize(np.column_stack((z.real,z.imag))) for name,z in inputs.items()}
    return result,inputs

def prepare():
    seal=live.document(ROOT/'seal.json');assert live.validate_capture_root(feature('tone'),'tone')==seal['tone']
    tone=live.match.tone_metrics(feature('tone'));assert live.match.assess_tone(tone)['passed']
    report=dict(schema_id='b210_lo_rejection_validation_v1',filter_contract=filter_contract(),cases={},
                model_inputs={},recognizer_available=False,production_profile_compatible=False,independent_labels=0,seal=seal)
    tensors={}
    for tag,offset in CASES:
        root=feature(tag);assert lo.seal_case(root,offset)==seal['cases'][tag]
        v=np.frombuffer(live.read(root/'train-tile.fc32'),dtype='<f4').reshape(1024,2);source=v[:,0].astype(float)+1j*v[:,1].astype(float)
        captures={t:live.match.read_iq(root,t)[0] for t in ('baseline','during-tx','after-tx')}
        result,inputs=evaluate(source,captures,tone['frequency_difference_hz'],offset)
        result.update(tx_lo_offset_hz=offset,link_evidence=live.document(root/'link-summary.json'),tx_evidence=live.document(root/'tx-summary.json'))
        report['cases'][tag]=result
        for name,data in inputs.items():tensors[tag+'_'+name]=data
    report['model_inputs']={key:lo.hashlib.sha256(value.tobytes()).hexdigest() for key,value in tensors.items()}
    report['all_offset_leakage_repairs_passed']=all(report['cases'][tag].get('leakage_repair_passed',False) for tag,offset in CASES if offset)
    report['all_fixed_model_blocks_passed']=all(c['model_control_passed'] for c in report['cases'].values())
    return report,tensors

def acquire(binary):
    # Source/response qualification is a pre-RF gate, including the first tone.
    for tag,offset in CASES:lo.validate_plan(feature(tag),offset)
    v=np.frombuffer(live.read(feature('zero')/'train-tile.fc32'),dtype='<f4').reshape(1024,2)
    source=v[:,0].astype(float)+1j*v[:,1].astype(float)
    contract=filter_contract();retention=source_retention(source)
    assert contract['passband_max_amplitude_error']<=.001 and contract['stopband_max_db']<=-80
    assert retention['power_fraction']>=.99
    assert live.document(ROOT/'filter-preflight.json')==dict(contract=contract,source_retention=retention)
    lo.acquire(binary,root=ROOT,cases=CASES,feature_path=feature)

async def infer(*, root=None, prepare_function=None, max_inputs=12):
    feature=ROOT if root is None else root
    assert max_inputs in (12,16) and feature.resolve()==feature
    report,tensors=(prepare_function or prepare)();assert report==live.document(feature/'prepared.json'),'sealed preparation changed'
    assert len(tensors)<=max_inputs
    lo.save(feature/'inference-started.json',dict(maximum_experiment_windows=4*max_inputs,actual_windows=4*len(tensors)))
    receipt=dict(status='skipped_no_qualified_fixed_blocks' if not tensors else 'failed',results={},model_windows=0,planned_model_windows=4*len(tensors),
                 warmup_windows=0,recognizer_available=False,independent_labels=0,production_profile_compatible=False,
                 result_semantics='fixed-window single-source engineering comparison; not production classified')
    if not tensors:lo.save(feature/'inference.json',receipt);return
    from gpu_lease import GpuLease
    lease=GpuLease(feature/'gpu-gate','mamba');token=None
    try:
        token=await lease.acquire(time.monotonic()+10,request='b210-fixed-lo-rejection')
        worker=live.affine.module('reject_worker','amc-mamba-worker.py')
        backend=worker.RfV1Backend(live.affine.ROOT/'jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json')
        assert all(p.dtype==worker.torch.float32 for p in backend.model.parameters())
        receipt.update(identity=backend.admission_identity,compute='cuda_fp16_autocast_fp32_weights',warmup_windows=2)
        for name,data in tensors.items():
            logits=[];elapsed=0
            for window in data:
                values,timing=backend.classify_logits(np.ascontiguousarray(window));logits.append(values);elapsed+=timing
                receipt['model_windows']+=1
            values=np.asarray(logits,dtype=np.float64);mean=values.mean(axis=0)
            receipt['results'][name]=dict(numeric_id=int(mean.argmax()),window_numeric_ids=values.argmax(axis=1).tolist(),
                logits=values.tolist(),mean_logits=mean.tolist(),name_status='provisional',inference_us=elapsed,
                input_sha256=report['model_inputs'][name],uncalibrated=True)
        receipt['status']='comparison_completed'
    except BaseException as error:
        receipt['failure']=f'{type(error).__name__}: {error}';raise
    finally:
        if token is not None:lease.release(token)
        receipt['gpu_lease']=lease.metrics.copy();lease.close();lo.save(feature/'inference.json',receipt)

def verify_retained():
    record=live.affine.ROOT/'docs/B210_LO_REJECTION_EVIDENCE_2026-09-07.json'
    inventory=live.document(record)
    expected={row['path'] for row in inventory['files']}
    actual={str(path) for name in inventory['roots'] for path in Path(name).rglob('*') if path.is_file()}
    assert actual==expected, 'retained files missing or unrecorded files present'
    for row in inventory['files']:
        data=live.read(Path(row['path']))
        assert len(data)==row['bytes'] and lo.hashlib.sha256(data).hexdigest()==row['sha256']
    current,_=prepare()
    audit=live.document(live.affine.ROOT/'docs/B210_LO_REJECTION_AUDIT_2026-09-07.json')
    assert all(audit[key]==value for key,value in current.items()), 'retained analysis changed'
    print(json.dumps(dict(retained_files=len(expected),logical_bytes=sum(row['bytes'] for row in inventory['files']),
                          sealed_analysis_reproduced=True,model_windows=0,rf_operations=0)))

def plot(destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    report,_=prepare();assert report==live.document(ROOT/'prepared.json')
    fig,axes=plt.subplots(2,3,figsize=(15,8),constrained_layout=True)
    for col,(tag,offset) in enumerate(CASES):
        raw=live.match.read_iq(feature(tag),'during-tx')[0];filtered=reject(raw)
        size=point.FIT-2*HALO;window=np.hanning(size)
        frequency=np.fft.fftshift(np.fft.fftfreq(size,1/point.RATE))/1000
        for z,label,color in ((raw[HALO:point.FIT-HALO],'RX raw','#b2182b'),(filtered[:size],'Fixed FIR','#2166ac')):
            power=abs(np.fft.fftshift(np.fft.fft(z*window)))**2/window.sum()**2
            axes[0,col].plot(frequency,10*np.log10(np.maximum(power,1e-20)),label=label,color=color,lw=.7)
        axes[0,col].set(xlim=(-300,300),xlabel='RX baseband (kHz)',ylabel='Prefix spectrum (dB ADC²)',title=tag+' / LO '+str(offset//1000)+' kHz')
        rows=report['cases'][tag]['segments'];times=np.array([r['raw_start'] for r in rows])/point.RATE*1000
        for key,label,color in (('raw_rms','RX raw','#b2182b'),('filtered_rms','Fixed FIR','#2166ac'),('gain_only_residual_rms','Source prediction residual','#777777')):
            axes[1,col].plot(times,[r[key] for r in rows],label=label,color=color,lw=.8)
        axes[1,col].axvspan(MODEL_START/point.RATE*1000,(MODEL_START+4096)/point.RATE*1000,color='gray',alpha=.2)
        axes[1,col].set(xlabel='Capture time (ms)',ylabel='128-sample RMS (ADC)')
        for axis in axes[:,col]:axis.grid(alpha=.2);axis.legend(fontsize=8)
    fig.suptitle('Fixed LO rejection: leakage suppressed; registered stopped-background gates failed')
    fig.savefig(destination,dpi=150);plt.close(fig)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--acquire',type=Path);g.add_argument('--prepare',action='store_true');g.add_argument('--infer',action='store_true');g.add_argument('--plot',type=Path);g.add_argument('--verify-retained',action='store_true')
    args=p.parse_args()
    if args.acquire:acquire(args.acquire)
    elif args.prepare:lo.save(ROOT/'prepared.json',prepare()[0])
    elif args.plot:plot(args.plot)
    elif args.verify_retained:verify_retained()
    else:
        def abort(signum,frame):raise RuntimeError(f'stop signal {signum}')
        for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,abort)
        asyncio.run(infer())
