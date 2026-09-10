"""No RF/model: shared-RMS parity and paired source provenance rejection."""
import asyncio
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import numpy as np

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,SCRIPTS/file)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
paired=module('paired','compare-b210-source-received.py')
link=module('link','validate-b210-p201-link.py')


class PairedTests(unittest.TestCase):
    def test_exact_frozen_golden_bytes(self):
        n=np.arange(4096)
        iq=np.stack(((n*37+11)%1901-950,(n*53+7)%1799-899),axis=1).astype('<i2')
        self.assertEqual(hashlib.sha256(iq.tobytes()).hexdigest(),
                         '9ddea8749993725208a8828bc68294396a9a50e4b5a4d242625d462913e518b6')
        data=paired.normalize(iq)
        self.assertEqual(hashlib.sha256(data.tobytes()).hexdigest(),
                         '937c7c9497ca9f7990ee4256c617d5c57739e66da3da7498de1ab9d1618d2db2')

    def test_amplitude_scaling_preserves_normalized_group_and_dc(self):
        rng=np.random.default_rng(714)
        iq=(rng.normal(size=(4096,2))+1).astype(np.float32)
        base=paired.normalize(iq)
        np.testing.assert_allclose(paired.normalize(iq*.2),base,rtol=1e-6,atol=1e-6)
        self.assertGreater(abs(base.mean()),.3)

    def test_constant_carrier_is_preserved(self):
        iq=np.zeros((4096,2),dtype=np.float32);iq[:,0]=3
        data=paired.normalize(iq)
        np.testing.assert_array_equal(data[:,0,:],np.ones((4,1024)))
        np.testing.assert_array_equal(data[:,1,:],np.zeros((4,1024)))

    def test_bad_shape_nonfinite_and_silence_fail(self):
        for data in (np.ones((1024,2)),np.full((4096,2),np.nan),np.zeros((4096,2))):
            with self.assertRaises(Exception):paired.normalize(data)

    def test_modified_source_fails_before_model_or_rx(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            root=Path(directory)
            (root/'train-tile.fc32').write_bytes(b'wrong')
            for file in ('transmission-plan.json','source-matched-analysis.json','link-summary.json'):
                (root/file).write_text('{}')
            with self.assertRaises((AssertionError,KeyError)):paired.prepare_inputs(root)

    def test_existing_attempt_or_invalid_gain_never_contacts_radio(self):
        root=Path('/var/tmp/sdrharness-dev')/f'b210-control-test-{os.getpid()}'
        root.mkdir(mode=0o700)
        try:
            (root/'link-started.json').write_text('{}')
            with mock.patch.object(link.asyncio,'create_subprocess_exec') as spawn:
                with self.assertRaises(FileExistsError):asyncio.run(link.run(root,Path('/absent'),'tone',40))
                with self.assertRaises(AssertionError):asyncio.run(link.run(root,Path('/absent'),'tone',60))
                spawn.assert_not_called()
        finally:
            (root/'link-started.json').unlink();root.rmdir()


class RfCaseBoundsTests(unittest.TestCase):
    def test_3500_tone_has_fixed_low_gain(self):
        self.assertEqual(link.validate_rf_case('tone',20,3500000000),0)

    def test_3500_does_not_enable_rml_other_gains_or_neighbor_frequencies(self):
        cases=[('rml',20,3500000000),('tone',40,3500000000),('tone',50,3500000000),
               ('tone',20,3499999999),('tone',20,3500000001),('tone',20,True)]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(AssertionError):
                link.validate_rf_case(*args)

    def test_explicit_3500_gain_matrix_and_rejection(self):
        for gain in (0,10,20):
            self.assertEqual(link.validate_rf_case('tone',20,3500000000,gain),gain)
        for gain in (-1,1,30,70,True,10.0):
            with self.assertRaises(AssertionError):link.validate_rf_case('tone',20,3500000000,gain)
        for mode,rx,center in [('rml',20,3500000000),('tone',40,3500000000),('tone',40,2455000000)]:
            with self.assertRaises(AssertionError):link.validate_rf_case(mode,rx,center,10)

    def test_historical_profiles_keep_their_gains(self):
        for center in (2440000000,2455000000):
            for mode in ('tone','rml'):
                for gain in (40,50):self.assertEqual(link.validate_rf_case(mode,gain,center),70)
            with self.assertRaises(AssertionError):link.validate_rf_case('tone',20,center)


if __name__=='__main__':unittest.main()
