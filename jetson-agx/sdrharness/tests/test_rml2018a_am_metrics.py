"""Analytic checks of diagnostic power fractions and estimator limitations."""
import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np
S=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(S))
spec=importlib.util.spec_from_file_location('am_metrics',S/'diagnose-rml2018a-am-metrics.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class AmMetricTests(unittest.TestCase):
    def tone(self):return np.exp(2j*np.pi*32*np.arange(1024)/1024)
    def test_mean_and_centered_power_decomposition(self):
        s=m.structure(2+self.tone())
        self.assertAlmostEqual(s['power'],5);self.assertAlmostEqual(s['window_mean_power_fraction'],.8)
        self.assertAlmostEqual(s['centered_fraction'],.2)
        for f in s['half_centered_fractions']:self.assertAlmostEqual(f,.2)
    def test_gain_invariant_fraction(self):
        x=2+self.tone();a=m.structure(x);b=m.structure(3j*x)
        self.assertAlmostEqual(b['power']/a['power'],9)
        for k in ('window_mean_power_fraction','centered_fraction','half_power_ratio'):self.assertAlmostEqual(a[k],b[k])
    def test_nearly_constant_reference_invalid_even_on_ideal_link(self):
        x=1+.001*self.tone();q=m.c.receive_quality('synchronized',x,x,30.)
        self.assertEqual(q['rx_sinr_reason'],'reference_not_identifiable');self.assertIsNone(q['rx_sinr_db'])
    def test_source_nonstationarity_alone_does_not_imply_bad_link(self):
        x=self.tone();x[512:]*=10
        self.assertAlmostEqual(m.structure(x)['half_power_ratio'],100)
        q=m.c.receive_quality('synchronized',x,3j*x,30.)
        self.assertEqual(q['rx_sinr_status'],'estimated');self.assertAlmostEqual(q['rx_sinr_db'],30)
    def test_carrier_inclusive_metric_is_not_modulation_only(self):
        x=2+self.tone();q=m.c.receive_quality('synchronized',x,x,30.)
        self.assertEqual(q['rx_sinr_status'],'estimated');self.assertAlmostEqual(q['rx_sinr_db'],30)
        self.assertGreater(m.structure(x)['window_mean_power_fraction'],.5)

if __name__=='__main__':unittest.main()
