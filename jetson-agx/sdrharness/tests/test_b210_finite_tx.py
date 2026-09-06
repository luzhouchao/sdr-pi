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
    def run_case(self, go=True, tamper=False):
        # Caller supplies the feature TMPDIR; no files touch user results.
        root = Path(tempfile.mkdtemp(prefix='fifo-',dir=os.environ['TMPDIR']))
        payload = bytes(range(256))*128
        plan = dict(center_hz=2440000000,rate_sps=2100000,bandwidth_hz=1500000,
                    tx_gain_db=40,tx_samples=2100000,tx_channel=0,tx_antenna='TX/RX',
                    payload_bytes=32768,split='train',locked_test_read=False,
                    payload_sha256=hashlib.sha256(payload).hexdigest())
        (root/'transmission-plan.json').write_text(json.dumps(plan))
        (root/'train-tile.fc32').write_bytes(payload if not tamper else payload[:-1])
        real_popen = subprocess.Popen
        original_select = tx.select.select
        original_read = os.read
        launched=[]
        def fake_uhd(args, **kwargs):
            self.assertNotIn('--repeat',args)
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
                if not go or tamper:
                    with self.assertRaises(AssertionError):tx.transmit(root)
                else:tx.transmit(root)
            self.assertFalse((root/'tx.fc32.fifo').exists())
            self.assertTrue(all(p.poll() is not None for p in launched))
            if tamper:
                self.assertFalse(launched)
            elif go:
                result=json.loads((root/'tx-uhd.log').read_text())
                total=2100000*8
                expected=(payload*(total//len(payload)+1))[:total]
                self.assertEqual(result,dict(bytes=total,sha256=hashlib.sha256(expected).hexdigest()))
            else:
                self.assertEqual(json.loads((root/'tx-summary.json').read_text())['bytes_written'],0)
        finally:
            for child in launched:
                if child.poll() is None:child.kill();child.wait()
            import shutil
            shutil.rmtree(root)

    def test_optimized_python_refuses_before_hardware_setup(self):
        result=subprocess.run([sys.executable,'-O',str(SCRIPT)],capture_output=True,text=True,timeout=3)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('optimized Python would disable validation',result.stderr)

    def test_exact_payload_and_finite_tail(self):self.run_case()
    def test_eof_before_go_does_not_send(self):self.run_case(go=False)
    def test_tampered_payload_never_starts_uhd(self):self.run_case(tamper=True)


if __name__=='__main__':unittest.main()
