import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_d10_synthetic as s

class SyntheticTests(unittest.TestCase):
    def test_reproducible_finite_centered_band_and_carrier(self):
        for name in s.LABELS:
            x=s.generate(name,77)
            np.testing.assert_array_equal(x,s.generate(name,77))
            self.assertEqual(x.shape,(1024,))
            self.assertAlmostEqual(float(s.power(x)),1)
            spectrum=abs(np.fft.fft(x*np.hanning(1024)))**2
            freq=np.fft.fftfreq(1024,1/s.RATE)
            self.assertLess(spectrum[abs(freq)>210000].sum()/spectrum.sum(),.002)
        self.assertGreater(abs(s.generate('AM-DSB-WC',77).mean()),.9)
        self.assertLess(abs(s.generate('AM-DSB-SC',77).mean()),.3)
        np.testing.assert_allclose(s.rrc(),s.rrc()[::-1])

    def test_oracle_exact_same_noise_and_guard_rule(self):
        x=s.generate('QPSK',91)
        a,ra=s.channel(x,12,0,-10);b,rb=s.channel(x,12,0,10)
        np.testing.assert_allclose(a['oracle_full'],b['oracle_full'],atol=1e-14)
        self.assertAlmostEqual(float(s.power(a['oracle_full']-x)),1)
        self.assertAlmostEqual(float(s.power(a['raw']-a['oracle_full'])),10)
        np.testing.assert_allclose(a['guard25'],.75*a['raw']+.25*a['guard_full'],atol=1e-14)
        np.testing.assert_array_equal(a['rule'],a['guard25'] if ra['ratio']<s.THRESHOLD else a['guard_full'])
        self.assertAlmostEqual(ra['raw_sinr'],-10*np.log10(s.power(a['raw']-x)))
        self.assertLess(ra['error_power']['oracle_full'],ra['error_power']['raw'])
        tensor=s.tensor(np.array([a['raw'],a['guard_full']]))
        np.testing.assert_allclose(np.mean(np.sum(tensor.astype(float)**2,axis=1),axis=1),1,atol=1e-7)

if __name__=='__main__':unittest.main()
