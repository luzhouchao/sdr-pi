#!/usr/bin/env python3
"""Known 1024-sample source: raw-domain channel predictions and pointwise errors."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path

import numpy as np

if not __debug__:
    raise RuntimeError('diagnostics require validation assertions')
SCRIPTS=Path(__file__).parent
spec=importlib.util.spec_from_file_location('pointwise_live',SCRIPTS/'validate-b210-v4-affine.py')
live=importlib.util.module_from_spec(spec);spec.loader.exec_module(live)
PERIOD,RATE,FIT,COUNT,CHUNK=1024,2100000,16*1024,65535,128
FEATURE=Path('/var/tmp/sdrharness-dev/b210-pointwise-906k')
TONE=Path('/var/tmp/sdrharness-dev/b210-pointwise-tone-906k')


def band(z,width):
    return np.fft.ifft(np.fft.fft(z)*(abs(np.fft.fftfreq(len(z),1/RATE))<=width))


def alignment(source,raw,tone_cfo,width):
    # Only the raw prefix is transformed; heldout samples cannot leak through FFT.
    prefix=band(raw[:FIT]*np.exp(-2j*np.pi*tone_cfo*np.arange(FIT)/RATE),width)
    reference=band(source,width)
    cc=live.match._centered_correlations(prefix.reshape(16,PERIOD),reference,all_lags=True)
    lag=int(np.argmax(np.mean(abs(cc),axis=0)))
    values=cc[:,lag];weights=abs(values)**2
    phase=np.unwrap(np.angle(values));times=(np.arange(16)+.5)*PERIOD/RATE
    design=np.column_stack((times,np.ones(16)))
    coefficients=np.linalg.lstsq(design*np.sqrt(weights[:,None]),phase*np.sqrt(weights),rcond=None)[0]
    error=phase-design@coefficients
    rmse=float(np.sqrt(np.sum(weights*error**2)/max(weights.sum(),1e-30)))
    residual=float(coefficients[0]/(2*np.pi));median=float(np.median(abs(values)))
    return dict(lag=lag,tone_cfo_hz=float(tone_cfo),residual_frequency_hz=residual,
                total_frequency_hz=float(tone_cfo+residual),weighted_phase_rmse_rad=rmse,
                prefix_coherences=list(map(float,abs(values))),prefix_median_coherence=median,
                phase_alias_period_hz=RATE/PERIOD,fit_samples=FIT,
                usable=bool(median>=.3 and rmse<=.3 and abs(residual)<=200))


def design_matrix(source,fit,taps,count):
    n=np.arange(count);carrier=np.exp(2j*np.pi*fit['total_frequency_hz']*n/RATE)
    columns=[source[(n-fit['lag']-tap)%PERIOD]*carrier for tap in taps]
    return np.column_stack([*columns,carrier,np.ones(count)])


def solve_channel(matrix,received,robust=False):
    a=np.asarray(matrix,dtype=np.complex128);y=np.asarray(received,dtype=np.complex128)
    if a.ndim!=2 or a.shape[0]!=FIT or y.shape!=(FIT,) or not np.isfinite(a).all() or not np.isfinite(y).all():
        raise ValueError('finite prefix-only channel fit required')
    scale=np.linalg.norm(a,axis=0)
    if np.any(scale<=0):raise ValueError('degenerate channel columns')
    normalized=a/scale
    condition=float(np.linalg.cond(normalized))
    if not np.isfinite(condition) or condition>1e6:raise ValueError('channel design is unidentifiable')
    weights=np.ones(FIT)
    for iteration in range(7 if robust else 1):
        coefficients,_,rank,_=np.linalg.lstsq(normalized*np.sqrt(weights[:,None]),y*np.sqrt(weights),rcond=None)
        if rank!=a.shape[1] or not np.isfinite(coefficients).all():raise ValueError('channel fit rank/finite failure')
        coefficients=coefficients/scale
        error=y-a@coefficients
        if robust and iteration<6:
            sigma=max(float(np.median(abs(error))/np.sqrt(np.log(2))),1e-12)
            weights=np.minimum(1.,2.5*sigma/np.maximum(abs(error),1e-30))
    return coefficients,dict(condition=condition,robust_iterations=6 if robust else 0,
                             weights_below_half_fraction=float(np.mean(weights<.5)),
                             coefficients=[[float(z.real),float(z.imag)] for z in coefficients])


def rms(z):return float(np.sqrt(np.mean(abs(z)**2)))


def compare(source,raw,controls,tone_cfo,width):
    source=np.asarray(source,dtype=np.complex128);raw=np.asarray(raw,dtype=np.complex128)
    if source.shape!=(PERIOD,) or raw.shape!=(COUNT,) or not np.isfinite(source).all() or not np.isfinite(raw).all():
        raise ValueError('one finite 1024 source and 65535 receive samples required')
    if set(controls)!={'baseline','after-tx'} or any(np.shape(z)!=(COUNT,) or not np.isfinite(z).all() for z in controls.values()):
        raise ValueError('both complete finite stopped captures required')
    if not np.isfinite([tone_cfo,width]).all() or abs(tone_cfo)>5000 or not 0<width<RATE/2:
        raise ValueError('invalid tone offset/source bandwidth')
    fit=alignment(source,raw,tone_cfo,width)
    report=dict(schema_id='b210_1024_pointwise_v1',alignment=fit,source_unit_samples=PERIOD,
                raw_samples=COUNT,models={},recognizer_available=False,independent_labels=0,
                model_windows=0,qualification_claimed=False,
                interpretation='known-source system identification and all-sample diagnostic; no classifier training')
    if not fit['usable']:return report,None
    predictions={}
    for name,taps in (('scalar',(0,)),('fir9',tuple(range(-4,5)))):
        matrix=design_matrix(source,fit,taps,COUNT)
        for robust in (False,True):
            key=name+('_robust' if robust else '_ols')
            try:coefficients,metrics=solve_channel(matrix[:FIT],raw[:FIT],robust)
            except ValueError as error:
                report['models'][key]=dict(unavailable_reason=str(error));continue
            predicted=matrix@coefficients;error=raw-predicted
            metrics.update(tap_offsets=list(taps),tx_carrier_bias=metrics['coefficients'][-2],
                           receiver_dc=metrics['coefficients'][-1],prefix_residual_rms=rms(error[:FIT]),
                           heldout_residual_rms=rms(error[FIT:]),
                           heldout_residual_to_received_power=rms(error[FIT:])**2/max(rms(raw[FIT:])**2,1e-30))
            report['models'][key]=metrics;predictions[key]=predicted
    if 'scalar_robust' not in predictions:return report,None
    predicted=predictions['scalar_robust'];error=raw-predicted
    prefix_scales=[rms(error[start:start+CHUNK]) for start in range(0,FIT,CHUNK)]
    threshold=4*max(float(np.median(prefix_scales)),1.)
    report['exploratory_event_threshold_adc']=threshold
    rows=[]
    for start in range(0,COUNT,CHUNK):
        stop=min(start+CHUNK,COUNT);y=raw[start:stop];p=predicted[start:stop];e=error[start:stop]
        power=float(np.vdot(p,p).real)
        gain=np.vdot(p,y)/power if power>0 else None
        row=dict(start=start,count=stop-start,heldout=start>=FIT,raw_rms=rms(y),predicted_rms=rms(p),residual_rms=rms(e),
                 centered_coherence=live.affine.fidelity.coherence(p-p.mean(),y-y.mean()),
                 local_amplitude_ratio=float(abs(gain)) if gain is not None else None,
                 local_phase_difference_rad=float(np.angle(gain)) if gain is not None else None,
                 residual_event=bool(rms(e)>threshold))
        if 'fir9_robust' in predictions:row['fir9_residual_rms']=rms(raw[start:stop]-predictions['fir9_robust'][start:stop])
        rows.append(row)
    report['segments']=rows
    report['stopped_controls']={tag:dict(segment_rms=[rms(z[start:min(start+CHUNK,COUNT)]) for start in range(0,COUNT,CHUNK)],
                                        threshold_exceeded_segments=sum(rms(z[start:min(start+CHUNK,COUNT)])>threshold for start in range(0,COUNT,CHUNK)))
                                for tag,z in controls.items()}
    derotated=raw[:63*PERIOD]*np.exp(-2j*np.pi*fit['total_frequency_hz']*np.arange(63*PERIOD)/RATE)
    cc=live.match._centered_correlations(derotated.reshape(63,PERIOD),source,all_lags=True)
    best=abs(cc).argmax(axis=1)
    report['local_lag_diagnostic']=[dict(window=i+1,start=i*PERIOD,best_lag=int(lag),
        delta_from_fixed_lag=int((lag-fit['lag']+PERIOD//2)%PERIOD-PERIOD//2),coherence=float(abs(cc[i,lag])),
        high_coherence=bool(abs(cc[i,lag])>=.8)) for i,lag in enumerate(best)]
    phase=(np.arange(FIT,COUNT)-fit['lag'])%PERIOD
    sums=np.bincount(phase,weights=abs(error[FIT:])**2,minlength=PERIOD)
    counts=np.bincount(phase,minlength=PERIOD)
    profile=np.sqrt(sums/counts)
    boundary=(phase<16)|(phase>=PERIOD-16)
    report['boundary_diagnostic']=dict(phase_rms=profile.tolist(),boundary_residual_rms=rms(error[FIT:][boundary]),
                                        nonboundary_residual_rms=rms(error[FIT:][~boundary]),
                                        interpretation='fixed source-phase folding; not a hardware root-cause test')
    worst=max((row for row in rows if row['heldout']),key=lambda row:row['residual_rms'])
    report['zoom_selection']=dict(worst_heldout_segment_start=worst['start'],fixed_reference_start=FIT,
                                  method='maximum frozen-model residual RMS among all heldout 128-sample segments')
    return report,dict(source=source,raw=raw,predicted=predicted,error=error,predictions=predictions)


def inventory(root,tone):
    plan=live.document(root/'transmission-plan.json');payload=live.read(root/'train-tile.fc32')
    for key,value in dict(schema_version=2,rows=[102400],source_unit_samples=1024,tx_unit_count=20480,
                          payload_bytes=8192,uhd_spb=1024,tx_samples=20971520,class_id=0,dataset_nominal_snr_db=30,
                          split='train',locked_test_read=False,center_hz=2440000000,rate_sps=2100000,
                          bandwidth_hz=1500000,tx_gain_db=70,complex_peak=.2,tx_channel=0,tx_antenna='TX/RX').items():
        assert plan[key]==value,key
    digest=live.affine.paired.sha(payload)
    assert len(payload)==8192 and digest==plan['payload_sha256']
    received=live.validate_capture_root(root,'rml',single_source_sha256=digest)
    control=live.validate_capture_root(tone,'tone')
    assert received['sdrd_pid']==control['sdrd_pid']
    return dict(schema_id='b210_1024_seal_v1',received=received,tone=control,
                source_hashes={name:live.affine.paired.sha(live.read(root/name)) for name in
                    ('train-tile.fc32','transmission-plan.json','tx-summary.json','tx-uhd.log')})


def run(root,tone):
    assert inventory(root,tone)==live.document(root/'pointwise-seal.json'),'sealed input changed'
    tile=np.frombuffer(live.read(root/'train-tile.fc32'),dtype='<f4').reshape(PERIOD,2)
    source=tile[:,0].astype(float)+1j*tile[:,1].astype(float)
    tone_result=live.match.tone_metrics(tone);assessment=live.match.assess_tone(tone_result)
    assert assessment['passed'],'tone control failed'
    captures={tag:live.match.read_iq(root,tag)[0] for tag in ('baseline','during-tx','after-tx')}
    width=live.match.source_bandwidth(source)
    report,arrays=compare(source,captures['during-tx'],{tag:captures[tag] for tag in ('baseline','after-tx')},
                          tone_result['frequency_difference_hz'],width)
    report.update(source_half_width_hz=width,tone=tone_result,tone_assessment=assessment,
                  seal_sha256=live.affine.paired.sha(live.read(root/'pointwise-seal.json')))
    return report,arrays


def write_samples(path,report,arrays):
    assert arrays is not None
    phase_floor=.1*rms(arrays['predicted'][:FIT])
    with path.open('x') as stream:
        writer=csv.writer(stream)
        writer.writerow(['sample','source_phase','source_i','source_q','rx_i','rx_q','pred_i','pred_q','error_i','error_q','amplitude_difference','phase_difference_rad'])
        for n,(y,p,e) in enumerate(zip(arrays['raw'],arrays['predicted'],arrays['error'])):
            phase=(n-report['alignment']['lag'])%PERIOD;s=arrays['source'][phase]
            angle=float(np.angle(y*p.conjugate())) if abs(p)>phase_floor and abs(y)>0 else None
            writer.writerow([n,phase,*[format(float(v),'.9g') for v in (s.real,s.imag,y.real,y.imag,p.real,p.imag,e.real,e.imag,abs(y)-abs(p))],
                             '' if angle is None else format(angle,'.9g')])


def fine_lag_diagnostic(source,raw,fit):
    """Posthoc peak interpolation; never changes alignment, prediction or raw IQ."""
    derotated=raw[:63*PERIOD]*np.exp(-2j*np.pi*fit['total_frequency_hz']*np.arange(63*PERIOD)/RATE)
    cc=abs(live.match._centered_correlations(derotated.reshape(63,PERIOD),source,all_lags=True))
    rows=[]
    for i,scores in enumerate(cc):
        k=int(scores.argmax());left,center,right=scores[(k-1)%PERIOD],scores[k],scores[(k+1)%PERIOD]
        curvature=left-2*center+right
        sub=float(.5*(left-right)/curvature) if curvature<-1e-12 else None
        delta=float((k-fit['lag']+PERIOD//2)%PERIOD-PERIOD//2+sub) if sub is not None else None
        rows.append(dict(window=i+1,time_s=(i+.5)*PERIOD/RATE,coherence=float(center),
                         interpolated_delay_change_samples=delta,usable=bool(center>=.8 and sub is not None and abs(sub)<=.5)))
    selected=[row for row in rows if row['usable']]
    result=dict(schema_id='b210_1024_posthoc_delay_interpolation_v1',rows=rows,used_windows=len(selected),
                applied_to_prediction=False,interpretation='posthoc apparent delay slope; filtering or phase distortion can also move a correlation peak')
    if len(selected)>=16:
        times=np.array([row['time_s'] for row in selected]);values=np.array([row['interpolated_delay_change_samples'] for row in selected])
        weights=np.array([row['coherence']**2 for row in selected]);design=np.column_stack((times,np.ones(len(times))))
        slope,intercept=np.linalg.lstsq(design*np.sqrt(weights[:,None]),values*np.sqrt(weights),rcond=None)[0]
        result.update(delay_slope_samples_per_second=float(slope),apparent_delay_slope_ppm=float(slope/RATE*1e6),
                      fit_rmse_samples=float(np.sqrt(np.average((values-design@[slope,intercept])**2,weights=weights))),
                      first_usable_delay_samples=selected[0]['interpolated_delay_change_samples'],
                      last_usable_delay_samples=selected[-1]['interpolated_delay_change_samples'])
    return result


def plot(report,arrays,directory):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rows=report['segments'];times=np.array([row['start'] for row in rows])/RATE*1000
    fig,axes=plt.subplots(4,1,figsize=(11,11),constrained_layout=True)
    for key,label,color in [('raw_rms','RX','#b2182b'),('predicted_rms','Fixed raw-domain prediction','#2166ac'),('residual_rms','Residual','#777777')]:
        axes[0].plot(times,[r[key] for r in rows],label=label,color=color,lw=.9)
    axes[0].axvline(FIT/RATE*1000,ls='--',color='black',label='End of parameter prefix')
    axes[0].set(xlabel='Capture time (ms)',ylabel='128-sample RMS (ADC units)');axes[0].legend()
    axes[1].plot(times,[r['local_phase_difference_rad'] for r in rows],color='#ff7f00',lw=.9)
    axes[1].set(xlabel='Capture time (ms)',ylabel='Local phase difference (rad)')
    axes[2].plot(range(PERIOD),report['boundary_diagnostic']['phase_rms'],color='#984ea3')
    axes[2].axvspan(0,16,color='gray',alpha=.2);axes[2].axvspan(1008,1023,color='gray',alpha=.2)
    axes[2].set(xlabel='Phase within repeated 1024-sample source',ylabel='Heldout residual RMS')
    lag=report['local_lag_diagnostic']
    scatter=axes[3].scatter([r['start']/RATE*1000 for r in lag],[r['delta_from_fixed_lag'] for r in lag],
                    c=[r['coherence'] for r in lag],vmin=0,vmax=1,cmap='viridis')
    axes[3].set(xlabel='Capture time (ms)',ylabel='Diagnostic lag change (samples)',title='Low-coherence lag changes do not establish sample loss')
    fig.colorbar(scatter,ax=axes[3],label='Correlation')
    for axis in axes:axis.grid(alpha=.2)
    fig.suptitle('Single 1024-sample source: raw-domain comparison, no classifier')
    fig.savefig(directory/'B210_1024_POINTWISE_OVERVIEW_2026-09-06.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(3,2,figsize=(12,8),constrained_layout=True)
    h=complex(*report['models']['scalar_robust']['coefficients'][0])
    for column,(start,title) in enumerate(((FIT,'Fixed first heldout segment'),(report['zoom_selection']['worst_heldout_segment_start'],'Largest heldout residual segment'))):
        lo=max(0,start-32);hi=min(COUNT,start+CHUNK+32);n=np.arange(lo,hi)
        source_only=h*arrays['source'][(n-report['alignment']['lag'])%PERIOD]*np.exp(2j*np.pi*report['alignment']['total_frequency_hz']*n/RATE)
        for row,component in ((0,np.real),(1,np.imag)):
            axes[row,column].plot(n,component(arrays['raw'][lo:hi]),label='RX',color='#b2182b',lw=1)
            axes[row,column].plot(n,component(arrays['predicted'][lo:hi]),label='Source through fixed channel model',color='#2166ac',lw=1)
            axes[row,column].plot(n,component(source_only),label='Source: gain/frequency only',color='#1b9e77',ls='--',lw=.9)
            axes[row,column].set_ylabel('I (ADC units)' if row==0 else 'Q (ADC units)')
        axes[0,column].set_title(title)
        axes[2,column].plot(n,abs(arrays['error'][lo:hi]),color='#555555')
        axes[2,column].set(xlabel='Absolute sample index',ylabel='Absolute complex residual')
        for row in range(3):axes[row,column].grid(alpha=.2)
    axes[0,0].legend(fontsize=8)
    fig.savefig(directory/'B210_1024_POINTWISE_ZOOM_2026-09-06.png',dpi=150);plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    modes=parser.add_mutually_exclusive_group();modes.add_argument('--seal',action='store_true');modes.add_argument('--plot',type=Path)
    modes.add_argument('--lag-supplement',action='store_true')
    args=parser.parse_args();assert args.directory==FEATURE and FEATURE.resolve()==FEATURE
    if args.seal:
        with (FEATURE/'pointwise-seal.json').open('x') as output:json.dump(inventory(FEATURE,TONE),output,indent=2);output.write('\n')
    else:
        report,arrays=run(FEATURE,TONE)
        if args.lag_supplement:
            assert report==live.document(FEATURE/'pointwise-analysis.json'),'primary analysis changed'
            result=fine_lag_diagnostic(arrays['source'],arrays['raw'],report['alignment'])
            with (FEATURE/'pointwise-lag-supplement.json').open('x') as output:json.dump(result,output,indent=2);output.write('\n')
            print(json.dumps({key:value for key,value in result.items() if key!='rows'},indent=2))
        elif args.plot:
            assert report==live.document(FEATURE/'pointwise-analysis.json'),'analysis changed'
            plot(report,arrays,args.plot)
        else:
            with (FEATURE/'pointwise-analysis.json').open('x') as output:json.dump(report,output,indent=2);output.write('\n')
            if arrays is not None:write_samples(FEATURE/'pointwise-samples.csv',report,arrays)
            print(json.dumps({key:value for key,value in report.items() if key not in ('segments','local_lag_diagnostic','stopped_controls','boundary_diagnostic')},indent=2))
