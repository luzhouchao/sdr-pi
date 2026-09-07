"""Train-only selection and strict registered source diagnostics; no live RF."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('multi', SCRIPTS / 'validate-b210-multiclass.py')
multi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(multi)
spec = importlib.util.spec_from_file_location('tx_multi', SCRIPTS / 'b210-finite-train-tx.py')
tx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tx)


class MulticlassTests(unittest.TestCase):
    def test_pinned_72_sources_cover_train_classes_without_selection_by_predictions(self):
        pinned = multi.live.document(multi.REPO / 'jetson-agx/sdrharness/config/amc/rf-preprocess-v1-selection-plan.json')['pinned_inputs']
        train = multi.train_member(multi.REPO / pinned['split']['path'])
        chosen = multi.select_rows(train)
        cases = multi.manifest()['cases']
        self.assertEqual(chosen, [(p['round'], p['class_id'], p['rows'][0]) for p in cases])
        self.assertEqual(len(set(row for _, _, row in chosen)), 72)
        for r in range(3):
            self.assertEqual({c for round_, c, _ in chosen if round_ == r}, set(range(24)))
        for p in cases:
            multi.validate_source(multi.feature(p['case_id']))

    def test_only_train_zip_member_is_read(self):
        array = np.array([1, 2, 3], dtype='<i8')
        stream = io.BytesIO()
        np.save(stream, array)
        class Archive:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, name):
                if name != 'train.npy': raise AssertionError('locked member accessed')
                return stream.getvalue()
        with patch.object(multi.zipfile, 'ZipFile', return_value=Archive()), patch.object(
                multi.contract, 'TRAIN_SHA256', multi.sha(array.tobytes())):
            np.testing.assert_array_equal(multi.train_member('unused'), array)

    def test_bad_train_hash_and_incomplete_population_fail(self):
        with self.assertRaises(AssertionError): multi.select_rows(np.array([102400]))
        pinned = multi.live.document(multi.REPO / 'jetson-agx/sdrharness/config/amc/rf-preprocess-v1-selection-plan.json')['pinned_inputs']
        with patch.object(multi.contract, 'TRAIN_SHA256', '0'*64):
            with self.assertRaises(AssertionError): multi.train_member(multi.REPO / pinned['split']['path'])

    def test_hdf_reader_only_indexes_selected_rows_and_validates_ground_truth(self):
        selection = [(p['round'], p['class_id'], p['rows'][0]) for p in multi.manifest()['cases']]
        expected = sorted(row for _, _, row in selection)
        labels = np.eye(24)[[next(c for _, c, row in selection if row == item) for item in expected]]
        class Field:
            def __init__(self, values): self.values = values
            def __getitem__(self, rows):
                if rows != expected: raise AssertionError('unregistered dataset read')
                return self.values
        class Dataset:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def __getitem__(self, key):
                return Field({'X': np.ones((72, 1024, 2)), 'Y': labels, 'Z': np.full(72, 30)}[key])
        with patch.object(multi.h5py, 'File', return_value=Dataset()):
            self.assertEqual(set(multi.read_selected('unused', selection)), set(expected))
            labels[:] = 0
            with self.assertRaises(AssertionError): multi.read_selected('unused', selection)

    def test_wrong_source_contract_never_launches_uhd(self):
        original = multi.feature(multi.manifest()['cases'][0]['case_id'])
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as temp:
            root = Path(temp)
            for name in ('transmission-plan.json', 'multiclass-manifest.json', 'train-tile.fc32'):
                shutil.copyfile(original / name, root / name)
            plan = json.loads((root / 'transmission-plan.json').read_text())
            for key, wrong in [('class_id', 24), ('rows', [0]), ('tx_samples', 20971521),
                               ('complex_peak', .3), ('split', 'test'), ('locked_test_read', True),
                               ('tx_lo_offset_hz', 0), ('source_iq_sha256', '0'*64), ('round', False)]:
                (root / 'transmission-plan.json').write_text(json.dumps(dict(plan, **{key: wrong})))
                with patch.object(tx.subprocess, 'Popen') as spawn:
                    with self.assertRaises(AssertionError): tx.transmit(root)
                    spawn.assert_not_called()
                self.assertFalse((root / 'tx.fc32.fifo').exists())
            (root / 'transmission-plan.json').write_text(json.dumps(plan))
            (root / 'train-tile.fc32').write_bytes(b'\0'*8192)
            with self.assertRaises(AssertionError): multi.contract.validate(root)
            shutil.copyfile(original / 'train-tile.fc32', root / 'train-tile.fc32')
            (root / 'multiclass-manifest.json').write_text('{}')
            with self.assertRaises(AssertionError): multi.contract.validate(root)

    def test_broad_source_filter_is_ineligible_without_dropping_primary(self):
        n = np.arange(1024)
        z = np.exp(2j*np.pi*.3*n)
        self.assertFalse(multi.fir_eligible(multi.repair.source_retention(z)))
        self.assertEqual(multi.normalize(np.tile(z, 4)).shape, (4, 2, 1024))

    def test_failed_background_does_not_gate_raw_diagnostic_inputs(self):
        p = multi.manifest()['cases'][0]
        captures = {phase: (np.arange(65535)%1024 + 1j*np.ones(65535)) for phase in multi.PHASES}
        with patch.object(multi, 'seal_capture', return_value='seal'), patch.object(
                multi.live.match, 'read_iq', side_effect=lambda root, phase: (captures[phase], None)):
            _, _, tensors = multi.inputs_for(p, dict(status='transport_valid', seal='seal'))
        self.assertIn('received_raw', tensors)
        self.assertEqual(tensors['received_raw'].shape, (4, 2, 1024))

    def test_failed_transport_still_keeps_source_in_all_case_denominator(self):
        for entry in (None, dict(status='failed')):
            _, captures, tensors = multi.inputs_for(multi.manifest()['cases'][0], entry)
            self.assertIsNone(captures)
            self.assertIn('source_original', tensors)
            self.assertNotIn('received_raw', tensors)

    def test_summary_keeps_missing_and_failed_cases_in_72_denominator(self):
        spec = importlib.util.spec_from_file_location('summary', SCRIPTS / 'summarize-b210-multiclass.py')
        summary = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(summary)
        matrix = multi.manifest()
        analysis = dict(cases={p['case_id']: dict(transport_status='failed', qualification_passed=False,
                                                 fir_eligible=True) for p in matrix['cases']})
        predictions = {p['case_id']+'/source_original': dict(numeric_id=p['class_id']) for p in matrix['cases']}
        p = matrix['cases'][0]
        predictions[p['case_id']+'/received_raw'] = dict(numeric_id=p['class_id'])
        report = summary.summarize(matrix, analysis, dict(results=predictions))
        self.assertEqual(report['total']['registered'], 72)
        self.assertEqual(report['total']['received_raw'], dict(measured=1, nominal_agreement=1))
        self.assertEqual(report['total']['qualification_passed'], 0)
        self.assertTrue(all(c['registered'] == 3 for c in report['by_class'].values()))

    def test_staging_cleanup_refuses_fifo_or_unknown_files_then_deletes_only_owned_root(self):
        root = Path(tempfile.mkdtemp(prefix='b210-multi-cleanup-test-', dir=multi.ROOT.parent))
        def local_remote(command):
            argv = shlex.split(command[-1])
            self.assertEqual(argv[:2], ['python3', '-c'])
            exec(argv[2], {})
        try:
            (root/'train-tile.fc32').write_bytes(b'fixture')
            (root/'unexpected').write_text('must not delete')
            with patch.object(multi, 'checked_command', side_effect=local_remote):
                with self.assertRaises(AssertionError): multi.remote_cleanup(root)
                self.assertTrue((root/'train-tile.fc32').exists())
                (root/'unexpected').unlink()
                os.mkfifo(root/'tx.fc32.fifo', 0o600)
                with self.assertRaises(AssertionError): multi.remote_cleanup(root)
                self.assertTrue((root/'train-tile.fc32').exists())
                (root/'tx.fc32.fifo').unlink()
                multi.remote_cleanup(root)
            self.assertFalse(root.exists())
        finally:
            if root.exists(): shutil.rmtree(root)

    def test_idle_spark_is_restored_and_watchdog_reaped_on_inference_failure(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as temp:
            base = Path(temp)
            proc = base/'123'
            proc.mkdir()
            (proc/'cmdline').write_bytes(b'/home/jetson/Spark/runtime/llama.cpp/build/bin/llama-server\0')
            (base/'key').write_text('test-only')
            def state(value):
                (proc/'stat').write_text(' '.join(['123', '(llama-server)', value] + ['0']*18 + ['100']))
            state('S')
            signals = []
            def send(pid, sig):
                self.assertEqual(pid, 123)
                signals.append(sig)
                state('T' if sig == multi.signal.SIGSTOP else 'S')
            def mapped_path(value):
                if value == '/proc': return base
                if value == '/home/jetson/Spark/config/api-key.txt': return base/'key'
                return Path(value)
            import urllib.request
            with patch.object(multi, 'Path', side_effect=mapped_path), \
                 patch.object(multi, 'checked_command', return_value='123'), \
                 patch.object(multi.os, 'kill', side_effect=send), \
                 patch.object(multi.subprocess, 'Popen') as spawn, \
                 patch.object(multi, 'save') as save, \
                 patch.object(urllib.request, 'urlopen', return_value=io.BytesIO(b'[{"is_processing":false}]')):
                spawn.return_value.returncode = -15
                with self.assertRaisesRegex(RuntimeError, 'injected'):
                    with multi.idle_spark_pause(): raise RuntimeError('injected inference error')
                self.assertEqual(signals, [multi.signal.SIGSTOP, multi.signal.SIGCONT])
                spawn.return_value.terminate.assert_called_once()
                spawn.return_value.wait.assert_called_once()
                self.assertTrue(save.call_args.args[1]['resumed'])


if __name__ == '__main__': unittest.main()
