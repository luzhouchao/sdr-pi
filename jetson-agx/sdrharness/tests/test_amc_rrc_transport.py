"""RF timing/lineage/heldout tests, no model, device or training activity."""
import sys
import unittest
import tempfile
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import amc_rrc_transport as r


def source(length, rows=33):
    rng = np.random.default_rng(91)
    n = np.arange(length)
    # Include nonzero mean and useful energy at nominal LO frequency after TX.
    return (1+.2j+np.exp(2j*np.pi*.47619*n)[None, :]+
            .2*(rng.normal(size=(rows, length))+1j*rng.normal(size=(rows, length))))


def channel(x, offset=317, cfo=1373., lo=.08, phase=.41):
    z = np.r_[np.zeros(offset), x, np.zeros(700)]
    n = np.arange(len(z))
    z = z*np.exp(2j*np.pi*cfo*n/r.c.RATE+1j*phase)
    z += lo*np.exp(2j*np.pi*(250000+cfo+1.37)*n/r.c.RATE+.2j)
    return z


def decode(x, length, rows, chunks=None):
    d = r.Decoder('rrc-test', length, rows)
    if chunks is None:
        d.feed(x, final=True)
    else:
        begin = 0
        for size in chunks:
            d.feed(x[begin:begin+size]); begin += size
        d.feed(x[begin:], final=True)
    return d.result()


def error(reference, got):
    x = reference/np.sqrt(np.mean(abs(reference)**2, axis=1))[:, None]
    y = got[:, 0]+1j*got[:, 1]
    return np.sqrt(np.mean(abs(x-y)**2, axis=1))


class TransportTests(unittest.TestCase):
    def test_roundtrip_cfo_lo_both_lengths_and_real_adc_lineage(self):
        for length in (128, 1024):
            x = source(length); tx, info = r.transmit(x, 'rrc-test')
            z = channel(tx)
            got = decode(z, length, len(x))
            self.assertTrue(got['masks']['raw'].all(), got['frames'])
            self.assertTrue(all(f['guard']['status']=='applied' for f in got['frames']), got['frames'])
            self.assertLess(max(error(x, got['inputs']['guard'])), .02)
            self.assertLess(np.mean(error(x, got['inputs']['guard'])), np.mean(error(x, got['inputs']['raw'])))
            self.assertEqual(len(got['inputs']['raw']), 33)
            self.assertTrue((got['sample_counts']==4*(length-1)+129).all())
            self.assertEqual(got['sample_starts'][0], 317+5120)
            self.assertTrue((got['sample_starts']+got['sample_counts']<=len(z)).all())
            for q in got['quality']:
                self.assertIsNone(q['raw']['rx_sinr_db']); r.validate_quality(q['raw'])

    def test_chunk_boundaries_do_not_reset_filter_or_shift_samples(self):
        x=source(1024); tx,_=r.transmit(x,'rrc-test'); z=channel(tx)
        full=decode(z,1024,len(x)); split=decode(z,1024,len(x),[11,997,2355,131017])
        for tag in ('raw','guard'):
            np.testing.assert_array_equal(full['inputs'][tag],split['inputs'][tag])
        np.testing.assert_array_equal(full['sample_starts'],split['sample_starts'])

    def test_missing_middle_pilot_does_not_relabel_next_frame(self):
        x=source(128,48);tx,_=r.transmit(x,'rrc-test');z=channel(tx, cfo=0, lo=0)
        at=317+4*(1536+16*128)+1088
        z[at-64:at+4096+64]=0
        got=decode(z,128,48)
        self.assertTrue(got['masks']['raw'][:16].all())
        self.assertFalse(got['masks']['raw'][16:32].any())
        self.assertTrue(got['masks']['raw'][32:].all(),got['frames'])
        self.assertTrue(np.isnan(got['inputs']['raw'][16:32]).all())
        self.assertLess(max(error(x[32:],got['inputs']['raw'][32:])),.01)

    def test_guard_validation_change_falls_back_exactly(self):
        x=source(128,16);tx,_=r.transmit(x,'rrc-test');z=channel(tx,cfo=0)
        origin=317;end=origin+4*(1280+16*128)
        z[end+512:end+896]*=2
        got=decode(z,128,16)
        self.assertTrue(got['masks']['raw'].all(),got['frames'])
        self.assertEqual(got['frames'][0]['guard']['status'],'skipped')
        np.testing.assert_array_equal(got['inputs']['raw'],got['inputs']['guard'])

    def test_truncated_or_wrong_run_cannot_create_valid_rows(self):
        x=source(128,16);tx,_=r.transmit(x,'rrc-test')
        got=decode(channel(tx)[:10000],128,16)
        self.assertFalse(got['masks']['raw'].any())
        d=r.Decoder('different-run',128,16);d.feed(channel(tx),final=True)
        self.assertFalse(d.result()['masks']['raw'].any())
        with self.assertRaisesRegex(ValueError,'finalized'):d.feed(np.empty(0,complex))

    def test_matched_filter_nyquist_and_known_quiet_regions(self):
        h=r.taps();g=np.convolve(h,h)[::4];center=len(g)//2
        self.assertAlmostEqual(g[center],1)
        self.assertLess(max(abs(np.delete(g,center))),.0002)
        x=source(1024,32);tx,_=r.transmit(x,'rrc-test')
        for frame in range(2):
            origin=frame*4*(1536+16*1024);end=origin+4*(1280+16*1024)
            np.testing.assert_array_equal(tx[origin+128:origin+896],0)
            np.testing.assert_array_equal(tx[end+128:end+896],0)

    def test_store_oversampled_lineage_and_pending_sinr(self):
        import amc_dataset_contract as native
        import rml2018a_campaign_store as store
        from test_rml2018a_store import configuration, metadata
        from test_amc_dataset_contract import contract
        x=source(128,16);tx,_=r.transmit(x,'rrc-test');z=channel(tx)
        adc=np.stack((z.real,z.imag),axis=1)
        adc=np.rint(adc*2000).astype('<i2')
        result=decode(adc,128,16)
        self.assertTrue(result['masks']['guard'].all())
        cfg=configuration();cfg.pop('source_snr_db');cfg['native_source']=contract(16)
        cfg['label_map_sha256']=native.label_hash(cfg['native_source']['class_names'])
        cfg['sample_transport']=r.contract()
        with tempfile.TemporaryDirectory() as d:
            with store.SnrStore(Path(d),configuration=cfg) as s:
                s.append_raw(adc,metadata())
                bad=result['sample_counts'].copy();bad[:]=128
                with self.assertRaisesRegex(ValueError,'window length'):
                    s.append_processed(result['inputs'],result['masks'],result['sample_starts'],bad,result['quality'])
                s.append_processed(result['inputs'],result['masks'],result['sample_starts'],result['sample_counts'],result['quality'])
                s.finish()
            with store.SnrStore(Path(d)) as s:
                batches=list(s.iter_processed('guard'))
                self.assertEqual(sum(len(b['source_row']) for b in batches),16)
                self.assertTrue((batches[0]['raw_sample_count']==637).all())

class UniformFrameTests(unittest.TestCase):
    def test_same_physical_frame_native_windows_and_tail(self):
        for capacity, length, rows in [(16384,128,259),(16384,1024,35),(2048,128,33),(2048,1024,5)]:
            x=source(length,rows);tx,_=r.transmit(x,'rrc-test',frame_payload_samples=capacity)
            frame_samples=4*(1536+capacity)
            self.assertEqual(len(tx),3*frame_samples+125)
            d=r.Decoder('rrc-test',length,rows,frame_payload_samples=capacity)
            z=channel(tx)
            for start in range(0,len(z),131099):d.feed(z[start:start+131099])
            d.feed(np.empty(0,complex),final=True);got=d.result()
            self.assertTrue(got['masks']['guard'].all(),got['frames'])
            self.assertLess(max(error(x,got['inputs']['guard'])),.02)
            per_frame=capacity//length
            expected=np.array([317+(i//per_frame)*frame_samples+5120+(i%per_frame)*4*length for i in range(rows)])
            np.testing.assert_array_equal(got['sample_starts'],expected)
            for q in got['quality']:r.validate_quality(q['raw'],capacity)
            self.assertEqual(got['transport']['frame_rf_samples'],frame_samples)

    def test_uniform_contract_rejects_unregistered_capacity(self):
        for capacity in (True,1024,16384.0,32768):
            with self.assertRaises(ValueError):r.contract(capacity)

if __name__=='__main__':unittest.main()
