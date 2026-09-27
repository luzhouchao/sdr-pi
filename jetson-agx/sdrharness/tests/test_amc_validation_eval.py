import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import h5py
import numpy as np

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
import amc_validation_eval as e


class EvaluationTests(unittest.TestCase):
    def test_resident_budget_reserves_model_memory(self):
        d=dict(rows=383385,window_samples=1024)
        self.assertFalse(e.resident_budget(d,12*1024**3)['allowed'])
        self.assertTrue(e.resident_budget(d,50*1024**3)['allowed'])

    def test_resident_matches_streaming_and_keeps_source_unchanged(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'rml2016a').mkdir();original=root/'original.h5';vds=root/'rx.h5'
            x=np.arange(4*2*128,dtype=np.float32).reshape(4,2,128)+1;ids=np.array([3,0,2]);labels=np.array([1,0,0])
            with h5py.File(original,'w') as f:
                f['X']=x;f['Y']=[0,1,0,1];f['Z']=np.arange(4);f['classes']=np.array(['a','b'],dtype='S')
            with h5py.File(vds,'w') as f:
                f['source_row']=ids;f['class_id']=labels;f['source_snr_db']=ids;f['validation_rank']=np.arange(3)
                for tag in ('raw','guard'):f['inputs/'+tag]=x[ids]*2;f['valid/'+tag]=np.ones(3,dtype=bool)
            d=dict(dataset='rml2016a',rows=3,window_samples=128,processed={},vds=str(vds),vds_sha256=e.backend.digest(vds),
                   source_path=str(original),source_sha256=e.backend.digest(original),class_names=['a','b'],raw_label_values=[0,1])
            with patch.object(e,'resource_gate',return_value={'available_kib':60*1024**2}):data=e.load_resident(d,root)
            np.testing.assert_array_equal(data['inputs/source'],x[ids])
            np.testing.assert_array_equal(data['inputs/raw'],e.normalize(x[ids]*2,'rml2016a'))
            self.assertTrue(all(not v.flags.writeable for v in data.values()))

    def test_original_source_preserves_values_and_member_order(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'source.h5';x=np.arange(6*2*128,dtype=np.float32).reshape(6,2,128)
            with h5py.File(p,'w') as f:
                f['X']=x;f['Y']=np.array([4,7,4,7,4,7]);f['Z']=np.arange(6);f['classes']=np.array(['a','b'],dtype='S')
            d=dict(dataset='hisarmod2019',source_path=str(p),window_samples=128,class_names=['a','b'],raw_label_values=[4,7])
            got=e.source_values(d,np.array([5,0,2]),np.array([1,0,0]),np.array([5,0,2]))
            np.testing.assert_array_equal(got,x[[5,0,2]])
            with self.assertRaisesRegex(ValueError,'labels and Z'):
                e.source_values(d,np.array([5]),np.array([0]),np.array([5]))

    def test_unreadable_gpu_is_recorded_but_unreadable_cpu_stops(self):
        names=['cpu-thermal','tj-thermal','soc0-thermal','soc1-thermal','soc2-thermal','gpu-thermal','cv0-thermal']
        missing={'gpu-thermal','cv0-thermal'}
        def read(path,*args,**kwargs):
            if str(path)=='/proc/meminfo':return 'MemAvailable: 60000000 kB\n'
            if path.name=='type':return path.parent.name
            if path.parent.name in missing:raise TypeError('power-gated sysfs read')
            return '49000'
        with patch.object(Path,'glob',return_value=[Path('/thermal')/n for n in names]),patch.object(Path,'read_text',read):
            self.assertEqual(set(e.resource_gate()['unmeasured']),missing)
            missing.add('cpu-thermal')
            with self.assertRaisesRegex(ValueError,'resource gate'):e.resource_gate()

    def test_native_normalization_uses_received_amplitude_only(self):
        x=np.array([[[3.,0.],[4.,2.]]],dtype=np.float32)
        got=e.normalize(x,'rml2016a')
        np.testing.assert_allclose(got,x/7,rtol=1e-7)
        np.testing.assert_array_equal(e.normalize(x,'rml2018a'),x)
        np.testing.assert_array_equal(x,[[[3.,0.],[4.,2.]]])
        with self.assertRaisesRegex(ValueError,'nonzero'):
            e.normalize(np.zeros_like(x),'rml2016b')

    def test_resume_shard_checks_membership_argmax_and_hash(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=root/'rows.npz'
            with h5py.File(root/'source.h5','w') as f:
                f['source_row']=[9,2];f['class_id']=[0,1]
                values=dict(source_row=np.array([9,2]),class_id=np.array([0,1]),validation_rank=np.array([0,1]))
                for tag in ('raw','guard'):
                    values[tag+'_logits']=np.array([[2,1],[1,3]],dtype=np.float32)
                    values[tag+'_prediction']=np.array([0,1])
                e.save_shard(p,values)
                np.testing.assert_array_equal(e.verify_shard(p,f,0,2,2)['guard'],np.eye(2,dtype=int))
                values['source_row']=np.array([2,9]);e.save_shard(p,values)
                with self.assertRaisesRegex(ValueError,'membership'):e.verify_shard(p,f,0,2,2)
                values['source_row']=np.array([9,2]);values['raw_prediction']=np.array([1,1]);e.save_shard(p,values)
                with self.assertRaisesRegex(ValueError,'argmax'):e.verify_shard(p,f,0,2,2)
                with p.open('ab') as out:out.write(b'changed')
                with self.assertRaisesRegex(ValueError,'hash'):e.verify_shard(p,f,0,2,2)


if __name__=='__main__':unittest.main()
