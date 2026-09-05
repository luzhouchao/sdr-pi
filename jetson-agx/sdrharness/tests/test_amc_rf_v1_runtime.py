"""Runtime contract tests with synthetic captures; no dataset access."""
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / 'jetson-agx/sdrharness/scripts'


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


worker = module('worker_rf_test', 'amc-mamba-worker.py')
helper = module('helper_rf_test', 'amc-rf-v1-runtime.py')
PROFILE = ROOT / 'jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json'


def backend():
    value = worker.RfV1Backend.__new__(worker.RfV1Backend)
    profile, candidate = helper.load_contract(PROFILE)
    value.profile_sha256 = helper.PROFILE_SHA256
    value.preprocess_sha256 = candidate['preprocess']['sha256']
    value.model_sha256 = candidate['checkpoint']['sha256']
    value.model_id = profile['model']['model_id']
    value.samples_per_channel = 1024
    value.sample_rate_hz = 2_100_000
    value.rms_tolerance = 0.000001
    value.active_batch = None
    value.completed_generation = value.completed_request = 0
    value.labels = [f'provisional:{index:02d}' for index in range(24)]
    value.classify_logits = lambda iq: (list(range(24)), 1)
    return value


def request(path, digest, index=0):
    b = backend()
    return {
        'protocol_version': 1, 'request_id': 100 + index, 'session_generation': 12,
        'candidate_id': 'candidate-1', 'max_latency_ms': 5000,
        'iq': {'storage': {'path': str(path), 'offset_bytes': index * 8192, 'length_bytes': 8192},
               'sample_format': 'f32_le', 'layout': 'planar_iq', 'normalization': 'capture_unit_rms',
               'samples_per_channel': 1024, 'sample_rate_hz': 2100000, 'center_hz': 433920000},
        'rf_v1': {'profile_sha256': b.profile_sha256, 'preprocess_sha256': b.preprocess_sha256,
                  'checkpoint_sha256': b.model_sha256, 'batch_sha256': digest,
                  'batch_request_id': 100, 'source_sweep_id': 'inspect-1', 'source_request_id': 11,
                  'source_session_generation': 10, 'source_sequence': 20,
                  'capture_request_id': 5, 'capture_sequence': 21, 'window_index': index},
    }


class RuntimeTests(unittest.TestCase):
    def test_frozen_candidate_and_runtime_profile_hashes(self):
        profile, candidate = helper.load_contract(PROFILE)
        self.assertFalse(profile['production_enabled'])
        self.assertFalse(candidate['recognizer_available'])
        with tempfile.TemporaryDirectory() as temporary:
            altered = Path(temporary) / 'profile.json'
            altered.write_text(PROFILE.read_text() + ' ')
            with self.assertRaisesRegex(ValueError, 'pinned file changed'):
                helper.load_contract(altered)

    def test_all_windows_share_capture_rms_and_return_complete_logits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            iq = np.zeros((4, 2, 1024), dtype=np.float64)
            iq[:, 0] = np.asarray([0, 1, 2, 4])[:, None]
            iq /= np.sqrt(np.square(iq).sum() / 4096)
            data = iq.astype('<f4').tobytes()
            path = root / 'capture.f32'
            path.write_bytes(data)
            path.chmod(0o600)
            digest = hashlib.sha256(data).hexdigest()
            b = backend()
            for index in range(4):
                req = request(path, digest, index)
                loaded = worker.load_iq(req, root, 1e-6)
                np.testing.assert_array_equal(loaded, iq[index].astype(np.float32))
                response = worker.classify_request(req, b, root)['output']['rf_v1']
                self.assertEqual(response['contract'], req['rf_v1'])
                self.assertEqual(response['logits'], list(range(24)))
                self.assertEqual(response['compute'], 'cuda_fp16_autocast')
            with self.assertRaisesRegex(worker.WorkerError, 'replayed'):
                b.accept_window(request(path, digest, 0))
            path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
            with self.assertRaisesRegex(worker.WorkerError, 'iq_hash'):
                worker.load_iq(request(path, digest), root, 1e-6)

    def test_hash_source_order_precision_and_shape_fail_closed(self):
        req = request(Path('/private/capture.f32'), 'a' * 64)
        for field in ('profile_sha256', 'checkpoint_sha256', 'preprocess_sha256'):
            changed = copy.deepcopy(req)
            changed['rf_v1'][field] = '0' * 64
            with self.assertRaisesRegex(worker.WorkerError, 'rf_v1_hash'):
                worker.validate_request(changed, backend())
        changed = copy.deepcopy(req)
        changed['iq']['normalization'] = 'unit_rms'
        with self.assertRaisesRegex(worker.WorkerError, 'iq_normalization'):
            worker.validate_request(changed, backend())
        for key in ('source_request_id', 'source_session_generation', 'source_sequence', 'capture_request_id'):
            changed = copy.deepcopy(req)
            changed['rf_v1'][key] = 0
            with self.assertRaises(worker.WorkerError):
                worker.validate_request(changed, backend())
        b = backend()
        with self.assertRaisesRegex(worker.WorkerError, 'window_order'):
            b.accept_window(request(Path('/private/capture.f32'), 'a' * 64, 1))
        b.accept_window(req)
        for field in ('source_sequence', 'source_session_generation', 'capture_sequence'):
            changed = request(Path('/private/capture.f32'), 'a' * 64, 1)
            changed['rf_v1'][field] += 1
            with self.assertRaisesRegex(worker.WorkerError, 'window_order'):
                b.accept_window(changed)
        with self.assertRaisesRegex(worker.WorkerError, 'window_order'):
            b.accept_window(request(Path('/private/capture.f32'), 'a' * 64, 2))

    def test_restore_comparison_keeps_manual_gain_and_all_fixed_state_strict(self):
        live = module('live_rf_test', 'validate-rf-v1-runtime-live.py')
        prefix = '/sys/bus/iio/devices/iio:device0/'
        def state(mode, gain, center='2400000000'):
            return f'{prefix}in_voltage0_gain_control_mode\n{mode}\n{prefix}in_voltage0_hardwaregain\n{gain}\n{prefix}out_altvoltage0_RX_LO_frequency\n{center}\n'
        self.assertTrue(live.restored_state(state('slow_attack', '71'), state('slow_attack', '49')))
        self.assertFalse(live.restored_state(state('manual', '50'), state('manual', '49')))
        self.assertFalse(live.restored_state(state('slow_attack', '71'), state('manual', '71')))
        self.assertFalse(live.restored_state(state('slow_attack', '71'), state('slow_attack', '71', '433920000')))

    def test_frozen_golden_reference(self):
        index = np.arange(4096)
        raw = np.stack(((index * 37 + 11) % 1901 - 950, (index * 53 + 7) % 1799 - 899), axis=1).astype('<i2')
        x = raw.astype(np.float64)
        x *= 1.0 / np.sqrt(np.square(x).sum() / 4096)
        data = x.reshape(4, 1024, 2).transpose(0, 2, 1).astype('<f4').tobytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), '937c7c9497ca9f7990ee4256c617d5c57739e66da3da7498de1ab9d1618d2db2')


if __name__ == '__main__':
    unittest.main()
