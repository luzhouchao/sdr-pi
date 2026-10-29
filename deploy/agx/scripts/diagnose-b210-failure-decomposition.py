#!/usr/bin/env python3
"""Posthoc local signal mismatch decomposition; never repairs/adopts failed inputs."""
import argparse
import importlib.util
import json
from pathlib import Path
import numpy as np

if not __debug__:raise RuntimeError('validation assertions required')
SCRIPTS=Path(__file__).parent
spec=importlib.util.spec_from_file_location('decomp_margin',SCRIPTS/'validate-b210-2455-margin.py')
margin=importlib.util.module_from_spec(spec);spec.loader.exec_module(margin)
repair,live=margin.repair,margin.live
RATE,PERIOD=2100000,1024
STARTS=np.arange(1024,63489,1024)
DELTAS=np.arange(-2000,2001,125)
ROOT=Path('/var/tmp/sdrharness-dev/b210-failure-decomp-907p')


def reference(source,frequency):
    source=np.asarray(source,dtype=np.complex128)
    if source.shape!=(PERIOD,) or not np.isfinite(source).all() or not np.isfinite(frequency):raise ValueError('finite source/frequency required')
    n=np.arange(3072);carrier=np.exp(2j*np.pi*frequency*n/RATE)
    return repair.reject(np.tile(source,3)*carrier)[1024-128:2048-128]/carrier[1024:2048]


def delayed(source,delay):
    return np.fft.ifft(np.fft.fft(source)*np.exp(-2j*np.pi*np.fft.fftfreq(PERIOD)*delay))


def projection(x,y,h=None):
    x=np.asarray(x,dtype=np.complex128);y=np.asarray(y,dtype=np.complex128)
    if x.shape!=(PERIOD,) or y.shape!=x.shape or not np.isfinite(x).all() or not np.isfinite(y).all():raise ValueError('finite 1024 pair required')
    xc=x-x.mean();yc=y-y.mean();px=float(np.vdot(xc,xc).real);py=float(np.vdot(yc,yc).real)
    if px<=1e-24 or py<=1e-24:return dict(available=False)
    dot=np.vdot(xc,yc);g=dot/px;rho=float(min(1.,abs(dot)/np.sqrt(px*py)))
    residual=yc-g*xc
    result=dict(available=True,coherence=rho,unexplained_fraction=float(np.vdot(residual,residual).real/py),
                unexplained_rms=repair.point.rms(residual),centered_rx_rms=float(np.sqrt(py/PERIOD)),
                gain=[float(g.real),float(g.imag)],mean_mismatch=[float((y.mean()-g*x.mean()).real),float((y.mean()-g*x.mean()).imag)])
    if h is not None:
        p=h*xc;initial=yc-p;angle=float(np.angle(np.vdot(p,yc)));phase_error=yc-p*np.exp(1j*angle)
        result.update(original_error_fraction=float(np.vdot(initial,initial).real/py),phase_only_error_fraction=float(np.vdot(phase_error,phase_error).real/py),
                      relative_phase_rad=float(np.angle(g/h)) if abs(h)>0 else None,
                      relative_amplitude=float(abs(g/h)) if abs(h)>0 else None,phase_display_eligible=bool(rho>=.9))
    return result


def guard_rms(raw):
    v=np.asarray(raw,dtype=np.complex128)
    if v.shape!=(PERIOD,) or not np.isfinite(v).all():raise ValueError('finite raw block required')
    window=np.hanning(PERIOD);freq=np.fft.fftfreq(PERIOD,1/RATE)
    power=abs(np.fft.fft(v*window))**2
    return float(np.sqrt(power[(abs(freq)>=350000)&(abs(freq)<=700000)].sum()/(PERIOD*np.sum(window**2))))


def search_blocks(source,windows,center):
    windows=np.asarray(windows,dtype=np.complex128)
    if windows.ndim!=2 or windows.shape[1]!=PERIOD or not np.isfinite(windows).all() or not np.isfinite(center):raise ValueError('finite complete blocks required')
    n=np.arange(PERIOD);best=[None]*len(windows)
    for delta in DELTAS:
        f=float(center+delta);ref=reference(source,f)
        y=windows*np.exp(-2j*np.pi*f*n/RATE)
        cc=live.match._centered_correlations(y,ref,all_lags=True)
        lags=np.argmax(abs(cc),axis=1)
        for i,lag in enumerate(lags):
            score=float(abs(cc[i,lag]))
            if best[i] is None or score>best[i]['coherence']:
                best[i]=dict(coherence=score,frequency_hz=f,integer_lag=int(lag))
    for i,row in enumerate(best):
        ref=reference(source,row['frequency_hz']);y=windows[i]*np.exp(-2j*np.pi*row['frequency_hz']*n/RATE)
        candidates=[]
        for fraction in np.arange(-.5,.501,.125):
            delay=float(row['integer_lag']+fraction);metrics=projection(delayed(ref,delay),y)
            if metrics['available']:candidates.append((metrics['coherence'],delay,metrics))
        if not candidates:
            row.update(available=False,high_coherence=False);continue
        score,delay,metrics=max(candidates,key=lambda v:v[0])
        row.update(available=True,coherence=score,delay_samples=delay%PERIOD,unexplained_fraction=metrics['unexplained_fraction'],
                   unexplained_rms=metrics['unexplained_rms'],high_coherence=bool(score>=.9),frequency_delta_hz=row['frequency_hz']-center)
    return best


def characterize(source,raw,center,fit=None,h=None):
    raw=np.asarray(raw,dtype=np.complex128)
    if raw.shape!=(65535,) or not np.isfinite(raw).all():raise ValueError('complete finite raw capture required')
    filtered=repair.reject(raw);windows=np.array([filtered[k-128:k+1024-128] for k in STARTS])
    searches=search_blocks(source,windows,center);rows=[]
    ref=reference(source,center)
    for i,start in enumerate(STARTS):
        row=dict(raw_start=int(start),samples=PERIOD,in_original_model_block=bool(32768<=start<36864),
                 guard_rms=guard_rms(raw[start:start+1024]),filtered_rms=repair.point.rms(windows[i]),search=searches[i])
        if fit is not None:
            y=windows[i]*np.exp(-2j*np.pi*center*np.arange(start,start+PERIOD)/RATE)
            row['fixed']=projection(np.roll(ref,fit['lag']),y,h)
        rows.append(row)
    x=np.array([r['guard_rms'] for r in rows]);y=np.array([r['search'].get('unexplained_rms',0.) for r in rows])
    valid=(x>0)&(y>0)
    correlation=None
    if valid.sum()>2 and np.std(np.log10(x[valid]))>1e-12 and np.std(np.log10(y[valid]))>1e-12:
        correlation=float(np.corrcoef(np.log10(x[valid]),np.log10(y[valid]))[0,1])
    return dict(rows=rows,search_high_coherence_blocks=sum(r['search']['high_coherence'] for r in rows),
                guard_vs_unexplained_log_correlation=correlation,guard_rms_p50=float(np.median(x)),guard_rms_max=float(x.max()))


def analyze():
    margin.verify_retained()
    original=live.document(live.affine.ROOT/'docs/evidence/B210_2455_MARGIN_AUDIT_2026-09-07.json')
    report=dict(schema_id='b210_posthoc_failure_decomposition_v1',analysis_numpy=np.__version__,posthoc=True,
                original_gate_changes=False,model_windows=0,rf_operations=0,independent_labels=0,recognizer_available=False,
                block_starts=STARTS.tolist(),block_samples=1024,cfo_deltas_hz=DELTAS.tolist(),fractional_step_samples=.125,
                parent_audit_sha256=margin.lo.hashlib.sha256(live.read(live.affine.ROOT/'docs/evidence/B210_2455_MARGIN_AUDIT_2026-09-07.json')).hexdigest(),cases={})
    for tag,_ in margin.CASES:
        v=np.frombuffer(live.read(margin.feature(tag)/'train-tile.fc32'),dtype='<f4').reshape(PERIOD,2);source=v[:,0].astype(float)+1j*v[:,1].astype(float)
        case=original['cases'][tag];fit=case['pointwise']['alignment'];usable=fit['usable']
        center=fit['total_frequency_hz'] if usable else original['tone']['frequency_difference_hz']
        h=complex(*case['pointwise']['models']['scalar_robust']['coefficients'][0]) if usable else None
        report['cases'][tag]=dict(original_model_control_passed=case['model_control_passed'],original_alignment_usable=usable,
                                 center_frequency_hz=center,center_basis='original prefix' if usable else 'independent tone',captures={})
        for phase in ('baseline','during-tx','after-tx'):
            raw=live.match.read_iq(margin.feature(tag),phase)[0]
            report['cases'][tag]['captures'][phase]=characterize(source,raw,center,fit if usable else None,h)
    return report


def plot(report,destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,4,figsize=(16,8),constrained_layout=True)
    for col,(tag,case) in enumerate(report['cases'].items()):
        rows=case['captures']['during-tx']['rows'];t=np.array([r['raw_start'] for r in rows])/RATE*1000
        axes[0,col].plot(t,[r['search']['coherence'] for r in rows],label='Local frequency/delay search',color='#2166ac')
        if case['original_alignment_usable']:axes[0,col].plot(t,[r['fixed'].get('coherence',0) for r in rows],label='Original frequency/delay',color='#b2182b')
        axes[0,col].axhline(.9,color='gray',ls=':');axes[0,col].set(ylim=(0,1.05),title=tag,ylabel='Source-coordinate centered correlation',xlabel='Capture time (ms)')
        axes[1,col].plot(t,[r['guard_rms'] for r in rows],label='Raw 350–700 kHz guard',color='#984ea3')
        axes[1,col].plot(t,[r['search'].get('unexplained_rms',0) for r in rows],label='Unexplained in-band RMS after search',color='#555555')
        axes[1,col].set(ylabel='ADC RMS',xlabel='Capture time (ms)')
        for axis in axes[:,col]:axis.axvspan(32768/RATE*1000,36864/RATE*1000,color='gray',alpha=.15);axis.grid(alpha=.2);axis.legend(fontsize=7)
    fig.suptitle('Posthoc explanation only: original gates unchanged; no new classifier or RF')
    fig.savefig(destination,dpi=150);plt.close(fig)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--analyze',action='store_true');g.add_argument('--plot',type=Path);g.add_argument('--verify',action='store_true');a=p.parse_args()
    if a.analyze:margin.lo.save(ROOT/'analysis.json',analyze())
    elif a.plot:plot(live.document(ROOT/'analysis.json'),a.plot)
    else:
        current=analyze();saved=live.document(live.affine.ROOT/'docs/evidence/B210_FAILURE_DECOMPOSITION_AUDIT_2026-09-07.json')
        assert all(saved[k]==v for k,v in current.items());print('Posthoc diagnostic reproduced; original gates/IQ/model outputs unchanged.')
