"""RX background statistics, independent selection and real-format evidence binding."""
import copy
import asyncio
from unittest.mock import patch
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import numpy as np
spec=importlib.util.spec_from_file_location('bg',Path(__file__).resolve().parents[1]/'scripts/diagnose-b210-background.py')
bg=importlib.util.module_from_spec(spec);spec.loader.exec_module(bg)

class BackgroundTests(unittest.TestCase):
    def test_complete_tail_and_broadband_burst_not_dc(self):
        rng=np.random.default_rng(90703);z=rng.normal(size=65535)+1j*rng.normal(size=65535)
        z[12800:14080]*=100
        r=bg.stats(z)
        self.assertEqual(sum(x['count'] for x in r['raw_segments']),65535)
        self.assertEqual(sum(x['count'] for x in r['filtered_segments']),65279)
        self.assertEqual(r['events'],[{'start':12800,'stop':14080}])
        self.assertLess(r['peak_segment']['dc_power_fraction'],.1)
        self.assertGreater(r['peak_segment']['in_175khz_power_fraction'],.05)
        self.assertLess(r['peak_segment']['in_175khz_power_fraction'],.6)

    def test_constant_bias_differs_from_out_of_band_tone(self):
        a=bg.stats(np.ones(65535)*30j)
        self.assertAlmostEqual(a['peak_segment']['dc_power_fraction'],1.)
        n=np.arange(65535);b=bg.stats(30*np.exp(2j*np.pi*250000*n/bg.point.RATE))
        self.assertLess(b['filtered']['maximum'],.01)
        self.assertGreater(a['filtered']['p50'],29.9)
        for z in (np.zeros(65534),np.full(65535,np.nan)):
            with self.assertRaises(ValueError):bg.stats(z)

    def test_discovery_only_selection_and_failed_confirmation_cannot_reselect(self):
        rows=[dict(center_hz=f,round=i,statistics={'filtered':{'maximum':1+j,'p95':1+j}}) for i in range(3) for j,f in enumerate(bg.CENTERS)]
        chosen=bg.select_candidate(rows);self.assertEqual(chosen['candidate_hz'],bg.CENTERS[0])
        confirms=[dict(center_hz=f,round=i,statistics={'filtered':{'maximum':9,'p95':1}}) for i in range(3) for f in (2440000000,chosen['candidate_hz'])]
        self.assertFalse(bg.confirmation(confirms,chosen['candidate_hz'])['passed'])
        self.assertEqual(chosen,bg.select_candidate(rows))
        with self.assertRaises(ValueError):bg.select_candidate(rows[:-1])
        confirms[-1]['round']=0
        with self.assertRaises(ValueError):bg.confirmation(confirms,chosen['candidate_hz'])

    def test_retained_capture_prevents_any_new_radio_operation(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            root=Path(directory);(root/'capture-24').mkdir()
            with patch.object(bg,'ROOT',root),patch.object(bg.asyncio,'create_subprocess_exec') as spawn:
                with self.assertRaises(AssertionError):asyncio.run(bg.run(Path('/absent')))
                spawn.assert_not_called()
            self.assertFalse((root/'started.json').exists())

class NativeBackgroundTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']);self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        historical=json.loads((bg.live.affine.ROOT/'docs/evidence/B210_LO_REJECTION_AUDIT_2026-09-07.json').read_text())['cases']['fix1']['link_evidence']
        self.report=copy.deepcopy(historical['baseline']);self.plan=copy.deepcopy(historical['plans'][0])
        self.data=self.root/'iq.sigmf-data';self.meta=self.root/'iq.sigmf-meta';self.data.write_bytes(bytes(262140))
        self.report['dataset'].update(data_path=str(self.data),metadata_path=str(self.meta))
        self.meta.write_text(json.dumps({'global':{'core:sample_rate':2100000,'core:datatype':'ci16_le','sdrharness:sample_layout':'interleaved_iq'},
         'captures':[{'core:sample_start':0,'core:frequency':2440000000,'sdrharness:point_index':0,'sdrharness:rf_bandwidth_hz':1500000,'sdrharness:gain_db':40}]}))
        self.save()
    def save(self):
        (self.root/'report.json').write_text(json.dumps(self.report));(self.root/'plan.json').write_text(json.dumps(self.plan))
    def test_valid_native_and_content_change_affects_seal(self):
        seal,z=bg.native(self.root,self.plan);self.assertEqual(z.shape,(65535,))
        data=bytearray(self.data.read_bytes());data[17]=1;self.data.write_bytes(data)
        other,_=bg.native(self.root,self.plan);self.assertNotEqual(seal,other)
    def test_wrong_identity_quality_and_saved_plan_rejected(self):
        original=copy.deepcopy(self.report)
        for key,value in [('clipped_samples',1),('session_generation',7),('actual_center_hz',2430000000),('request_id',0)]:
            self.report=copy.deepcopy(original);self.report['points'][0][key]=value;self.save()
            with self.assertRaises(AssertionError):bg.native(self.root,self.plan)
        self.report=copy.deepcopy(original);self.report['points'][0]['rx_input']['front_panel_port']='RX2';self.save()
        with self.assertRaises(AssertionError):bg.native(self.root,self.plan)
        self.report=original;self.save();(self.root/'plan.json').write_text('{}')
        with self.assertRaises(AssertionError):bg.native(self.root,self.plan)
    def test_wrong_metadata_gain_rejected(self):
        m=json.loads(self.meta.read_text());m['captures'][0]['sdrharness:gain_db']=50;self.meta.write_text(json.dumps(m))
        with self.assertRaises(AssertionError):bg.native(self.root,self.plan)

if __name__=='__main__':unittest.main()
