"""Independent transfer-function and convolution checks for the fixed filter."""
import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('wideband',SCRIPTS/'compare-rml2018a-wideband.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)


class WidebandTests(unittest.TestCase):
    def test_dc_symmetry_and_known_passband_tones(self):
        h=w.taps();self.assertEqual(len(h),129)
        np.testing.assert_allclose(h,h[::-1],atol=1e-16)
        self.assertAlmostEqual(float(h.sum()),1.,places=14)
        n=np.arange(8192)
        for hz in (-175000,0,175000):
            x=np.exp(2j*np.pi*hz*n/w.c.RATE);y=np.convolve(x,h,mode='same')
            self.assertLess(float(np.mean(abs(y[64:-64]-x[64:-64])**2)),1e-8)

    def test_stopband_and_white_noise_gain(self):
        h=w.taps();n=np.arange(32768)
        for hz in (-800000,800000):
            x=np.exp(2j*np.pi*hz*n/w.c.RATE)
            self.assertLess(float(np.mean(abs(np.convolve(x,h,mode='same')[64:-64])**2)),1e-8)
        rng=np.random.default_rng(578);z=rng.normal(size=len(n))+1j*rng.normal(size=len(n))
        ratio=np.mean(abs(np.convolve(z,h,mode='same')[64:-64])**2)/np.mean(abs(z[64:-64])**2)
        self.assertLess(abs(10*np.log10(ratio/np.sum(h*h))),.1)

    def test_whole_capture_uses_neighbours_without_wrap(self):
        z=np.zeros(4096,complex);z[1023]=3+2j;h=w.taps()
        y=np.convolve(z,h,mode='same')
        np.testing.assert_allclose(y[959:1088],(3+2j)*h)
        np.testing.assert_array_equal(y[:959],0)
        self.assertGreater(np.linalg.norm(y[1024:1088]),0)


if __name__=='__main__':unittest.main()
