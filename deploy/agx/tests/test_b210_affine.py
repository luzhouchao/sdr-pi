"""Known-source affine channel tests; no RF or model loading."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import numpy as np

spec=importlib.util.spec_from_file_location('affine',Path(__file__).resolve().parents[1]/'scripts/diagnose-b210-rx-affine.py')
affine=importlib.util.module_from_spec(spec);spec.loader.exec_module(affine)


class AffineTests(unittest.TestCase):
    def reference(self):
        rng=np.random.default_rng(218)
        return .5+.2j+.3*(rng.normal(size=4096)+1j*rng.normal(size=4096))

    def test_bias_fit_preserves_genuine_source_mean(self):
        source=np.tile(self.reference(),7);gain=2*np.exp(.7j);bias=.9+1.4j
        received=gain*source+bias
        result=affine.fit_affine(source,received)
        np.testing.assert_allclose(affine.complex_value(result['gain']),gain,atol=1e-12)
        np.testing.assert_allclose(affine.complex_value(result['bias']),bias,atol=1e-12)
        recovered=(received-affine.complex_value(result['bias']))/affine.complex_value(result['gain'])
        np.testing.assert_allclose(recovered,source,atol=1e-12)
        self.assertGreater(abs(recovered.mean()),.4)

    def test_fixed_affine_coefficients_explain_heldout_and_detect_later_change(self):
        reference=self.reference();source=np.tile(reference,16)[:65535]
        received=(1.2+.4j)*source+(.6-.3j)
        coefficients=affine.fit_affine(source[:affine.FIT_SAMPLES],received[:affine.FIT_SAMPLES])
        rows=affine.heldout(reference,received,coefficients)
        self.assertEqual(len(rows),8)
        self.assertLess(max(r['affine_residual_fraction'] for r in rows),1e-25)
        self.assertGreater(min(r['gain_only_residual_fraction'] for r in rows),.01)
        received[affine.FIT_SAMPLES:]+=2j
        changed=affine.heldout(reference,received,coefficients)
        self.assertGreater(min(r['affine_residual_fraction'] for r in changed),.1)

    def test_raw_tail_cannot_influence_estimator_even_through_fft(self):
        reference=self.reference();raw=np.tile(reference,16)[:65535]*(1+.3j)+(.4-.1j)
        raw*=np.exp(2j*np.pi*(affine.RATE/affine.FIT_SAMPLES)*np.arange(len(raw))/affine.RATE)
        before,_=affine.estimate(raw,reference,0,125000)
        changed=raw.copy();changed[affine.FIT_SAMPLES:]=700+230j
        after,_=affine.estimate(changed,reference,0,125000)
        self.assertEqual(before,after)

    def test_unidentifiable_or_nonfinite_reference_is_rejected(self):
        for x,y in [(np.ones(affine.FIT_SAMPLES),np.ones(affine.FIT_SAMPLES)),
                    (np.zeros(4096),np.zeros(4096)),
                    (np.full(affine.FIT_SAMPLES,np.nan),np.ones(affine.FIT_SAMPLES))]:
            with self.assertRaises(ValueError):affine.fit_affine(x,y)

    def test_exploration_preserves_failed_gate_and_cannot_override_other_gates(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            root=Path(tmp);(root/'affine-prepared.json').write_text('{}')
            analysis=dict(tone=dict(frequency_difference_hz=0),source_99_percent_half_width_hz=125000,
                          engineering_controls=dict(passed=False))
            (root/'source-matched-analysis.json').write_text(json.dumps(analysis))
            originals=dict(source_original_order=np.ones((4096,2)),received_unmodified=np.ones((4096,2)))
            with mock.patch.object(affine.paired,'prepare_inputs',return_value=(originals,{'parent_iq_sha256':'d'})), \
                 mock.patch.object(affine.fidelity.source_match,'read_iq',return_value=(np.ones(65535),'d')), \
                 mock.patch.object(affine,'estimate',return_value=({'residual_gate_passed':False,'affine':None},np.ones(4096))):
                details,tensors=affine.prepare(root,True)
                self.assertFalse(details['source_control_passed'])
                self.assertFalse(details['qualified_bidirectional_validation'])
                self.assertEqual(len(tensors),3)  # No bypass of the residual-phase gate.
                analysis['engineering_controls']['passed']=True
                (root/'source-matched-analysis.json').write_text(json.dumps(analysis))
                with self.assertRaises(ValueError):affine.prepare(root,True)

    def test_changed_preparation_stops_before_inference_marker(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            root=Path(tmp);(root/'affine-prepared.json').write_text('{"version":1}')
            with mock.patch.object(affine,'prepare',return_value=({'version':2},{})):
                with self.assertRaises(AssertionError):asyncio.run(affine.infer(root))
            self.assertFalse((root/'affine-inference-started.json').exists())


if __name__=='__main__':unittest.main()
