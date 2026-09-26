"""Real SigMF/HDF5 byte integrity, failed rows, interruption and single writer."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_campaign_store as s


def configuration():
    return dict(session_id='offline-storage-test', source_snr_db=30, max_raw_samples=3*1024**2,
        source_sha256='0'*64, preprocess_id='offline-fixture', profile_sha256='1'*64,
        label_map_sha256='2'*64, sample_rate_hz=2100000, center_hz=2455000000, bandwidth_hz=1500000,
        rx_gain_db=50, tx_gain_db=60)


def metadata():
    return dict(capture_id='offline-synthetic-0', timestamp_utc='2026-09-13T00:00:00Z',
        dropped_samples=0, overflow=False, clipped_samples=0,
        background=dict(status='not_measured', reason='offline test, no radio'))


def block(valid=True, start=0):
    x = np.ones((1024,2,1024), dtype='<f4')/np.sqrt(np.float32(2))
    inputs = {tag:x.copy() for tag in s.TAGS}
    masks = {tag:np.ones(1024, dtype=bool) for tag in s.TAGS}
    starts = np.arange(1024, dtype='<i8')*1024+start
    counts = np.full(1024, 1024, dtype='<i8')
    if not valid:
        for tag in ('raw','guard'): inputs[tag][:] = np.nan; masks[tag][:] = False
        starts[:] = -1; counts[:] = 0
    q = s.c.receive_quality('sync_failed' if not valid else 'synchronized')
    quality = [dict(raw=q, sync=dict(status='sync_failed' if not valid else 'synchronized')) for _ in range(1024)]
    return inputs, masks, starts, counts, quality


class StoreTests(unittest.TestCase):
    def test_explicit_mapping_preserves_repeats_classes_and_failed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [int((i % 24)*106496+25*4096+i//24) for i in range(1024)]
            config = dict(configuration(), source_rows=rows+rows[::-1])
            with s.SnrStore(root, configuration=config) as store:
                store.append_processed(*block(False))
            with s.SnrStore(root) as store:
                store.append_processed(*block(False))
                store.verify()
                with self.assertRaisesRegex(ValueError, 'block budget'):
                    store.append_processed(*block(False))
                with self.assertRaisesRegex(ValueError, 'explicit pilot'):
                    store.finish()
            with h5py.File(root/'processed.h5', 'r+') as f:
                for i, expected in enumerate((rows, rows[::-1])):
                    np.testing.assert_array_equal(f[f'blocks/{i:03d}/source_row'][:], expected)
                    np.testing.assert_array_equal(f[f'blocks/{i:03d}/class_id'][:], np.asarray(expected)//106496)
                f['blocks/000/source_row'][0] += 1
            with self.assertRaisesRegex(ValueError, 'stored source mapping'):
                s.SnrStore(root)

    def test_invalid_explicit_mapping_rejected_before_corpus_creation(self):
        valid = [102400]*1024
        for rows in ([], valid[:-1], [True]*1024, [102400.0]*1024,
                     [-1]*1024, [2555904]*1024, [0]*1024, valid*97):
            with self.subTest(first=rows[:1], size=len(rows)), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with self.assertRaisesRegex(ValueError, 'explicit source mapping'):
                    s.SnrStore(root, configuration=dict(configuration(), source_rows=rows))
                self.assertEqual({p.name for p in root.iterdir()}, {'writer.lock'})

    def test_roundtrip_resume_after_raw_before_gpu_and_failed_denominator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); raw = np.arange(2*1024**2, dtype='<i2').reshape(-1,2)
            with s.SnrStore(root, configuration=configuration()) as store:
                receipt = store.append_raw(raw, metadata())
                self.assertEqual(receipt['sample_count'], 1024**2)
                self.assertEqual((root/'raw.sigmf-data').read_bytes(), raw.tobytes())
            with s.SnrStore(root) as store:
                store.append_processed(*block())
                store.append_processed(*block(False))
                self.assertEqual(len(store.index['processed']),2)
                store.verify()
                with self.assertRaisesRegex(ValueError,'96 blocks'): store.finish()
                with self.assertRaisesRegex(ValueError,'sealed SNR reader'): next(store.iter_processed())
            with h5py.File(root/'processed.h5','r') as f:
                self.assertEqual(f['blocks/000/inputs/raw'].compression,None)
                self.assertFalse(f['blocks/001/valid/raw'][:].any())
                self.assertEqual(len(f['blocks/001/source_row']),1024)
                np.testing.assert_array_equal(f['blocks/000/raw_sample_start'][:], np.arange(1024)*1024)
            meta = json.loads((root/'raw.sigmf-meta').read_text())
            self.assertEqual(meta['global']['core:datatype'],'ci16_le')
            self.assertEqual(meta['annotations'][0]['core:sample_count'],1024**2)

    def test_stop_and_single_writer_preserve_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with s.SnrStore(root, configuration=configuration()) as store:
                with self.assertRaises(BlockingIOError): s.SnrStore(root)
                (root/'STOP').touch()
                with self.assertRaisesRegex(ValueError,'STOP'): store.append_raw(np.zeros((4,2),'<i2'),metadata())
                self.assertEqual((root/'raw.sigmf-data').stat().st_size,0)

    def test_corrupt_raw_and_processed_are_rejected_without_deletion(self):
        for target in ('raw','processed'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                with s.SnrStore(root,configuration=configuration()) as store:
                    store.append_raw(np.zeros((1024**2,2),'<i2'),metadata()); store.append_processed(*block())
                if target=='raw':
                    with (root/'raw.sigmf-data').open('r+b') as f: f.write(b'\x01')
                else:
                    with h5py.File(root/'processed.h5','r+') as f: f['blocks/000/inputs/raw'][0,0,0]=2
                with self.assertRaisesRegex(ValueError,'SHA'): s.SnrStore(root)
                self.assertTrue((root/'raw.sigmf-data').exists()); self.assertTrue((root/'processed.h5').exists())

    def test_commit_failure_retains_uncommitted_raw_or_hdf5_tail(self):
        for target in ('raw','processed'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                with s.SnrStore(root,configuration=configuration()) as store:
                    if target=='processed': store.append_raw(np.zeros((1024**2,2),'<i2'),metadata())
                    with patch.object(store,'_commit',side_effect=OSError('simulated power loss before index')):
                        with self.assertRaises(OSError):
                            if target=='raw': store.append_raw(np.zeros((100,2),'<i2'),metadata())
                            else: store.append_processed(*block())
                with self.assertRaisesRegex(ValueError,'tail'): s.SnrStore(root)
                self.assertGreater((root/'raw.sigmf-data').stat().st_size,0)
                if target=='processed':
                    with h5py.File(root/'processed.h5','r') as f: self.assertIn('000',f['blocks'])

    def test_boundaries_quality_and_lineage_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with s.SnrStore(root,configuration=configuration()) as store:
                with self.assertRaisesRegex(ValueError,'lineage'): store.append_processed(*block())
                with self.assertRaisesRegex(ValueError,'shape'): store.append_raw(np.zeros((4,2),'<f4'),metadata())
                bad=metadata(); bad['background']={'status':'measured','power_adc_squared':2}
                with self.assertRaisesRegex(ValueError,'semantics'): store.append_raw(np.zeros((4,2),'<i2'),bad)
                with patch.object(store,'_space',side_effect=ValueError('disk full')):
                    with self.assertRaisesRegex(ValueError,'disk full'): store.append_raw(np.zeros((4,2),'<i2'),metadata())
                self.assertEqual((root/'raw.sigmf-data').stat().st_size,0)

    def test_background_power_is_not_a_sinr(self):
        value=dict(status='measured',tx_state='off',reference_plane='raw_adc',unit='adc_counts_squared',
            power_adc_squared=12.,frequency_hz=2455000000,sample_rate_hz=2100000,bandwidth_hz=1500000,
            rx_gain_db=50,sample_count=4096,capture_id='background-before',timestamp_utc='2026-09-13T00:00:00Z',raw_sha256='3'*64)
        s.background(value)
        value['tx_state']='on'
        with self.assertRaises(ValueError): s.background(value)

    def test_committed_raw_rebuilds_metadata_after_interruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with s.SnrStore(root,configuration=configuration()) as store:
                with patch.object(store,'_meta',side_effect=OSError('metadata update interrupted')):
                    with self.assertRaises(OSError): store.append_raw(np.tile(np.array([[3,4]],'<i2'),(32,1)),metadata())
            with s.SnrStore(root) as store:
                self.assertEqual(len(store.index['raw']),1)
                self.assertEqual(store.index['raw'][0]['metadata']['received_total_power_adc_squared'],25.)
                annotations=json.loads((root/'raw.sigmf-meta').read_text())['annotations']
                self.assertEqual(annotations[0]['core:sample_count'],32)
                store.append_raw(np.zeros((2,2),'<i2'),metadata())

    def test_pending_metadata_and_over_budget_raw_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); config=configuration(); config['max_raw_samples']=1
            with s.SnrStore(root,configuration=config) as store:
                with self.assertRaisesRegex(ValueError,'finite budget'): store.append_raw(np.zeros((2,2),'<i2'),metadata())
                pending=root/'index.json.pending'; pending.write_bytes(b'interrupted evidence')
                with self.assertRaisesRegex(ValueError,'interrupted metadata'): store.append_raw(np.zeros((1,2),'<i2'),metadata())
                self.assertEqual(pending.read_bytes(),b'interrupted evidence')


if __name__ == '__main__': unittest.main()
