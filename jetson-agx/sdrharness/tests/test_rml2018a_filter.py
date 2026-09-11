import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import h5py
import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('filter_replay',SCRIPTS/'diagnose-rml2018a-campaign-filter.py')
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
c=f.c


class FilterReplayTests(unittest.TestCase):
    def fixture(self, root, frequency=30000):
        n=np.arange(24*1024).reshape(24,1024)
        z=np.exp(2j*np.pi*frequency*n/c.RATE)
        x=np.stack((z.real,z.imag),axis=-1).astype('float32')
        dataset=root/'source.h5'
        with h5py.File(dataset,'w') as h:
            h['X']=x;h['Y']=np.eye(24);h['Z']=np.full((24,1),30)
        frame,_=c.packet(x,'filter-test',0)
        raw=np.tile(frame,3)[:c.RX_SAMPLES]
        raw=raw+0.8*np.exp(2j*np.pi*250000*np.arange(len(raw))/c.RATE)
        ci16=np.stack((raw.real,raw.imag),axis=-1)
        batch=root/'batch-0000000';batch.mkdir()
        iq=batch/'capture.sigmf-data';iq.write_bytes(np.rint(ci16*2000).astype('<i2').tobytes())
        source=dict(rows=list(range(24)),class_ids=list(range(24)),source_snr_db=[30]*24,
                    original_iq_sha256=c.digest(x.tobytes()))
        c.save(batch/'source.json',source)
        a=dict(status='synchronized',restored=True,
               seal=dict(iq_path=str(iq),iq_sha256=c.file_hash(iq),request_id=1,session_generation=1),
               sync=dict(payload_marker_offset=c.GUARD,estimated_cfo_hz=0,phase_rotation_rad=0),
               tx_plan=dict(payload_sha256=c.digest(frame.tobytes())))
        c.save(batch/'audit.json',a)
        c.save(batch/'capture-complete.json',dict(status='synchronized',rows=list(range(24)),audit_sha256=c.file_hash(batch/'audit.json')))
        c.save(root/'run-plan.json',dict(run_id='filter-test',source=dict(path=str(dataset),
               bytes=dataset.stat().st_size,mtime_ns=dataset.stat().st_mtime_ns)))
        return batch

    def test_fixed_filter_removes_offset_tone_without_selecting_rows(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as d:
            root=Path(d);self.fixture(root)
            report,arrays=f.prepare(root,(0,))
            self.assertTrue(report['all_sources_filter_eligible'])
            b=report['results'][0]
            self.assertLess(b['raw_coherence_mean'],.3)
            self.assertGreater(b['filtered_coherence_mean'],.99)
            self.assertEqual(len(b['rows']),24)
            self.assertEqual(set(arrays[0]),{'source_original','source_filtered','received_raw','received_filtered'})
            for values in arrays[0].values():self.assertEqual(values.shape,(24,1024))
            self.assertIsNone(report['filtered_rx_sinr_db'])

    def test_filter_rejects_wide_source_and_preserves_all_failures(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as d:
            root=Path(d);self.fixture(root,300000)
            report,_=f.prepare(root,(0,))
            self.assertFalse(report['all_sources_filter_eligible'])
            self.assertEqual(len(report['results'][0]['rows']),24)
            self.assertTrue(all(not row['source_filter_eligible'] for row in report['results'][0]['rows']))

    def test_invalid_batch_budget_rejected_before_io(self):
        with patch.object(f,'load_runner') as loader:
            for indices in ((),(0,0),(0,1,2,3),(True,),(-1,),(106496,)):
                with self.assertRaisesRegex(ValueError,'bounded unique batches'):
                    f.prepare(Path('/unused'),indices)
                with self.assertRaisesRegex(ValueError,'bounded unique batches'):
                    f.infer(Path('/unused'),Path('/unused-output'),indices)
            loader.assert_not_called()

    def test_tampered_iq_rejected(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as d:
            root=Path(d);b=self.fixture(root)
            p=b/'capture.sigmf-data';p.write_bytes(p.read_bytes()+b'\0\0\0\0')
            with self.assertRaisesRegex(ValueError,'native IQ hash'):f.prepare(root,(0,))


if __name__=='__main__':unittest.main()
