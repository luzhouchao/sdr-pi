"""原生源行血缘和复用SigMF/HDF5存储；不触及射频或真实训练成员。"""
import copy
import tempfile
from pathlib import Path
import sys
import unittest
import numpy as np
import h5py
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import amc_dataset_contract as a
import rml2018a_campaign_store as s
from test_rml2018a_store import configuration, metadata


def contract(count=1031):
    return dict(schema=a.SCHEMA,dataset_id='rml2016a',total_source_rows=220000,window_samples=128,
        class_names=[str(i) for i in range(11)],raw_label_values=list(range(11)),source_rows=list(range(count-1,-1,-1)),
        class_ids=[i%11 for i in range(count)],source_snr_db=[float(2*(i%20)-20) for i in range(count)],source_sha256='0'*64)


class DatasetTests(unittest.TestCase):
    def test_selection_intersection_is_balanced_and_deterministic(self):
        y=np.repeat(np.arange(3),100);z=np.full(300,18.)
        v1=np.arange(300);v2=np.arange(0,300,3)
        rows,report=a.select_rows(y,z,[v1,v2],3)
        self.assertEqual(report['selected_per_class'],32)
        self.assertTrue(set(rows)<=set(v1)&set(v2))
        np.testing.assert_array_equal(y[rows].reshape(-1,3),np.tile(np.arange(3),(32,1)))
        np.testing.assert_array_equal(rows,a.select_rows(y,z,[v1,v2],3)[0])
        with self.assertRaisesRegex(ValueError,'empty class'):a.select_rows(y,z,[np.arange(100)],3)

    def test_contract_rejects_wrong_shape_duplicates_labels_and_z(self):
        for key,value in [('window_samples',1024),('source_rows',[1]*1031),('class_ids',[11]*1031),('source_snr_db',[float('nan')]*1031)]:
            c=contract();c[key]=value
            with self.assertRaises(ValueError):a.validate(c)

    def test_native_store_partial_block_and_raw_guard_only(self):
        value=contract();cfg=configuration();cfg.pop('source_snr_db')
        cfg.update(native_source=value,label_map_sha256=a.label_hash(value['class_names']))
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with s.SnrStore(root,configuration=cfg) as store:
                with self.assertRaises(ValueError):store.finish()
                store.append_raw(np.ones((1031*128,2),dtype='<i2'),metadata())
                for block,count in [(0,1024),(1,7)]:
                    x=np.ones((count,2,128),dtype='<f4');mask=np.ones(count,bool)
                    inputs={tag:x.copy() for tag in ('raw','guard')};masks={tag:mask.copy() for tag in inputs}
                    starts=np.arange(count,dtype='<i8')*128+block*1024*128;counts=np.full(count,128,dtype='<i8')
                    # 最后一行模拟同步失败，仍保留在源行分母。
                    if block==1:
                        for tag in inputs:inputs[tag][-1]=np.nan;masks[tag][-1]=False
                        starts[-1]=-1;counts[-1]=0
                    quality=[dict(raw=s.c.receive_quality('synchronized',window_samples=128),sync=dict(status='synchronized')) for _ in range(count)]
                    store.append_processed(inputs,masks,starts,counts,quality)
                store.finish()
            with s.SnrStore(root) as store:
                got=list(store.iter_processed('raw'))
                np.testing.assert_array_equal(np.concatenate([x['source_row'] for x in got]),value['source_rows'])
                np.testing.assert_array_equal(np.concatenate([x['class_id'] for x in got]),value['class_ids'])
                np.testing.assert_array_equal(np.concatenate([x['source_snr_db'] for x in got]),value['source_snr_db'])
                self.assertEqual(sum(len(x['valid']) for x in got),1031)
            with h5py.File(root/'processed.h5','r') as f:
                self.assertEqual(set(f['blocks/000/inputs']),{'raw','guard'})
                self.assertEqual(f['blocks/001/inputs/raw'].shape,(7,2,128))
            with h5py.File(root/'processed.h5','r+') as f:f['blocks/000/class_id'][0]=9
            with self.assertRaisesRegex(ValueError,'stored source mapping'):s.SnrStore(root)

    def test_hisar_sparse_labels_follow_training_sorted_mapping(self):
        raw=[0,1,2,3,4,10,11,12,13,14,20,21,22,23,24,30,31,32,34,40,41,44,50,51,54,61]
        names=[str(i) for i in range(26)]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'source.h5'
            with h5py.File(path,'w') as f:
                f.create_dataset('X',shape=(780000,2,1024),dtype='f4',chunks=(1,2,1024))
                f['X'][0]=1;f['X'][10]=2;f['X'][25]=3
                y=f.create_dataset('Y',shape=(780000,),dtype='i8');y[:26]=raw
                z=f.create_dataset('Z',shape=(780000,),dtype='f4');z[:26]=18
                f.create_dataset('classes',data=names,dtype=h5py.string_dtype())
            x,c=a.read_selected(path,'hisarmod2019',np.array([25,10,0]),names,'0'*64)
            self.assertEqual(c['class_ids'],[25,10,0]);self.assertEqual(c['raw_label_values'],raw)
            np.testing.assert_array_equal(x[:,0],[3+3j,2+2j,1+1j])
            with self.assertRaisesRegex(ValueError,'class order'):
                a.read_selected(path,'hisarmod2019',np.array([0]),names[::-1],'0'*64)

    def test_spectrum_preserves_dc_and_rejects_outside_tx_passband(self):
        n=np.arange(128)
        x=(2+np.exp(2j*np.pi*8*n/128))[None,:]
        good=a.spectrum_screen(x);self.assertTrue(good['passed'])
        self.assertAlmostEqual(good['mean_projection_fraction'][0],.8)
        bad=a.spectrum_screen(np.exp(-2j*np.pi*40*n/128)[None,:])
        self.assertFalse(bad['passed']);self.assertGreater(bad['outside_fraction'][0],.99)

    def test_wrong_class_order_digest_rejected_before_data_write(self):
        cfg=configuration();cfg['native_source']=contract()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'native source identity'):s.SnrStore(Path(d),configuration=cfg)
            self.assertFalse((Path(d)/'raw.sigmf-data').exists())

if __name__=='__main__':unittest.main()
