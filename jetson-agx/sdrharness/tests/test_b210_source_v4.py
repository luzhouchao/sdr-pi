"""Conditional phase-null checks and a separately invoked independent matrix."""
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import signal
import sys
import time
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location('v4_fixture', Path(__file__).with_name('test_b210_source_v3.py'))
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
match = prior.match


def compact(result):
    value = prior.compact(result)
    value['stopped_phase_null'] = result['stopped_phase_null']
    return value


class SourceV4Tests(unittest.TestCase):
    def flat_spectra(self, bins):
        spectrum = np.zeros(4096, dtype=complex)
        spectrum[1:bins+1] = 1
        rng = np.random.default_rng(95101)
        noise = np.zeros((16,4096), dtype=complex)
        noise[:,1:bins+1] = np.exp(1j*rng.uniform(-np.pi,np.pi,(16,bins)))
        return np.fft.ifft(spectrum), np.fft.ifft(noise,axis=1)

    def test_uniform_spectra_match_analytic_bound_and_dimension_scaling(self):
        values = []
        for bins in (128,512):
            source,noise = self.flat_spectra(bins)
            result = match.phase_null_stopped_control(source,noise)
            expected = np.sqrt(np.log(16*16/1e-4)/bins)/np.cos(np.pi/16)
            np.testing.assert_allclose([row['threshold'] for row in result['windows']],expected,atol=1e-14)
            np.testing.assert_allclose([row['overlap_effective_dimension'] for row in result['windows']],bins,atol=1e-10)
            self.assertFalse(result['assumption_verified_for_input'])
            self.assertFalse(result['production_calibration'])
            values.append(result['windows'][0]['threshold'])
        self.assertAlmostEqual(values[0]/values[1],2)

    def test_concentrated_spectrum_is_unidentifiable_not_clamped_to_pass(self):
        source,noise = self.flat_spectra(16)
        result = match.phase_null_stopped_control(source,noise)
        self.assertFalse(result['passed'])
        self.assertTrue(all(row['threshold']>.5 and not row['identifiable'] for row in result['windows']))

    def test_zero_power_and_nonfinite_or_missing_windows(self):
        source,noise = self.flat_spectra(128)
        result = match.phase_null_stopped_control(source,np.zeros_like(noise))
        self.assertTrue(result['passed'])
        self.assertTrue(all(row['threshold']==row['correlation']==0 for row in result['windows']))
        for bad in (noise[:8],np.full_like(noise,np.nan)):
            with self.assertRaises(ValueError):
                match.phase_null_stopped_control(source,bad)
        with self.assertRaises(ValueError):
            match.phase_null_stopped_control(np.zeros(4096),noise)

    def test_old_narrowband_failures_are_preserved_and_v4_resolves_them(self):
        evidence = json.loads((prior.base.SCRIPT.parents[3]/'docs/evidence/B210_SOURCE_V3_AUDIT_2026-09-06.json').read_text())
        for seed,bias,residual in ((91827,0j,0),(91842,2+1.5j,65)):
            source,captures = prior.fixture(seed=seed,lag=776,bias=bias,residual=residual,half_width=32000)
            old = match.assess_centered_source_v3(source,captures,3450,32000)
            saved = next(row['positive'] for row in evidence['rows'] if row['source_seed']==seed)
            for key in ('checks','fit','during_minimum','off_maximum','source_wrong_margin'):
                self.assertEqual(old[key],saved[key])
            self.assertFalse(old['waveform_association_passed'])
            new = match.assess_centered_source_v4(source,captures,3450,32000)
            self.assertFalse(new['legacy_v3_passed'])
            self.assertTrue(new['waveform_association_passed'],compact(new))
            self.assertFalse(new['live_rf_qualified'])
            self.assertFalse(new['recognizer_available'])

    def test_independent_window_ffts_cannot_leak_other_windows_or_change_raw(self):
        source,captures = prior.fixture(seed=95102)
        raw = captures['during-tx'];saved = raw.copy()
        fit = match.fit_centered_source(raw,source,3450,125000)
        first = match.v4_heldout_windows(raw,3450,125000,fit)
        np.testing.assert_array_equal(raw,saved)
        changed = raw.copy();changed[9*4096:10*4096] = 999+777j
        second = match.v4_heldout_windows(changed,3450,125000,fit)
        for index in (0,1,3,4,5,6,7):
            np.testing.assert_array_equal(first[index],second[index])
        changed[:match.FIT_SAMPLES] = -555j
        np.testing.assert_array_equal(second,match.v4_heldout_windows(changed,3450,125000,fit))

    def test_either_stopped_capture_containing_source_still_fails(self):
        for tag in ('baseline','after-tx'):
            source,captures = prior.fixture(seed=95103)
            captures[tag] = captures['during-tx'].copy()
            result = match.assess_centered_source_v4(source,captures,3450,125000)
            self.assertFalse(result['checks']['stopped_controls'])
            self.assertFalse(result['waveform_association_passed'])

    def test_one_bad_source_window_cannot_be_rescued_by_noise_bound(self):
        source,captures = prior.fixture(seed=95104)
        captures['during-tx'][10*4096:11*4096] = 0
        result = match.assess_centered_source_v4(source,captures,3450,125000)
        self.assertFalse(result['checks']['during_every_window'])
        self.assertFalse(result['waveform_association_passed'])


def registered_matrix():
    root = Path('/var/tmp/sdrharness-dev/b210-source-v4-906i')
    if root.resolve()!=root or not root.is_dir():
        raise ValueError('registered feature directory required')
    with (root/'matrix-started.json').open('x') as marker:
        json.dump(dict(started_at_ns=time.time_ns(),maximum_positive_cases=72,maximum_negative_cases=72),marker)
    report = dict(schema_id='b210_source_v4_synthetic_matrix_v1',status='incomplete',
                  source_code_sha256=hashlib.sha256(prior.base.SCRIPT.read_bytes()).hexdigest(),rows=[],
                  rf_operations=0,model_windows=0,dataset_rows_read=0)
    def terminate(signum,frame):
        raise TimeoutError('matrix interrupted; retain partial evidence')
    previous = signal.signal(signal.SIGTERM,terminate)
    try:
        for index,(lag,bias,residual,width) in enumerate(itertools.product(
                (0,776,4095),(0j,2+1.5j),(-80.,0.,65.,150.),(32000,125000,350000))):
            source,captures = prior.fixture(seed=93800+index,lag=lag,bias=bias,residual=residual,half_width=width)
            positive = match.assess_centered_source_v4(source,captures,3450,width)
            wrong = match._phase_surrogate(source,94800+index)
            negative = match.assess_centered_source_v4(wrong,captures,3450,width)
            report['rows'].append(dict(source_seed=93800+index,wrong_seed=94800+index,lag=lag,
                                       bias=[bias.real,bias.imag],residual_hz=residual,half_width_hz=width,
                                       positive=compact(positive),negative=compact(negative)))
            if (index+1)%12==0:
                print(json.dumps(dict(completed_pairs=index+1)),flush=True)
        report['accepted_positive_cases'] = sum(row['positive']['waveform_association_passed'] for row in report['rows'])
        report['accepted_negative_cases'] = sum(row['negative']['waveform_association_passed'] for row in report['rows'])
        report['registered_acceptance_passed'] = report['accepted_positive_cases']==72 and report['accepted_negative_cases']==0
        report['status'] = 'complete'
    finally:
        signal.signal(signal.SIGTERM,previous)
        with (root/'matrix.json').open('x') as output:
            json.dump(report,output,indent=2);output.write('\n')
    print(json.dumps({key:value for key,value in report.items() if key!='rows'}))
    if not report['registered_acceptance_passed']:
        raise SystemExit('Registered acceptance failed; retain all evidence and limits')


if __name__=='__main__':
    if sys.argv[1:]==['--registered-matrix']:
        registered_matrix()
    else:
        unittest.main()
