"""Lossless archives, explicit chunk membership and storage exhaustion gates."""
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zlib
from unittest.mock import patch
import numpy as np
S=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(S))
import rml2018a_event_archive as a
import rml2018a_campaign_events as e
c=a.c


class ArchiveTests(unittest.TestCase):
    def test_full_projection_includes_failure_and_transient_budgets(self):
        b=a.budget([1,2]);p=b['full_dataset_projection']
        self.assertEqual(b['maximum_source_rows'],48)
        self.assertEqual(p['successful_retention_budget_bytes'],106496*(2*a.ARCHIVE_LIMIT+65535*4))
        self.assertEqual(p['required_bytes'],p['successful_retention_budget_bytes']+a.FAILURE_POOL+a.RAW_LIMIT+a.ARCHIVE_LIMIT+a.SCRATCH_RESERVE)
        self.assertLess(p['required_bytes'],500*10**9)
        for rows in (None,[],[1,1],[-1],[106496],[True],list(range(33))):
            with self.assertRaises((ValueError,TypeError)):a.budget(rows)

    def test_lossless_hashes_and_existing_receipt_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);raw=d/'tx-events.jsonl';data=b'{"kind":"send","timestamp":1234567890}\n'*9000
            raw.write_bytes(data);v=a.seal(d)
            self.assertFalse(raw.exists());self.assertEqual(a.read(a.verify(d)),data)
            self.assertEqual(v['original_sha256'],c.digest(data));self.assertLess(v['archive_bytes'],v['original_bytes'])
            raw.write_bytes(data);self.assertEqual(a.seal(d),v);self.assertFalse(raw.exists())

    def test_partial_archive_recovery_without_losing_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);raw=d/'tx-events.jsonl';raw.write_bytes(b'abc\n'*50)
            (d/'tx-events.jsonl.gz').write_bytes(gzip.compress(raw.read_bytes(),compresslevel=6,mtime=0))
            a.seal(d);self.assertEqual(a.read(a.verify(d)),b'abc\n'*50)

    def test_truncation_trailing_members_bombs_and_tampering_fail(self):
        data=gzip.compress(b'x'*100)
        for invalid in (data[:-1],data+b'extra',data+data,gzip.compress(b'x'*a.RAW_LIMIT)):
            with self.assertRaises((ValueError,zlib.error)):a.decompress(invalid)
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);(d/'tx-events.jsonl').write_bytes(b'hello');a.seal(d)
            (d/'tx-events.jsonl.gz').write_bytes(gzip.compress(b'changed'))
            with self.assertRaises(ValueError):a.verify(d)

    def test_size_gate_preserves_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);raw=d/'tx-events.jsonl';raw.write_bytes(b'original')
            with patch.object(a,'ARCHIVE_LIMIT',1):
                with self.assertRaises(ValueError):a.seal(d)
            self.assertEqual(raw.read_bytes(),b'original');self.assertFalse((d/'event-storage.json').exists())

    def test_chunk_packet_does_not_relax_old_fixtures(self):
        for batch in (0,17407,66218,106495):
            iq=np.random.default_rng(batch).normal(size=(24,1024,2))
            frame,_=c.packet(iq,'a'*32,batch,level_profile='event-chunk')
            tx=c.tx_plan(frame,'a'*32,batch,c.batch_rows(2555904,batch),60,level_profile='event-chunk');c.validate_tx(tx,frame.tobytes())
            with self.assertRaises(ValueError):c.packet(iq,'a'*32,batch,level_profile='event-boundary-pilot')
        p=dict(tx_level_profile='event-chunk',tx_host='agx',rf=dict(tx_gain_db=60,rx_gain_db=50,peak=c.packet_peak('event-chunk')),execution_limits=a.budget([17407,17408]))
        self.assertEqual(e.m.campaign_level(p,[17407]),'event-chunk')
        with self.assertRaises(ValueError):e.m.campaign_level(p,[66218])

    def test_retention_ceiling_is_checked_separately_from_free_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);(d/'metadata.json').write_bytes(b'x'*100)
            with patch.object(a,'METADATA_PER_BATCH',99):
                with self.assertRaisesRegex(ValueError,'successful retention'):a.retained_usage(d,a.budget([0]))

    def test_real_previous_log_compresses_with_identical_event_semantics(self):
        # Read-only replay of sealed prior evidence; conversion happens in memory.
        path=Path('/var/tmp/sdrharness-dev/b210-rml2018a-boundaries-20260913/batch-0004266/attempt-0/capture/tx-events.jsonl')
        data=path.read_bytes();compressed=gzip.compress(data,compresslevel=6,mtime=0)
        self.assertEqual(a.decompress(compressed),data)
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'events.gz';out.write_bytes(compressed)
            self.assertEqual(e.r.events.parse_events(path),e.r.events.parse_events(out))


if __name__=='__main__':unittest.main()
