import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import numpy as np

from rml2018a_lo_temporal_diagnostic import RATE, metrics, phasors


class TemporalTests(unittest.TestCase):
    def tone(self, delta=0., amp_slope=0., curvature=0.):
        n = np.arange(55000)
        t = n / 17920
        return (20 + amp_slope*t) * np.exp(2j*np.pi*(250000+delta)*n/RATE + 1j*curvature*t*t)

    def measure(self, z):
        return metrics(phasors(z, 250000, [0,17920,35840,53760]))

    def test_constant(self):
        m = self.measure(self.tone())
        self.assertLess(np.max(abs(np.array(m['future_phase_curvature_rad']))), 1e-10)
        self.assertLess(np.max(m['future_amplitude_range_fraction']), 1e-10)

    def test_frequency_error_is_slope_not_curvature(self):
        m = self.measure(self.tone(delta=5))
        np.testing.assert_allclose(m['residual_phase_slope_hz'], 5, atol=1e-9)
        np.testing.assert_allclose(m['future_phase_curvature_rad'], 0, atol=1e-9)

    def test_amplitude_change(self):
        m = self.measure(self.tone(amp_slope=1))
        self.assertTrue(all(m['amplitude_both_halves_4se']))
        self.assertGreater(min(m['future_endpoint_amplitude_change_fraction']), .09)

    def test_curvature(self):
        m = self.measure(self.tone(curvature=.04))
        np.testing.assert_allclose(m['future_phase_curvature_rad'], .08, atol=1e-6)
        self.assertTrue(all(m['curvature_both_halves_4se']))

    def test_noise_and_se(self):
        rng = np.random.RandomState(42)
        z = self.tone() + rng.normal(size=55000) + 1j*rng.normal(size=55000)
        h = phasors(z,250000,[17920,35840,53760])
        self.assertTrue(all(x > 0 for row in h for x in row['se']))
        self.assertFalse(any(metrics(h)['curvature_both_halves_4se']))

    def test_reject_bad_input_and_unidentifiable(self):
        with self.assertRaises(ValueError):
            phasors([np.nan],250000,[0])
        with self.assertRaises(ValueError):
            phasors([1],250000,[0])
        self.assertFalse(self.measure(np.zeros(55000))['identifiable'])


if __name__ == '__main__':
    unittest.main()
