"""No RF: exercise FIFO byte bounds, explicit GO and cleanup with a fake UHD reader."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/b210-finite-train-tx.py'
spec = importlib.util.spec_from_file_location('finite_tx', SCRIPT)
tx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tx)


class FiniteTxTests(unittest.TestCase):
    def run_case(self, go=True, tamper=False, extended=False, invalid=False, single=False, bad_unit=False, lo_offset=None, bad_version=False, margin_peak=None, bad_margin=False):
        # Caller supplies the feature TMPDIR; no files touch user results.
        root = Path(tempfile.mkdtemp(prefix='fifo-',dir=os.environ['TMPDIR']))
        payload = bytes(range(256))*(32 if single else 128)
        plan = dict(center_hz=2440000000,rate_sps=2100000,bandwidth_hz=1500000,
                    tx_gain_db=40,tx_samples=2100000,tx_nominal_seconds=1,complex_peak=0.1,tx_channel=0,tx_antenna='TX/RX',
                    payload_bytes=32768,split='train',locked_test_read=False,
                    payload_sha256=hashlib.sha256(payload).hexdigest())
        if extended:
            plan.update(tx_samples=21000000,tx_nominal_seconds=10,tx_gain_db=70,complex_peak=0.2)
        if single:
            plan.update(schema_version=2,payload_bytes=8192,source_unit_samples=4096 if bad_unit else 1024,
                        rows=[102400],tx_unit_count=20480,uhd_spb=1024,
                        tx_samples=20971520,tx_nominal_seconds=10,tx_gain_db=70,complex_peak=0.2)
        if lo_offset is not None:
            plan.update(schema_version=2 if bad_version else 3,tx_lo_offset_hz=lo_offset,
                        tx_requested_lo_hz=2440000000+lo_offset,diagnostic_contract='b210_1024_lo_offset_v1')
        bad_offset=lo_offset is not None and (lo_offset not in (-250000,0,250000) or bad_version)
        if margin_peak is not None:
            lo_offset=250000
            plan.update(schema_version=4,center_hz=2455000000,tx_lo_offset_hz=250000,
                        tx_requested_lo_hz=2455250000,complex_peak=margin_peak,diagnostic_contract='b210_2455_margin_v1',
                        parent_payload_sha256='c8e3d54629eb7dde75e6a49554090f570522e7b438d2602dce85a18cd1d771f9',
                        source_gain_multiplier=1. if margin_peak==.2 else 1.5)
            if bad_margin:plan['parent_payload_sha256']='0'*64
        bad_margin=bad_margin or (margin_peak is not None and margin_peak not in (.2,.3))
        if invalid:
            plan['tx_samples'] += 1
        (root/'transmission-plan.json').write_text(json.dumps(plan))
        (root/'train-tile.fc32').write_bytes(payload if not tamper else payload[:-1])
        real_popen = subprocess.Popen
        original_select = tx.select.select
        original_read = os.read
        launched=[]
        def fake_uhd(args, **kwargs):
            self.assertNotIn('--repeat',args)
            self.assertEqual(args[args.index('--spb')+1],'1024' if single else '10000')
            if lo_offset is not None:self.assertEqual(args[args.index('--lo-offset')+1],str(lo_offset))
            self.assertEqual(args[args.index('--freq')+1],str(2455000000 if margin_peak is not None else 2440000000))
            fifo=args[args.index('--file')+1]
            child=real_popen([sys.executable,'-c',
                'import sys,hashlib,json; f=open(sys.argv[1],"rb"); h=hashlib.sha256(); n=0\n'
                'while True:\n b=f.read(8192)\n if not b: break\n h.update(b); n+=len(b)\n'
                'print(json.dumps(dict(bytes=n,sha256=h.hexdigest())))',fifo],**kwargs)
            launched.append(child)
            return child
        def fake_select(read,write,error,timeout):
            return ([0],[],[]) if read==[0] else original_select(read,write,error,timeout)
        try:
            with patch.object(tx.subprocess,'Popen',fake_uhd), \
                 patch.object(tx.select,'select',fake_select), \
                 patch.object(tx.os,'read',lambda fd,n: (b'GO\n' if go else b'') if fd==0 else original_read(fd,n)), \
                 patch.object(tx.signal,'signal'):
                if not go or tamper or invalid or bad_unit or bad_offset or bad_margin:
                    with self.assertRaises(AssertionError):tx.transmit(root)
                else:tx.transmit(root)
            self.assertFalse((root/'tx.fc32.fifo').exists())
            self.assertTrue(all(p.poll() is not None for p in launched))
            if tamper or invalid or bad_unit or bad_offset or bad_margin:
                self.assertFalse(launched)
            elif go:
                result=json.loads((root/'tx-uhd.log').read_text())
                total=plan['tx_samples']*8
                expected=hashlib.sha256()
                for _ in range(total//len(payload)):expected.update(payload)
                expected.update(payload[:total%len(payload)])
                self.assertEqual(result,dict(bytes=total,sha256=expected.hexdigest()))
            else:
                self.assertEqual(json.loads((root/'tx-summary.json').read_text())['bytes_written'],0)
        finally:
            for child in launched:
                if child.poll() is None:child.kill();child.wait()
            import shutil
            shutil.rmtree(root)

    def test_margin_amplitudes_keep_finite_1024_stream(self):
        for peak in (.2,.3):self.run_case(single=True,margin_peak=peak)

    def test_margin_unregistered_peak_parent_and_tamper_rejected(self):
        self.run_case(single=True,margin_peak=.4)
        self.run_case(single=True,margin_peak=.3,bad_margin=True)
        self.run_case(single=True,margin_peak=.3,tamper=True)

    def test_registered_lo_offsets_preserve_payload_and_bound(self):
        for offset in (-250000,0,250000):self.run_case(single=True,lo_offset=offset)

    def test_lo_offset_fails_closed_before_uhd(self):
        self.run_case(single=True,lo_offset=1000000)
        self.run_case(single=True,lo_offset=250000,bad_version=True)

    def test_optimized_python_refuses_before_hardware_setup(self):
        result=subprocess.run([sys.executable,'-O',str(SCRIPT)],capture_output=True,text=True,timeout=3)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('optimized Python would disable validation',result.stderr)

    def test_extended_plan_exact_ten_second_sample_bound(self):self.run_case(extended=True)
    def test_unregistered_sample_bound_refuses_before_uhd(self):self.run_case(invalid=True)

    def test_exact_payload_and_finite_tail(self):self.run_case()
    def test_eof_before_go_does_not_send(self):self.run_case(go=False)
    def test_tampered_payload_never_starts_uhd(self):self.run_case(tamper=True)
    def test_single_row_exact_full_1024_units(self):self.run_case(single=True)
    def test_single_row_wrong_unit_is_rejected_before_uhd(self):self.run_case(single=True,bad_unit=True)
    def test_single_row_partial_final_unit_is_rejected(self):self.run_case(single=True,invalid=True)
    def test_single_row_hash_tampering_is_rejected(self):self.run_case(single=True,tamper=True)


if __name__=='__main__':unittest.main()
