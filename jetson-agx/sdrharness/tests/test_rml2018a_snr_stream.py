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




class FullCampaignTests(unittest.TestCase):
    def test_all_original_rows_exactly_once_in_thirteen_pairs(self):
        rows=[]
        for pair in stream.PAIRS:
            self.assertTrue(stream.valid_snrs(pair))
            for snr in pair:
                rows.extend(stream.g.snr_rows(snr))
        np.testing.assert_array_equal(np.sort(rows),np.arange(2555904))
        for invalid in ([30,26],[30,30],[32,30],[-20,-22],[30,28,26],[30.,28],[]):
            self.assertFalse(stream.valid_snrs(invalid))
        self.assertEqual(stream.snr_name(-20),'snr-minus20')

    def test_partial_rx_cannot_be_recovered_as_a_complete_group(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'plan.json').write_text('{}')
            (root/'execution.json').write_text(json.dumps(dict(plan_sha256=stream.c.file_hash(root/'plan.json'),
                status='failed',worker_threads_stopped=True,restored=True)))
            (root/'rx-process.json').write_text(json.dumps(dict(status='failed',bytes_received=4)))
            with self.assertRaisesRegex(ValueError,'entire finite RX'):
                stream.recovery_preflight(root)

    def test_changed_sealed_artifact_rejected_before_skipping(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'plan.json').write_text(json.dumps(dict(snrs=[26,24],source_sha256=stream.DATA_SHA)))
            (root/'execution.json').write_text(json.dumps(dict(status='passed',source_rows=196608,
                all_frames_synchronized=True,raw_verified=True,worker_threads_stopped=True,restored=True,
                plan_sha256=stream.c.file_hash(root/'plan.json'),sealed_artifacts={'raw':'expected'})))
            with patch.object(stream,'sealed_artifacts',return_value={'raw':'changed'}):
                with self.assertRaisesRegex(ValueError,'artifact seals'):stream.completed(root,[26,24])

    def ledger(self,root,child):
        (root/'entries').mkdir()
        p=dict(groups=[dict(index=1,snrs=[26,24],attempts=[str(child)])],maximum_wall_seconds=21600,
            maximum_retained_bytes=208*1024**3,backend='/unused',initial=dict(root='/unused'))
        return p

    def test_stopped_campaign_never_creates_or_runs_child(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);child=root/'child';p=self.ledger(root,child);(root/'STOP').touch()
            with patch.object(stream,'full_load',return_value=p),patch.object(stream,'create') as create,patch.object(stream.subprocess,'Popen') as launch:
                with self.assertRaisesRegex(ValueError,'STOP exists'):stream.full_run(root)
                create.assert_not_called();launch.assert_not_called()

    def test_restart_reconciles_completed_child_without_retransmission(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);child=root/'child';p=self.ledger(root,child);child.mkdir();(child/'execution.json').write_text('{}')
            result=dict(root=str(child),snrs=[26,24],source_rows=196608)
            with patch.object(stream,'full_load',return_value=p),patch.object(stream,'full_status',return_value={'complete':False}),patch.object(stream,'completed',return_value=result),patch.object(stream.subprocess,'Popen') as launch:
                stream.full_run(root,stop_after=1)
                self.assertEqual(json.loads((root/'entries/01.complete.json').read_text()),result)
                stream.full_run(root,stop_after=1);launch.assert_not_called()

    def test_failed_attempt_needs_explicit_retry_and_has_no_implicit_extra_budget(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);child=root/'child';p=self.ledger(root,child);child.mkdir();(child/'started.json').write_text('{}')
            with patch.object(stream,'full_load',return_value=p),patch.object(stream,'full_status',return_value={'complete':False}),patch.object(stream.subprocess,'Popen') as launch:
                with self.assertRaisesRegex(ValueError,'explicit --retry'):stream.full_run(root)
                with self.assertRaisesRegex(ValueError,'attempts exhausted'):stream.full_run(root,retry=True)
                launch.assert_not_called()

    def test_partial_global_coverage_never_opens_model_gate(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=self.ledger(root,root/'child')
            with patch.object(stream,'full_load',return_value=p):
                result=stream.full_status(root)
                self.assertFalse(result['complete']);self.assertFalse(result['model_loaded'])
                self.assertEqual(result['source_rows'],0)


class ServiceGateTests(unittest.TestCase):
    def test_invalid_service_identity_never_touches_hardware(self):
        from unittest.mock import patch
        service=stream.module('test_snr_service',stream.SCRIPTS/'rml2018a-snr-campaign-service.py')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'ledger-plan.json').write_text('{}')
            (root/'service-plan.json').write_text(json.dumps(dict(service_sha256='wrong',ledger_plan_sha256='wrong')))
            with patch.object(stream,'full_load',return_value={}),patch.object(service,'hardware_idle') as hardware:
                with self.assertRaisesRegex(ValueError,'identities'):service.main(root)
                hardware.assert_not_called()

    def test_failed_live_gate_never_launches_full_acquisition(self):
        from unittest.mock import patch,MagicMock
        service=stream.module('test_snr_service',stream.SCRIPTS/'rml2018a-snr-campaign-service.py')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);first=root/'first';second=root/'second';first.mkdir()
            (root/'ledger-plan.json').write_text('{}')
            (root/'service-plan.json').write_text(json.dumps(dict(service_sha256=stream.c.file_hash(Path(service.__file__)),
                ledger_plan_sha256=stream.c.file_hash(root/'ledger-plan.json'))))
            (first/'rx-events.jsonl').write_bytes(b'x'*262145)
            (first/'execution.json').write_text(json.dumps(dict(status='failed',restored=False,worker_threads_stopped=True)))
            (first/'rx-process.json').write_text(json.dumps(dict(bytes_received=4)))
            process=MagicMock();process.wait.return_value=2;process.poll.return_value=2
            p=dict(backend='/unused',groups=[{},dict(attempts=[str(first),str(second)])])
            with patch.object(stream,'full_load',return_value=p),patch.object(service,'hardware_idle',return_value={}),patch.object(service,'final_inventory'),patch.object(service.subprocess,'Popen',return_value=process) as launch:
                with self.assertRaisesRegex(ValueError,'partial RX preserved/restored'):service.main(root)
                self.assertEqual(launch.call_count,1)
                self.assertEqual(json.loads((root/'service-state.json').read_text())['phase'],'stopped_or_failed')


if __name__=='__main__':unittest.main()
