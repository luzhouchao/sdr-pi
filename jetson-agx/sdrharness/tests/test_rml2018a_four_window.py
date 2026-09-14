import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import rml2018a_four_window as w
import rml2018a_snr_infer as m


class FourTests(unittest.TestCase):
    def example(self):
        rows=np.arange(8);ids=np.repeat([0,1],4)
        masks={t:np.ones(8,bool) for t in m.TAGS};logits={t:np.zeros((8,24),np.float32) for t in m.TAGS}
        q=[{t:dict(rx_sinr_status='estimated',rx_sinr_db=i-4) for t in ('raw','guard')} for i in range(8)]
        return rows,ids,logits,masks,q

    def test_shared_rms_preserves_unequal_amplitudes(self):
        x=np.array([1,2,3,4])[:,None]*np.ones((4,1024),np.complex128)
        y=w.shared_rms(x)
        np.testing.assert_allclose(y[:,0,0],np.arange(1,5)/np.sqrt(7.5),rtol=1e-6)
        self.assertAlmostEqual(float((y*y).sum(1).mean()),1,places=6)
        self.assertFalse(np.allclose((y*y).sum(1).mean(1),1))

    def test_mean_logits_is_not_majority_vote(self):
        rows,ids,logits,masks,q=self.example()
        for t in m.TAGS:logits[t][:3,0]=1;logits[t][3,1]=10
        _,mean,_=w.reduce(rows,ids,logits,masks)
        self.assertEqual(mean['raw'][0].argmax(),1)
        self.assertEqual(mean['raw'].dtype,np.float64)

    def test_missing_member_retains_group_denominator(self):
        rows,ids,logits,masks,q=self.example();masks['raw'][1]=False;logits['raw'][1]=np.nan
        s=w.statistics(rows,ids,logits,masks,q)['raw']
        self.assertEqual((s['total'],s['predicted'],s['missing']),(2,1,1))
        self.assertEqual(s['member_window_sinr_status'],{'estimated':8})
        self.assertEqual(s['sinr_bins_2db'],{})

    def test_cross_class_and_nonadjacent_rejected(self):
        rows,ids,logits,masks,_=self.example();ids[1]=2
        with self.assertRaises(ValueError):w.reduce(rows,ids,logits,masks)
        ids[1]=0;rows[1]=100
        with self.assertRaises(ValueError):w.reduce(rows,ids,logits,masks)

    def test_cross_frame_offsets_rejected_before_raw_read(self):
        rows=np.arange(1024);ids=np.zeros(1024,int);masks={t:np.ones(1024,bool) for t in m.TAGS}
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as d:
            root=Path(d)/'snr';root.mkdir();(root/'configuration.json').write_text('{"campaign_snrs":[30]}')
            (root.parent/'frames').mkdir();(root.parent/'frames/000.json').write_text('['+','.join(['{}']*64)+']')
            with m.h5py.File(root/'processed.h5','w') as f:
                b=f.create_group('blocks/000');starts=np.arange(1024)*1024;starts[2]+=256
                b['raw_sample_start']=starts;b['raw_sample_count']=np.full(1024,1024)
            with self.assertRaisesRegex(ValueError,'no guard/frame crossing'):
                w.restore(dict(root=str(root),snr=30),0,(rows,ids,None,masks,[]))

    def test_joint_commit_resume_lineage_and_tamper(self):
        rows,ids,logits,masks,q=self.example();recipe=dict(method=w.METHOD,shared_input_sha256='derived')
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as d:
            root=Path(d);(root/'blocks').mkdir()
            entry=dict(block=0,key='0',sha='parent',rows=rows,ids=ids,masks=masks,quality=q,stats=None,recipe=recipe)
            result=m.commit_group(root,[entry],np.concatenate([logits[t] for t in m.TAGS]))
            self.assertEqual(result[0][1]['source']['total'],2)
            data=(rows,ids,None,masks,q)
            self.assertEqual(m.completed_statistics(root,'0',data,'parent',recipe),result[0][1])
            with np.load(root/'blocks/0.npz') as f:
                self.assertEqual(f['group_source_rows'].shape,(2,4));self.assertEqual(f['logits_raw'].shape,(8,24))
            with self.assertRaises(ValueError):m.completed_statistics(root,'0',data,'parent',dict(method='changed'))
            with self.assertRaises(ValueError):m.completed_statistics(root,'0',data,'parent')


if __name__=='__main__':unittest.main()
