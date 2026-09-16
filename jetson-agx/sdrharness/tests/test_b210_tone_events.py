import copy
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
S=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(S))
spec=importlib.util.spec_from_file_location('tone_events',S/'validate-b210-tone-events.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class ToneEventTests(unittest.TestCase):
    def test_tone_matches_prior_source_and_is_continuous_across_packets(self):
        _,prior=m.c.lo_reference('0'*32,1,schema=m.c.LO_GAIN_PAIR_SCHEMA)
        z=m.waveform();self.assertEqual(z.shape,(26112,));self.assertEqual(z.nbytes,208896)
        np.testing.assert_array_equal(z[:1024],prior)
        np.testing.assert_array_equal(z[-512:],prior[:512])
        self.assertAlmostEqual(float(abs(z).max()),.316227766,places=6)
        self.assertAlmostEqual(float(np.angle(z[0]/z[-1])),2*np.pi*98437.5/2100000,places=6)

    def test_fixed_plan_rejects_scope_and_budget_changes_before_executor(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as d, patch.object(m.e,'check_root'):
            root=Path(d);(root/'build').mkdir();(root/'build/tx-events').write_bytes(b'test-not-executable')
            p=m.plan(root);m.validate(root,p)
            for key,value in [('maximum_tx_samples',16763905),('maximum_rx_bytes',1048561),
                              ('deadline_seconds',900),('maximum_component_peak_counts',1024),
                              ('daemon_sha256','0'*64),('source_rows',1),('model_windows',1)]:
                q=copy.deepcopy(p);q[key]=value
                with self.assertRaises(ValueError):m.validate(root,q)
            for key,value in [('tx_gain_db',70),('tx_lo_offset_hz',500000)]:
                q=copy.deepcopy(p);q['rf'][key]=value
                with self.assertRaises(ValueError):m.validate(root,q)
            q=copy.deepcopy(p);q['points'][1]['rx']['gain_db']=50
            with self.assertRaises(ValueError):m.validate(root,q)
            (root/'build/tx-events').write_bytes(b'changed')
            with self.assertRaises(ValueError):m.validate(root,p)

    def test_timestamp_phases_keep_unknown_and_boundary_events(self):
        rows=[dict(event_code=2,device_seconds=t) for t in (9.,10.,13.99,14.,None)]
        phases=m.event_phases(rows,10.,14.)
        self.assertEqual([x['phase'] for x in phases],['before_start','within_nominal_burst','within_nominal_burst','at_or_after_nominal_end','unknown'])
        self.assertIsNone(phases[-1]['seconds_from_nominal_end'])
        self.assertEqual(len(phases),len(rows))

if __name__=='__main__':unittest.main()
