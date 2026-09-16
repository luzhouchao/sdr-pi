import importlib.util
from pathlib import Path
import unittest
import numpy as np
spec=importlib.util.spec_from_file_location('spectral_diag',Path(__file__).resolve().parents[1]/'scripts/rml2018a_spectrum_diagnostic.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SpectralTests(unittest.TestCase):
    def tone(self,hz):return np.exp(2j*np.pi*hz*np.arange(1024)/m.FS)
    def test_scaling_preserves_spectral_fractions(self):
        z=np.random.default_rng(42).normal(size=(2,1024));z=z[0]+1j*z[1]
        a,p=m.metrics(z);b,q=m.metrics(z*.037)
        np.testing.assert_allclose(p,q,rtol=1e-12,atol=1e-15)
        for key in a:self.assertAlmostEqual(a[key],b[key],places=10)
    def test_tx_coordinate_sign_and_receiver_intersection(self):
        a,_=m.metrics(self.tone(-600000));self.assertGreater(a['tx250000_outside_fraction'],.999)
        self.assertLess(a['rx_nominal_outside_fraction'],.001)
        b,_=m.metrics(self.tone(-100000));self.assertLess(b['joint250000_outside_fraction'],.001)
        self.assertGreater(b['joint750000_outside_fraction'],.999)
    def test_lo_band_and_dc_are_not_removed(self):
        a,p=m.metrics(self.tone(250000));self.assertGreater(a['lo250_fraction'],.999)
        b,q=m.metrics(np.ones(1024));self.assertGreater(q[abs(m.F)<10000].sum(),.999)
        self.assertGreaterEqual(b['f995_hz'],0);self.assertLessEqual(b['f005_hz'],0)
    def test_parseval_and_invalid_data(self):
        z=self.tone(173000)+.2*self.tone(-411000)
        self.assertAlmostEqual(np.sum(abs(np.fft.fft(z*m.W,m.FFT))**2)/m.FFT,np.sum(abs(z*m.W)**2),places=10)
        for bad in (np.zeros(1024),np.full(1024,np.nan),np.ones(1023)):
            with self.assertRaises(ValueError):m.metrics(bad)

if __name__=='__main__':unittest.main()
