import json
import os
from pathlib import Path
import tempfile
import unittest

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


if __name__=='__main__':unittest.main()
