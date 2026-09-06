"""Separated LO identification, independent controls and prefix isolation; no RF."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np
spec=importlib.util.spec_from_file_location('lo_diag',Path(__file__).resolve().parents[1]/'scripts/diagnose-b210-lo-offset.py')
lo=importlib.util.module_from_spec(spec);spec.loader.exec_module(lo)

class LoOffsetTests(unittest.TestCase):
    def fixture(self,offset=250000):
        rng=np.random.default_rng(90701)
        source=.1*(rng.normal(size=1024)+1j*rng.normal(size=1024))+.05j
        fit=dict(lag=37,total_frequency_hz=3500.)
        n=np.arange(lo.point.COUNT)
        raw=lo.point.design_matrix(source,fit,(0,),len(n))@np.array([3+2j,.2-.1j,.03j])
        raw+=(2+.4j)*np.exp(2j*np.pi*(offset+3500)*n/lo.point.RATE)
        controls={tag:.001*(rng.normal(size=len(n))+1j*rng.normal(size=len(n))) for tag in ('baseline','after-tx')}
        return source,raw,controls,fit

    def test_both_signed_lines_detected_and_source_bias_separated(self):
        for offset in (-250000,250000):
            source,raw,controls,fit=self.fixture(offset)
            result=lo.extra_line(source,raw,controls,fit,offset)
            self.assertTrue(result['line_observed'])
            self.assertLess(abs(result['peak_minus_expected_hz']),3)
            coefficients=np.array([complex(*v) for v in result['models']['robust']['coefficients']])
            self.assertLess(abs(coefficients[0]-(3+2j)),.02)
            self.assertLess(abs(coefficients[1]-(.2-.1j)),.01)
            self.assertLess(result['models']['robust']['heldout_residual_rms'],.6)

    def test_matching_stopped_line_prevents_source_attribution(self):
        source,raw,controls,fit=self.fixture()
        controls['after-tx']=raw.copy()
        self.assertFalse(lo.extra_line(source,raw,controls,fit,250000)['line_observed'])

    def test_heldout_mutation_cannot_change_frequency_or_coefficients(self):
        source,raw,controls,fit=self.fixture()
        a=lo.extra_line(source,raw,controls,fit,250000)
        raw[lo.point.FIT:]+=100j
        b=lo.extra_line(source,raw,controls,fit,250000)
        self.assertEqual(a['peak_hz'],b['peak_hz'])
        self.assertEqual(a['models']['robust']['coefficients'],b['models']['robust']['coefficients'])
        self.assertGreater(b['models']['robust']['heldout_residual_rms'],90)

    def test_coincident_unregistered_or_nonfinite_input_rejected(self):
        source,raw,controls,fit=self.fixture()
        for offset in (0,999999):
            with self.assertRaises(ValueError):lo.extra_line(source,raw,controls,fit,offset)
        raw[0]=np.nan
        with self.assertRaises(ValueError):lo.extra_line(source,raw,controls,fit,250000)

if __name__=='__main__':unittest.main()
