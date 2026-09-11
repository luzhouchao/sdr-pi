"""No hardware: packet identity, CFO/timing recovery, budgets and rejection."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import hashlib
import unittest
from unittest.mock import patch, MagicMock

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
import rml2018a_campaign as c


def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


class CampaignTests(unittest.TestCase):
    def test_explicit_pilot_selection_preserves_order_and_rejects_ambiguous_budget(self):
        runner=load('campaign_selection',SCRIPTS/'rml2018a-rf-campaign.py')
        self.assertEqual(runner.selected_batches(106496,0,1,[22016,4267]),[22016,4267])
        self.assertEqual(runner.selected_batches(5,3,10),[3,4])
        for values in ([],[1,1],[-1],[106496],[True],list(range(33))):
            with self.assertRaises(ValueError):runner.selected_batches(106496,0,1,values)
        for start,count in ((1,1),(0,2)):
            with self.assertRaises(ValueError):runner.selected_batches(106496,start,count,[1])

    def source(self, count=24):
        rng=np.random.default_rng(312)
        return rng.normal(size=(count,1024,2)).astype('<f4')

    def test_full_budget_and_tail_cover_exactly_once(self):
        b=c.budget(2555904)
        self.assertEqual(b['batches'],106496)
        self.assertEqual(b['maximum_rx_iq_bytes'],27916861440)
        self.assertEqual(c.batch_rows(25,0),list(range(24)))
        self.assertEqual(c.batch_rows(25,1),[24])
        self.assertEqual(c.batch_rows(2555904,106495)[-1],2555903)
        for value in (-1,106496):
            with self.assertRaises(ValueError):c.batch_rows(2555904,value)

    def test_packet_peak_and_per_row_source_shape(self):
        iq=self.source();frame,scales=c.packet(iq,'run',4)
        self.assertEqual(frame.dtype,np.dtype('<c8'))
        self.assertEqual(len(frame),26112)
        data=frame[c.GUARD+c.MARKER:-c.GUARD].reshape(24,1024)
        np.testing.assert_allclose(abs(data).max(axis=1),.2,atol=1e-7)
        np.testing.assert_allclose(data/scales[:,None],iq[...,0]+1j*iq[...,1],rtol=2e-7)

    def test_payload_hash_and_gain_frequency_identity_reject_before_uhd(self):
        frame,_=c.packet(self.source(),'run',0);plan=c.tx_plan(frame,'run',0,range(24))
        c.validate_tx(plan,frame.tobytes())
        for key,value in [('center_hz',433920000),('center_hz',2440000000),('schema','rml2018a-all-row-rf-v1'),('tx_gain_db',71),('tx_samples',1),
                          ('serial','other'),('repeats',0),('rows',[0]*24)]:
            changed={**plan,key:value}
            with self.assertRaises(ValueError):c.validate_tx(changed,frame.tobytes())
        with self.assertRaises(ValueError):c.validate_tx(plan,frame.tobytes()[:-1]+b'X')
        nx=load('test_nx',SCRIPTS/'rml2018a-nx-tx.py')
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            root=Path(directory);(root/'tx-plan.json').write_text(json.dumps(plan));(root/'packet.fc32').write_bytes(b'bad')
            with patch.object(nx.subprocess,'Popen') as spawn:
                with self.assertRaises(ValueError):nx.transmit(root)
                spawn.assert_not_called()

    def test_marker_recovery_with_unknown_phase_cfo_and_partial_leading_packet(self):
        iq=self.source();frame,scales=c.packet(iq,'session',3)
        start=11937;n=np.arange(c.RX_SAMPLES)
        raw=np.tile(frame,5)[start:start+c.RX_SAMPLES].astype(np.complex128)
        raw=raw*1000*np.exp(1j*(.7+2*np.pi*710*n/c.RATE))
        raw+=np.random.default_rng(11).normal(size=len(raw))*.02
        recovered,report=c.synchronize(raw,'session',3,24)
        expected=(iq[...,0]+1j*iq[...,1])*scales[:,None]*1000
        self.assertGreater(report['marker_score'],.99)
        self.assertAlmostEqual(report['estimated_cfo_hz'],710,delta=1)
        self.assertLess(float(np.mean(abs(recovered-expected)**2)/np.mean(abs(expected)**2)),1e-4)

    def test_wrong_batch_marker_and_silence_do_not_create_labels(self):
        frame,_=c.packet(self.source(),'run',1)
        raw=np.tile(frame,3)[:c.RX_SAMPLES]
        with self.assertRaises(ValueError):c.synchronize(raw,'run',2,24)
        with self.assertRaises(ValueError):c.synchronize(np.zeros(c.RX_SAMPLES),'run',1,24)
        with self.assertRaises(ValueError):c.synchronize(raw[:-1],'run',1,24)

    def test_2455_cfo_allowance_scales_with_carrier_without_lowering_quality(self):
        frame,_=c.packet(self.source(),'cfo2455',1)
        n=np.arange(c.RX_SAMPLES)
        for hz in (3370,-9100):
            raw=np.tile(frame,3)[:c.RX_SAMPLES]*np.exp(2j*np.pi*hz*n/c.RATE)
            _,report=c.synchronize(raw,'cfo2455',1,24)
            self.assertGreater(report['marker_score'],.99)
            self.assertAlmostEqual(report['estimated_cfo_hz'],hz,delta=2)
        self.assertEqual(c.CFO_SEARCH_MAX_HZ,14500)
        self.assertEqual(c.CFO_LIMIT_HZ,17000)

    def test_detector_rejects_out_of_band_tone_but_preserves_payload(self):
        frame,_=c.packet(self.source(),'tone',1)
        n=np.arange(c.RX_SAMPLES)
        raw=np.tile(frame,3)[:c.RX_SAMPLES]*np.exp(2j*np.pi*710*n/c.RATE)
        raw+=2*np.exp(-2j*np.pi*589170*n/c.RATE)
        recovered,report=c.synchronize(raw,'tone',1,24)
        at=report['payload_marker_offset']+c.MARKER
        expected=raw[at:at+24*1024]*np.exp(-2j*np.pi*report['estimated_cfo_hz']*
            n[at:at+24*1024]/c.RATE+1j*report['phase_rotation_rad'])
        np.testing.assert_allclose(recovered.ravel(),expected,rtol=1e-10)
        self.assertGreater(report['marker_score'],.95)
        self.assertFalse(report['detector_filter']['payload_filtered'])

    def test_clean_trailing_pilot_anchors_previous_complete_repeated_payload(self):
        frame,_=c.packet(self.source(),'tail',3)
        raw=np.tile(frame,3)[:c.RX_SAMPLES].astype(np.complex128)
        # First two markers erased by interference; third marker is intact but
        # has fewer than 24 payload rows following it within the RX budget.
        for k in (0,1):raw[k*len(frame)+c.GUARD:k*len(frame)+c.GUARD+c.MARKER]=0
        recovered,report=c.synchronize(raw,'tail',3,24)
        self.assertEqual(report['marker_offset'],2*len(frame)+c.GUARD)
        self.assertEqual(report['payload_marker_offset'],len(frame)+c.GUARD)
        expected=frame[c.GUARD+c.MARKER:-c.GUARD].reshape(24,1024)
        np.testing.assert_allclose(recovered,expected,atol=1e-5)

    def test_summary_distinguishes_captured_pending_inference_and_unattempted(self):
        runner=load('campaign_summary',SCRIPTS/'rml2018a-rf-campaign.py')
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            root=Path(directory);batch=root/'batch-0000000';batch.mkdir()
            c.save(batch/'audit.json',{'status':'sync_failed','receive_quality':[
                dict(row=k,source_snr_db=30,**c.receive_quality('sync_failed')) for k in range(24)]})
            c.save(batch/'capture-complete.json',dict(rows=list(range(24)),audit_sha256=c.file_hash(batch/'audit.json')))
            with patch('builtins.print'):
                runner.summarize(root,{'budget':c.budget(25),'rf':{'rx_gain_db':40,'tx_gain_db':70}})
            report=json.loads((root/'summary.json').read_text())
            self.assertEqual(report['attempted_rows'],24)
            self.assertEqual(report['pending_inference_rows'],24)
            self.assertEqual(report['not_yet_attempted_rows'],1)
            self.assertIsNone(report['received_accuracy'])
            self.assertEqual(report['rx_sinr']['not_measured'],24)
            self.assertEqual(report['rx_sinr']['measured_rows'],0)
            self.assertFalse(report['complete'])

    def test_noisy_source_label_and_failed_sync_never_become_measured_sinr(self):
        runner=load('campaign_quality',SCRIPTS/'rml2018a-rf-campaign.py')
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            root=Path(directory);batch=root/'batch-0000000';batch.mkdir()
            entries=[dict(row=k,true_id=0,source_snr_db=snr,receive_status=status,
                source_prediction={'id':0},received_prediction=prediction,
                **c.receive_quality(status)) for k,snr,status,prediction in (
                    (0,30,'synchronized',{'id':0}),(1,-20,'sync_failed',None))]
            x=np.exp(2j*np.pi*np.arange(1024)/16)
            entries[0].update(c.receive_quality('synchronized',x,2*x+.1,30))
            quality=[{k:v for k,v in e.items() if k not in (
                'true_id','source_prediction','received_prediction','receive_status')} for e in entries]
            c.save(batch/'audit.json',{'status':'synchronized','receive_quality':quality})
            seal=c.file_hash(batch/'audit.json')
            c.save(batch/'capture-complete.json',dict(rows=[0,1],audit_sha256=seal))
            result=dict(schema=c.SCHEMA,batch=0,audit_sha256=seal,rows=entries)
            c.save(batch/'predictions.json',result)
            with patch('builtins.print'):runner.summarize(root,{'budget':c.budget(2),'rf':{'rx_gain_db':40,'tx_gain_db':70}})
            report=json.loads((root/'summary.json').read_text())
            self.assertEqual(set(report['by_source_snr_db']),{'30','-20'})
            self.assertNotIn('by_snr',report)
            self.assertEqual(report['rx_sinr']['measured_rows'],0)
            self.assertEqual(report['rx_sinr']['not_measured'],1)
            self.assertEqual(report['rx_sinr']['estimated'],1)
            self.assertEqual(sum(g['correct'] for g in report['rx_sinr']['by_estimated_rx_sinr_db'].values()),1)
            self.assertEqual(report['rx_sinr']['unavailable_reasons'],{'payload_not_synchronized':1})
            self.assertEqual(report['end_to_end_success_fraction'],.5)
            for key,value in [('rx_sinr_db',30),('rx_sinr_db',0),('rx_sinr_status','measured')]:
                changed=dict(entries[0]);changed[key]=value
                c.save(batch/'predictions.json',{**result,'rows':[changed,entries[1]]})
                with self.assertRaisesRegex(ValueError,'prediction quality differs from capture audit'):
                    runner.summarize(root,{'budget':c.budget(2),'rf':{'rx_gain_db':40,'tx_gain_db':70}})
            c.save(batch/'predictions.json',{**result,'schema':'rml2018a-all-row-rf-v1'})
            with self.assertRaisesRegex(ValueError,'prediction schema changed'):
                runner.summarize(root,{'budget':c.budget(2),'rf':{'rx_gain_db':40,'tx_gain_db':70}})

    def test_archived_pilot_remains_byte_identical_across_record_schema_change(self):
        bits=np.unpackbits(np.frombuffer(hashlib.shake_256(
            b'rml2018a-all-row-rf-v1:archive:4267').digest(32),dtype=np.uint8))
        chips=((bits[::2].astype(float)*2-1)+1j*(bits[1::2].astype(float)*2-1))/np.sqrt(2)
        np.testing.assert_array_equal(c.marker('archive',4267),np.tile(np.repeat(chips,4),2)*.2)

    def test_old_frequency_plan_rejected_before_software_or_device_access(self):
        runner=load('campaign_plan_frequency',SCRIPTS/'rml2018a-rf-campaign.py')
        plan=dict(schema=c.SCHEMA,budget=c.budget(2555904),rf={'center_hz':433920000})
        with patch.object(runner,'document',return_value=plan),patch.object(runner,'file_hash') as hash_file:
            with self.assertRaisesRegex(ValueError,'RF center changed'):
                runner.load_plan(Path('/var/tmp/sdrharness-dev/b210-rml2018a-fake-plan'))
            hash_file.assert_not_called()

    def test_completed_resume_verifies_iq_without_transmit(self):
        runner=load('campaign_resume',SCRIPTS/'rml2018a-rf-campaign.py')
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            root=Path(directory);batch=root/'batch-0000000';batch.mkdir()
            c.save(batch/'audit.json',{'seal':{'iq_sha256':'expected'}})
            c.save(batch/'rx-plan.json',{})
            c.save(batch/'capture-complete.json',dict(rows=list(range(24)),audit_sha256=c.file_hash(batch/'audit.json')))
            bg=MagicMock()
            with patch.object(runner,'module',return_value=bg),patch.object(runner,'native_check',return_value=(None,{'iq_sha256':'expected'})):
                runner.acquire_batch(root,{'budget':c.budget(25),'rf':{'rx_gain_db':40,'tx_gain_db':70}},0)
                bg.tx_preflight.assert_not_called()
                bg.command.assert_not_called()
            with patch.object(runner,'module',return_value=bg),patch.object(runner,'native_check',return_value=(None,{'iq_sha256':'tampered'})):
                with self.assertRaisesRegex(ValueError,'completed IQ changed'):
                    runner.acquire_batch(root,{'budget':c.budget(25),'rf':{'rx_gain_db':40,'tx_gain_db':70}},0)

    def test_normalization_keeps_constant_carrier_and_is_scale_invariant(self):
        z=np.ones(1024)*(.2+.4j)
        a=c.normalize_window(z)
        np.testing.assert_array_equal(a,c.normalize_window(z*10))
        self.assertGreater(abs(a.mean()),.6)
        self.assertAlmostEqual(float(np.sqrt(np.mean(np.sum(a.astype(float)**2,axis=0)))),1,places=6)
        with self.assertRaises(ValueError):c.normalize_window(np.zeros(1024))

    def test_unregistered_gains_rejected_before_hardware_or_dataset_access(self):
        runner=load('campaign_gain_limits',SCRIPTS/'rml2018a-rf-campaign.py')
        with patch.object(runner,'file_hash') as hashing,patch.object(runner,'document') as read:
            for gain in (-1,39,41,True,40.):
                with self.assertRaises(ValueError):runner.create_plan(Path('/unused'),gain)
                with self.assertRaises(ValueError):runner.native_check(Path('/unused'),{'gain_db':gain})
            hashing.assert_not_called();read.assert_not_called()
        frame,_=c.packet(self.source(),'gain-test',0)
        for gain in (69,71,81,90,True,80.):
            with self.assertRaises(ValueError):c.tx_plan(frame,'gain-test',0,range(24),gain)

    def fifo_case(self, go, gain=70, executable='/usr/lib/uhd/examples/tx_samples_from_file'):
        nx=load('fifo_nx',SCRIPTS/'rml2018a-nx-tx.py')
        frame,_=c.packet(self.source(2),'fifo-test',0)
        plan=c.tx_plan(frame,'fifo-test',0,[0,1],gain)
        launched=[];real_popen=subprocess.Popen;real_select=nx.select.select;real_read=os.read
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            root=Path(directory);(root/'packet.fc32').write_bytes(frame.tobytes())
            (root/'tx-plan.json').write_text(json.dumps(plan))
            def fake_uhd(args,**kwargs):
                self.assertEqual(args[0],executable)
                self.assertEqual(args[args.index('--freq')+1],'2455000000')
                self.assertEqual(args[args.index('--gain')+1],str(gain))
                self.assertNotIn('--repeat',args)
                code=('import sys,hashlib,json; f=open(sys.argv[1],"rb"); h=hashlib.sha256(); n=0\n'
                      'while True:\n b=f.read(8192)\n if not b:break\n h.update(b);n+=len(b)\n'
                      'print(json.dumps(dict(bytes=n,sha256=h.hexdigest())))')
                child=real_popen([sys.executable,'-c',code,args[args.index('--file')+1]],**kwargs)
                launched.append(child);return child
            def fake_select(read,write,error,timeout):
                return ([0],[],[]) if read==[0] else real_select(read,write,error,timeout)
            with patch.object(nx.subprocess,'Popen',fake_uhd),patch.object(nx.select,'select',fake_select),\
                 patch.object(nx.os,'read',lambda fd,n:(b'GO\n' if go else b'') if fd==0 else real_read(fd,n)),\
                 patch.object(nx.signal,'signal'),patch.object(nx.signal,'alarm'),\
                 patch.dict(os.environ,{'SDRHARNESS_B210_TX_BINARY':executable}),\
                 patch.object(nx,'file_hash',side_effect=lambda p:'fe3aebc556c16a5065d63d4e6ef8f02ef277ac01dcf250a35dec58b84eceb5cf' if str(p)==executable else c.file_hash(p)):
                if go:nx.transmit(root)
                else:
                    with self.assertRaises(ValueError):nx.transmit(root)
            self.assertFalse((root/'packet.fifo').exists())
            self.assertTrue(all(child.poll() is not None for child in launched))
            audit=json.loads((root/'tx-summary.json').read_text())
            self.assertTrue(audit['child_stopped'])
            if go:
                actual=json.loads((root/'tx-uhd.log').read_text())
                expected=hashlib.sha256()
                for _ in range(plan['repeats']):expected.update(frame.tobytes())
                self.assertEqual(actual,dict(bytes=plan['tx_samples']*8,sha256=expected.hexdigest()))
            else:self.assertEqual(audit['bytes_written'],0)

    def test_finite_fifo_exact_bytes_and_child_exit(self):self.fifo_case(True)

    def test_higher_registered_gain_reaches_uhd_with_same_finite_budget(self):self.fifo_case(True,80)

    def test_agx_low_gain_and_pinned_binary_override(self):self.fifo_case(True,0,'/fake/agx/tx_samples_from_file')

    def test_unverified_uhd_binary_rejected_before_process(self):
        nx=load('unverified_nx',SCRIPTS/'rml2018a-nx-tx.py')
        frame,_=c.packet(self.source(2),'binary-test',0);plan=c.tx_plan(frame,'binary-test',0,[0,1],0)
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            root=Path(directory);(root/'packet.fc32').write_bytes(frame.tobytes());c.save(root/'tx-plan.json',plan)
            with patch.object(nx,'file_hash',return_value='bad'),patch.object(nx.subprocess,'Popen') as launch:
                with self.assertRaisesRegex(ValueError,'UHD TX binary identity'):nx.transmit(root)
                launch.assert_not_called();self.assertFalse((root/'tx-started.json').exists())

    def test_fifo_eof_before_go_cancels_without_payload(self):self.fifo_case(False)


if __name__=='__main__':unittest.main()
