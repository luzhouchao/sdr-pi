"""Shared raw lineage, independent receive process and original-Z frame layout."""
import ctypes
import json
import multiprocessing as mp
from pathlib import Path
import sys
import tempfile
import time
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rml2018a_snr_stream as stream
import rml2018a_campaign_store as storage
from test_rml2018a_store import configuration,metadata,block


class SnrStreamTests(unittest.TestCase):
    def test_rolling_decoder_exceeds_old_stream_length_with_bounded_working_memory(self):
        values=np.ones((1024,1024),np.complex64)
        decoder=stream.dsp.Decoder('rolling-long',None,stream.g.PayloadBatch('cpu'),
            source_loader=lambda block:(values,30),total_blocks=96)
        decoder.marker=256;decoder.hz=0.;outputs=[]
        for block_index in range(18):
            wave=stream.packet_block(values,'rolling-long',block_index)*100
            iq=np.stack((wave.real,wave.imag),1).astype('<i2')
            outputs.extend(decoder.feed(iq))
        outputs.extend(decoder.feed(np.zeros((1048576,2),'<i2')))
        self.assertEqual(decoder.frame,18*64)
        self.assertEqual([x['block'] for x in outputs],list(range(18)))
        self.assertGreater(decoder.sample_base,16*1048576)
        self.assertLess(decoder.peak_samples,3*1048576)
        for i,result in enumerate(outputs):
            self.assertEqual(result['sample_starts'][0],i*64*17920+1280)

    def test_shared_raw_parent_reopen_and_global_offsets_without_iq_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'a';b=root/'b';a.mkdir();b.mkdir()
            with storage.SnrStore(a,configuration=configuration()) as owner:
                config={**configuration(),'source_snr_db':28,'raw_parent':dict(root=str(a),configuration_sha256=stream.c.file_hash(a/'configuration.json'))}
                with storage.SnrStore(b,configuration=config,raw_parent=owner) as child:
                    with self.assertRaisesRegex(ValueError,'only raw owner'):child.append_raw(np.zeros((4,2),'<i2'),metadata())
                    with self.assertRaisesRegex(ValueError,'lineage bounds'):child.append_processed(*block())
                    owner.append_raw(np.zeros((1048576,2),'<i2'),metadata());child.append_processed(*block())
                    child.verify();self.assertFalse((b/'raw.sigmf-data').exists())
                with storage.SnrStore(b,raw_parent=owner) as child:
                    self.assertEqual(len(child.index['processed']),1)
                    self.assertEqual(child.raw_path(),a/'raw.sigmf-data')
                    meta=json.loads((b/'raw.sigmf-meta').read_text())
                    self.assertEqual(meta['global']['core:dataset'],str(a/'raw.sigmf-data'))
            with self.assertRaisesRegex(ValueError,'parent required'):storage.SnrStore(b)

    def test_packet_block_uses_global_pilot_id_across_snr_boundary(self):
        values=np.ones((1024,1024),np.complex64)
        first=stream.packet_block(values,'snr-boundary',95);second=stream.packet_block(values,'snr-boundary',96)
        self.assertEqual(len(first),64*17920)
        np.testing.assert_allclose(second[256:1280],stream.c.marker('snr-boundary',6144)*np.sqrt(10),atol=1e-7)
        self.assertFalse(np.array_equal(first[256:1280],second[256:1280]))
        self.assertLessEqual(abs(second).max(),.632456)

    def test_receive_process_fills_shared_ram_while_parent_does_not_consume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);helper=root/'fake-controller'
            helper.write_text('#!'+sys.executable+'\n'+'''import json,sys
def send(h,data=b''):
 h.update(schema_version=1,generation=7,status='ok');sys.stdout.buffer.write(json.dumps(h).encode()+b'\\n'+data);sys.stdout.buffer.flush()
send(dict(event='rx_ready'))
for i in range(16):send(dict(event='rx_chunk',sample_offset=i*65536,bytes=262144),b'\\x01\\x02'*131072)
send(dict(event='rx_end',restored=True))
''');helper.chmod(0o700)
            context=mp.get_context('spawn');arena=context.RawArray(ctypes.c_int16,2*1048576)
            rx,tx=context.Pipe(duplex=False);stop=context.Event()
            p=dict(controller=str(helper),generation=7,maximum_rx_bytes=4194304)
            child=context.Process(target=stream.receive_process,args=(p,root,arena,tx,stop));child.start();tx.close()
            try:
                child.join(15)  # No parent reads until the receiver exits.
                self.assertFalse(child.is_alive());self.assertEqual(child.exitcode,0)
                result=json.loads((root/'rx-process.json').read_text());self.assertEqual(result['status'],'completed')
                np.testing.assert_array_equal(np.frombuffer(arena,dtype='<i2'),np.full(2*1048576,513,dtype='<i2'))
                messages=[]
                while rx.poll():
                    try:messages.append(rx.recv())
                    except EOFError:break
                self.assertEqual([m[0] for m in messages],['pid','first','buffer','end'])
            finally:
                if child.is_alive():stop.set();child.terminate();child.join(5)
                rx.close()


if __name__=='__main__':unittest.main()
