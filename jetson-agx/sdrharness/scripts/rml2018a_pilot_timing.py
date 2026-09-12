"""Bounded, pilot-only fractional timing correction after guard LO cancellation."""
import numpy as np
import rml2018a_campaign as c
import rml2018a_lo_cancellation as lo

METHOD='known-pilot-fractional-timing-v1'
PLANE='received_payload_after_guard_lo_and_pilot_timing_before_rms'


def contract():
    return dict(method=METHOD,source_payload_used=False,labels_used=False,
        fit='first pilot half[64:448], centered reference+bandlimited derivative',
        validation='second half[576:960], never refit',minimum_pilots=2,
        maximum_abs_delay_samples=.6,maximum_abs_drift_ppm=10,
        maximum_fit_rms_samples=.04,maximum_validation_error_samples=.08,
        maximum_pilot_residual_fraction=.03,maximum_quadrature_derivative_ratio=.08,
        interpolation='129-tap Kaiser8 windowed sinc; normalized DC; symmetric64-sample halo',
        interpolation_noise_gain='finite interpolator not exactly allpass; whitenoise/occupied-band tests required',
        failure_action='unchanged LO-cancelled payload with reason',
        sinr='separate post-timing conditional estimate, not calibrated physical RF SINR')


def sample(z, coordinates):
    """Finite bandlimited interpolation, no FFT wrap or row-edge padding."""
    z=np.asarray(z,dtype=np.complex128);coordinates=np.asarray(coordinates,dtype=float)
    c.require(z.ndim==coordinates.ndim==1 and np.isfinite(z).all() and np.isfinite(coordinates).all(),'finite interpolation')
    nearest=np.floor(coordinates+.5).astype(int)
    c.require(len(coordinates)<=24*1024 and np.all(nearest>=64) and np.all(nearest+64<len(z)),'interpolation halos/budget')
    out=np.empty(len(coordinates),complex);offset=np.arange(-64,65);window=np.kaiser(129,8)
    for start in range(0,len(out),512):
        end=min(start+512,len(out));ix=nearest[start:end,None]+offset
        weights=np.sinc(coordinates[start:end,None]-ix)*window
        weights/=weights.sum(axis=1,keepdims=True)
        out[start:end]=(z[ix]*weights).sum(axis=1)
    return out


def correct(raw, sync, run_id, batch):
    z=np.asarray(raw,dtype=np.complex128)
    c.require(z.shape==(c.RX_SAMPLES,) and np.isfinite(z).all(),'native timing input')
    baseline=lo.payload(z,sync);info=dict(method=METHOD,status='skipped',reason=None,contract=contract(),pilots=[])
    def skip(reason):info['reason']=reason;return baseline.copy(),info
    n=np.arange(len(z));hz=sync['estimated_cfo_hz']
    c.require(np.isfinite(hz) and abs(hz)<=c.CFO_LIMIT_HZ,'pilot CFO')
    rotated=z*np.exp(-2j*np.pi*hz*n/c.RATE+1j*sync['phase_rotation_rad'])
    taps=np.arange(129)-64;fir=(2*500000/c.RATE)*np.sinc(2*500000/c.RATE*taps)*np.hamming(129);fir/=fir.sum()
    detected=np.convolve(rotated,fir,mode='same')
    ref=np.convolve(np.tile(c.marker(run_id,batch),3),fir,mode='same')[1024:2048]
    dx=np.fft.ifft(np.fft.fft(ref)*2j*np.pi*np.fft.fftfreq(1024))
    X=np.column_stack((ref,dx));frame=2*c.GUARD+c.MARKER+24*1024
    for at in range(sync['payload_marker_offset']%frame,len(z)-c.MARKER+1,frame):
        halves=[]
        for left,right in ((64,448),(576,960)):
            A=X[left:right];y=detected[at+left:at+right]
            coef,_,rank,_=np.linalg.lstsq(A-A.mean(axis=0),y-y.mean(),rcond=1e-6)
            if rank<2 or abs(coef[0])<1e-12:return skip('pilot_not_identifiable')
            ratio=-coef[1]/coef[0]
            residual=float(np.mean(abs(y-A@coef)**2)/max(np.mean(abs(y)**2),1e-30))
            halves.append(dict(time_sample=float(at+(left+right-1)/2),delay_samples=float(ratio.real),
                quadrature_ratio=float(ratio.imag),residual_fraction=residual))
        info['pilots'].append(dict(marker_offset=at,training=halves[0],validation=halves[1]))
    if len(info['pilots'])<2:return skip('insufficient_complete_pilots')
    measurements=[v[half] for v in info['pilots'] for half in ('training','validation')]
    if any(v['residual_fraction']>.03 or abs(v['quadrature_ratio'])>.08 for v in measurements):
        return skip('pilot_fit_quality')
    train=[v['training'] for v in info['pilots']];test=[v['validation'] for v in info['pilots']]
    times=np.array([v['time_sample'] for v in train]);delays=np.array([v['delay_samples'] for v in train])
    slope,offset=np.polyfit(times,delays,1)
    fit_rms=float(np.sqrt(np.mean((delays-(slope*times+offset))**2)))
    errors=np.array([v['delay_samples']-(slope*v['time_sample']+offset) for v in test])
    start=sync['payload_marker_offset']+c.MARKER;targets=start+np.arange(24*1024)
    tau=offset+slope*targets
    info.update(drift_ppm=float(slope*1e6),offset_samples=float(offset),fit_rms_samples=fit_rms,
        maximum_validation_error_samples=float(max(abs(errors))),
        payload_delay_first_samples=float(tau[0]),payload_delay_last_samples=float(tau[-1]))
    if abs(slope*1e6)>10 or max(abs(tau))>.6:return skip('timing_outside_registered_range')
    if fit_rms>.04 or max(abs(errors))>.08:return skip('timing_not_predictable_on_heldout_pilot')
    coords=targets+tau/(1-slope)
    try:out=sample(rotated,coords).reshape(24,1024)
    except ValueError:return skip('missing_interpolation_halo')
    info.update(status='applied',output_sha256=c.digest(out.astype('<c16').tobytes()))
    return out,info


def quality(reference, received, source_z, info):
    q=c.receive_quality('synchronized',reference,received,source_z);c.validate_receive_quality(q,source_z)
    q.update(rx_sinr_reference_plane=PLANE,rx_timing_correction=METHOD if info['status']=='applied' else 'none_skipped',
        rx_payload_filter='129-tap Kaiser8 sinc interpolator' if info['status']=='applied' else 'none')
    return q
