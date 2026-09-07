"""Synthetic known-source controls; no hardware, model or dataset access."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('residual', SCRIPTS/'diagnose-b210-multiclass-residual.py')
residual = importlib.util.module_from_spec(spec)
spec.loader.exec_module(residual)


class ResidualTests(unittest.TestCase):
    def source(self):
        n = np.arange(1024)
        return sum(a*np.exp(2j*np.pi*k*n/1024) for a, k in [(1, 3), (.7j, 17), (.3, 48)])+.2

    def capture(self):
        source = self.source()
        n = np.arange(residual.COUNT)
        fit = dict(lag=63, total_frequency_hz=3500.)
        coefficients = np.array([1.2+.8j, .2j, .15])
        h, b, d = coefficients
        raw = (h*source[(n-63)%1024]+b)*np.exp(2j*np.pi*3500*n/residual.RATE)+d
        return source, raw, fit, coefficients

    def test_prefix_fit_does_not_observe_heldout(self):
        source, raw, _, _ = self.capture()
        first, coefficients = residual.estimate(source, raw, 3500., 150000)
        self.assertTrue(first['available'])
        modified = raw.copy()
        modified[16384:] = 1234-888j
        second, other = residual.estimate(source, modified, 3500., 150000)
        self.assertEqual(first, second)
        np.testing.assert_array_equal(coefficients, other)

    def test_counterfactuals_recover_known_channel_and_preserve_source_mean(self):
        source, raw, fit, coefficients = self.capture()
        outputs, metrics = residual.transforms(source, raw, fit, coefficients)
        self.assertEqual(set(outputs), set(residual.KINDS))
        self.assertLess(metrics['fixed_block_affine_residual_fraction'], 1e-20)
        self.assertGreater(metrics['fixed_block_source_only_residual_fraction'], .001)
        # Mixing moves each tone along the finite FIR passband response; it does
        # not commute exactly with filtering, even for a noiseless channel.
        bound = 2*residual.repair.filter_contract()['passband_max_amplitude_error']*2.2
        np.testing.assert_allclose(outputs['received_affine'], outputs['source_shifted'], atol=bound)
        self.assertAlmostEqual(outputs['received_affine'].mean().real, .2, places=5)
        self.assertTrue(all(v.shape == (4096,) for v in outputs.values()))

    def test_strong_dc_band_diagnostic_is_not_model_dc_removal(self):
        source = self.source()*.01+10
        original = source.copy()
        result = residual.centered_width(source)
        self.assertEqual(result['total_99_width_hz'], 0)
        self.assertGreater(result['centered_99_width_hz'], 3000)
        self.assertFalse(result['applied_to_model_iq'])
        self.assertFalse(result['original_gate_revised'])
        np.testing.assert_array_equal(source, original)

    def test_constant_nonfinite_or_short_source_has_no_fake_band(self):
        for z in (np.ones(1024), np.full(1024, np.nan), np.ones(1000)):
            with self.assertRaises(ValueError): residual.centered_width(z)

    def test_model_case_selection_includes_all_success_controls(self):
        plans = [p for p in residual.multi.manifest()['cases'] if p['class_id'] in residual.CLASSES]
        self.assertEqual(len(plans), 12)
        self.assertEqual(sum(p['case_id'] in residual.BAD for p in plans), 4)
        for c in residual.CLASSES:
            self.assertEqual({p['round'] for p in plans if p['class_id'] == c}, {0, 1, 2})

    def test_retained_preparation_never_opens_dataset_or_split(self):
        with patch.object(residual.multi.h5py, 'File', side_effect=AssertionError('dataset opened')), \
             patch.object(residual.multi.zipfile, 'ZipFile', side_effect=AssertionError('split opened')):
            report, tensors = residual.prepare()
        self.assertEqual(len(report['cases']), 12)
        self.assertEqual(len(report['strong_dc']), 6)
        self.assertEqual(len(tensors), 108)


if __name__ == '__main__': unittest.main()
