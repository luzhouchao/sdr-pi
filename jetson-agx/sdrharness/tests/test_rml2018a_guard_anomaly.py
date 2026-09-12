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


if __name__ == '__main__':
    unittest.main()
