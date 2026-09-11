"""Discovery and independent confirmation selection, no RF."""
import importlib.util
from pathlib import Path
import sys
import unittest

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('survey',SCRIPTS/'diagnose-rml2018a-link-quality.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def row(center,maximum,p95=2,status='captured'):
    return dict(center_hz=center,status=status,statistics=dict(filtered=dict(maximum=maximum,p95=p95),raw=dict(maximum=maximum*2)))


class SurveyTests(unittest.TestCase):
    def discovery(self):
        return [row(center,8) for center in m.SURVEY_CENTERS+m.SURVEY_CENTERS[::-1]+m.SURVEY_CENTERS]

    def test_worst_round_ranking_rejects_a_single_lucky_capture_and_clipping(self):
        rows=self.discovery()
        for r in rows:
            if r['center_hz']==m.c.CENTER:r['statistics']['filtered']['maximum']=.1
            if r['center_hz']==2415000000:r['statistics']['filtered']['maximum']=3
            if r['center_hz']==2405000000:r['statistics']['filtered']['maximum']=1
        rows[15]['statistics']['filtered']['maximum']=50  #2405MHz second round
        selected=m.select_survey(rows)
        self.assertEqual(selected['candidate_hz'],2415000000)
        rows[1]['status']='clipped'
        self.assertNotEqual(m.select_survey(rows)['candidate_hz'],2415000000)
        self.assertIn(2415000000,m.select_survey(rows)['excluded_clipped_or_failed'])

    def test_incomplete_discovery_never_selects(self):
        with self.assertRaises(ValueError):m.select_survey(self.discovery()[:-1])

    def test_confirmation_preserves_failure_and_does_not_reselect(self):
        candidate=2415000000
        centers=[m.c.CENTER,candidate,candidate,m.c.CENTER,m.c.CENTER,candidate]
        rows=[row(f,3 if f==candidate else 30) for f in centers]
        result=m.confirm_survey(rows,candidate)
        self.assertTrue(result['quiet_background_gate'])
        self.assertEqual(result['paired_filtered_peak_reduction_db'],[20.,20.,20.])
        rows[2]['status']='clipped'
        result=m.confirm_survey(rows,candidate)
        self.assertFalse(result['quiet_background_gate'])
        self.assertIsNone(result['paired_filtered_peak_reduction_db'][1])
        self.assertFalse(result['reselection'])
        rows[2]['status']='captured';rows[2]['statistics']['filtered']['maximum']=9
        self.assertFalse(m.confirm_survey(rows,candidate)['quiet_background_gate'])


if __name__=='__main__':unittest.main()
