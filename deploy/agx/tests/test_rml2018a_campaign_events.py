"""Boundary indexing, failure denominators and idempotent campaign publication."""
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np
S=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(S))
import rml2018a_campaign_events as e
c=e.c


class EventCampaignTests(unittest.TestCase):
    def test_mixed_boundaries_and_strict_tx(self):
        expected=[({0},{-20,-18}),({0},{28,30}),({0,1},{30,-20}),({13,14},{30,-20})]
        for batch,(ids,zs) in zip(c.RML_BOUNDARY_BATCHES,expected):
            rows=c.batch_rows(2555904,batch)
            self.assertEqual({r//106496 for r in rows},ids)
            self.assertEqual({2*((r%106496)//4096)-20 for r in rows},zs)
            iq=np.random.default_rng(batch).normal(size=(24,1024,2))
            frame,_=c.packet(iq,'a'*32,batch,level_profile=e.PROFILE)
            tx=c.tx_plan(frame,'a'*32,batch,rows,60,level_profile=e.PROFILE)
            c.validate_tx(tx,frame.tobytes())
            for changes in ({'batch':0},{'schema':c.RML_EVENT_SCHEMA},{'rows':rows[::-1]},{'repeats':322},{'tx_gain_db':70}):
                with self.assertRaises(ValueError):c.validate_tx({**tx,**changes},frame.tobytes())
        self.assertEqual(c.packet_peak('standard'),.2)
        self.assertEqual(e.limits()['maximum_tx_seconds'],32)
        self.assertEqual(e.limits()['maximum_rx_iq_bytes'],2097120)
        self.assertGreater(e.limits()['reserve_bytes'],8*16000000+2097120)

    def test_source_uses_real_per_row_y_z(self):
        # A real read-only24-row sample catches mixed class/SNR assumptions.
        _,frame,src,tx=e.source('b'*32,4437)
        self.assertEqual(src['class_ids'],[0]*8+[1]*16)
        self.assertEqual(src['source_snr_db'],[30]*8+[-20]*16)
        c.validate_tx(tx,frame.tobytes())
        with self.assertRaises(ValueError):e.source('b'*32,4438)

    def test_missing_and_invalid_rows_remain_in_denominator(self):
        rows=[dict(true_id=0,predictions=dict(source={'id':0},raw={'id':0},guard={'id':1}),
            quality={t:dict(rx_sinr_status='invalid') for t in ('raw','guard')}),
            dict(true_id=1,predictions={}),
            dict(true_id=1,predictions=dict(source={'id':1},raw=None,guard=None),
                quality={t:dict(rx_sinr_status='not_measured') for t in ('raw','guard')})]
        a=e.aggregate(rows)
        self.assertEqual(a['classification']['source'],dict(total=3,predicted=2,correct=2))
        self.assertEqual(a['classification']['raw'],dict(total=3,predicted=1,correct=1))
        self.assertEqual(a['quality']['raw'],dict(estimated=0,invalid=1,not_measured=1,pending=1))
        self.assertEqual(a['raw_to_guard'],dict(corrected=0,regressed=1))

    def test_completed_capture_never_enters_executor(self):
        with patch.object(e,'capture_complete',return_value={'attempt':0}) as check,patch.object(e.r.events,'acquire_validated') as run:
            self.assertEqual(e.acquire_batch(Path('/unused'),{},170,True),{'attempt':0})
            check.assert_called_once();run.assert_not_called()

    def test_completed_attempt_recovers_without_retransmission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d=e.batch_dir(root,170);a=d/'attempt-0';a.mkdir(parents=True)
            for name,value in [('source.json',{'rows':[1]})]:c.save(d/name,value)
            c.save(a/'plan.json',{'sealed':1});c.save(a/'postflight.json',dict(status='completed',restored=True))
            p=dict(event_sources={'170':dict(source={'rows':[1]})})
            with patch.object(e,'capture_complete',return_value=None),patch.object(e,'attempt_plan',return_value={'sealed':1}),patch.object(e,'attempt_seal',return_value={'done':1}),patch.object(e.r.events,'acquire_validated') as run:
                self.assertEqual(e.acquire_batch(root,p,170),{'done':1});run.assert_not_called()

    def test_retry_requires_restoration_and_stops_at_two(self):
        for restored in (False,True):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);d=e.batch_dir(root,170);d.mkdir()
                c.save(d/'source.json',{'rows':[1]})
                for i in range(2):
                    a=d/f'attempt-{i}';(a/'capture').mkdir(parents=True)
                    c.save(a/'plan.json',{'sealed':1});c.save(a/'postflight.json',dict(status='failed',restored=restored))
                    c.save(a/'capture/audit.json',dict(restored=restored))
                p=dict(event_sources={'170':dict(source={'rows':[1]})})
                with patch.object(e,'capture_complete',return_value=None),patch.object(e,'attempt_plan',return_value={'sealed':1}),patch.object(e.r.events,'acquire_validated') as run:
                    with self.assertRaisesRegex(ValueError,'budget exhausted' if restored else 'retry requires'):
                        e.acquire_batch(root,p,170,True)
                    run.assert_not_called()

    def test_stop_handlers_restored_even_when_executor_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=dict(event_sources={'170':dict(source={'rows':[1]})})
            before={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
            def cancelled(*args):
                for s in before:signal.signal(s,signal.SIG_IGN)
                raise RuntimeError('cancelled')
            with patch.object(e,'capture_complete',return_value=None),patch.object(e,'attempt_plan',return_value={}),patch.object(e.r.events,'acquire_validated',side_effect=cancelled):
                with self.assertRaisesRegex(RuntimeError,'cancelled'):e.acquire_batch(root,p,170)
            self.assertEqual(before,{s:signal.getsignal(s) for s in before})

    def test_inference_skip_has_no_model_call(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(e,'prediction_complete',return_value=True),patch.object(e.r.compare,'infer') as model:
            e.infer_batches(Path(tmp),{},[170,4266]);model.assert_not_called()

    def test_completion_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dest=e.batch_dir(root,170);dest.mkdir()
            c.save(dest/'source.json',{'rows':[1]});c.save(dest/'capture-complete.json',dict(attempt=0,seal='modified'))
            with patch.object(e,'attempt_seal',return_value=dict(attempt=0,seal='original')):
                with self.assertRaisesRegex(ValueError,'completed capture changed'):
                    e.capture_complete(root,dict(event_sources={'170':dict(source={'rows':[1]})}),170)

    def test_guard_plane_validation_and_arithmetic(self):
        source=np.random.default_rng(71).normal(size=1024)+1j*np.random.default_rng(72).normal(size=1024)
        raw=c.receive_quality('synchronized',source,source,10.)
        guarded=e.r.guard.quality(source,source,10.,{'status':'applied'})
        e.validate_quality(raw,guarded,10.,{'status':'applied'},True)
        self.assertEqual(guarded['rx_sinr_reference_plane'],e.r.guard.PLANE)
        for change in ({'rx_sinr_reference_plane':raw['rx_sinr_reference_plane']},
                       {'rx_sinr_db':9.},{'rx_interference_cancellation':'none_skipped'}):
            with self.assertRaises(ValueError):e.validate_quality(raw,{**guarded,**change},10.,{'status':'applied'},True)
        missing=c.receive_quality('sync_failed')
        e.validate_quality(missing,{**missing,'rx_sinr_reference_plane':e.r.guard.PLANE},-20.,{'status':'skipped'},False)

    def test_analysis_revision_cannot_acquire(self):
        for command in ('acquire','run','plan'):
            with patch.object(sys,'argv',['campaign',command,'--root','/unused','--analysis-revision']),patch.object(e.m,'load_plan') as load:
                with self.assertRaisesRegex(ValueError,'cannot transmit'):e.m.main()
                load.assert_not_called()

    def test_readonly_verification_requires_all_captures_first(self):
        with patch.object(e,'capture_complete',side_effect=[{'done':1},None]),patch.object(e,'acquire_batch') as acquire:
            with self.assertRaisesRegex(ValueError,'read-only completed'):e.verify_completed(Path('/unused'),{},[170,4266])
            acquire.assert_not_called()

    def test_nested_inference_keeps_top_level_spark_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'inference-key'/'attempt-0';out.mkdir(parents=True)
            z=np.ones((1,1024),dtype=complex);sha=c.digest(c.normalize_window(z[0]).tobytes())
            row=dict(row=0,true_id=0,inputs={tag:sha for tag in e.TAGS})
            report=dict(source_rows=1,maximum_model_windows=3,tags=list(e.TAGS),profile_sha256='profile',
                label_map_sha256='labels',semantics='test',results=[dict(batch=0,rows=[row])])
            c.save(out/'prepared.json',report)
            backend=SimpleNamespace(model=SimpleNamespace(parameters=lambda:[]),admission_identity={},
                classify_logits=lambda x:([1.]+[0.]*23,1))
            @contextmanager
            def pause(*,evidence_root):
                self.assertEqual(evidence_root,root);yield
            multi=SimpleNamespace(idle_spark_pause=pause)
            worker=SimpleNamespace(RfV1Backend=lambda _:backend,torch=SimpleNamespace(float32='float32'))
            lease=MagicMock();lease.acquire=AsyncMock(return_value='token');lease.metrics={}
            def inputs(_):return report,{0:{tag:z for tag in e.TAGS}}
            with patch.dict(os.environ),patch.object(tempfile,'tempdir',tempfile.gettempdir()),patch.object(e.r.compare,'runner',return_value=e.m),patch.object(e.m,'module',side_effect=[multi,worker]),patch('gpu_lease.GpuLease',return_value=lease):
                receipt=e.r.compare.infer(root,out,prepare_inputs=inputs,isolation_root=root)
            self.assertEqual(receipt['model_windows'],3);self.assertEqual(receipt['status'],'completed')
            lease.release.assert_called_once_with('token');lease.close.assert_called_once()

    def test_complete_inference_repairs_partial_publication_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'inference-key'/'attempt-0';out.mkdir(parents=True)
            report=dict(results=[dict(batch=i) for i in (170,4266)])
            receipt=dict(status='completed',rows=[dict(batch=i,row=i*24) for i in (170,4266)])
            c.save(out/'prepared.json',report);c.save(out/'inference.json',receipt)
            for index in (170,4266):
                d=e.batch_dir(root,index);d.mkdir();c.save(d/'capture-complete.json',dict(batch=index))
            with patch.object(e.r.compare,'verify'),patch.object(e,'prepare',return_value=(report,{})),patch.object(e.r.compare,'infer') as model:
                e.publish(root,{},out)
                (e.batch_dir(root,4266)/'predictions.json').unlink()  # synthetic interrupted publication
                with patch.object(e,'prediction_complete',side_effect=lambda root,p,i:(e.batch_dir(root,i)/'predictions.json').exists()):
                    e.infer_batches(root,{},[4266])
                self.assertTrue((e.batch_dir(root,4266)/'predictions.json').exists());model.assert_not_called()

    def test_changing_shard_does_not_reset_inference_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for key in ('a','b'):
                out=root/f'inference-{key}'/'attempt-0';out.mkdir(parents=True)
                c.save(out/'prepared.json',dict(results=[dict(batch=170)]))
                c.save(out/'inference.json',dict(status='failed'))
            with patch.object(e,'prediction_complete',return_value=False),patch.object(e.r.compare,'infer') as model:
                with self.assertRaisesRegex(ValueError,'ceiling across shards'):e.infer_batches(root,{},[170])
                model.assert_not_called()

    def test_full_main_profile_dispatch(self):
        with patch.object(e.m,'event_backend',return_value=e),patch.object(e,'acquire_batch',return_value='done') as run:
            p=dict(tx_level_profile=e.PROFILE,tx_host='agx',rf=dict(tx_gain_db=60,rx_gain_db=50,peak=c.packet_peak(e.PROFILE)),execution_limits=e.limits())
            self.assertEqual(e.m.acquire_batch(Path('/unused'),p,170),'done');run.assert_called_once()
            with self.assertRaises(ValueError):e.m.acquire_batch(Path('/unused'),p,0)


if __name__=='__main__':unittest.main()
