"""Independent oversampled synthesis, interpolation fidelity, and pilot holdout."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_campaign as c
import rml2018a_pilot_timing as t
import rml2018a_lo_cancellation as lo


def capture(delay=.3,ppm=-2.,seed=14):
    rng=np.random.default_rng(seed);run='0123456789abcdef'*2;batch=4267
    N=24*1024;f=np.fft.fftfreq(N);s=rng.normal(size=N)+1j*rng.normal(size=N);s[abs(f)>.08]=0
    z=np.fft.ifft(s);z=.5*z/max(abs(z));iq=np.stack((z.real,z.imag),axis=-1).reshape(24,1024,2)
    frame,_=c.packet(iq,run,batch,level_profile='gain-pair-pilot');size=len(frame);os=16
    # Fourier interpolation at16x followed by linear evaluation is independent
    # of the receiver's129-tap sinc, and models modest analog bandwidth.
    spectrum=np.fft.fft(frame);freq=np.fft.fftfreq(size);spectrum*=np.exp(-(abs(freq)/.36)**12)
    padded=np.zeros(size*os,complex);padded[:size//2]=spectrum[:size//2];padded[-size//2:]=spectrum[size//2:]
    high=np.fft.ifft(padded)*os;high=np.r_[high,high[0]]
    offset=2000;n=np.arange(c.RX_SAMPLES);tau=delay+ppm*1e-6*n
    position=((n-offset-tau)%size)*os
    raw=np.interp(position,np.arange(len(high)),high.real)+1j*np.interp(position,np.arange(len(high)),high.imag)
    raw*=np.exp(2j*np.pi*3800*n/c.RATE+.3j)
    sync=dict(payload_marker_offset=offset+c.GUARD,estimated_cfo_hz=3800.,phase_rotation_rad=-.3)
    clean=np.tile(frame,3)[c.GUARD+c.MARKER:c.GUARD+c.MARKER+N].reshape(24,1024)
    return raw,sync,run,batch,clean


class TimingTests(unittest.TestCase):
    def test_independent_fractional_delay_and_drift(self):
        for delay,ppm in ((-.3,-2.),(.3,-2.),(.1,2.)):
            raw,sync,run,batch,x=capture(delay,ppm);before=raw.copy()
            y,info=t.correct(raw,sync,run,batch)
            self.assertEqual(info['status'],'applied',info)
            self.assertAlmostEqual(info['drift_ppm'],ppm,delta=.8)
            original=lo.payload(raw,sync)
            self.assertLess(np.mean(abs(y-x)**2),np.mean(abs(original-x)**2)/4)
            np.testing.assert_array_equal(raw,before)

    def test_no_payload_access_for_estimation(self):
        raw,sync,run,batch,_=capture();_,a=t.correct(raw,sync,run,batch);changed=raw.copy()
        frame=2*c.GUARD+c.MARKER+24*1024
        for at in range(sync['payload_marker_offset'],len(raw),frame):
            changed[at+c.MARKER+128:min(at+c.MARKER+24*1024-128,len(raw))]+=30j
        _,b=t.correct(changed,sync,run,batch)
        for key in ('pilots','drift_ppm','offset_samples','maximum_validation_error_samples'):
            self.assertEqual(a[key],b[key])

    def test_missing_and_out_of_range_pilots_leave_payload_unchanged(self):
        for delay,ppm in ((.9,0.),(.1,30.)):
            raw,sync,run,batch,_=capture(delay,ppm);out,info=t.correct(raw,sync,run,batch)
            self.assertEqual(info['status'],'skipped',info)
            np.testing.assert_array_equal(out,lo.payload(raw,sync))
        raw,sync,run,batch,_=capture();out,info=t.correct(raw*0,sync,run,batch)
        self.assertEqual(info['status'],'skipped')

    def test_passband_and_white_noise_power(self):
        n=np.arange(32768);coords=np.arange(128,24704)+.5
        for f in (-.083,0.,.083):
            out=t.sample(np.exp(2j*np.pi*f*n),coords)
            self.assertLess(float(np.mean(abs(out-np.exp(2j*np.pi*f*coords))**2)),1e-8)
        rng=np.random.default_rng(67);noise=rng.normal(size=len(n))+1j*rng.normal(size=len(n))
        ratio=np.mean(abs(t.sample(noise,coords))**2)/np.mean(abs(noise[128:24704])**2)
        self.assertLess(abs(10*np.log10(ratio)),.1)
        with self.assertRaises(ValueError):t.sample(noise,np.arange(10))


if __name__=='__main__':unittest.main()
