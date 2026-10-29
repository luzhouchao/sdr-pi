"""Explanatory phase/gain/delay/CFO fits and negative controls; no RF/model."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np
spec=importlib.util.spec_from_file_location('decomp',Path(__file__).resolve().parents[1]/'scripts/diagnose-b210-failure-decomposition.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

class DecompositionTests(unittest.TestCase):
    def source(self):
        rng=np.random.default_rng(90704)
        spectrum=rng.normal(size=1024)+1j*rng.normal(size=1024)
        spectrum[abs(np.fft.fftfreq(1024,1/d.RATE))>90000]=0
        x=np.fft.ifft(spectrum);return x/np.sqrt(np.mean(abs(x)**2))+.3+.2j

    def test_pure_phase_error_is_explained_without_gain_change(self):
        x=self.source();h=2+.7j;y=h*x*np.exp(.8j)
        r=d.projection(x,y,h)
        self.assertGreater(r['original_error_fraction'],.5)
        self.assertLess(r['phase_only_error_fraction'],1e-25)
        self.assertLess(r['unexplained_fraction'],1e-25)
        self.assertAlmostEqual(r['relative_phase_rad'],.8)
        self.assertAlmostEqual(r['relative_amplitude'],1.)

    def test_gain_change_and_uncorrelated_energy_separate(self):
        x=self.source();r=d.projection(x,1.5*x*np.exp(.4j),1)
        self.assertGreater(r['phase_only_error_fraction'],.1);self.assertLess(r['unexplained_fraction'],1e-25)
        rng=np.random.default_rng(4);y=x+5*(rng.normal(size=1024)+1j*rng.normal(size=1024))
        r=d.projection(x,y,1);self.assertGreater(r['unexplained_fraction'],.9)
        self.assertAlmostEqual(r['unexplained_fraction'],1-r['coherence']**2,places=13)

    def test_search_recovers_nonzero_frequency_and_fractional_delay(self):
        x=self.source();frequency=4975.;delay=31.375;n=np.arange(1024)
        raw=d.delayed(d.reference(x,frequency),delay)*np.exp(2j*np.pi*frequency*n/d.RATE)
        original=raw.copy();r=d.search_blocks(x,raw[None,:],3600.)[0]
        self.assertGreater(r['coherence'],.999999)
        self.assertEqual(r['frequency_hz'],frequency);self.assertEqual(r['delay_samples'],delay)
        np.testing.assert_array_equal(raw,original)

    def test_same_spectrum_wrong_source_not_mistaken_for_exact_transform(self):
        x=self.source();rng=np.random.default_rng(90705)
        wrong=np.fft.ifft(abs(np.fft.fft(x))*np.exp(1j*rng.uniform(-np.pi,np.pi,1024)))
        raw=d.reference(wrong,3600.)*np.exp(2j*np.pi*3600*np.arange(1024)/d.RATE)
        r=d.search_blocks(x,raw[None,:],3600.)[0]
        self.assertLess(r['coherence'],.9);self.assertFalse(r['high_coherence'])

    def test_guard_band_excludes_source_and_lo_but_detects_broadband(self):
        n=np.arange(1024)
        self.assertLess(d.guard_rms(20*np.exp(2j*np.pi*253700*n/d.RATE)),.01)
        self.assertAlmostEqual(d.guard_rms(3*np.exp(2j*np.pi*500000*n/d.RATE)),3.,places=5)
        rng=np.random.default_rng(9);noise=20*(rng.normal(size=1024)+1j*rng.normal(size=1024))
        self.assertGreater(d.guard_rms(noise),10.)

    def test_zero_and_invalid_inputs_fail_without_meaningless_parameters(self):
        x=self.source();self.assertFalse(d.projection(x,np.zeros(1024))['available'])
        self.assertFalse(d.search_blocks(x,np.zeros((1,1024)),3600.)[0]['high_coherence'])
        with self.assertRaises(ValueError):d.projection(x,np.zeros(1000))
        with self.assertRaises(ValueError):d.guard_rms(np.full(1024,np.nan))
        with self.assertRaises(ValueError):d.characterize(x,np.zeros(65534),3600.)
        self.assertEqual(len(d.STARTS),62)
        self.assertEqual(sum(32768<=k<36864 for k in d.STARTS),4)

if __name__=='__main__':unittest.main()
