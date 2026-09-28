from pathlib import Path
import sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import amc_matched_source_baseline as b

class MatchedTests(unittest.TestCase):
    def test_matching_and_scale_invariance(self):
        rng=np.random.default_rng(28)
        for dataset,length in [('rml2016a',128),('rml2018a',1024)]:
            x=rng.normal(size=(4,2,length)).astype(np.float32);old=x.copy();y=b.transform(x,dataset)
            np.testing.assert_allclose(y,b.transform(x*np.array([.25,.5,2,4],dtype=np.float32)[:,None,None],dataset),atol=1e-7,rtol=1e-6)
            np.testing.assert_array_equal(x,old)
            if length==128:np.testing.assert_allclose(np.sqrt((y.astype(float)**2).sum(1)).sum(1),1,rtol=1e-6)
            else:np.testing.assert_allclose(np.mean((y.astype(float)**2).sum(1),axis=1),1,rtol=1e-6)

    def test_tx_does_not_encode_original_absolute_row_amplitude(self):
        rng=np.random.default_rng(29);x=rng.normal(size=(2,1024))+1j*rng.normal(size=(2,1024))
        a,aa=b.transport.transmit(x,'scale-proof',frame_payload_samples=2048)
        z,zz=b.transport.transmit(x*np.array([2.,.25])[:,None],'scale-proof',frame_payload_samples=2048)
        np.testing.assert_array_equal(a,z);self.assertEqual(aa['tx_sha256'],zz['tx_sha256'])

if __name__=='__main__':unittest.main()
