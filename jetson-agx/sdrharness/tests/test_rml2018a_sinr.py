"""Known-component simulation, independent of RF and model predictions."""
import json
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_campaign as c


def unit_noise(rng):
    z=rng.normal(size=1024)+1j*rng.normal(size=1024)
    return z/np.sqrt(np.mean(abs(z)**2))


class SinrTests(unittest.TestCase):
    def test_known_source_noise_plus_awgn_and_tone(self):
        rng=np.random.default_rng(9921)
        errors=[]
        for source_db in (-20,0,10,30):
            for link_db in (0,10,20):
                for trial in range(20):
                    clean=rng.choice([-1.,1.],1024)+1j*rng.choice([-1.,1.],1024)
                    clean/=np.sqrt(2)
                    source_noise=unit_noise(rng)*10**(-source_db/20)
                    x=clean+source_noise;gain=1.7*np.exp(.7j)
                    # Test additional noise and a narrowband interferer, not only AWGN.
                    disturbance=unit_noise(rng)+np.exp(2j*np.pi*.271*np.arange(1024)+.3j)
                    disturbance*=np.sqrt(np.mean(abs(gain*x)**2)/10**(link_db/10)/np.mean(abs(disturbance)**2))
                    y=gain*x+disturbance
                    result=c.receive_quality('synchronized',x,y,source_db)
                    self.assertEqual(result['rx_sinr_status'],'estimated',result)
                    actual=10*np.log10(np.mean(abs(gain*clean)**2)/
                        np.mean(abs(gain*source_noise+disturbance)**2))
                    errors.append(result['rx_sinr_db']-actual)
                    self.assertLessEqual(result['rx_sinr_db'],source_db+1e-9)
                    c.validate_receive_quality(result,source_db)
        self.assertLess(abs(float(np.mean(errors))),.15)
        self.assertLess(float(np.quantile(abs(np.array(errors)),.95)),.6)
        print(json.dumps(dict(simulation_trials=len(errors),mean_error_db=float(np.mean(errors)),
            p95_absolute_error_db=float(np.quantile(abs(np.array(errors)),.95)),
            maximum_absolute_error_db=float(max(abs(np.array(errors)))))))

    def test_no_added_error_returns_nominal_source_ceiling_not_infinity(self):
        rng=np.random.default_rng(14);x=unit_noise(rng)
        for db in (-20,0,30):
            q=c.receive_quality('synchronized',x,x*(2+.7j),db)
            self.assertEqual(q['rx_sinr_status'],'estimated')
            self.assertAlmostEqual(q['rx_sinr_db'],db,places=8)
            json.dumps(q,allow_nan=False)

    def test_weak_link_retains_rejections_and_reports_conditional_error(self):
        # Covers the roughly -9dB link regime seen in the finite RF validation.
        rng=np.random.default_rng(663);errors=[];invalid=0
        for _ in range(200):
            clean=(rng.choice([-1.,1.],1024)+1j*rng.choice([-1.,1.],1024))/np.sqrt(2)
            noise=unit_noise(rng)*np.sqrt(.001);x=clean+noise
            disturbance=rng.normal(size=1024)+1j*rng.normal(size=1024)+np.exp(2j*np.pi*.271*np.arange(1024))
            disturbance*=np.sqrt(np.mean(abs(x)**2)/10**(-9/10)/np.mean(abs(disturbance)**2))
            q=c.receive_quality('synchronized',x,x+disturbance,30)
            if q['rx_sinr_status']=='estimated':
                errors.append(q['rx_sinr_db']-10*np.log10(1/np.mean(abs(noise+disturbance)**2)))
            else:invalid+=1
        self.assertEqual(len(errors)+invalid,200)
        self.assertGreater(len(errors),0);self.assertGreater(invalid,0)
        self.assertLess(float(np.quantile(abs(np.array(errors)),.95)),2.)

    def test_gain_changes_bursts_and_constant_reference_are_invalid(self):
        rng=np.random.default_rng(31);x=unit_noise(rng)
        cases=[(x,np.r_[x[:512],3*x[512:]],'gain_not_stable_across_halves'),
            (x,x+np.r_[.01*unit_noise(rng)[:512],unit_noise(rng)[512:]],'residual_not_stationary_across_halves'),
            (np.ones(1024),np.ones(1024),'reference_not_identifiable'),
            (x,np.zeros(1024),'zero_reference_or_receive_power')]
        for ref,rx,reason in cases:
            q=c.receive_quality('synchronized',ref,rx,30)
            self.assertEqual(q['rx_sinr_status'],'invalid')
            self.assertEqual(q['rx_sinr_reason'],reason)
            self.assertIsNone(q['rx_sinr_db'])

    def test_dc_interference_is_counted_without_removing_legitimate_source_dc(self):
        x=np.tile(np.array([0.,1.]),512).astype(complex)
        q=c.receive_quality('synchronized',x,2*x+.1j,30)
        self.assertEqual(q['rx_sinr_status'],'estimated')
        d=q['rx_sinr_diagnostics']
        self.assertAlmostEqual(d['link_error_power_relative']*d['received_power_adc_squared'],.01)
        self.assertAlmostEqual(d['predicted_reference_power_relative']*d['received_power_adc_squared'],2.)

    def test_scale_phase_invariance_and_no_input_mutation(self):
        rng=np.random.default_rng(91);x=unit_noise(rng);y=x+.2*unit_noise(rng)
        before=(x.copy(),y.copy())
        a=c.receive_quality('synchronized',x,y,10)
        b=c.receive_quality('synchronized',x*7*np.exp(.7j),y*.03*np.exp(-.2j),10)
        self.assertAlmostEqual(a['rx_sinr_db'],b['rx_sinr_db'],places=9)
        np.testing.assert_array_equal(x,before[0]);np.testing.assert_array_equal(y,before[1])

    def test_invalid_input_and_tampered_power_accounting(self):
        x=np.exp(2j*np.pi*np.arange(1024)/16)
        for ref,rx,db in ((x[:-1],x,30),(x,x*np.nan,30),(x,x,31)):
            with self.assertRaises(ValueError):c.receive_quality('synchronized',ref,rx,db)
        q=c.receive_quality('synchronized',x,2*x+.1,30)
        q['rx_sinr_db']=30
        with self.assertRaises(ValueError):c.validate_receive_quality(q,30)
        self.assertIsNone(c.receive_quality('sync_failed',x,x,30)['rx_sinr_db'])


if __name__=='__main__':unittest.main()
