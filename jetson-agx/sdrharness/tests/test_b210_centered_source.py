"""Candidate source-association checks; synthetic arrays only, no radio/model."""
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import unittest

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1]/'scripts/analyze-b210-source-match.py'
spec = importlib.util.spec_from_file_location('centered_source', SCRIPT)
match = importlib.util.module_from_spec(spec)
spec.loader.exec_module(match)


class CenteredSourceTests(unittest.TestCase):
    def fixture(self, seed=90607, lag=776, bias=2+1.5j, residual=65., half_width=125000):
        rng = np.random.default_rng(seed)
        source = rng.normal(size=4096)+1j*rng.normal(size=4096)
        source = match._source_band(source, half_width)
        source /= np.sqrt(np.mean(abs(source)**2))
        source += .7+.2j
        samples = np.tile(np.roll(source, lag), 16)[:65535]
        received = 1.2*np.exp(.9j)*samples+bias
        received += .05*(rng.normal(size=65535)+1j*rng.normal(size=65535))
        received *= np.exp(2j*np.pi*(3450+residual)*np.arange(65535)/match.RATE)
        captures = {tag: .1*(rng.normal(size=65535)+1j*rng.normal(size=65535))
                    for tag in ('baseline', 'after-tx')}
        captures['during-tx'] = received
        return source, captures

    def assess(self, source, captures):
        return match.assess_centered_source(source, captures, 3450., 125000.)

    def test_bias_nonzero_source_mean_and_frequency_do_not_change_source_identity(self):
        source, captures = self.fixture()
        saved = {tag: value.copy() for tag, value in captures.items()}
        original = source.copy()
        result = self.assess(source, captures)
        self.assertTrue(result['waveform_association_passed'], result)
        self.assertEqual(result['fit']['lag'], 776)
        self.assertLess(abs(result['fit']['residual_frequency_hz']-65), 2)
        self.assertFalse(result['live_rf_qualified'])
        self.assertFalse(result['recognizer_available'])
        self.assertFalse(result['production_preprocess_changed'])
        self.assertEqual(result['independent_labels'], 0)
        np.testing.assert_array_equal(original, source)
        for tag in saved:
            np.testing.assert_array_equal(saved[tag], captures[tag])

    def test_registered_24_positive_and_24_same_spectrum_negative_cases(self):
        rows = []
        for index, (lag, bias, residual) in enumerate(itertools.product(
                (0, 776, 4095), (0j, 2+1.5j), (-80., 0., 65., 150.))):
            source, captures = self.fixture(seed=90700+index, lag=lag, bias=bias, residual=residual)
            positive = self.assess(source, captures)
            # Evaluate the preregistered gate without turning a false rejection
            # into an implementation failure or silently changing its limits.
            self.assertGreater(positive['during_minimum'], .98, (index, positive))
            self.assertEqual(positive['fit']['lag'], lag)
            rng = np.random.default_rng(90800+index)
            spectrum = np.fft.fft(source)
            wrong_spectrum = abs(spectrum)*np.exp(1j*rng.uniform(-np.pi, np.pi, 4096))
            wrong_spectrum[0] = spectrum[0]
            wrong = np.fft.ifft(wrong_spectrum)
            # Identical power spectrum, different waveform; give the negative
            # the full prefix search, not the positive's fitted lag/frequency.
            np.testing.assert_allclose(abs(np.fft.fft(wrong)), abs(spectrum), atol=1e-10)
            negative = self.assess(wrong, captures)
            self.assertFalse(negative['waveform_association_passed'], (index, negative))
            rows.append(dict(seed=90700+index, lag=lag, bias=[bias.real, bias.imag],
                             residual_hz=residual, positive=positive, same_spectrum_negative=negative))
        destination = os.environ.get('B210_CENTERED_MATRIX_OUTPUT')
        if destination is None:
            return
        root = Path(os.environ['TMPDIR']).resolve()
        output = Path(destination)
        self.assertEqual(output.resolve().parent, root)
        with output.open('x') as stream:
            json.dump(dict(schema_id='b210_centered_synthetic_validation_v1',
                           source_code_sha256=hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
                           positive_cases=24, same_spectrum_negative_cases=24,
                           accepted_positive_cases=sum(row['positive']['waveform_association_passed'] for row in rows),
                           accepted_negative_cases=sum(row['same_spectrum_negative']['waveform_association_passed'] for row in rows),
                           registered_all_positive_condition_met=all(row['positive']['waveform_association_passed'] for row in rows),
                           rows=rows,
                           rf_operations=0, model_windows=0, dataset_rows_read=0), stream, indent=2)
            stream.write('\n')

    def test_fit_ignores_entire_raw_tail_and_fixed_heldout_ignores_prefix(self):
        source, captures = self.fixture()
        raw = captures['during-tx']
        fit = match.fit_centered_source(raw, source, 3450, 125000)
        changed = raw.copy()
        changed[match.FIT_SAMPLES:] = 777+123j
        self.assertEqual(fit, match.fit_centered_source(changed, source, 3450, 125000))
        changed = raw.copy()
        changed[:match.FIT_SAMPLES] = 777+123j
        self.assertEqual(match._heldout_centered(raw, source, 3450, 125000, fit),
                         match._heldout_centered(changed, source, 3450, 125000, fit))
        changed[match.END_SAMPLES:] = -900j
        self.assertEqual(match._heldout_centered(raw, source, 3450, 125000, fit),
                         match._heldout_centered(changed, source, 3450, 125000, fit))

    def test_correct_prefix_does_not_accept_changed_later_source(self):
        source, captures = self.fixture()
        rng = np.random.default_rng(913)
        captures['during-tx'][match.FIT_SAMPLES:] = rng.normal(size=65535-match.FIT_SAMPLES)
        result = self.assess(source, captures)
        self.assertTrue(result['fit']['passed'])
        self.assertFalse(result['waveform_association_passed'])

    def test_one_bad_heldout_window_is_not_hidden_by_median(self):
        source, captures = self.fixture()
        captures['during-tx'][10*4096:11*4096] = 0
        result = self.assess(source, captures)
        self.assertTrue(result['checks']['during_median'])
        self.assertFalse(result['checks']['during_every_window'])
        self.assertFalse(result['waveform_association_passed'])

    def test_either_stopped_control_containing_source_fails(self):
        for tag in ('baseline', 'after-tx'):
            source, captures = self.fixture()
            captures[tag] = captures['during-tx'].copy()
            result = self.assess(source, captures)
            self.assertFalse(result['checks']['stopped_controls'])
            self.assertFalse(result['waveform_association_passed'])

    def test_zero_power_controls_are_finite_and_zero_power_during_fails(self):
        source, captures = self.fixture()
        captures['baseline'][:] = 0
        captures['after-tx'][:] = 0
        result = self.assess(source, captures)
        self.assertTrue(result['waveform_association_passed'])
        self.assertEqual(result['off_maximum'], 0)
        captures['during-tx'][:] = 0
        self.assertFalse(self.assess(source, captures)['waveform_association_passed'])

    def test_constant_and_single_tone_sources_are_not_identifiable(self):
        _, captures = self.fixture()
        for source in (np.ones(4096), np.exp(2j*np.pi*11*np.arange(4096)/4096)):
            with self.assertRaises(ValueError):
                self.assess(source, captures)

    def test_missing_nonfinite_shape_and_frequency_fail_closed(self):
        source, captures = self.fixture()
        with self.assertRaises(ValueError):
            self.assess(source, {'during-tx': captures['during-tx']})
        for bad in (source[:1024], np.full(4096, np.nan), np.full(4096, np.inf)):
            with self.assertRaises(ValueError):
                self.assess(bad, captures)
        for frequency, width in ((np.nan, 125000), (5001, 125000), (0, 0), (0, match.RATE/2)):
            with self.assertRaises(ValueError):
                match.assess_centered_source(source, captures, frequency, width)
        captures['after-tx'][50000] = np.nan
        with self.assertRaises(ValueError):
            self.assess(source, captures)


if __name__ == '__main__':
    unittest.main()
