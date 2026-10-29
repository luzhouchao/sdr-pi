"""Synthetic transport-artifact controls, using no hardware or retained IQ."""
import importlib.util
from pathlib import Path
import struct
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location('rx_bytes', Path(__file__).resolve().parents[1] / 'scripts/diagnose-b210-rx-bytes.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


class ByteAuditTests(unittest.TestCase):
    def noise(self):
        return np.random.default_rng(90717).integers(-100, 101, (65535, 2), dtype=np.int16)

    def test_signed_little_endian_and_wrong_endian(self):
        raw = struct.pack('<hh', -2048, 2047) * 65535
        r = d.characterize(raw)
        self.assertEqual(r['i_range'], [-2048, -2048])
        self.assertEqual(r['signed12_mismatch_components'], 0)
        self.assertGreater(d.characterize(struct.pack('>hh', -1000, 1000) * 65535)['signed12_mismatch_components'], 0)
        # Some byte swaps remain valid 12-bit values: the range check is not
        # an error-detecting code and must not be sold as one.
        self.assertEqual(d.characterize(struct.pack('>hh', -2048, 2047) * 65535)['signed12_mismatch_components'], 0)
        self.assertEqual(r['longest_constant_run'], dict(start=0, count=65535))

    def test_duplicate_dma_block_and_cross_capture(self):
        v = self.noise()
        self.assertEqual(d.block_groups({'clean': v.tobytes()}, 4096), [])
        v[8192:12288] = v[4096:8192]
        r = d.block_groups({'repeated': v.tobytes()}, 4096)
        self.assertEqual([x['start'] for x in r[0]['occurrences']], [4096, 8192])
        r = d.block_groups({'a': v.tobytes(), 'b': v.tobytes()}, 4096)
        self.assertTrue(all({x['capture'] for x in g['occurrences']} == {'a', 'b'} for g in r))

    def test_zero_fill_and_constant_spans_include_capture_ends(self):
        v = self.noise()
        v[-500:] = 0
        r = d.characterize(v.tobytes())
        self.assertEqual(r['longest_zero_run'], dict(start=65035, count=500))
        v[:700] = [15, -23]
        self.assertEqual(d.characterize(v.tobytes())['longest_constant_run'], dict(start=0, count=700))

    def test_boundary_and_non_boundary_power_steps_are_distinguished(self):
        for start in (8192, 8576):
            v = np.ones((65535, 2), dtype='<i2')
            v[start:] *= 100
            r = d.characterize(v.tobytes())
            self.assertEqual(r['largest_power_transitions'][0]['start'], start)
            self.assertEqual(r['largest_power_transitions'][0]['modulo4096'], start % 4096)
            jump = next(b for b in r['boundaries'] if b['start'] == 8192)['jump_adc']
            self.assertEqual(jump > 0, start == 8192)

    def test_full_length_tail_and_malformed_input(self):
        raw = self.noise().tobytes()
        r = d.characterize(raw)
        self.assertEqual(r['block_coverage']['128'], dict(complete_blocks=511, tail_samples=127))
        self.assertEqual(r['block_coverage']['4096'], dict(complete_blocks=15, tail_samples=4095))
        self.assertEqual(r['tail_128_segment']['start'], 65408)
        self.assertEqual(len(r['boundaries']), 15)
        for bad in (b'', raw[:-1], raw[:-4], raw + b'\0', np.zeros(65535)):
            with self.assertRaises(ValueError):
                d.decode(bad)

    def test_all_zero_is_reported_without_nan_or_continuity_claim(self):
        r = d.characterize(bytes(65535 * 4))
        self.assertEqual(r['longest_zero_run'], dict(start=0, count=65535))
        self.assertEqual(r['signed12_mismatch_components'], 0)
        self.assertEqual(r['boundaries'][0]['jump_adc'], 0)
        self.assertEqual(d.longest_run(np.zeros(3, dtype=bool)), dict(start=None, count=0))


if __name__ == '__main__':
    unittest.main()
