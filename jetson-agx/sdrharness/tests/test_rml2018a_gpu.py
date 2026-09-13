"""SNR partition and experimental batch DSP, independent of radio/model state."""
from pathlib import Path
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_campaign as c
import rml2018a_campaign_gpu as g


class BatchTests(unittest.TestCase):
    def test_all_snr_groups_cover_original_dataset_once(self):
        counts = np.zeros(2555904, dtype=np.uint8)
        for snr in range(-20, 31, 2):
            rows = g.snr_rows(snr)
            self.assertEqual(len(rows), 98304)
            np.testing.assert_array_equal(2*((rows%106496)//4096)-20, snr)
            np.testing.assert_array_equal(np.bincount(rows//106496), np.full(24, 4096))
            counts[rows] += 1
            blocks = [g.snr_block_rows(snr, k) for k in range(96)]
            np.testing.assert_array_equal(np.concatenate(blocks), rows)
        np.testing.assert_array_equal(counts, 1)

    def test_snr_ranges_reject_invalid_and_cross_group(self):
        for args in [(True,), (31,), (-19,), (30, -1, 1), (30, 98303, 2), (30, 0, 0)]:
            with self.assertRaises(ValueError): g.snr_rows(*args)
        for block in (-1, 96, True):
            with self.assertRaises(ValueError): g.snr_block_rows(30, block)

    def test_vector_cpu_normalization_preserves_scalar_bytes(self):
        rng = np.random.default_rng(741)
        for dtype in (np.complex64, np.complex128):
            x = (rng.normal(size=(1024,1024))+1j*rng.normal(size=(1024,1024))).astype(dtype)
            expected = np.stack([c.normalize_window(v) for v in x])
            actual = g.PayloadBatch('cpu').normalize(x)
            self.assertEqual(actual.tobytes(), expected.tobytes())
            self.assertTrue(actual.flags.c_contiguous)

    def test_batch_validation_does_not_silently_drop_bad_rows(self):
        b = g.PayloadBatch('cpu')
        for x in (np.zeros((1,1024),complex), np.ones((0,1024),complex),
                  np.ones((8193,1024),complex), np.ones((1,1023),complex),
                  np.ones((1,1024)), np.full((1,1024), complex(float('nan'),0))):
            with self.assertRaises(ValueError): b.normalize(x)
        with self.assertRaises(ValueError): g.PayloadBatch('auto')
        with self.assertRaises(ValueError): b.quality(np.ones((1,1024),complex), np.ones((1,1024),complex), [31])

    def test_quality_preserves_zero_unidentifiable_and_unstable_rows(self):
        rng = np.random.default_rng(52)
        x = rng.normal(size=(5,1024))+1j*rng.normal(size=(5,1024))
        y = x.copy()
        x[0] = 0; x[1] = 1; y[2] = 0; y[3,512:] *= 10
        y[4] += .03*(rng.normal(size=1024)+1j*rng.normal(size=1024))
        z = np.array([-20, 0, 10, 20, 30])
        q = g.PayloadBatch('cpu').quality(x, y, z)
        self.assertEqual([v['rx_sinr_status'] for v in q], ['invalid']*4+['estimated'])
        for v, snr in zip(q, z): c.validate_receive_quality(v, float(snr))

    @unittest.skipUnless(os.environ.get('RML_TEST_CUDA') == '1', 'explicit offline GPU lease required')
    def test_cuda_rejections_and_numeric_contract(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('gpu_benchmark', Path(g.__file__).with_name('benchmark-rml2018a-gpu.py'))
        benchmark = importlib.util.module_from_spec(spec); spec.loader.exec_module(benchmark)
        rng = np.random.default_rng(57)
        x = rng.normal(size=(64,1024))+1j*rng.normal(size=(64,1024))
        y = x+.1*(rng.normal(size=x.shape)+1j*rng.normal(size=x.shape))
        z = np.resize(np.arange(-20,31,2),len(x))
        x[0] = 0; x[1] = 1; y[2] = 0; y[3,512:] *= 10; y[4] = 1
        y[5,:512] += 2*(rng.normal(size=512)+1j*rng.normal(size=512))
        expected = g.PayloadBatch('cpu').quality(x,y,z)
        actual = g.PayloadBatch('cuda').quality(x,y,z)
        benchmark.quality_difference(expected, actual)
        self.assertIn('reference_not_detectable', [v['rx_sinr_reason'] for v in actual])
        self.assertIn('residual_not_stationary_across_halves', [v['rx_sinr_reason'] for v in actual])
        with self.assertRaises(ValueError): g.PayloadBatch('cuda').normalize(x)


if __name__ == '__main__': unittest.main()
