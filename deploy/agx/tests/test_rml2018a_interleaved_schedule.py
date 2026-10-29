"""Source pairing and physical waveform invariants before any radio use."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_interleaved_schedule as s


class ScheduleTests(unittest.TestCase):
    def design(self):
        validation = np.concatenate([np.arange(k*106496+102400, k*106496+102450, dtype=np.int64)
                                     for k in range(24)])
        return validation, s.schedule(validation)

    def test_balanced_paired_validation_and_tail(self):
        validation, design = self.design()
        self.assertEqual(design, s.schedule(validation))
        rows = np.asarray(design['source_rows'])
        self.assertTrue(np.isin(rows, validation).all())
        self.assertEqual(len(np.unique(rows[:2016])), 672)
        for db in s.POWER_DB:
            selected = rows[:2016][np.asarray(design['payload_power_db'][:2016]) == db]
            np.testing.assert_array_equal(np.bincount(selected//106496, minlength=24), [28]*24)
            np.testing.assert_array_equal(np.sort(selected), np.unique(rows[:2016]))
        for start in range(0, 2016, 48):
            np.testing.assert_array_equal(rows[start:start+16], rows[start+16:start+32])
            np.testing.assert_array_equal(rows[start:start+16], rows[start+32:start+48])
        self.assertEqual(design['primary'], [True]*2016+[False]*32)
        self.assertEqual(design['pair_group'][-32:], [-1]*32)

    def test_pilot_guard_unchanged_payload_gain_is_not_renormalized(self):
        _, design = self.design()
        values = np.tile(np.exp(2j*np.pi*np.arange(1024)/31), (2048, 1))
        original, original_scales = s.packet(values, 'offline-interleaved-test')
        wave, scales = s.waveform(values, 'offline-interleaved-test', design)
        base = original.reshape(128, s.FRAME_SAMPLES)
        frames = wave.reshape(128, s.FRAME_SAMPLES)
        np.testing.assert_array_equal(frames[:, :1280], base[:, :1280])
        np.testing.assert_array_equal(frames[:, -256:], base[:, -256:])
        gain = np.power(10., np.asarray(design['payload_power_db'])/20.)
        payload = frames[:, 1280:-256].reshape(2048, 1024)
        np.testing.assert_allclose(payload, base[:, 1280:-256].reshape(2048, 1024)*gain[:, None], rtol=1e-6)
        np.testing.assert_allclose(scales, original_scales*gain)
        self.assertLessEqual(float(np.max(np.abs(wave))), .632456)
        self.assertEqual(wave.dtype, np.dtype('<c8'))
        self.assertEqual(wave.nbytes, 18350080)

    def test_incomplete_or_duplicate_validation_rejected(self):
        validation, _ = self.design()
        for bad in (validation[:50], np.append(validation, validation[-1]), validation.astype(float)):
            with self.assertRaises(ValueError):
                s.schedule(bad)


if __name__ == '__main__':
    unittest.main()
