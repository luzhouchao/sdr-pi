"""The remaining-class pilot is finite and complements the prior eight classes."""
import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(SCRIPTS))
import rml2018a_campaign as c
spec=importlib.util.spec_from_file_location('remaining_runner',SCRIPTS/'rml2018a-rf-campaign.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class RemainingTests(unittest.TestCase):
    def test_complete_complement_and_source_membership(self):
        self.assertEqual(set(c.RML_REMAINING_CLASSES)|set(c.RML_TIMING_CLASSES),set(range(24)))
        self.assertFalse(set(c.RML_REMAINING_CLASSES)&set(c.RML_TIMING_CLASSES))
        self.assertEqual(len(c.RML_REMAINING_BATCHES),16)
        for batch,cid in zip(c.RML_REMAINING_BATCHES,c.RML_REMAINING_CLASSES):
            rows=c.batch_rows(2555904,batch)
            self.assertTrue(all(cid*106496+102400<=r<(cid+1)*106496 for r in rows))

    def test_only_rx50_tx60_finite_budget(self):
        profile='remaining-high-snr-pilot';p=dict(tx_host='agx',tx_level_profile=profile,
            rf=dict(tx_gain_db=60,rx_gain_db=50,peak=c.packet_peak(profile)),execution_limits=m.level_limits(profile))
        self.assertEqual(p['execution_limits'],dict(allowed_batch_indices=list(c.RML_REMAINING_BATCHES),
            maximum_tx_seconds=64,maximum_rx_iq_bytes=4194240,maximum_source_rows=384))
        m.campaign_level(p,c.RML_REMAINING_BATCHES)
        for change in ({'rx_gain_db':40},{'tx_gain_db':70},{'peak':.2}):
            with self.assertRaises(ValueError):m.campaign_level({**p,'rf':{**p['rf'],**change}},c.RML_REMAINING_BATCHES)
        with self.assertRaises(ValueError):m.campaign_level(p,[66440])
        with self.assertRaises(ValueError):m.campaign_level({**p,'tx_host':'nx'},c.RML_REMAINING_BATCHES)

    def test_transmit_packet_identity(self):
        rng=np.random.default_rng(177);iq=rng.normal(size=(24,1024,2));batch=c.RML_REMAINING_BATCHES[-1]
        frame,_=c.packet(iq,'remaining',batch,level_profile='remaining-high-snr-pilot')
        plan=c.tx_plan(frame,'remaining',batch,c.batch_rows(2555904,batch),60,level_profile='remaining-high-snr-pilot')
        c.validate_tx(plan,frame.tobytes())
        for change in ({'schema':c.SCHEMA},{'batch':66440},{'rows':[0]},{'tx_gain_db':70}):
            with self.assertRaises(ValueError):c.validate_tx({**plan,**change},frame.tobytes())


if __name__=='__main__':unittest.main()
