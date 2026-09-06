"""Deterministic synthetic checks for diagnostic matching; never invokes radios."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
import numpy as np

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/analyze-b210-source-match.py'
spec=importlib.util.spec_from_file_location('source_match',SCRIPT)
match=importlib.util.module_from_spec(spec)
spec.loader.exec_module(match)


class SourceMatchTests(unittest.TestCase):
    def test_known_delay_and_frequency_match_but_noise_does_not(self):
        rng=np.random.default_rng(841)
        reference=rng.normal(size=4096)+1j*rng.normal(size=4096)
        lag=371
        clean=np.tile(np.roll(reference,lag),16)[:65535]
        offset=3532.5
        received=(clean+.01*(rng.normal(size=65535)+1j*rng.normal(size=65535)))*np.exp(2j*np.pi*offset*np.arange(65535)/match.RATE)
        bw=match.source_bandwidth(reference)
        cc=match.envelope_correlations(received,reference,offset,bw)
        inferred=int(np.median(cc[:7].argmax(axis=1)))
        self.assertEqual(inferred,lag)
        self.assertGreater(np.median(cc[7:,inferred]),.99)
        noise=rng.normal(size=65535)+1j*rng.normal(size=65535)
        null=match.envelope_correlations(noise,reference,offset,bw)
        self.assertLess(abs(np.median(null[7:,inferred])),.05)

    def test_tone_offset_and_same_bin_comparison(self):
        rng=np.random.default_rng(183)
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            root=Path(tmp)
            for tag in ['baseline','during-tx','after-tx']:
                directory=root/tag;directory.mkdir()
                z=5*(rng.normal(size=65535)+1j*rng.normal(size=65535))
                if tag=='during-tx':z+=1000*np.exp(2j*np.pi*103500*np.arange(65535)/2500000)
                np.stack([z.real,z.imag],axis=1).astype('<i2').tofile(directory/'test.sigmf-data')
            result=match.tone_metrics(root)
            self.assertLess(abs(result['frequency_difference_hz']-3500),20)
            cases=result['cases']
            for tag in ['baseline','after-tx']:
                self.assertGreater(cases['during-tx']['same_observed_bin_dbfs']-cases[tag]['same_observed_bin_dbfs'],50)


if __name__=='__main__':unittest.main()
