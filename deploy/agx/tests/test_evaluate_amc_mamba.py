import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
import h5py
import numpy as np

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
import amc_dataset_contract as native

SPEC=importlib.util.spec_from_file_location('evaluate_amc_mamba',SCRIPTS/'evaluate-amc-mamba.py')
evaluation=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


class LabelTests(unittest.TestCase):
    def test_hisar_labels_follow_raw_codes_without_changing_ids(self):
        h5_names=list(native.HISARMOD2019_CODE_TO_NAME.values())
        raw=np.array(sorted(native.HISARMOD2019_CODE_TO_NAME))
        with tempfile.TemporaryDirectory() as directory:
            with h5py.File(Path(directory)/'source.h5','w') as source_file:
                source_file['classes']=np.array(h5_names,dtype='S');source_file['Y']=raw[::-1]
                source_file['X']=np.zeros((26,2,4),dtype=np.float32);source_file['Z']=np.arange(26)
                names,source,values=evaluation.load_labels('hisarmod2019',source_file,None,26)
                self.assertEqual(names,native.source_class_names(h5_names,raw))
                self.assertEqual([names[class_id] for class_id in [0,2,10,25]],['BPSK','2FSK','8PSK','256QAM'])
                np.testing.assert_array_equal(values,raw)
                self.assertEqual(source['raw_label_values'],raw.tolist())
                stats=dict(hdf5_read_seconds=0.,preprocess_seconds=0.)
                batches=list(evaluation.iter_h5_batches(source_file,np.arange(26),'N2T',values,26,26,stats))
                np.testing.assert_array_equal(batches[0][1],np.arange(25,-1,-1))

    def test_rml2018_onehot_keeps_h5_class_order(self):
        names=[str(class_id) for class_id in range(24)]
        with tempfile.TemporaryDirectory() as directory:
            with h5py.File(Path(directory)/'source.h5','w') as source_file:
                source_file['classes']=np.array(names,dtype='S');source_file['Y']=np.eye(24,dtype=np.int64)
                got,source,values=evaluation.load_labels('rml2018a',source_file,None,24)
                self.assertEqual(got,names)
                self.assertEqual(source,dict(kind='hdf5_dataset',key='classes'))
                self.assertIsNone(values)


if __name__=='__main__':unittest.main()
