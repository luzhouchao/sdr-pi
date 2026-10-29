"""Forward error attribution only. Fitted source X never becomes model input.

All variants are fixed before evaluation. Half-window held-out error is kept
separate from received SINR and does not uniquely identify physical hardware.
"""
import numpy as np

import rml2018a_campaign as c

METHOD = 'post-guard-lo-forward-error-crossfit-v1'
TAGS = ('scalar','timing','time_gain','rx_image','tx_image','rx_dc','cubic','fir5','combined')


def contract():
    return dict(method=METHOD, source_assisted=True, receiver_correction=False,
        model_inference=False, rx_sinr_db=None,
        target='held-out forward-model residual power; not corrected receiver SINR',
        variants=list(TAGS), folds='train first512, evaluate last512; reverse; keep both',
        centered_fit=True, evaluation_includes_source_dc=True,
        least_squares_rcond=1e-6, maximum_normalized_condition=1e6,
        meaningful_error_reduction_db=3,
        timing='x + ideal bandlimited dx/dn; real negative derivative/gain ratio estimates small delay',
        time_gain='complex linear time*x; includes amplitude slope and linearized CFO',
        rx_image='conjugate x rotated by -2*original CFO after carrier correction',
        tx_image='conjugate x rotated by +500kHz, reflection about TX LO+250kHz',
        rx_dc='native receiver DC rotated by -original CFO',
        cubic='x*abs(x)^2',fir5='source shifts -2,-1,0,+1,+2, fixed length',
        combined='x + derivative + time_gain + RX/TX mirrors + RX DC + cubic',
        timing_trend='first12 row estimates predict last12; report all24 diagnostic estimates separately',
        pilot='known marker only, matched500kHz129-tap FIR and derivative; no payload X',
        caveats=['source-assisted fits are not deployable compensation or independent accuracy',
            'timing, channel group delay and frequency response can be confounded',
            'guard residual includes prediction error/spurs and is not calibrated thermal noise',
            'two classes, one cable setting, original source Z30 only'])


def matrices(shifts, derivative, indices, cfo_hz):
    shifts=np.asarray(shifts,dtype=np.complex128);derivative=np.asarray(derivative,dtype=np.complex128)
    c.require(shifts.shape==(1024,5) and derivative.shape==(1024,), 'diagnostic source shape')
    indices=np.asarray(indices)
    c.require(indices.shape==(1024,) and np.isfinite(indices).all() and np.isfinite(cfo_hz), 'sample coordinates')
    x=shifts[:,2];t=(np.arange(1024)-511.5)/512
    extra=dict(timing=derivative,time_gain=1j*t*x,
        rx_image=x.conj()*np.exp(-4j*np.pi*cfo_hz*indices/c.RATE),
        tx_image=x.conj()*np.exp(4j*np.pi*250000*indices/c.RATE),
        rx_dc=np.exp(-2j*np.pi*cfo_hz*indices/c.RATE),cubic=x*abs(x)**2)
    out={'scalar':x[:,None]}
    out.update({k:np.column_stack((x,v)) for k,v in extra.items()})
    out.update(fir5=shifts,combined=np.column_stack((x,*extra.values())))
    return out


def crossfit(design, received):
    X=np.asarray(design,dtype=np.complex128);y=np.asarray(received,dtype=np.complex128)
    c.require(X.ndim==2 and X.shape[0]==1024 and 1<=X.shape[1]<=8 and y.shape==(1024,) and
        np.isfinite(X).all() and np.isfinite(y).all(), 'finite diagnostic inputs')
    folds=[]
    for train,test in ((slice(0,512),slice(512,1024)),(slice(512,1024),slice(0,512))):
        A=X[train]-X[train].mean(axis=0);b=y[train]-y[train].mean()
        scale=np.sqrt(np.mean(abs(A)**2,axis=0))
        if np.any(scale<1e-12):
            folds.append(dict(status='invalid',reason='unidentifiable_centered_column'));continue
        beta,_,rank,singular=np.linalg.lstsq(A/scale,b,rcond=1e-6)
        condition=float(singular[0]/singular[-1]) if singular[-1]>0 else None
        if rank<X.shape[1] or condition is None or condition>1e6:
            folds.append(dict(status='invalid',reason='rank_or_condition',rank=int(rank),condition=condition));continue
        beta/=scale;prediction=X[test]@beta
        folds.append(dict(status='estimated',error_power_counts2=float(np.mean(abs(y[test]-prediction)**2)),
            predicted_power_counts2=float(np.mean(abs(prediction)**2)),rank=int(rank),condition=condition,
            coefficients=[[float(v.real),float(v.imag)] for v in beta]))
    ok=all(v['status']=='estimated' for v in folds)
    return dict(status='estimated' if ok else 'invalid',folds=folds,
        error_power_counts2=float(np.mean([v['error_power_counts2'] for v in folds])) if ok else None)


def evaluate(shifts, derivative, received, indices, cfo_hz):
    designs=matrices(shifts,derivative,indices,cfo_hz)
    results={tag:crossfit(designs[tag],received) for tag in TAGS}
    baseline=results['scalar']['error_power_counts2']
    for result in results.values():
        error=result['error_power_counts2']
        result['error_reduction_db']=(float(10*np.log10(baseline/error))
            if baseline is not None and baseline>0 and error is not None and error>0 else None)
    timing=results['timing'];delays=[]
    if timing['status']=='estimated':
        for fold in timing['folds']:
            b=[complex(*v) for v in fold['coefficients']]
            if abs(b[0])>1e-12:delays.append(float(-(b[1]/b[0]).real))
    return dict(variants=results,delay_samples=float(np.mean(delays)) if len(delays)==2 else None,
        delay_fold_difference_samples=abs(delays[0]-delays[1]) if len(delays)==2 else None)


def trends(rows):
    c.require(len(rows)==24,'fixed24-row trend')
    delays=[r['delay_samples'] for r in rows]
    if any(v is None for v in delays):return dict(status='invalid',reason='missing_delay_estimates')
    n=np.arange(24)*1024+511.5;y=np.array(delays)
    slope,offset=np.polyfit(n,y,1)
    train_slope,train_offset=np.polyfit(n[:12],y[:12],1)
    heldout=y[12:]-(train_slope*n[12:]+train_offset)
    coefficients=[np.mean([complex(*f['coefficients'][0]) for f in r['variants']['scalar']['folds']]) for r in rows]
    phase=np.unwrap(np.angle(coefficients));phase_slope,phase_offset=np.polyfit(n,phase,1)
    return dict(status='estimated',median_delay_samples=float(np.median(y)),
        all_rows_delay_slope_ppm=float(slope*1e6),all_rows_delay_intercept_samples=float(offset),
        all_rows_delay_trend_rms_samples=float(np.sqrt(np.mean((y-(slope*n+offset))**2))),
        first12_slope_ppm=float(train_slope*1e6),first12_intercept_samples=float(train_offset),
        last12_prediction_rms_samples=float(np.sqrt(np.mean(heldout**2))),
        all_rows_residual_cfo_hz=float(phase_slope*c.RATE/(2*np.pi)),
        all_rows_phase_trend_rms_rad=float(np.sqrt(np.mean((phase-(phase_slope*n+phase_offset))**2))),
        physical_clock_attribution='consistent timing drift; clock error and channel/timing fit bias not independently separated')


def pilot_timing(corrected, sync, run_id, batch):
    """Known pilot observation only; this function never receives source payload."""
    z=np.asarray(corrected,dtype=np.complex128)
    c.require(z.shape==(c.RX_SAMPLES,) and np.isfinite(z).all(),'pilot capture shape')
    n=np.arange(len(z));hz=sync['estimated_cfo_hz']
    taps=np.arange(129)-64;fir=(2*500000/c.RATE)*np.sinc(2*500000/c.RATE*taps)*np.hamming(129);fir/=fir.sum()
    z=np.convolve(z*np.exp(-2j*np.pi*hz*n/c.RATE+1j*sync['phase_rotation_rad']),fir,mode='same')
    ref=np.convolve(np.tile(c.marker(run_id,batch),3),fir,mode='same')[1024:2048]
    dx=np.fft.ifft(np.fft.fft(ref)*(2j*np.pi*np.fft.fftfreq(1024)))
    X=np.column_stack((ref,dx));frame=2*c.GUARD+c.MARKER+24*1024;rows=[]
    for at in range(sync['payload_marker_offset']%frame,len(z)-c.MARKER+1,frame):
        ix=np.arange(64,960);y=z[at:at+c.MARKER]
        beta,_,rank,s=np.linalg.lstsq(X[ix],y[ix],rcond=1e-6)
        if rank<2 or abs(beta[0])<1e-12:
            rows.append(dict(marker_offset=at,status='invalid'));continue
        ratio=-beta[1]/beta[0]
        rows.append(dict(marker_offset=at,status='estimated',delay_samples=float(ratio.real),
            quadrature_derivative_ratio=float(ratio.imag),condition=float(s[0]/s[-1]),
            residual_fraction=float(np.mean(abs(y[ix]-X[ix]@beta)**2)/max(np.mean(abs(y[ix])**2),1e-30))))
    valid=[v for v in rows if v['status']=='estimated']
    if len(valid)<2:return dict(status='invalid',pilots=rows)
    slope,offset=np.polyfit([v['marker_offset']+511.5 for v in valid],[v['delay_samples'] for v in valid],1)
    targets=sync['payload_marker_offset']+c.MARKER+np.arange(24)*1024+511.5
    return dict(status='estimated',pilots=rows,source_payload_used=False,
        delay_slope_ppm=float(slope*1e6),predicted_payload_delays_samples=(offset+slope*targets).tolist(),
        receiver_correction=False)
