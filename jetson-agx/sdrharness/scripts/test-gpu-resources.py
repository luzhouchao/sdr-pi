#!/usr/bin/env python3
"""Negative checks for S4b's pre-registered acceptance reducer; no GPU required."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('resource_validation',Path(__file__).with_name('validate-gpu-resources.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.samples=[dict(elapsed=i*5,max_temp_c=50,available_kib=8*1024**2,pss_kib=2*1024**2,nvmap_kib=12*1024**2) for i in range(240)]
        self.rounds=[dict(history_bytes=(0,2048,8192,16384)[i%4],mamba_seconds=.25,planner_seconds=2) for i in range(96)]

    def test_valid_bounded_run(self):
        self.assertEqual(m.evaluate(self.samples,self.rounds,1200)['mamba_seconds']['0']['p95'],.25)

    def test_short_or_missing_measurement_rejected(self):
        for samples,rounds,duration in [(self.samples,self.rounds,1199),(self.samples[:100],self.rounds,1200),(self.samples,self.rounds[:-1],1200)]:
            with self.assertRaises(AssertionError):m.evaluate(samples,rounds,duration)

    def test_resource_ceiling_or_growth_rejected(self):
        for key,value,after in [('max_temp_c',80,0),('available_kib',1,0),('pss_kib',25*1024**2,0),('nvmap_kib',25*1024**2,0),('pss_kib',3*1024**2,180),('nvmap_kib',13*1024**2,180),('max_temp_c',56,180)]:
            samples=copy.deepcopy(self.samples)
            for row in samples[after:]:row[key]=value
            with self.assertRaises(AssertionError,msg=key):m.evaluate(samples,self.rounds,1200)

    def test_missing_gpu_temperature_never_passes(self):
        self.samples[100]['missing_temperatures'] = ['gpu']
        with self.assertRaisesRegex(AssertionError, 'temperature coverage'):
            m.evaluate(self.samples,self.rounds,1200)

    def test_explicit_gpu_exception_never_waives_other_gates(self):
        self.samples[100]['missing_temperatures'] = ['gpu']
        m.evaluate(self.samples,self.rounds,1200,allow_missing_gpu_temperature=True)
        self.samples[100]['missing_temperatures'] = ['cpu','gpu']
        with self.assertRaises(AssertionError):
            m.evaluate(self.samples,self.rounds,1200,allow_missing_gpu_temperature=True)
        self.samples[100]['missing_temperatures'] = ['gpu']
        self.samples[100]['max_temp_c'] = 81
        with self.assertRaises(AssertionError):
            m.evaluate(self.samples,self.rounds,1200,allow_missing_gpu_temperature=True)

    def test_latency_and_late_degradation_rejected(self):
        for key,value,after in [('mamba_seconds',6,0),('planner_seconds',61,0),('mamba_seconds',1,48),('planner_seconds',5,48)]:
            rounds=copy.deepcopy(self.rounds)
            for row in rounds[after:]:row[key]=value
            with self.assertRaises(AssertionError,msg=key):m.evaluate(self.samples,rounds,1200)


if __name__=='__main__':unittest.main()
