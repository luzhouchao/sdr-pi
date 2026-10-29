"""Finite RX-gain profile cannot expand the existing TX authorization."""
import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(SCRIPTS))
import rml2018a_campaign as c
spec=importlib.util.spec_from_file_location('rxgain_runner',SCRIPTS/'rml2018a-rf-campaign.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class RxGainTests(unittest.TestCase):
    def plan(self,profile='qam-rx-gain-pilot',gain=40):
        return dict(tx_host='agx',tx_level_profile=profile,
            rf=dict(tx_gain_db=60,rx_gain_db=gain,peak=c.packet_peak(profile)),execution_limits=m.level_limits(profile))

    def test_only_new_profile_permits_rx50(self):
        for gain in (40,50):m.campaign_level(self.plan(gain=gain),c.RML_RXGAIN_BATCHES)
        for profile in ('qam-guard-pilot','timing-multiclass-pilot','gain-pair-pilot'):
            with self.assertRaises(ValueError):m.campaign_level(self.plan(profile,50),c.level_batches(profile))
        for gain in (0,20,60):
            with self.assertRaises(ValueError):m.campaign_level(self.plan(gain=gain),c.RML_RXGAIN_BATCHES)

    def test_bound_and_mutations(self):
        p=self.plan();self.assertEqual(p['execution_limits'],dict(allowed_batch_indices=list(c.RML_RXGAIN_BATCHES),
            maximum_tx_seconds=16,maximum_rx_iq_bytes=1048560,maximum_source_rows=96))
        for bad in ({**p,'tx_host':'nx'},{**p,'execution_limits':{}},{**p,'rf':{**p['rf'],'tx_gain_db':70}}):
            with self.assertRaises(ValueError):m.campaign_level(bad,c.RML_RXGAIN_BATCHES)
        for indices in ([66422],[True],[0]):
            with self.assertRaises(ValueError):m.campaign_level(p,indices)

    def test_new_packets_and_old_rows_disjoint(self):
        prior=set(r for b in (*c.RML_GAIN_PAIR_BATCHES,*c.RML_TIMING_BATCHES,*c.RML_GUARD_BATCHES) for r in c.batch_rows(2555904,b))
        rng=np.random.default_rng(135);iq=rng.normal(size=(24,1024,2))
        for batch in c.RML_RXGAIN_BATCHES:
            rows=c.batch_rows(2555904,batch);self.assertFalse(prior.intersection(rows))
            frame,_=c.packet(iq,'rxgain',batch,level_profile='qam-rx-gain-pilot')
            p=c.tx_plan(frame,'rxgain',batch,rows,60,level_profile='qam-rx-gain-pilot');c.validate_tx(p,frame.tobytes())
            for change in ({'batch':66422},{'rows':[0]},{'tx_gain_db':70},{'schema':c.SCHEMA}):
                with self.assertRaises(ValueError):c.validate_tx({**p,**change},frame.tobytes())


if __name__=='__main__':unittest.main()
