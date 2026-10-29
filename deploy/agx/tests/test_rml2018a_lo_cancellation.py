"""Known-component fidelity, held-out guards, and sparse-frequency alias failure."""
from pathlib import Path
import json
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_campaign as c
import rml2018a_lo_cancellation as lo


def capture(seed=51, amplitude=7., error=0., drift=False, payload_tone=False):
    rng=np.random.default_rng(seed); run='abcdef0123456789'*2; batch=4267
    iq=rng.normal(size=(24,1024,2))
    if payload_tone:
        t=np.arange(24*1024)
        z=np.exp(2j*np.pi*250000*t/c.RATE).reshape(24,1024)
        iq=np.stack((z.real,z.imag),axis=-1)
    frame,_=c.packet(iq,run,batch,level_profile='gain-pair-pilot')
    offset=3000; n=np.arange(c.RX_SAMPLES); cfo=3800.
    clean=40*np.tile(frame,4)[offset:offset+c.RX_SAMPLES]*np.exp(2j*np.pi*cfo*n/c.RATE+.3j)
    first=c.GUARD-offset+len(frame)
    sync=dict(marker_offset=first,payload_marker_offset=first,
              estimated_cfo_hz=cfo+error,phase_rotation_rad=-.3)
    noise=.4*(rng.normal(size=len(n))+1j*rng.normal(size=len(n)))
    tone=amplitude*np.exp(2j*np.pi*(250000+cfo)*n/c.RATE+.8j)
    if drift:tone[n>35000]*=-1
    return clean+noise+tone,clean,noise,sync


class CancellationTests(unittest.TestCase):
    def test_cancels_known_tone_across_noise_seeds(self):
        for seed in range(10):
            raw,clean,noise,sync=capture(seed=seed)
            before=raw.copy();out,record=lo.cancel(raw,sync)
            self.assertEqual(record['status'],'applied',record)
            self.assertEqual(record,json.loads(json.dumps(record,allow_nan=False)))
            np.testing.assert_array_equal(raw,before)
            residual=np.mean(abs(lo.payload(out-clean-noise,sync))**2)
            self.assertLess(residual,.05)
            # Assess predicted interference on payload, not an arbitrary
            # sub-Hz parameter tolerance in this noisy finite observation.
            self.assertGreater(10*np.log10(49/residual),29.9)

    def test_does_not_fit_or_remove_legitimate_payload_at_lo_frequency(self):
        raw,clean,noise,sync=capture(payload_tone=True)
        out,record=lo.cancel(raw,sync)
        self.assertEqual(record['status'],'applied',record)
        x=lo.payload(clean,sync);y=lo.payload(out-noise,sync)
        self.assertLess(np.mean(abs(y-x)**2)/np.mean(abs(x)**2),1e-4)

    def test_payload_change_cannot_change_fitted_parameters(self):
        raw,clean,noise,sync=capture();first=lo.cancel(raw,sync)[1]
        changed=raw.copy();start=sync['payload_marker_offset']+c.MARKER
        # Exclude the pilot FIR halo when probing data independence.
        changed[start+128:start+24*1024-128]+=500j
        second=lo.cancel(changed,sync)[1]
        for key in ('frequency_hz','amplitude_real','amplitude_imag','heldout_suppression_db'):
            self.assertEqual(first[key],second[key])

    def test_no_leak_is_unchanged(self):
        raw,_,_,sync=capture(amplitude=0.)
        out,record=lo.cancel(raw,sync)
        self.assertEqual(record['status'],'skipped')
        np.testing.assert_array_equal(out,raw)

    def test_wrong_sparse_alias_prior_is_rejected_by_pilot(self):
        raw,_,_,sync=capture(error=c.RATE/(2*c.GUARD+c.MARKER+24*1024))
        out,record=lo.cancel(raw,sync)
        self.assertEqual(record['status'],'skipped',record)
        self.assertEqual(record['reason'],'pilot_does_not_confirm_frequency_prior')
        np.testing.assert_array_equal(out,raw)

    def test_outside_frequency_prior_or_unstable_guards_skip(self):
        for kwargs in ({'error':35.},{'drift':True}):
            raw,_,_,sync=capture(**kwargs)
            out,record=lo.cancel(raw,sync)
            self.assertEqual(record['status'],'skipped',record)
            np.testing.assert_array_equal(out,raw)

    def test_invalid_shapes_and_coordinates(self):
        raw,_,_,sync=capture()
        for bad in (raw[:-1],raw*np.nan):
            with self.assertRaises(ValueError):lo.cancel(bad,sync)
        with self.assertRaises(ValueError):lo.cancel(raw,{**sync,'payload_marker_offset':-1})
        with self.assertRaises(ValueError):lo.cancel(raw,{**sync,'estimated_cfo_hz':float('nan')})

    def test_quality_has_separate_plane_and_source_ceiling(self):
        rng=np.random.default_rng(17);x=rng.normal(size=1024)+1j*rng.normal(size=1024)
        for z in (0,10,30):
            q=lo.quality(x,x*(2+.7j),z,{'status':'applied'})
            self.assertEqual(q['rx_sinr_reference_plane'],lo.PLANE)
            self.assertAlmostEqual(q['rx_sinr_db'],z,places=8)
            self.assertEqual(q['rx_payload_filter'],'none')


if __name__=='__main__':unittest.main()
