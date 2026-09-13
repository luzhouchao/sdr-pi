"""Finite RF gates and failed-receive accounting; no live hardware or model."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import numpy as np

S=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(S))
spec=importlib.util.spec_from_file_location('event_retest',S/'rml2018a-event-retest.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
c=m.c


class RetestTests(unittest.TestCase):
    def test_new_members_and_exact_packet_budget(self):
        old=set(c.RML_REMAINING_BATCHES)|set(c.RML_TIMING_BATCHES)|set(c.RML_RXGAIN_BATCHES)|set(c.RML_GUARD_BATCHES)
        self.assertFalse(old&set(c.RML_EVENT_BATCHES))
        iq=np.random.default_rng(20260913).normal(size=(24,1024,2))
        for batch,cid in zip(c.RML_EVENT_BATCHES,c.RML_EVENT_CLASSES):
            rows=c.batch_rows(2555904,batch)
            self.assertTrue(all(cid*106496+102400<=r<(cid+1)*106496 for r in rows))
            frame,_=c.packet(iq,'new',batch,level_profile=m.PROFILE)
            tx=c.tx_plan(frame,'new',batch,rows,60,level_profile=m.PROFILE)
            c.validate_tx(tx,frame.tobytes());self.assertEqual(tx['tx_samples'],8381952)
            for change in ({'tx_gain_db':70},{'schema':c.SCHEMA},{'batch':17664},{'rows':[0]},{'repeats':322}):
                with self.assertRaises(ValueError):c.validate_tx({**tx,**change},frame.tobytes())
        self.assertEqual(c.pilot_rx_gains(m.PROFILE),(50,))
        self.assertEqual(c.packet_peak('standard'),.2)

    def test_plan_mutations_fail_before_hardware(self):
        root=Path('/var/tmp/sdrharness-dev/b210-rml-event-retest-test')
        stat=SimpleNamespace(st_size=21449148312,st_mtime_ns=123)
        points=[dict(mode='rml',source=dict(rows=list(range(96))))]
        p=dict(**m.fixed_fields(),generation=1,run_id='a'*32,points=points,software={},free_bytes=2**30,
            source_disjointness=dict(previous_source_records=[],previous_unique_rows=0,intersection=0),
            source=dict(path=str(m.m.DATASET),bytes=stat.st_size,mtime_ns=stat.st_mtime_ns,sha256=m.DATA_SHA))
        dataset=Mock();dataset.stat.return_value=stat
        p['source']['path']=str(dataset)
        with patch.object(m.m,'DATASET',dataset),patch.object(m,'identity',return_value={}),patch.object(m,'software',return_value={}),patch.object(m,'fixed_points',return_value=points):
            m.validate(root,p)
            for change in ({'maximum_tx_seconds':20},{'maximum_rx_bytes':1572841},{'maximum_model_windows':289},
                           {'points':['other']},{'rf':{**p['rf'],'rx_gain_db':40}},{'source_rows':120},
                           {'guard_contract':{}},{'free_bytes':1}):
                with self.assertRaises(ValueError):m.validate(root,{**p,**change})

    def test_sync_failure_retains_missing_inputs(self):
        with patch.object(c,'synchronize',side_effect=ValueError('no marker')),patch.object(m.guard,'cancel') as cancel:
            raw,guarded,sync,info,error=m.receive_parts(np.ones(65535),'run',17680)
        self.assertIsNone(raw);self.assertIsNone(guarded);self.assertIsNone(sync)
        self.assertEqual(error,'no marker');self.assertEqual(info['reason'],'not_synchronized');cancel.assert_not_called()

    def test_guard_rejection_preserves_payload(self):
        # Rejecting LO must not drop a row or silently use another correction.
        raw=np.arange(65535,dtype=float).astype(complex);sync={'payload_marker_offset':256,'estimated_cfo_hz':0.,'phase_rotation_rad':0.}
        payload=m.lo.payload(raw,sync)
        with patch.object(c,'synchronize',return_value=(payload,sync)),patch.object(m.guard,'cancel',return_value=(raw.copy(),dict(status='skipped',reason='guard_tone_error_margin'))):
            received,guarded,_,info,error=m.receive_parts(raw,'run',17680)
        np.testing.assert_array_equal(received,guarded);self.assertIsNone(error);self.assertEqual(info['status'],'skipped')

    def test_root_escape_rejected(self):
        for root in (Path('/tmp/b210-rml-event-retest-test'),Path('/var/tmp/sdrharness-dev/b210-rml-event-retest-a/child')):
            with self.assertRaises(ValueError):m.check_root(root)


if __name__=='__main__':unittest.main()
