"""Guard diagnostic checks independent of archived hardware observations."""
import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('guard_diagnostic', SCRIPTS/'diagnose-rml2018a-guard-anomaly.py')
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


class GuardDiagnosticTests(unittest.TestCase):
    def test_power_localizes_event_without_discarding_it(self):
        z = np.ones(192, complex); z[128:] *= 6
        before = z.copy(); result = diagnostic.stats(z)
        self.assertEqual(result['blocks64_power_counts2'], [1., 1., 36.])
        self.assertAlmostEqual(result['power_counts2'], 38/3)
        np.testing.assert_array_equal(before, z)

    def test_spectrum_integrates_to_window_weighted_power(self):
        rng = np.random.default_rng(311)
        z = rng.normal(size=192)+1j*rng.normal(size=192)
        w = np.hanning(192)
        result = diagnostic.stats(z)
        self.assertAlmostEqual(sum(result['spectrum_band_power_counts2']),
                               float(np.sum(abs(z*w)**2)/np.sum(w*w)), places=12)
        self.assertLess(result['peak_tone_projection_fraction'], .15)

    def test_tone_projection_distinguishes_known_tone(self):
        for hz in (-208000, 254000):
            z = 6*np.exp(2j*np.pi*hz*np.arange(192)/diagnostic.c.RATE)
            result = diagnostic.stats(z)
            self.assertLess(abs(result['spectrum_peak_hz']-hz), 65)
            self.assertGreater(result['peak_tone_projection_fraction'], .999)

    def test_invalid_data_and_replay_change_rejected(self):
        for z in (np.zeros(191), np.full(192, np.nan)):
            with self.assertRaises(ValueError): diagnostic.stats(z)
        self.assertTrue(diagnostic.compatible({'x': .1}, {'x': .1+1e-16}))
        self.assertFalse(diagnostic.compatible({'status': 'skipped'}, {'status': 'applied'}))
        self.assertFalse(diagnostic.compatible({'db': 5.98}, {'db': 10.}))

    def test_frozen_lo_split_preserves_other_tones_and_power(self):
        start = 1673; n = np.arange(start, start+192); frequency = 253000.
        lo = 3*np.exp(2j*np.pi*frequency*n/diagnostic.c.RATE)
        other = 5*np.exp(2j*np.pi*(frequency+7*diagnostic.c.RATE/192)*n/diagnostic.c.RATE)
        result = diagnostic.tone_parts(lo+other, start, frequency)
        self.assertAlmostEqual(result['coherent_at_frozen_lo_counts2'], 9., places=10)
        self.assertAlmostEqual(result['noncoherent_counts2'], 25., places=10)
        self.assertAlmostEqual(result['total_counts2'], 34., places=10)

    def test_neighborhood_covers_all_guards_with_calibrated_bins(self):
        z = np.ones(diagnostic.c.RX_SAMPLES, complex)
        before = z.copy()
        result = diagnostic.neighborhoods(z, [[8070,8454],[34182,34566],[60294,60678]])
        self.assertEqual(len(result), 3)
        for item in result:
            windows = item['windows']
            self.assertEqual(len(windows), 28)
            for w in windows:
                self.assertEqual(w['stop']-w['start'], 192)
                self.assertAlmostEqual(sum(w['spectrum_bin_power_counts2']), 1.)
        np.testing.assert_array_equal(z, before)

    def test_tone_split_refuses_invalid_inputs(self):
        for z, start, frequency in ((np.zeros(191),0,1), (np.zeros(192),-1,1),
                                    (np.zeros(192),0,float('nan'))):
            with self.assertRaises(ValueError): diagnostic.tone_parts(z,start,frequency)


if __name__ == '__main__':
    unittest.main()
