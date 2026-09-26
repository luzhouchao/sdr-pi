"""Durable cross-dataset ordering; no hardware or model access."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import h5py
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import amc_validation_campaign as v

class CampaignTests(unittest.TestCase):
    def test_next_dataset_requires_previous_durable_seal(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);d=dict(dataset='a',rows=3,validation_rows_sha256='abc');p=dict(datasets=[d,dict(dataset='b')]);folder=root/'a';folder.mkdir()
            v.barrier(root,p,0)
            with self.assertRaisesRegex(ValueError,'not committed'):v.barrier(root,p,1)
            (folder/'raw-guard.h5').write_bytes(b'index')
            v.durable(folder/'dataset-complete.json',dict(status='complete',rows=3,validation_rows_sha256='abc',virtual_dataset_sha256=v.c.file_hash(folder/'raw-guard.h5')))
            v.barrier(root,p,1)
            (folder/'raw-guard.h5').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'index changed'):v.barrier(root,p,1)

    def test_complete_virtual_dataset_preserves_rank_and_native_shape(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);rows=np.array([9,3,7]);d=dict(dataset='test',rows=3,batch_rows=2,window_samples=128,validation_rows_sha256='abc')
            for i,start in enumerate((0,2)):
                root=folder/f'batch-{i:05d}';(root/'corpus').mkdir(parents=True);n=min(2,3-start)
                with h5py.File(root/'corpus/processed.h5','w') as f:
                    b=f.create_group('blocks/000');b['source_row']=rows[start:start+n]
                    for k in ('class_id','source_snr_db','raw_sample_start','raw_sample_count'):b[k]=np.arange(n)
                    for tag in ('raw','guard'):
                        b['inputs/'+tag]=np.ones((n,2,128),np.float32)*(i+1);b['valid/'+tag]=np.ones(n,bool)
                v.durable(root/'batch-complete.json',dict(test=True))
            with patch.object(v,'verify_batch',return_value={}):
                v.seal_dataset(folder,d,rows)
            with h5py.File(folder/'raw-guard.h5') as f:
                np.testing.assert_array_equal(f['source_row'][:],rows)
                self.assertEqual(f['inputs/raw'].shape,(3,2,128))
                self.assertEqual(f['inputs/raw'][2,0,0],2)
                np.testing.assert_array_equal(f['validation_rank'][:],np.arange(3))
            self.assertTrue((folder/'dataset-complete.json').exists())

    def test_bad_batch_prevents_dataset_commit(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t)
            with patch.object(v,'verify_batch',side_effect=ValueError('bad SHA')):
                with self.assertRaisesRegex(ValueError,'bad SHA'):
                    v.seal_dataset(folder,dict(rows=1,batch_rows=1),np.array([3]))
            self.assertFalse((folder/'dataset-complete.json').exists())

    def test_fingerprint_detects_source_mutation(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'source';p.write_bytes(b'abc');before=v.fingerprint(p);p.write_bytes(b'abcd')
            self.assertNotEqual(before,v.fingerprint(p))

if __name__=='__main__':unittest.main()
