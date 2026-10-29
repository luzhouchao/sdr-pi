"""Independent known-component checks for the new empirical tone criterion."""
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_campaign as c
import rml2018a_guard_tone as guard
import rml2018a_lo_cancellation as old
from test_rml2018a_lo_cancellation import capture


class GuardToneTests(unittest.TestCase):
    def test_broad_guard_burst_retained_while_stable_tone_is_removed(self):
        accepted=rescued=0
        for seed in range(40):
            raw,clean,noise,sync=capture(seed=seed)
            rng=np.random.default_rng(seed+1234)
            at,stop=old.guard_intervals(sync['payload_marker_offset'],24)[-1]
            burst=np.zeros(len(raw),complex)
            burst[at+192:stop]=4*(rng.normal(size=192)+1j*rng.normal(size=192))
            raw+=burst;before=raw.copy();result,info=guard.cancel(raw,sync)
            np.testing.assert_array_equal(raw,before)
            if info['status']=='applied':
                accepted+=1;rescued+=info['v1']['status']=='skipped'
                # Ground truth includes all injected broadband noise: none is erased.
                error=np.mean(abs(result-clean-noise-burst)**2)
                self.assertLess(error,49/100,info)
            else:np.testing.assert_array_equal(result,raw)
        self.assertGreaterEqual(accepted,20)
        self.assertGreaterEqual(rescued,20)

    def test_changed_lo_and_wrong_alias_rejected(self):
        for kwargs in ({'drift':True},{'error':c.RATE/(2*c.GUARD+c.MARKER+24*1024)}, {'error':35.}):
            raw,_,_,sync=capture(**kwargs);out,info=guard.cancel(raw,sync)
            self.assertEqual(info['status'],'skipped',info);np.testing.assert_array_equal(out,raw)

    def test_large_correlated_guard_uncertainty_rejected(self):
        raw,_,_,sync=capture()
        a,b=old.guard_intervals(sync['payload_marker_offset'],24)[-1]
        n=np.arange(a+192,b)
        raw[n]+=20*np.repeat(np.array([1,-1]*4),24)*np.exp(2j*np.pi*253800*n/c.RATE)
        result,info=guard.cancel(raw,sync)
        self.assertEqual(info['status'],'skipped');np.testing.assert_array_equal(result,raw)

    def test_payload_cannot_control_fit_or_gate(self):
        raw,_,_,sync=capture();first=guard.cancel(raw,sync)[1]
        at=sync['payload_marker_offset']+1024
        raw[at+128:at+24*1024-128]+=100j
        second=guard.cancel(raw,sync)[1]
        for key in ('status','reason','halves','maximum_relative_error_margin'):
            self.assertEqual(first[key],second[key])

    def test_finite_qam_profile(self):
        rng=np.random.default_rng(9);iq=rng.normal(size=(24,1024,2))
        for b in c.RML_GUARD_BATCHES:
            frame,_=c.packet(iq,'qam-test',b,level_profile='qam-guard-pilot')
            p=c.tx_plan(frame,'qam-test',b,c.batch_rows(2555904,b),60,level_profile='qam-guard-pilot')
            c.validate_tx(p,frame.tobytes())
            for change in ({'batch':66406},{'tx_gain_db':70},{'schema':c.SCHEMA},{'rows':[0]}):
                with self.assertRaises(ValueError):c.validate_tx({**p,**change},frame.tobytes())


if __name__=='__main__':unittest.main()
