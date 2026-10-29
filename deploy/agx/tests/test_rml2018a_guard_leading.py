import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_campaign as c
import rml2018a_guard_leading as candidate
import rml2018a_lo_cancellation as lo


def fixture():
    n=np.arange(65535);hz=3800.
    useful=np.zeros(65535,np.complex128)
    for k in range(4):
        start=448+k*17920
        if start+1024<=len(n):useful[start:start+1024]=c.marker('synthetic-leading',k)*200
        end=min(start+1024+16384,len(n))
        if end>start+1024:
            q=np.arange(end-start-1024)
            useful[start+1024:end]=40*(1+.3*np.cos(2*np.pi*q/256))*np.exp(.3j)
    useful*=np.exp(2j*np.pi*hz*n/c.RATE)
    leakage=(20+3j)*np.exp(2j*np.pi*(250000+hz)*n/c.RATE)
    return useful+leakage,useful


class LeadingGuardTests(unittest.TestCase):
    def test_four_guard_coordinates(self):
        self.assertEqual(lo.guard_intervals(448,16),[[0,384],[17920,18304],[35840,36224],[53760,54144]])

    def test_known_lo_removal_preserves_am_payload(self):
        raw,useful=fixture();payload,info=candidate.cancel(raw,3800.,frame_index=1,previous_spacing_samples=17920)
        self.assertEqual(info['status'],'applied')
        np.testing.assert_allclose(payload,useful[1472:17856],atol=2e-5,rtol=0)
        self.assertTrue(np.array_equal(raw,fixture()[0]))

    def test_payload_not_used_for_fit(self):
        raw,_=fixture();a,ai=candidate.cancel(raw,3800.,frame_index=1,previous_spacing_samples=17920)
        changed=raw.copy();changed[2000:17000]+=7-11j
        b,bi=candidate.cancel(changed,3800.,frame_index=1,previous_spacing_samples=17920)
        for key in ('frequency_hz','amplitude_real','amplitude_imag'):
            self.assertEqual(ai['proposal']['v1'][key],bi['proposal']['v1'][key])
        np.testing.assert_allclose(b-a,(changed-raw)[1472:17856],atol=1e-12,rtol=0)

    def test_unverified_leading_context_keeps_baseline(self):
        raw,_=fixture()
        for frame,spacing in [(0,None),(1,17921)]:
            value,info=candidate.cancel(raw,3800.,frame_index=frame,previous_spacing_samples=spacing)
            self.assertIsNone(value);self.assertEqual(info['status'],'baseline_fallback')

    def test_wrong_frequency_prior_rejected(self):
        raw,_=fixture();value,info=candidate.cancel(raw,3900.,frame_index=1,previous_spacing_samples=17920)
        self.assertIsNone(value);self.assertEqual(info['status'],'baseline_fallback')

    def test_leading_guard_step_rejected(self):
        raw,_=fixture();n=np.arange(384);raw[:384]+=(30+5j)*np.exp(2j*np.pi*253800*n/c.RATE)
        value,info=candidate.cancel(raw,3800.,frame_index=1,previous_spacing_samples=17920)
        self.assertIsNone(value);self.assertEqual(info['status'],'baseline_fallback')


if __name__=='__main__':unittest.main()
