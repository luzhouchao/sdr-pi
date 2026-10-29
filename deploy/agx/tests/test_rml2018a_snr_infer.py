import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import rml2018a_snr_infer as m


class InferenceTests(unittest.TestCase):
    def example(self):
        ids = np.array([0,1,1],dtype=np.int16)
        masks = {t:np.array([True,True,t=='source']) for t in m.TAGS}
        logits = {t:np.full((3,24),np.nan,np.float32) for t in m.TAGS}
        for t in m.TAGS:
            logits[t][masks[t]] = 0
            logits[t][0,0] = 1
        quality = [{t:dict(rx_sinr_status='invalid',rx_sinr_reason='gain_unstable')
                    for t in ('raw','guard')} for _ in ids]
        quality[0] = {t:dict(rx_sinr_status='estimated',rx_sinr_db=-0.5) for t in ('raw','guard')}
        return ids,logits,masks,quality

    def test_full_denominator_and_invalid_sinr_still_predicted(self):
        s=m.statistics(*self.example())['raw']
        self.assertEqual((s['total'],s['predicted'],s['missing'],s['correct']),(3,2,1,1))
        self.assertEqual(s['sinr_status']['invalid'],dict(total=2,predicted=1,correct=0))
        self.assertEqual(s['sinr_bins_2db']['-2']['total'],1)
        self.assertEqual(np.asarray(s['confusion']).sum(),2)

    def test_nonfinite_valid_prediction_rejected(self):
        ids,logits,masks,q=self.example();logits['raw'][0,0]=np.nan
        with self.assertRaises(ValueError):m.statistics(ids,logits,masks,q)

    def test_merge_preserves_class_confusion_and_denominators(self):
        s=m.statistics(*self.example());out={};m.merge(out,s);m.merge(out,s)
        self.assertEqual(out['guard']['total'],6)
        self.assertEqual(out['guard']['confusion'][0][0],2)
        self.assertEqual(out['guard']['sinr_status']['invalid']['predicted'],2)

    def test_atomic_results_no_overwrite(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as d:
            root=Path(d);(root/'blocks').mkdir()
            ids,logits,masks,q=self.example();stats=m.statistics(ids,logits,masks,q)
            r=m.publish(root,'sample',np.arange(3),ids,logits,masks,stats,'input-pin')
            self.assertEqual(r['output_sha256'],m.c.file_hash(root/'blocks/sample.npz'))
            with np.load(root/'blocks/sample.npz',allow_pickle=False) as f:
                self.assertTrue(np.array_equal(f['class_id'],ids))
            with self.assertRaises(ValueError):
                m.publish(root,'sample',np.arange(3),ids,logits,masks,stats,'input-pin')

    def test_missing_full_acquisition_gate(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as d:
            root=Path(d);(root/'acquisition-complete.json').write_text(json.dumps(dict(complete=False)))
            with self.assertRaises(ValueError):m.corpus(root)

    def test_batched_scatter_keeps_missing_rows_and_empty_plane(self):
        inputs={t:np.zeros((4,2,1024),np.float32) for t in m.TAGS}
        masks=dict(source=np.ones(4,bool),raw=np.array([True,False,True,False]),guard=np.zeros(4,bool))
        for t in m.TAGS:
            inputs[t][:,0,0]=np.arange(4)
            inputs[t][~masks[t]]=np.nan
        calls=[];progress=[]
        def fake(backend,x,size,check,notify):
            check();self.assertTrue(np.isfinite(x).all());calls.append(len(x));notify(len(x))
            return np.repeat(x[:,0,:1],24,axis=1)
        with patch('rml2018a_infer_batch.infer',side_effect=fake):
            out=m.infer_inputs(None,inputs,masks,1024,lambda:None,lambda n,t:progress.append((n,t)))
        self.assertEqual(calls,[4,2]);self.assertEqual(progress,[(4,'source'),(2,'raw')])
        self.assertEqual(out['raw'][2,0],2)
        self.assertTrue(np.isnan(out['raw'][[1,3]]).all() and np.isnan(out['guard']).all())

    def test_batch_validation_requires_registered_size(self):
        with self.assertRaises(ValueError):m.batch_validation(None,8192,Path('/unused'))
        with self.assertRaises(ValueError):m.batch_validation(None,1024,Path('/unused'))

    def test_batch_cancel_does_not_return_partial_predictions(self):
        inputs={t:np.zeros((4,2,1024),np.float32) for t in m.TAGS}
        masks={t:np.ones(4,bool) for t in m.TAGS}
        def stop():raise InterruptedError('requested stop')
        def fake(backend,x,size,check,notify):check()
        with patch('rml2018a_infer_batch.infer',side_effect=fake):
            with self.assertRaises(InterruptedError):m.infer_inputs(None,inputs,masks,1024,stop,lambda *_:None)

    def test_group_commit_and_restart_preserve_cross_block_mapping(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as d:
            root=Path(d);(root/'blocks').mkdir();entries=[];packed=[]
            for number in range(2):
                ids,logits,masks,q=self.example()
                rows=np.arange(3)+number*3
                entries.append(dict(block=number,key=str(number),sha='input',rows=rows,ids=ids,masks=masks,quality=q,stats=None))
                packed.extend(logits[t][masks[t]] for t in m.TAGS)
            output=np.concatenate(packed);results=m.commit_group(root,entries,output)
            self.assertEqual([n for n,_ in results],[0,1])
            for e in entries:
                stats=m.completed_statistics(root,e['key'],(e['rows'],e['ids'],None,e['masks'],e['quality']),'input')
                self.assertEqual(stats,results[e['block']][1])
                e['stats']=stats
            self.assertEqual(m.commit_group(root,entries,np.empty((0,24),np.float32)),results)
            (root/'blocks/0.npz').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):m.completed_statistics(root,'0',(entries[0]['rows'],entries[0]['ids'],None,
                entries[0]['masks'],entries[0]['quality']),'input')

    def test_batch_gate_rechecks_metrics_despite_passed_flag(self):
        filenames=('rml2018a_infer_batch.py','amc-mamba-worker.py','amc-rf-v1-runtime.py','validate-rf-aligned-checkpoint.py')
        registration=dict(samples=1024,acquisition_sha256='pin',profile_sha256='pin',
                          software={str(m.SCRIPTS/name):'pin' for name in filenames})
        result=dict(complete=True,results=[dict(batch_size=8192,passed=True,top1_mismatches=0,
                    max_abs_logit=0.02,max_abs_softmax=0.006,peak_reserved_bytes=1000,speedup=80)])
        with patch.object(m,'read',side_effect=[result,registration]),patch.object(m.c,'file_hash',return_value='pin'):
            with self.assertRaises(ValueError):m.batch_validation(Path('/proof'),8192,Path('/corpus'))


if __name__=='__main__':unittest.main()
