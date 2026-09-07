"""Real-format report/identity/hash negatives; all IQ here is synthetic zero data."""
import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import numpy as np

spec=importlib.util.spec_from_file_location('v4_live',Path(__file__).resolve().parents[1]/'scripts/validate-b210-v4-affine.py')
live=importlib.util.module_from_spec(spec);spec.loader.exec_module(live)


class V4LiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        history=json.loads((live.SCRIPTS.resolve().parents[2]/'docs/evidence/B210_RX_AFFINE_AUDIT_2026-09-06.json').read_text())
        self.link=copy.deepcopy(history['links']['tone'])
        self.link['feature_directory']=str(self.root)
        self.link['radio_before']=self.link['radio_after']=history['final_radio_state']
        for tag,field in (('baseline','baseline'),('during-tx','during_tx'),('after-tx','after_tx')):
            directory=self.root/tag;directory.mkdir()
            data=directory/'test.sigmf-data';data.write_bytes(bytes(262140))
            meta=directory/'test.sigmf-meta'
            meta.write_text(json.dumps({'global':{'core:datatype':'ci16_le','core:sample_rate':2500000,
                'sdrharness:sample_layout':'interleaved_iq'},'captures':[{'core:sample_start':0,'core:frequency':2440000000,
                'sdrharness:point_index':0,'sdrharness:rf_bandwidth_hz':1000000,'sdrharness:gain_db':40}]}))
            report=self.link[field]
            report['dataset']['data_path']=str(data);report['dataset']['metadata_path']=str(meta)
        self.save()

    def save(self):
        (self.root/'link-summary.json').write_text(json.dumps(self.link))
        for tag,field in (('baseline','baseline'),('during-tx','during_tx'),('after-tx','after_tx')):
            (self.root/f'{tag}-report.json').write_text(json.dumps(self.link[field]))

    def test_valid_capture_reports_bind_all_three_raw_and_metadata_hashes(self):
        result=live.validate_capture_root(self.root,'tone')
        self.assertEqual(len(result['captures']),3)
        self.assertEqual(len(result['hashes']),10)
        self.assertEqual(result['captures'][1]['request_id'],self.link['during_tx']['points'][0]['request_id'])

    def test_wrong_physical_rx_even_in_consistent_parent_and_child_is_rejected(self):
        self.link['during_tx']['points'][0]['rx_input']['front_panel_port']='RX2';self.save()
        with self.assertRaises(AssertionError):live.validate_capture_root(self.root,'tone')

    def test_request_session_quality_or_restoration_conflict_is_rejected(self):
        original=copy.deepcopy(self.link)
        for field,value in (('session_generation',123),('dropped_samples',1),('clipped_samples',1),('request_id',0)):
            self.link=copy.deepcopy(original)
            self.link['during_tx']['points'][0][field]=value;self.save()
            with self.assertRaises(AssertionError):live.validate_capture_root(self.root,'tone')
        self.link=copy.deepcopy(original);self.link['restoration_errors']=['not restored'];self.save()
        with self.assertRaises(AssertionError):live.validate_capture_root(self.root,'tone')

    def test_metadata_gain_or_symlink_input_is_rejected(self):
        path=self.root/'during-tx/test.sigmf-meta';original=path.read_text()
        value=json.loads(original);value['captures'][0]['sdrharness:gain_db']=50
        path.write_text(json.dumps(value))
        with self.assertRaises(AssertionError):live.validate_capture_root(self.root,'tone')
        path.write_text(original)
        data=self.root/'during-tx/test.sigmf-data';data.unlink()
        data.symlink_to(self.root/'baseline/test.sigmf-data')
        with self.assertRaises(AssertionError):live.validate_capture_root(self.root,'tone')

    def test_raw_hash_change_invalidates_sealed_preparation_before_analysis(self):
        before=live.validate_capture_root(self.root,'tone')
        with mock.patch.object(live,'inventory',return_value=before):live.seal(self.root,self.root)
        data=self.root/'during-tx/test.sigmf-data'
        raw=bytearray(data.read_bytes());raw[100]=1;data.write_bytes(raw)
        after=live.validate_capture_root(self.root,'tone')
        self.assertNotEqual(before,after)
        with mock.patch.object(live,'inventory',return_value=after),mock.patch.object(live.match,'analyze') as analyze:
            with self.assertRaises(AssertionError):live.prepare(self.root)
            analyze.assert_not_called()

    def test_failed_source_gate_cannot_load_model_or_create_inference_marker(self):
        with mock.patch.object(live,'prepare',return_value=({'engineering_source_qualified':False},{})):
            with self.assertRaises(AssertionError):
                asyncio.run(live.affine.infer(self.root,prepare_function=live.admitted_prepare,prefix_override='v4-affine'))
        self.assertFalse((self.root/'affine-inference-started.json').exists())

    def test_changed_v4_preparation_is_rejected_before_inference_marker(self):
        (self.root/'v4-affine-prepared.json').write_text('{"version":1}')
        with self.assertRaises(AssertionError):
            asyncio.run(live.affine.infer(self.root,prepare_function=lambda root,flag:({'version':2},{}),prefix_override='v4-affine'))
        self.assertFalse((self.root/'affine-inference-started.json').exists())

    def test_fixed_window_statistics_retain_a_short_power_excursion(self):
        tile=np.exp(2j*np.pi*np.arange(4096)/4096)
        raw=np.tile(tile,16)[:65535];raw[4096:8192]*=4
        result=live.continuity_summary(raw)
        self.assertEqual(len(result['rows']),15)
        self.assertAlmostEqual(result['rows'][0]['raw_rms'],1)
        self.assertAlmostEqual(result['rows'][1]['raw_rms'],4)
        self.assertAlmostEqual(result['rows'][2]['raw_rms'],1)
        self.assertEqual(result['rows'][-1]['complex_offset'],57344)


if __name__=='__main__':unittest.main()
