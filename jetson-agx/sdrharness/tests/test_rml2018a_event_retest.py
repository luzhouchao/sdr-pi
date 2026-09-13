"""Finite RF gates and failed-receive accounting; no live hardware or model."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, MagicMock, patch
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
        for profile in (m.PROFILE,'uniform24-high-snr-pilot','four-class-snr-strata'):
            with self.subTest(profile=profile):self.check_mutations(profile)

    def check_mutations(self,profile):
        root=Path('/var/tmp/sdrharness-dev')/(m.experiment(profile)['prefix']+'test')
        count=m.fixed_fields(profile)['source_rows']
        stat=SimpleNamespace(st_size=21449148312,st_mtime_ns=123)
        points=[dict(mode='rml',source=dict(rows=list(range(count))))]
        p=dict(**m.fixed_fields(profile),generation=1,run_id='a'*32,points=points,software={},free_bytes=2**30,
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

    def test_uniform_class_partition_packet_and_budgets(self):
        profile='uniform24-high-snr-pilot';fields=m.fixed_fields(profile)
        self.assertEqual((fields['source_rows'],fields['maximum_tx_seconds'],fields['maximum_tx_samples'],fields['maximum_rx_bytes'],fields['maximum_model_windows']),(576,96,201166848,6815640,1728))
        self.assertGreater(fields['reserve_bytes'],24*fields['maximum_log_bytes_per_tx']+fields['maximum_rx_bytes'])
        self.assertEqual(list(c.RML_UNIFORM_CLASSES),list(range(24)))
        old=set(c.RML_EVENT_BATCHES+c.RML_TIMING_BATCHES+c.RML_REMAINING_BATCHES+c.RML_GUARD_BATCHES+c.RML_RXGAIN_BATCHES)
        self.assertFalse(old&set(c.RML_UNIFORM_BATCHES))
        iq=np.random.default_rng(414).normal(size=(24,1024,2))
        for batch,cid in zip(c.RML_UNIFORM_BATCHES,c.RML_UNIFORM_CLASSES):
            rows=c.batch_rows(2555904,batch)
            self.assertTrue(all(cid*106496+102400<=r<(cid+1)*106496 for r in rows))
            frame,_=c.packet(iq,'uniform',batch,level_profile=profile)
            tx=c.tx_plan(frame,'uniform',batch,rows,60,level_profile=profile);c.validate_tx(tx,frame.tobytes())
            with self.assertRaises(ValueError):c.validate_tx({**tx,'schema':c.RML_EVENT_SCHEMA},frame.tobytes())
        with self.assertRaises(ValueError):m.experiment('all-unbounded')
        with self.assertRaises(ValueError):m.check_root(Path('/var/tmp/sdrharness-dev/b210-rml-event-retest-test'),profile)

    def test_summary_keeps_invalid_quality_and_missing_predictions(self):
        quality={tag:dict(rx_sinr_status=status,rx_sinr_reason='reason') for tag,status in [('raw','invalid'),('guard','invalid')]}
        b=dict(batch=1,class_id=3,class_name='BPSK',rows=[dict(row=1,true_id=3,quality=quality),dict(row=2,true_id=3,quality=quality)],
            status='synchronized',guard_correction=dict(status='skipped',reason='guard'),component_peak_counts=10,events=dict(event_counts={}),quality_summary=dict(raw={},guard={}))
        report=dict(source_rows=2,results=[b],stopped_controls=[],semantics='test')
        receipt=dict(status='completed',rows=[dict(batch=1,row=1,true_id=3,predictions=dict(source=dict(id=3),raw=dict(id=3),guard=dict(id=3))),
            dict(batch=1,row=2,true_id=3,predictions=dict(source=dict(id=3),raw=None,guard=None))],
            summary=dict(source=dict(total=2,predicted=2,correct=2),raw=dict(total=2,predicted=1,correct=1),guard=dict(total=2,predicted=1,correct=1)))
        result=m.summarize_predictions(report,receipt)
        self.assertEqual(result['classification']['guard'],dict(total=2,predicted=1,correct=1))
        self.assertEqual(result['by_source_snr']['30.0']['classification']['guard'],dict(total=2,predicted=1,correct=1))
        self.assertEqual(result['results'][0]['quality']['guard']['recognition_by_quality']['invalid'],dict(total=2,correct=1))
        with self.assertRaises(ValueError):m.summarize_predictions(report,{**receipt,'rows':receipt['rows'][:1]})

    def test_strata_complete_cells_and_source_block_bounds(self):
        profile='four-class-snr-strata';e=m.experiment(profile);f=m.fixed_fields(profile)
        self.assertEqual(set(zip(e['classes'],e['snrs'])),{(cid,z) for cid in (3,12,14,21) for z in (-20,-10,0,10,20)})
        self.assertEqual(len(set(e['batches'])),20)
        self.assertEqual((f['source_rows'],f['maximum_tx_seconds'],f['maximum_tx_samples'],f['maximum_rx_bytes'],f['maximum_model_windows']),(480,80,167639040,5767080,1440))
        for batch,cid,z in zip(e['batches'],e['classes'],e['snrs']):
            self.assertEqual(m.source_snr(profile,batch,cid),z)
            for row in c.batch_rows(2555904,batch):
                self.assertEqual(row//106496,cid);self.assertEqual(2*((row%106496)//4096)-20,z)
            with self.assertRaises(ValueError):m.source_snr(profile,batch,(cid+1)%24)
        with self.assertRaises(ValueError):m.source_snr(profile,c.RML_UNIFORM_BATCHES[3],3)
        self.assertFalse(set(e['batches'])&set(c.RML_UNIFORM_BATCHES))

    def test_actual_source_z_checked_before_packet(self):
        class Selection:
            def __init__(self,values):self.values=values
            def __getitem__(self,rows):return self.values
        profile='four-class-snr-strata';batch=c.RML_STRATIFIED_BATCHES[0];cid=c.RML_STRATIFIED_CLASSES[0]
        iq=np.random.default_rng(100).normal(size=(24,1024,2)).astype('float32')
        labels=np.zeros((24,24));labels[:,cid]=1
        handle=MagicMock();handle.__enter__.return_value={'X':Selection(iq),'Y':Selection(labels),'Z':Selection(np.zeros((24,1)))}
        with patch.object(m.h5py,'File',return_value=handle):
            _,frame,src,tx=m.source('strata',batch,cid,profile)
            self.assertEqual(src['source_snr_db'],[0.]*24);c.validate_tx(tx,frame.tobytes())
            handle.__enter__.return_value['Z']=Selection(np.full((24,1),30.))
            with self.assertRaises(ValueError):m.source('strata',batch,cid,profile)

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
