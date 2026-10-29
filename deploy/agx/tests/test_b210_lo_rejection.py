"""Fixed FIR leakage repair, original IQ coordinates and fail-closed model blocks."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile
import os
import json
import asyncio
import numpy as np
spec=importlib.util.spec_from_file_location('repair',Path(__file__).resolve().parents[1]/'scripts/repair-b210-lo-leakage.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

class RejectionTests(unittest.TestCase):
    def source(self):
        rng=np.random.default_rng(90702)
        spectrum=rng.normal(size=1024)+1j*rng.normal(size=1024)
        spectrum[abs(np.fft.fftfreq(1024,1/r.point.RATE))>60000]=0
        z=np.fft.ifft(spectrum);return z/r.point.rms(z)*.1+.04j

    def test_response_and_nonzero_dc_preserved(self):
        c=r.filter_contract();self.assertLess(c['passband_max_amplitude_error'],.001);self.assertLess(c['stopband_max_db'],-80)
        np.testing.assert_allclose(r.reject(np.ones(8192)*(2+3j)),2+3j,atol=1e-14)
        retained=r.source_retention(self.source());self.assertGreater(retained['power_fraction'],.99);self.assertLess(retained['complex_mean_error'],1e-14)

    def test_separated_lo_rejected_but_inband_carrier_kept(self):
        n=np.arange(8192)
        for f,maximum in ((253500,1e-4),(3500,1.001)):
            z=r.reject(np.exp(2j*np.pi*f*n/r.point.RATE));self.assertLess(r.point.rms(z),maximum)
            if f==3500:self.assertGreater(r.point.rms(z),.999)

    def test_local_fir_dependency_and_coordinates(self):
        rng=np.random.default_rng(7);z=rng.normal(size=8192)+1j*rng.normal(size=8192)
        a=r.reject(z);z[7000:]+=100j;b=r.reject(z)
        np.testing.assert_array_equal(a[:7000-256],b[:7000-256])
        np.testing.assert_allclose(r.reject(z[1000-128:2000+128]),b[1000-128:2000-128])
        for invalid in (np.zeros(256),[complex('nan')]*300,np.zeros((300,2))):
            with self.assertRaises(ValueError):r.reject(invalid)

    def fixture(self,offset):
        source=self.source();n=np.arange(r.point.COUNT);fit=dict(lag=31,total_frequency_hz=3500.)
        raw=r.point.design_matrix(source,fit,(0,),len(n))@np.array([20+5j,0j,0j])
        raw+=2*np.exp(2j*np.pi*(3500+offset)*n/r.point.RATE)
        rng=np.random.default_rng(88)
        captures={tag:.01*(rng.normal(size=len(n))+1j*rng.normal(size=len(n))) for tag in ('baseline','after-tx')}
        captures['during-tx']=raw;return source,captures

    def test_fixed_offset_repairs_and_retains_all_valid_samples(self):
        source,captures=self.fixture(250000)
        report,inputs=r.evaluate(source,captures,3500.,250000)
        self.assertTrue(report['leakage_repair_passed']);self.assertTrue(report['model_control_passed'])
        self.assertEqual(len(inputs),4);self.assertEqual(len(report['heldout_blocks']),11)
        self.assertEqual(sum(x['samples'] for x in report['segments']),65535-256)
        self.assertEqual(report['fixed_model_block']['raw_start'],32768)

    def test_inband_bias_and_noisy_fixed_window_do_not_claim_repair(self):
        source,captures=self.fixture(0)
        report,_=r.evaluate(source,captures,3500.,0)
        self.assertFalse(report['leakage_repair_passed']);self.assertLess(abs(report['lo_band_suppression_db']),.1)
        source,captures=self.fixture(250000)
        captures['during-tx'][32768:36864]+=100j
        report,inputs=r.evaluate(source,captures,3500.,250000)
        self.assertFalse(report['model_control_passed']);self.assertEqual(inputs,{})

    def test_failed_fixed_gates_skip_model_loading_and_warmup(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            root=Path(directory);report={'model_inputs':{}}
            (root/'prepared.json').write_text(json.dumps(report))
            with patch.object(r,'ROOT',root),patch.object(r,'prepare',return_value=(report,{})),patch.object(r.live.affine,'module') as backend:
                asyncio.run(r.infer());backend.assert_not_called()
            receipt=json.loads((root/'inference.json').read_text())
            self.assertEqual(receipt['model_windows'],0);self.assertEqual(receipt['warmup_windows'],0)
            self.assertEqual(receipt['status'],'skipped_no_qualified_fixed_blocks')

    def test_changed_preparation_rejected_before_any_model_attempt(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            root=Path(directory);(root/'prepared.json').write_text('{}')
            with patch.object(r,'ROOT',root),patch.object(r,'prepare',return_value=({'changed':True},{})):
                with self.assertRaises(AssertionError):asyncio.run(r.infer())
            self.assertFalse((root/'inference-started.json').exists())

if __name__=='__main__':unittest.main()
