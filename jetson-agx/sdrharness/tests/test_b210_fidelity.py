"""Synthetic fidelity checks; no hardware/model calls."""
import asyncio
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import numpy as np

spec=importlib.util.spec_from_file_location('fidelity',Path(__file__).resolve().parents[1]/'scripts/diagnose-b210-rx-fidelity.py')
fidelity=importlib.util.module_from_spec(spec);spec.loader.exec_module(fidelity)


class FidelityTests(unittest.TestCase):
    def reference(self):
        rng=np.random.default_rng(617)
        return rng.normal(size=4096)+1j*rng.normal(size=4096)

    def test_band_partition_and_rejection_of_outside_tone(self):
        n=np.arange(65535)
        source=np.exp(2j*np.pi*128*n/65535)
        received=source+3*np.exp(2j*np.pi*20000*n/65535)
        self.assertAlmostEqual(fidelity.power_partition(received,125000)['inside_fraction'],.1,places=12)
        np.testing.assert_allclose(fidelity.bandlimit(received,125000),source,atol=2e-11)

    def test_cfo_round_trip_and_dc_retention(self):
        raw=self.reference();copy=raw.copy()
        shifted=fidelity.correct_cfo(raw,3532.46)
        np.testing.assert_allclose(fidelity.correct_cfo(shifted,-3532.46),raw,atol=1e-12)
        np.testing.assert_array_equal(raw,copy)
        dc=np.full(4096,1+2j)
        np.testing.assert_allclose(fidelity.bandlimit(dc,125000),dc,atol=1e-12)

    def test_fit_uses_only_first_seven_and_heldout_residual_detects_phase_change(self):
        reference=self.reference();gain=2*np.exp(.7j)
        received=np.tile(reference,16)[:65535]*gain
        original=fidelity.fit_transfer(reference,received)
        self.assertAlmostEqual(original['gain_real'],gain.real,places=12)
        self.assertAlmostEqual(original['gain_imag'],gain.imag,places=12)
        self.assertLess(max(row['normalized_residual_power'] for row in original['heldout_windows']),1e-25)
        received[fidelity.FIT_SAMPLES:]*=-1
        changed=fidelity.fit_transfer(reference,received)
        self.assertEqual(original['gain_real'],changed['gain_real'])
        self.assertEqual(original['gain_imag'],changed['gain_imag'])
        for row in changed['heldout_windows']:self.assertAlmostEqual(row['normalized_residual_power'],4,places=12)

    def test_direct_and_conjugate_hypotheses_are_distinct(self):
        reference=self.reference();received=np.tile(reference.conj(),16)[:65535]*np.exp(.4j)
        direct=fidelity.fit_transfer(reference,received)
        conjugate=fidelity.fit_transfer(reference.conj(),received)
        self.assertLess(direct['train_coherence'],.1)
        self.assertGreater(conjugate['train_coherence'],.9999)

    def test_residual_phase_fit_uses_early_windows_and_predicts_later_drift(self):
        reference=self.reference();n=np.arange(65535)
        received=np.tile(reference,16)[:65535]*np.exp(2j*np.pi*72*n/fidelity.RATE)
        first=fidelity.phase_drift(reference,received)
        self.assertTrue(first['identifiable'])
        self.assertAlmostEqual(first['residual_phase_rate_hz'],72,places=9)
        self.assertLess(first['heldout_phase_rmse_rad'],1e-10)
        received[fidelity.FIT_SAMPLES:]*=np.exp(1j)
        changed=fidelity.phase_drift(reference,received)
        self.assertEqual(first['residual_phase_rate_hz'],changed['residual_phase_rate_hz'])
        self.assertGreater(changed['heldout_phase_rmse_rad'],.99)
        self.assertFalse(changed['applied_to_model_input'])

    def test_invalid_fidelity_inputs_fail(self):
        with self.assertRaises(ValueError):fidelity.bandlimit(self.reference(),0)
        with self.assertRaises(ValueError):fidelity.correct_cfo(self.reference(),float('nan'))
        with self.assertRaises(ValueError):fidelity.fit_transfer(np.zeros(4096),np.zeros(65535))
        with self.assertRaises(ValueError):fidelity.fit_transfer(self.reference(),np.zeros(4096))
        with self.assertRaises(ValueError):fidelity.phase_drift(np.full(4096,np.nan),np.zeros(65535))
        with self.assertRaises(ValueError):fidelity.power_partition(np.full(4096,np.nan),125000)

    def test_changed_preparation_cannot_load_model(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            root=Path(tmp);(root/'fidelity-prepared.json').write_text('{"version":1}')
            with mock.patch.object(fidelity,'prepare',return_value=({'version':2},{})):
                with self.assertRaises(AssertionError):asyncio.run(fidelity.infer(root))
            self.assertFalse((root/'fidelity-inference-started.json').exists())


if __name__=='__main__':unittest.main()
