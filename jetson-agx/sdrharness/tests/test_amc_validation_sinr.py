from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import amc_validation_sinr as s

class StrataTests(unittest.TestCase):
    def test_bin_edges_and_invalid_are_exhaustive(self):
        values=np.array([-30,-10,-5,0,5,10,15,20,30,np.nan,np.inf])
        np.testing.assert_array_equal(s.bin_ids(values),[0,1,2,3,4,5,6,7,7,8,8])

    def test_paired_counts_share_members_not_own_plane_bins(self):
        y=np.array([0,0,1,1]);raw=np.array([0,1,0,1]);guard=np.array([1,0,1,1]);source=y
        v=s.pair_counts(y,raw,guard,source,np.array([True,True,True,False]))
        self.assertEqual(v,dict(rows=3,source_correct=3,raw_correct=1,guard_correct=2,corrected=2,regressed=1))
        self.assertEqual(v['guard_correct']-v['raw_correct'],v['corrected']-v['regressed'])

if __name__=='__main__':unittest.main()
