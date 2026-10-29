from pathlib import Path
import sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_d10_synthetic_randomized as r

class RandomizedTests(unittest.TestCase):
    def test_pulse_reference_and_fractional_center(self):
        for sps in (2,4,8,16):
            np.testing.assert_allclose(r.pulse(sps,.35,0),r.s.rrc(sps=sps),atol=1e-14)
            h=r.pulse(sps,.25,0)  # Exercises removable singularity.
            self.assertTrue(np.isfinite(h).all());self.assertAlmostEqual(float(np.dot(h,h)),1)
            shifted=r.pulse(sps,.2,.75)
            self.assertGreater(float(np.dot(np.arange(len(shifted))-6*sps,shifted**2)),.5)

    def test_pairing_class_independent_nuisance_and_symbol_recovery(self):
        for sps in (2,4,8,16):
            reference=None
            for label in ('BPSK','QPSK','16QAM'):
                records=[]
                for variant in r.VARIANTS:
                    wave,info=r.realization(label,9,sps,variant)
                    self.assertEqual(wave.shape,(1024,));self.assertAlmostEqual(float(r.s.power(wave)),1)
                    self.assertEqual(info['errors'],0);self.assertLess(info['evm'],.12);records.append(info)
                self.assertEqual(len({x['seed'] for x in records}),1)
                self.assertEqual(len({x['phase'] for x in records}),1)
                self.assertEqual(records[0]['tau'],0);self.assertEqual(records[1]['tau'],0)
                self.assertEqual(records[0]['beta'],.35);self.assertEqual(records[2]['beta'],.35)
                nuisance=[(v['beta'],v['tau'],v['phase']) for v in records]
                if reference is not None:self.assertEqual(nuisance,reference)
                reference=nuisance

if __name__=='__main__':unittest.main()
