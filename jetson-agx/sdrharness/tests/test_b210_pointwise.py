"""1024-unit alignment, raw-domain channel identification and complete residual coverage."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec=importlib.util.spec_from_file_location('pointwise',Path(__file__).resolve().parents[1]/'scripts/diagnose-b210-1024-pointwise.py')
point=importlib.util.module_from_spec(spec);spec.loader.exec_module(point)


class PointwiseTests(unittest.TestCase):
    def fixture(self):
        rng=np.random.default_rng(96102)
        source=.2*(rng.normal(size=1024)+1j*rng.normal(size=1024))+.1+.04j
        fit=dict(lag=137,total_frequency_hz=3500.)
        design=point.design_matrix(source,fit,(0,),point.COUNT)
        coefficients=np.array([2+.7j,.6-.2j,.03+.02j])
        raw=design@coefficients
        controls={tag:.01*(rng.normal(size=point.COUNT)+1j*rng.normal(size=point.COUNT)) for tag in ('baseline','after-tx')}
        return source,fit,raw,controls

    def test_exact_scalar_channel_separates_carrier_bias_and_receiver_dc(self):
        source,fit,raw,_=self.fixture()
        coefficients,_=point.solve_channel(point.design_matrix(source,fit,(0,),point.FIT),raw[:point.FIT],True)
        np.testing.assert_allclose(coefficients,[2+.7j,.6-.2j,.03+.02j],atol=1e-12)
        self.assertGreater(abs(source.mean()),.08)

    def test_robust_prefix_fit_retains_pulse_in_heldout_residual(self):
        source,fit,raw,_=self.fixture()
        design=point.design_matrix(source,fit,(0,),point.COUNT)
        damaged=raw.copy();damaged[1000:1100]+=100j;damaged[40000:40128]+=150j
        ordinary,_=point.solve_channel(design[:point.FIT],damaged[:point.FIT],False)
        robust,metrics=point.solve_channel(design[:point.FIT],damaged[:point.FIT],True)
        self.assertLess(np.linalg.norm(robust-np.array([2+.7j,.6-.2j,.03+.02j])),np.linalg.norm(ordinary-np.array([2+.7j,.6-.2j,.03+.02j]))/100)
        self.assertGreater(metrics['weights_below_half_fraction'],0)
        self.assertGreater(point.rms((damaged-design@robust)[40000:40128]),140)

    def test_fir_ground_truth_predicts_independent_tail_better_than_scalar(self):
        source,fit,_,_=self.fixture()
        design=point.design_matrix(source,fit,tuple(range(-4,5)),point.COUNT)
        coefficients=np.zeros(11,dtype=complex);coefficients[4]=2+.7j;coefficients[2]=.3-.1j;coefficients[7]=-.2j
        coefficients[-2:]=[.6-.2j,.03+.02j]
        raw=design@coefficients
        fitted,_=point.solve_channel(design[:point.FIT],raw[:point.FIT],True)
        scalar=point.design_matrix(source,fit,(0,),point.COUNT)
        h,_=point.solve_channel(scalar[:point.FIT],raw[:point.FIT],True)
        self.assertLess(point.rms((raw-design@fitted)[point.FIT:]),1e-10)
        self.assertGreater(point.rms((raw-scalar@h)[point.FIT:]),.05)

    def test_alignment_and_all_sample_segments_including_tail(self):
        source,fit,raw,controls=self.fixture();saved=raw.copy()
        report,arrays=point.compare(source,raw,controls,3500.,1000000.)
        self.assertTrue(report['alignment']['usable'])
        self.assertEqual(report['alignment']['lag'],fit['lag'])
        self.assertLess(abs(report['alignment']['residual_frequency_hz']),1)
        self.assertEqual(sum(row['count'] for row in report['segments']),65535)
        self.assertEqual(len(report['segments']),512);self.assertEqual(report['segments'][-1]['count'],127)
        self.assertEqual(len(arrays['error']),65535)
        np.testing.assert_array_equal(saved,raw)

    def test_later_sample_slip_is_reported_not_applied_to_primary_prediction(self):
        source,fit,raw,controls=self.fixture()
        changed=point.design_matrix(source,dict(lag=142,total_frequency_hz=3500.),(0,),point.COUNT)@np.array([2+.7j,.6-.2j,.03+.02j])
        raw[24576:]=changed[24576:]
        report,_=point.compare(source,raw,controls,3500.,1000000.)
        rows=report['local_lag_diagnostic']
        self.assertTrue(all(row['delta_from_fixed_lag']==5 and row['high_coherence'] for row in rows[24:]))
        self.assertGreater(report['models']['scalar_robust']['heldout_residual_rms'],.5)

    def test_raw_tail_cannot_change_alignment_or_channel_coefficients(self):
        source,_,raw,controls=self.fixture()
        before,_=point.compare(source,raw,controls,3500.,1000000.)
        raw[point.FIT:]+=100j
        after,_=point.compare(source,raw,controls,3500.,1000000.)
        self.assertEqual(before['alignment'],after['alignment'])
        for name in before['models']:
            self.assertEqual(before['models'][name]['coefficients'],after['models'][name]['coefficients'])

    def test_nonfinite_shape_and_unidentifiable_design_rejected(self):
        source,_,raw,controls=self.fixture()
        with self.assertRaises(ValueError):point.compare(source[:1000],raw,controls,3500.,1000000.)
        raw[0]=np.nan
        with self.assertRaises(ValueError):point.compare(source,raw,controls,3500.,1000000.)
        with self.assertRaises(ValueError):point.solve_channel(np.ones((point.FIT,3)),np.ones(point.FIT),True)

    def test_posthoc_delay_interpolation_does_not_invent_clock_drift_for_fixed_delay(self):
        source,fit,raw,_=self.fixture();saved=raw.copy()
        result=point.fine_lag_diagnostic(source,raw,fit)
        self.assertEqual(result['used_windows'],63)
        self.assertLess(abs(result['apparent_delay_slope_ppm']),1)
        self.assertFalse(result['applied_to_prediction'])
        np.testing.assert_array_equal(raw,saved)


if __name__=='__main__':unittest.main()
