"""No hardware: constrained TX sources and independent tone/LO attribution."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
import rml2018a_campaign as c


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,SCRIPTS/filename)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


class CableLoTests(unittest.TestCase):
    def test_daemon_identity_is_pinned_per_plan_and_unknown_release_refused(self):
        diagnostic=load('lo_deployment','validate-b210-cable-lo.py')
        self.assertEqual(diagnostic.expected_daemon({}), diagnostic.LEGACY_DAEMON_SHA256)
        self.assertEqual(diagnostic.expected_daemon({'daemon_sha256':diagnostic.FULL_SNR_DAEMON_SHA256}),
                         diagnostic.FULL_SNR_DAEMON_SHA256)
        with patch.object(diagnostic.socket,'create_connection') as connect:
            for value in ('0'*64, None, '', ['invalid']):
                with self.assertRaises(ValueError):diagnostic.preflight(None,None,value)
            connect.assert_not_called()

    def test_gain_pair_compensates_nominal_level_without_unregistered_overrides(self):
        nominal=[]
        for index in range(4):
            plan,z=c.lo_reference('d'*32,index,schema=c.LO_GAIN_PAIR_SCHEMA)
            c.validate_tx(plan,z.tobytes())
            nominal.append(float(np.mean(abs(z.astype(complex))**2))*10**(plan['tx_gain_db']/10))
            self.assertEqual(plan['lo_offset_hz'],250000)
            self.assertEqual(plan['tx_gain_db'],70 if index%2==0 else 60)
            self.assertEqual(plan['tx_samples'],8399872)
            self.assertLessEqual(abs(z).max(),.316228)
            for key,value in (('tx_gain_db',80),('complex_peak',.4),('lo_offset_hz',-250000),
                ('schema','unregistered'),('batch',4)):
                with self.assertRaises(ValueError):c.validate_tx({**plan,key:value},z.tobytes())
            if index%2:
                with self.assertRaises(ValueError):
                    c.validate_tx({**plan,'schema':c.LO_REFERENCE_SCHEMA},z.tobytes())
        np.testing.assert_allclose(nominal,nominal[0],rtol=1e-7)

    def test_pair_assessment_requires_repeatability_and_matched_signal_level(self):
        diagnostic=load('gain_pair_metrics','validate-b210-cable-lo.py')
        def metrics(tone,line):
            return dict(heldout_tone_power_counts2=tone,heldout_lo_power_counts2=line,tone_to_lo_db=10*np.log10(tone/line))
        cases=dict(baseline1=metrics(100,100),paired1=metrics(100,10),baseline2=metrics(105,95),paired2=metrics(105,9.5))
        result=diagnostic.gain_pair_comparison(cases)
        self.assertTrue(result['both_pairs_passed'])
        for row in result['pairs']:
            self.assertAlmostEqual(row['tone_change_db'],0)
            self.assertAlmostEqual(row['lo_suppression_db'],10)
        for bad in (metrics(200,10),metrics(100,40)):
            changed={**cases,'paired2':bad}
            result=diagnostic.gain_pair_comparison(changed)
            self.assertTrue(result['pairs'][0]['passed'])
            self.assertFalse(result['both_pairs_passed'])

    def test_only_registered_sources_and_budgets_are_accepted(self):
        for index in range(4):
            plan,z=c.lo_reference('a'*32,index)
            c.validate_tx(plan,z.tobytes())
            self.assertEqual(plan['tx_samples'],8399872)
            self.assertLessEqual(plan['tx_samples']/c.RATE,4)
            self.assertEqual(int(np.argmax(abs(np.fft.fft(z)))),48)
            self.assertAlmostEqual(float(np.mean(abs(z)**2)),plan['complex_peak']**2,places=8)
            for key,value in (('lo_offset_hz',0),('tx_gain_db',80),('max_seconds',5),
                ('center_hz',3500000000),('batch',True),('extra',1)):
                with self.assertRaises(ValueError):c.validate_tx({**plan,key:value},z.tobytes())
            changed=z.copy();changed[0]=0
            with self.assertRaises(ValueError):
                c.validate_tx({**plan,'payload_sha256':c.digest(changed.tobytes())},changed.tobytes())
        with self.assertRaises(ValueError):c.lo_reference('invalid',0)
        with self.assertRaises(ValueError):c.lo_reference('a'*32,4)

    def test_diagnostic_does_not_relax_rml_frequency_contract(self):
        iq=np.random.default_rng(14).normal(size=(24,1024,2)).astype('<f4')
        frame,_=c.packet(iq,'ordinary',0);plan=c.tx_plan(frame,'ordinary',0,range(24))
        for offset in (0,-250000):
            with self.assertRaises(ValueError):c.validate_tx({**plan,'lo_offset_hz':offset},frame.tobytes())

    def test_invalid_diagnostic_never_opens_uhd_or_creates_fifo(self):
        helper=load('lo_tx_helper','rml2018a-nx-tx.py')
        for schema in (c.LO_REFERENCE_SCHEMA,c.LO_GAIN_PAIR_SCHEMA):
            plan,z=c.lo_reference('b'*32,1,schema=schema);plan['tx_gain_db']=80
            with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
                root=Path(directory);(root/'packet.fc32').write_bytes(z.tobytes())
                (root/'tx-plan.json').write_text(json.dumps(plan))
                with patch.object(helper.subprocess,'Popen') as spawn:
                    with self.assertRaises(ValueError):helper.transmit(root)
                    spawn.assert_not_called()
                self.assertFalse((root/'packet.fifo').exists())
                self.assertFalse((root/'tx-started.json').exists())

    def test_peak_tracking_separates_lo_from_tone_and_source_amplitude(self):
        diagnostic=load('lo_metrics','validate-b210-cable-lo.py')
        rng=np.random.default_rng(83);n=np.arange(c.RX_SAMPLES)
        controls={tag:rng.normal(size=len(n))+1j*rng.normal(size=len(n)) for tag in ('before','after')}
        values=[]
        for index in (0,1,2):
            plan,_=c.lo_reference('c'*32,index)
            raw=80*plan['complex_peak']/.1*np.exp(2j*np.pi*(plan['tone_hz']+3100)*n/c.RATE)
            raw+=60*np.exp(2j*np.pi*(plan['lo_offset_hz']+3100)*n/c.RATE+.3j)
            raw+=rng.normal(size=len(n))+1j*rng.normal(size=len(n))
            q=diagnostic.line_metrics(raw,controls,plan);values.append(q)
            self.assertAlmostEqual(q['cfo_hz'],3100,delta=2)
            self.assertAlmostEqual(q['lo_minus_expected_hz'],0,delta=2)
            self.assertGreater(min(q['stopped_lo_contrast_db'].values()),40)
            self.assertLess(q['tone_and_lo_error_counts2']/q['tone_only_error_counts2'],.05)
        self.assertAlmostEqual(values[1]['lo_candidate_hz']-values[0]['lo_candidate_hz'],-500000,delta=2)
        self.assertAlmostEqual(10*np.log10(values[2]['heldout_tone_power_counts2']/values[0]['heldout_tone_power_counts2']),-6.0206,delta=.05)
        self.assertAlmostEqual(10*np.log10(values[2]['heldout_lo_power_counts2']/values[0]['heldout_lo_power_counts2']),0,delta=.05)


if __name__=='__main__':unittest.main()
