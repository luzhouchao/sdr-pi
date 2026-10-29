"""Guard-only fit identity, unchanged holdout gates and optional real CUDA."""
import os
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_campaign as c
import rml2018a_guard_tone as guard
import rml2018a_lo_cancellation as lo
from rml2018a_guard_gpu import FrequencyFit,GuardBatch
from test_rml2018a_lo_cancellation import capture


def fit_for(raw,sync,frequency):
    n=np.concatenate([np.arange(a,a+192) for a,b in lo.guard_intervals(sync['payload_marker_offset'],24)])
    return FrequencyFit(c.digest(raw[n].astype('<c16').tobytes()),c.digest(n.astype('<i8').tobytes()),
                        250000+sync['estimated_cfo_hz'],frequency),n


class GuardFitTests(unittest.TestCase):
    def test_proposal_cannot_be_reused_on_different_guards_or_prior(self):
        raw,_,_,sync=capture();frequency=lo.cancel(raw,sync)[1]['frequency_hz']
        fit,n=fit_for(raw,sync,frequency)
        self.assertEqual(fit.verify(raw[n],n,fit.prior_hz),frequency)
        with self.assertRaises(ValueError):fit.verify(raw[n]+1,n,fit.prior_hz)
        with self.assertRaises(ValueError):fit.verify(raw[n],n+1,fit.prior_hz)
        with self.assertRaises(ValueError):fit.verify(raw[n],n,fit.prior_hz+1)

    def test_heldout_and_pilot_gates_remain_required(self):
        raw,_,_,sync=capture();fit,n=fit_for(raw,sync,253800.)
        # A valid fit of unchanged training guards cannot authorize changed
        # heldout IQ; the same original gate must still reject the window.
        modified=raw.copy();a,b=lo.guard_intervals(sync['payload_marker_offset'],24)[-1]
        modified[a+192:b]+=100*np.exp(2j*np.pi*253800*np.arange(a+192,b)/c.RATE)
        out,info=guard.cancel(modified,sync,frequency_fit=fit,pilot_only=True)
        self.assertEqual(info['status'],'skipped');np.testing.assert_array_equal(out,modified)

    def test_boundary_and_out_of_prior_proposals_do_not_apply(self):
        raw,_,_,sync=capture()
        fit,_=fit_for(raw,sync,None)
        out,info=lo.cancel(raw,sync,frequency_fit=fit)
        self.assertEqual(info['reason'],'frequency_at_prior_boundary');np.testing.assert_array_equal(out,raw)
        fit,_=fit_for(raw,sync,260000.)
        with self.assertRaises(ValueError):lo.cancel(raw,sync,frequency_fit=fit)

    @unittest.skipUnless(os.environ.get('RML_GUARD_CUDA_TESTS')=='1','explicit CUDA validation')
    def test_cuda_search_finds_known_pilot_through_zero_preamble(self):
        import rml2018a_stream_dsp as dsp
        import rml2018a_campaign_gpu as gpu
        run_id='cuda-search-known-pilot'
        decoder=dsp.Decoder(run_id,np.empty((2048,1024)),gpu.PayloadBatch('cuda'))
        decoder.samples=np.zeros(1048576,complex)
        n=np.arange(4096,5120)
        decoder.samples[4096:5120]=c.marker(run_id,0)*np.exp(2j*np.pi*8000*n/c.RATE)
        decoder.find_first()
        self.assertEqual(decoder.marker,4096);self.assertEqual(decoder.hz,8000.)

    @unittest.skipUnless(os.environ.get('RML_GUARD_CUDA_TESTS')=='1','explicit CUDA validation')
    def test_cuda_known_tone_wrong_prior_drift_and_payload_tone(self):
        import torch
        cases=[{},dict(error=35.),dict(drift=True),dict(error=c.RATE/(2*c.GUARD+c.MARKER+24*1024)),dict(payload_tone=True)]
        captures=[capture(**kw) for kw in cases];raws=[v[0] for v in captures];syncs=[v[3] for v in captures]
        fits=GuardBatch(torch).fit(raws,syncs,24)
        for raw,sync,fit in zip(raws,syncs,fits):
            expected,a=guard.cancel(raw,sync,pilot_only=True)
            actual,b=guard.cancel(raw,sync,pilot_only=True,frequency_fit=fit)
            self.assertEqual((a['status'],a['reason']),(b['status'],b['reason']))
            error=np.sqrt(np.mean(abs(actual-expected)**2)/np.mean(abs(expected)**2))
            self.assertLess(error,1e-5)


if __name__=='__main__':unittest.main()
