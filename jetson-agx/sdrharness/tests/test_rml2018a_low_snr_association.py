import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from rml2018a_low_snr_association import index_unique, stratified_comparison


class AssociationTests(unittest.TestCase):
    def row(self,c,s,state,value):
        return dict(truth=c,source_snr_db=s,state=state,value=value)

    def test_duplicate_identity_rejected(self):
        with self.assertRaises(ValueError):
            index_unique([dict(source_row=1),dict(source_row=1)])

    def test_class_and_snr_confound_not_matched(self):
        rows=[self.row(1,-10,'regressed',100),self.row(2,-10,'retained_correct',0),
              self.row(1,-8,'retained_correct',0)]
        r=stratified_comparison(rows,'value')
        self.assertEqual(r['matched_cells'],0)
        self.assertIsNone(r['cell_equal_fraction_higher'])

    def test_cell_equal_not_pair_weighted_and_ignore_wrong(self):
        rows=[self.row(0,-10,'regressed',3),self.row(0,-10,'retained_correct',2),
              self.row(1,-10,'regressed',0),self.row(1,-10,'regressed',0),
              self.row(1,-10,'retained_correct',1),self.row(1,-10,'retained_correct',1),
              self.row(1,-10,'both_wrong',999),self.row(1,-10,'corrected',999)]
        r=stratified_comparison(rows,'value')
        self.assertEqual(r['pairs'],5)
        self.assertEqual(r['regressions'],3)
        self.assertEqual(r['controls'],3)
        self.assertEqual(r['cell_equal_fraction_higher'],.5)
        self.assertEqual(r['cell_equal_mean_difference'],0)

    def test_ties_half_credit(self):
        rows=[self.row(0,-10,'regressed',1),self.row(0,-10,'retained_correct',1)]
        self.assertEqual(stratified_comparison(rows,'value')['cell_equal_fraction_higher'],.5)


if __name__=='__main__':unittest.main()
