"""V3 unit checks and an explicit, exclusive, independently seeded matrix."""
import copy
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest import mock

import numpy as np

spec = importlib.util.spec_from_file_location('v3_fixture', Path(__file__).with_name('test_b210_centered_source.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
match = base.match


def fixture(**kwargs):
    return base.CenteredSourceTests().fixture(**kwargs)


def compact(result):
    keys = ('schema_id', 'waveform_association_passed', 'checks', 'fit', 'source_effective_bins',
            'during_median', 'during_minimum', 'off_maximum', 'surrogate_maximum',
            'source_wrong_margin', 'surrogate_count', 'live_rf_qualified', 'recognizer_available')
    value = {key: result[key] for key in keys}
    value['surrogate_maxima'] = [row['maximum_coherence'] for row in result['surrogates']]
    return value


class SourceV3Tests(unittest.TestCase):
    def test_old_false_rejections_remain_failed_in_v2_and_are_resolved_in_v3(self):
        evidence = json.loads((base.SCRIPT.parents[3]/'docs/evidence/B210_CENTERED_SOURCE_AUDIT_2026-09-06.json').read_text())
        for seed, lag, bias, residual in ((90708, 776, 0j, -80), (90721, 4095, 2+1.5j, 0)):
            source, captures = fixture(seed=seed, lag=lag, bias=bias, residual=residual)
            old = match.assess_centered_source(source, captures, 3450, 125000)
            saved = next(row['positive'] for row in evidence['rows'] if row['seed']==seed)
            for key in saved:
                self.assertEqual(old[key], saved[key])
            self.assertFalse(old['waveform_association_passed'])
            new = match.assess_centered_source_v3(source, captures, 3450, 125000)
            self.assertTrue(new['waveform_association_passed'], compact(new))
            self.assertFalse(new['legacy_v2_three_surrogate_passed'])

    def test_31_full_search_controls_are_deterministic_without_mutating_inputs(self):
        source, captures = fixture(seed=91500)
        original = source.copy()
        received = captures['during-tx'].copy()
        one = match.assess_centered_source_v3(source, captures, 3450, 125000)
        two = match.assess_centered_source_v3(source, captures, 3450, 125000)
        self.assertEqual(one, two)
        self.assertEqual([row['seed'] for row in one['surrogates']], list(range(9060701, 9060732)))
        self.assertEqual(one['surrogate_count'], 31)
        self.assertFalse(one['live_rf_qualified'])
        self.assertFalse(one['recognizer_available'])
        self.assertEqual(one['independent_labels'], 0)
        np.testing.assert_array_equal(source, original)
        np.testing.assert_array_equal(captures['during-tx'], received)

    def test_tail_cannot_change_any_of_the_31_prefix_fits(self):
        source, captures = fixture(seed=91501)
        one = match.assess_centered_source_v3(source, captures, 3450, 125000)
        captures['during-tx'][match.FIT_SAMPLES:] = 123+789j
        two = match.assess_centered_source_v3(source, captures, 3450, 125000)
        self.assertEqual(one['fit'], two['fit'])
        self.assertEqual([row['fit'] for row in one['surrogates']], [row['fit'] for row in two['surrogates']])
        self.assertFalse(two['waveform_association_passed'])

    def test_relative_margin_uses_worst_window_and_cannot_bypass_other_gates(self):
        source, captures = fixture(seed=91502)
        template = match.assess_centered_source(source, captures, 3450, 125000)
        def assess(minimum=.8, maximum=.5, fail=None):
            value = copy.deepcopy(template)
            value['during_minimum'] = minimum
            value['surrogates'] = [dict(maximum_coherence=maximum)]*3
            if fail:
                value['checks'][fail] = False
            with mock.patch.object(match, 'assess_centered_source', return_value=value), \
                 mock.patch.object(match, '_centered_surrogate', return_value=dict(maximum_coherence=maximum)):
                return match.assess_centered_source_v3(source, captures, 3450, 125000)
        self.assertTrue(assess()['waveform_association_passed'])
        self.assertFalse(assess(maximum=.500001)['waveform_association_passed'])
        self.assertFalse(assess(minimum=.6)['waveform_association_passed'])
        for gate in ('prefix_estimate', 'during_median', 'during_every_window', 'stopped_controls', 'source_off_margin'):
            self.assertFalse(assess(fail=gate)['waveform_association_passed'])

    def test_missing_or_nonfinite_input_still_fails_before_surrogate_work(self):
        source, captures = fixture(seed=91503)
        with mock.patch.object(match, '_centered_surrogate') as surrogate:
            with self.assertRaises(ValueError):
                match.assess_centered_source_v3(source, {}, 3450, 125000)
            captures['baseline'][0] = np.nan
            with self.assertRaises(ValueError):
                match.assess_centered_source_v3(source, captures, 3450, 125000)
            surrogate.assert_not_called()


def registered_matrix():
    root = Path('/var/tmp/sdrharness-dev/b210-source-v3-906h')
    if root.resolve()!=root or not root.is_dir():
        raise ValueError('registered feature directory required')
    # Separate from unit regression; do not consume the independent matrix on
    # every unittest discovery or rerun a failed matrix under changed criteria.
    with (root/'matrix-started.json').open('x') as marker:
        json.dump(dict(started_at_ns=time.time_ns(),maximum_positive_cases=72,maximum_negative_cases=72), marker)
    report = dict(schema_id='b210_source_v3_synthetic_matrix_v1', status='incomplete',
                  source_code_sha256=hashlib.sha256(base.SCRIPT.read_bytes()).hexdigest(), rows=[],
                  rf_operations=0, model_windows=0, dataset_rows_read=0)
    try:
        for index, (lag, bias, residual, width) in enumerate(itertools.product(
                (0,776,4095), (0j,2+1.5j), (-80.,0.,65.,150.), (32000,125000,350000))):
            source, captures = fixture(seed=91800+index, lag=lag, bias=bias, residual=residual, half_width=width)
            positive = match.assess_centered_source_v3(source, captures, 3450, width)
            spectrum = np.fft.fft(source)
            rng = np.random.default_rng(92800+index)
            wrong_spectrum = abs(spectrum)*np.exp(1j*rng.uniform(-np.pi, np.pi, 4096))
            wrong_spectrum[0] = spectrum[0]
            wrong = np.fft.ifft(wrong_spectrum)
            negative = match.assess_centered_source_v3(wrong, captures, 3450, width)
            report['rows'].append(dict(source_seed=91800+index,wrong_seed=92800+index,lag=lag,
                                       bias=[bias.real,bias.imag],residual_hz=residual,half_width_hz=width,
                                       positive=compact(positive),negative=compact(negative)))
            if (index+1)%12==0:
                print(json.dumps(dict(completed_pairs=index+1)),flush=True)
        report['accepted_positive_cases'] = sum(row['positive']['waveform_association_passed'] for row in report['rows'])
        report['accepted_negative_cases'] = sum(row['negative']['waveform_association_passed'] for row in report['rows'])
        report['registered_acceptance_passed'] = report['accepted_positive_cases']==72 and report['accepted_negative_cases']==0
        report['status'] = 'complete'
    finally:
        with (root/'matrix.json').open('x') as output:
            json.dump(report,output,indent=2);output.write('\n')
    print(json.dumps({key:value for key,value in report.items() if key!='rows'}))
    if not report['registered_acceptance_passed']:
        raise SystemExit('Registered acceptance failed; retain all evidence and limits')


if __name__ == '__main__':
    if sys.argv[1:]==['--registered-matrix']:
        registered_matrix()
    else:
        unittest.main()
