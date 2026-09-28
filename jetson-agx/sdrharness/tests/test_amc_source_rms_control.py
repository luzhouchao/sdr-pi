from pathlib import Path
import sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from amc_source_rms_control import rms_only

class RmsControlTests(unittest.TestCase):
    def test_only_scalar_changes_and_input_stays_intact(self):
        x=np.array([[[3.,3.],[4.,4.]],[[1.,2.],[3.,4.]]],dtype=np.float32);before=x.copy();out,rms=rms_only(x)
        np.testing.assert_array_equal(x,before)
        np.testing.assert_allclose(np.mean(np.sum(out.astype(float)**2,axis=1),axis=1),1,rtol=1e-6)
        np.testing.assert_allclose(out*rms[:,None,None],x,rtol=1e-6)
        self.assertNotEqual(float(out[0,0].mean()),0)
        with self.assertRaisesRegex(ValueError,'positive RMS'):rms_only(np.zeros_like(x))

if __name__=='__main__':unittest.main()
