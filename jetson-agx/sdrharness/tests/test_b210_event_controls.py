import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
import json
import numpy as np
S=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(S))
spec=importlib.util.spec_from_file_location('event_controls',S/'validate-b210-event-controls.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class EventTests(unittest.TestCase):
    def test_sources_are_finite_and_independent_of_dataset(self):
        z=m.waveform('zero','test');q=m.waveform('known','test')
        self.assertEqual(z.nbytes,208896);self.assertFalse(np.any(z))
        self.assertFalse(np.any(q[:256]));self.assertFalse(np.any(q[-256:]))
        self.assertLessEqual(float(abs(q).max()),.632456)
        np.testing.assert_array_equal(q[256:1280],(m.c.marker('test',0)*np.sqrt(10)).astype('<c8'))
        np.testing.assert_array_equal(q,m.waveform('known','test'))
        with self.assertRaises(ValueError):m.waveform('tone','test')
    def record(self,events):
        d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup);p=Path(d.name)/'events.jsonl'
        p.write_text('\n'.join(json.dumps(r) for r in events)+'\n');return p
    def rows(self):
        return [dict(kind='go',scheduled_device_seconds=10.),dict(kind='send',offset_samples=0,requested=1024,accepted=17,host_before_ns=1,host_after_ns=2,start_of_burst=True),
         dict(kind='send',offset_samples=17,requested=1024,accepted=21,host_before_ns=3,host_after_ns=4,start_of_burst=False),
         dict(kind='async',channel=0,event_code=2,has_device_time=True,device_seconds=10.01,host_receive_mono_ns=100,host_receive_unix_ns=200),
         dict(kind='async',channel=0,event_code=1,has_device_time=False,device_seconds=None,host_receive_mono_ns=101,host_receive_unix_ns=201),
         dict(kind='summary',status='failed',accepted_samples=38,send_records=2,async_records=2,error='TX cancelled')]
    def test_partial_send_accounting_and_missing_device_time(self):
        d=m.parse_events(self.record(self.rows()),False)
        self.assertEqual(d['summary']['accepted_samples'],38)
        self.assertAlmostEqual(d['events'][0]['nominal_sample_from_scheduled_start'],21000)
        self.assertIsNone(d['events'][1]['nominal_sample_from_scheduled_start'])
    def test_cancellation_is_not_completion(self):
        with self.assertRaises(ValueError):m.parse_events(self.record(self.rows()),True)
    def test_changed_count_offset_and_timestamp_refused(self):
        for idx,key,value in [(2,'offset_samples',0),(2,'accepted',1025),(1,'host_after_ns',0),(4,'device_seconds',0),(5,'accepted_samples',100)]:
            r=self.rows();r[idx][key]=value
            with self.assertRaises(ValueError):m.parse_events(self.record(r),False)
    def test_unknown_code_preserved(self):
        r=self.rows();r[3]['event_code']=128
        d=m.parse_events(self.record(r),False);self.assertEqual(d['events'][0]['name'],'unrecognized_event_code')
    def test_exact_go_count(self):
        r=self.rows();r.insert(1,r[0])
        with self.assertRaises(ValueError):m.parse_events(self.record(r),False)

if __name__=='__main__':unittest.main()
