"""Synthetic perturbation invariants; never loads a model or contacts a radio."""
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
import numpy as np

spec=importlib.util.spec_from_file_location('sensitivity',Path(__file__).resolve().parents[1]/'scripts/diagnose-b210-source-sensitivity.py')
sensitivity=importlib.util.module_from_spec(spec);spec.loader.exec_module(sensitivity)


class SensitivityTests(unittest.TestCase):
    def source(self):
        return np.random.default_rng(31).normal(size=(4096,2)).astype(np.float32)

    def test_cfo_sign_continuity_and_constant_phase_preserve_envelope(self):
        source=np.zeros((4096,2),dtype=np.float32);source[:,0]=1
        data,_=sensitivity.variants(source,0,3532.4635690852447)
        plus=data['aligned_cfo_positive'];minus=data['aligned_cfo_negative']
        np.testing.assert_allclose(np.square(plus).sum(axis=1),1,atol=2e-7)
        np.testing.assert_array_equal(plus[:,0],minus[:,0])
        np.testing.assert_array_equal(plus[:,1],-minus[:,1])
        self.assertGreater(abs(float(plus[1024,1])),.1)  # No phase reset between model windows.
        np.testing.assert_array_equal(data['aligned_phase90'],np.tile([0.,1.],(4096,1)))

    def test_added_noise_ratio_and_same_noise_realization(self):
        source=self.source();data,metadata=sensitivity.variants(source,19,3532.4635690852447)
        aligned=data['source_aligned'].astype(np.float64)
        low=data['aligned_awgn20'].astype(np.float64)-aligned
        high=data['aligned_awgn10'].astype(np.float64)-aligned
        # Each noisy source is finally cast to FP32; subtracting a larger source
        # amplifies the relative residual error. Bound the two casts explicitly.
        bound=np.finfo(np.float32).eps*(abs(data['aligned_awgn10'].astype(np.float64))
                                      +np.sqrt(10)*abs(data['aligned_awgn20'].astype(np.float64)))
        self.assertTrue(np.all(abs(high-low*np.sqrt(10)) <= bound+1e-12))
        for db in (20,10):
            self.assertAlmostEqual(metadata[f'aligned_awgn{db}']['actual_component_ratio_db'],db,places=5)
            self.assertFalse(metadata[f'aligned_awgn{db}']['total_snr_known'])

    def test_determinism_source_preservation_and_finite_case_budget(self):
        source=self.source();before=source.copy()
        first,_=sensitivity.variants(source,3152,3532.4635690852447)
        second,_=sensitivity.variants(source,3152,3532.4635690852447)
        np.testing.assert_array_equal(source,before)
        self.assertEqual(len(first),7)
        for name in first:np.testing.assert_array_equal(first[name],second[name])
        self.assertEqual(sum(sensitivity.paired.normalize(iq).nbytes for iq in first.values()),229376)

    def test_invalid_source_or_frequency_cannot_create_cases(self):
        for source,lag,freq in [(np.zeros((4096,2)),0,3500), (self.source(),4096,3500),
                                (self.source(),0,float('nan')), (self.source(),0,2100000),
                                (np.ones((1024,2)),0,3500)]:
            with self.assertRaises(ValueError):sensitivity.variants(source,lag,freq)

    def test_modified_historical_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            path=Path(tmp)/'audit.json';raw=b'{"lag":3152}'
            path.write_bytes(raw)
            digest=hashlib.sha256(raw).hexdigest()
            self.assertEqual(sensitivity.pinned_json(path,digest)['lag'],3152)
            path.write_bytes(raw+b' ')
            with self.assertRaises(ValueError):sensitivity.pinned_json(path,digest)


if __name__=='__main__':unittest.main()
