"""Known-component tests for attribution and source-independent pilot timing."""
import json
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_campaign as c
import rml2018a_link_diagnostics as d


def source(seed=6):
    rng=np.random.default_rng(seed);f=np.fft.fftfreq(1024)
    spec=rng.normal(size=1024)+1j*rng.normal(size=1024)
    spec[abs(f)>.085]=0
    x=np.fft.ifft(spec);x/=np.sqrt(np.mean(abs(x)**2))
    dx=np.fft.ifft(np.fft.fft(x)*2j*np.pi*f)
    return np.column_stack([np.roll(x,k) for k in range(-2,3)]),dx


class DiagnosticsTests(unittest.TestCase):
    def test_known_timing_error_explained_on_heldout_samples(self):
        for seed in range(5):
            shifts,dx=source(seed);x=shifts[:,2];rng=np.random.default_rng(100+seed)
            noise=.01*(rng.normal(size=1024)+1j*rng.normal(size=1024))
            result=d.evaluate(shifts,dx,(2+.4j)*(x-.31*dx)+noise,np.arange(1024),3800.)
            self.assertAlmostEqual(result['delay_samples'],.31,delta=.006)
            self.assertGreater(result['variants']['timing']['error_reduction_db'],20)
            self.assertLess(result['variants']['timing']['error_power_counts2'],.00026)
            self.assertEqual(result,json.loads(json.dumps(result,allow_nan=False)))

    def test_receive_and_transmit_images_are_different_observables(self):
        shifts,dx=source();n=np.arange(1024)+10000;X=d.matrices(shifts,dx,n,3800.)
        for tag in ('rx_image','tx_image','rx_dc','cubic'):
            noise=.005*np.exp(2j*np.pi*.43*np.arange(1024))
            y=2*shifts[:,2]+.12*X[tag][:,1]+noise
            result=d.evaluate(shifts,dx,y,n,3800.)['variants']
            self.assertGreater(result[tag]['error_reduction_db'],15,tag)
            if tag=='tx_image':self.assertLess(result['rx_image']['error_reduction_db'],1)

    def test_complex_dc_is_not_silently_removed(self):
        shifts,dx=source();y=2*shifts[:,2]+.2j
        result=d.crossfit(shifts[:,2,None],y)
        self.assertAlmostEqual(result['error_power_counts2'],.04,places=10)

    def test_rank_failures_and_nonfinite_inputs_retained_or_rejected(self):
        x=np.exp(2j*np.pi*np.arange(1024)/16)
        result=d.crossfit(np.column_stack((x,x)),x)
        self.assertEqual(result['status'],'invalid');self.assertIsNone(result['error_power_counts2'])
        self.assertEqual(len(result['folds']),2)
        with self.assertRaises(ValueError):d.crossfit(x[:,None],x*np.nan)

    def test_white_noise_not_explained_by_extra_parameters(self):
        values=[]
        for seed in range(10):
            shifts,dx=source(seed);rng=np.random.default_rng(77+seed)
            y=2*shifts[:,2]+.2*(rng.normal(size=1024)+1j*rng.normal(size=1024))
            result=d.evaluate(shifts,dx,y,np.arange(1024),3800.)
            values.append(result['variants']['combined']['error_reduction_db'])
        self.assertLess(float(np.median(values)),.15)

    def test_pilot_observation_does_not_use_payload(self):
        rng=np.random.default_rng(72);run='abcdef0123456789'*2;index=4267
        frame,_=c.packet(rng.normal(size=(24,1024,2)),run,index,level_profile='gain-pair-pilot')
        raw=np.tile(frame,3)[:c.RX_SAMPLES].astype(complex)
        # The ideal bandlimited derivative is a controlled small-delay model.
        deriv=np.fft.ifft(np.fft.fft(frame)*2j*np.pi*np.fft.fftfreq(len(frame)))
        raw-=.15*np.tile(deriv,3)[:len(raw)]
        sync=dict(payload_marker_offset=c.GUARD,estimated_cfo_hz=0.,phase_rotation_rad=0.)
        first=d.pilot_timing(raw,sync,run,index)
        self.assertEqual(first['status'],'estimated')
        self.assertTrue(all(abs(v['delay_samples']-.15)<.01 for v in first['pilots']))
        changed=raw.copy()
        for at in range(c.GUARD,len(raw)-1024+1,len(frame)):
            changed[at+1024+128:min(at+1024+24*1024-128,len(raw))]+=100j
        self.assertEqual(first,d.pilot_timing(changed,sync,run,index))


if __name__=='__main__':unittest.main()
