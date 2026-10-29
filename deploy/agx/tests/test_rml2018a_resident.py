"""Resident lifetime, exact disk inputs, finite limits and sequential model use."""
from pathlib import Path
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_campaign_resident as r
c=r.c


def fixture():
    x=np.random.default_rng(89).normal(size=(24,1024))+1j*np.random.default_rng(90).normal(size=(24,1024))
    inputs=[c.normalize_window(v) for v in x]
    report=dict(source_rows=24,maximum_model_windows=72,tags=list(r.e.TAGS),parent_plan_sha256='plan',
        profile_sha256='profile',label_map_sha256='labels',semantics='test',
        results=[dict(batch=3,rows=[dict(row=72+i,true_id=0,inputs={tag:c.digest(v.tobytes()) for tag in r.e.TAGS}) for i,v in enumerate(inputs)])])
    return report,{3:{tag:x for tag in r.e.TAGS}}


class ResidentTests(unittest.TestCase):
    def test_window_budget_counts_failed_calls_and_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c.save(root/'resident-plan.json',{})
            backend=SimpleNamespace(admission_identity={},classify_logits=lambda x:([0]*24,1))
            value=r.Resident(backend,root,1,time.monotonic()+10)
            value.classify_logits(None)
            with self.assertRaisesRegex(ValueError,'window budget'):value.classify_logits(None)
            (root/'STOP').touch()
            with self.assertRaisesRegex(ValueError,'STOP'):value.check()
            (root/'STOP').unlink();value.deadline=0
            with self.assertRaisesRegex(ValueError,'deadline'):value.check()
            value.deadline=time.monotonic()+10;value.backend=None
            with self.assertRaisesRegex(ValueError,'closed'):value.check()

    def test_failed_model_call_consumes_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c.save(root/'resident-plan.json',{})
            def fail(_):raise RuntimeError('CUDA failure')
            value=r.Resident(SimpleNamespace(admission_identity={},classify_logits=fail),root,1,time.monotonic()+10)
            with self.assertRaises(RuntimeError):value.classify_logits(None)
            self.assertEqual(value.calls,1)

    def test_disk_roundtrip_preserves_all_original_input_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);child=root/'child';child.mkdir();c.save(child/'run-plan.json',{})
            task=dict(child=str(child),batch=3,ordinal=0);expected,_=fixture()
            with patch.object(r.e,'prepare',return_value=fixture()):receipt=r.prepare_task(root,task)
            self.assertLessEqual(receipt['cache_bytes'],r.CACHE_LIMIT)
            report,tensors=r.cached(root,task);self.assertEqual(report,expected)
            for tag,values in tensors[3].items():
                self.assertEqual(values.shape,(24,2,1024))
                self.assertEqual([c.digest(x.tobytes()) for x in values],[q['inputs'][tag] for q in report['results'][0]['rows']])
            path=root/'prepared/task-000/inputs.npz';data=bytearray(path.read_bytes());data[-1]^=1;path.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'cache pin'):r.cached(root,task)

    def test_single_resident_is_reused_across_two_comparisons(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c.save(root/'resident-plan.json',{})
            backend=SimpleNamespace(admission_identity={'frozen':True},classify_logits=lambda x:([1.]+[0.]*23,1))
            resident=r.Resident(backend,root,144,time.monotonic()+10)
            report,tensors=fixture()
            tensors={3:{tag:np.stack([c.normalize_window(x) for x in vals]) for tag,vals in tensors[3].items()}}
            for n in range(2):
                out=root/str(n);out.mkdir();c.save(out/'prepared.json',report)
                result=r.e.r.compare.infer(root,out,prepare_inputs=lambda _: (report,tensors),resident=resident,normalized_inputs=True)
                self.assertEqual(result['warmup_windows'],0);self.assertEqual(result['model_windows'],72)
                self.assertEqual(result['resident_session']['pid'],resident.identity['pid'])
                r.e.r.compare.verify(root,out,prepare_inputs=lambda _: (report,tensors))
            self.assertEqual(resident.calls,144)

    def test_wrong_cached_input_rejected_before_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'out';out.mkdir();c.save(root/'resident-plan.json',{})
            report,tensors=fixture();c.save(out/'prepared.json',report)
            resident=r.Resident(SimpleNamespace(admission_identity={},classify_logits=lambda x:([0]*24,1)),root,72,time.monotonic()+10)
            tensors={3:{tag:np.zeros((24,2,1024),dtype=np.float32) for tag in r.e.TAGS}}
            with self.assertRaisesRegex(ValueError,'actual model input'):
                r.e.r.compare.infer(root,out,prepare_inputs=lambda _: (report,tensors),resident=resident,normalized_inputs=True)
            self.assertEqual(resident.calls,0)
            self.assertEqual(r.m.document(out/'inference.json')['status'],'failed')

    def test_existing_resident_does_not_create_another_backend_or_lease(self):
        value=SimpleNamespace(check=lambda:None,admission_identity={'pin':1},identity={'pid':1})
        with patch.object(r.e.r.compare,'runner',side_effect=AssertionError('new cold loader')):
            with r.e.r.compare.inference_backend(Path('/unused'),None,value) as (backend,identity):
                self.assertIs(backend,value);self.assertEqual(identity['warmup_windows'],0)

    def test_model_loads_only_after_all_disk_preprocessing_and_cpu_failure_stops_it(self):
        for fail in (False,True):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);c.save(root/'resident-plan.json',{});events=[];tasks=[];parents=[]
                for n in range(3):
                    child=root/f'child-{n}';child.mkdir();c.save(child/'run-plan.json',{})
                    parents.append({'root':str(child)});tasks.append(dict(child=str(child),batch=n,ordinal=n))
                plan=dict(acquire=False,parents=parents,tasks=tasks,deadline_seconds=600,maximum_cache_bytes=3*r.CACHE_LIMIT,maximum_model_windows=216)
                class Pool:
                    def __enter__(self):return self
                    def __exit__(self,*args):events.append('cpu_join')
                    def submit(self,fn,folder,task):
                        events.append(('submit',task['ordinal']))
                        def result():
                            if fail:raise RuntimeError('CPU preprocessing failed')
                            events.append(('disk_ready',task['ordinal']));return {'cache_bytes':1}
                        return SimpleNamespace(result=result)
                @contextmanager
                def model(*args):
                    self.assertIn('cpu_join',events)
                    self.assertEqual(sum(isinstance(x,tuple) and x[0]=='disk_ready' for x in events),3)
                    events.append('load_once');yield SimpleNamespace(check=lambda:None)
                with patch.object(r,'load',return_value=plan),patch.object(r,'ProcessPoolExecutor',return_value=Pool()),patch.object(r,'session',side_effect=model),patch.object(r,'combined',return_value=fixture()),patch.object(r.e.r.compare,'infer'),patch.object(r.e.r.compare,'verify'),patch.object(r.signal,'signal'),patch.object(r.signal,'alarm'):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError,'CPU preprocessing'):r.worker(root)
                        self.assertNotIn('load_once',events)
                    else:
                        r.worker(root);self.assertEqual(events.count('load_once'),1)
                        # Backpressure waits for the oldest of two tasks before accepting a third.
                        self.assertLess(events.index(('disk_ready',0)),events.index(('submit',2)))


if __name__=='__main__':unittest.main()
