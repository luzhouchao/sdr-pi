#!/usr/bin/env python3
"""Focused tests for validation-only RF preprocessing selection."""

from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPO_ROOT
    / "jetson-agx"
    / "sdrharness"
    / "scripts"
    / "select-rf-preprocess-validation.py"
)
SPEC = importlib.util.spec_from_file_location("rf_preprocess_selection", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {SCRIPT_PATH}")
selection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selection)
SPEC_PATH = REPO_ROOT / "jetson-agx" / "sdrharness" / "config" / "amc" / "rf-preprocess-v1.json"
GOLDEN_PATH = (
    REPO_ROOT
    / "raspberry-pi"
    / "sdr-agent"
    / "controller"
    / "tests"
    / "fixtures"
    / "rf-preprocess-v1-golden.json"
)


def npy_bytes(value: np.ndarray) -> bytes:
    stream = io.BytesIO()
    np.save(stream, value, allow_pickle=False)
    return stream.getvalue()


class SplitAccessTests(unittest.TestCase):
    def test_allowed_member_loader_does_not_touch_poison_test_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rf-preprocess-split-") as temporary:
            path = Path(temporary) / "split.npz"
            with zipfile.ZipFile(path, "w") as archive:
                for name in selection.EXPECTED_ARCHIVE_MEMBERS:
                    if name == "test.npy":
                        archive.writestr(name, b"poison-not-an-npy")
                    else:
                        archive.writestr(name, npy_bytes(np.asarray([1], dtype=np.int64)))
            access_log: list[str] = []
            train = selection.read_npz_member(path, "train", access_log)
            self.assertEqual(train.tolist(), [1])
            self.assertEqual(access_log, ["train"])

    def test_test_member_is_rejected_before_archive_access(self) -> None:
        access_log: list[str] = []
        with self.assertRaisesRegex(selection.SelectionError, "test_lock"):
            selection.read_npz_member(Path("does-not-exist.npz"), "test", access_log)
        self.assertEqual(access_log, [])


class TransformTests(unittest.TestCase):
    def test_per_window_unit_rms_preserves_dc_and_normalizes(self) -> None:
        groups = np.zeros((1, 4, 2, 1024), dtype=np.float32)
        phase = np.linspace(0.0, 8.0 * np.pi, 1024, endpoint=False, dtype=np.float32)
        for window in range(4):
            groups[0, window, 0] = 3.0 + window + np.sin(phase)
            groups[0, window, 1] = 4.0 + np.cos(phase)
        transformed = selection.transform_group_batch(groups)
        rms = selection.complex_rms_rows(transformed["per_window_unit_rms"])
        self.assertTrue(np.allclose(rms, 1.0, atol=1e-6))
        self.assertGreater(abs(float(transformed["per_window_unit_rms"][0].mean())), 0.1)

    def test_dc_candidate_removes_each_window_mean(self) -> None:
        sample = np.arange(1024, dtype=np.float32)
        groups = np.empty((1, 4, 2, 1024), dtype=np.float32)
        for window in range(4):
            groups[0, window, 0] = sample + 100.0 * window
            groups[0, window, 1] = sample[::-1] - 50.0 * window
        transformed = selection.transform_group_batch(groups)
        centered = transformed["per_window_dc_unit_rms"]
        self.assertTrue(np.allclose(centered.mean(axis=2), 0.0, atol=1e-6))
        self.assertTrue(np.allclose(selection.complex_rms_rows(centered), 1.0, atol=1e-6))

    def test_capture_normalization_uses_one_scale_for_four_windows(self) -> None:
        groups = np.zeros((1, 4, 2, 1024), dtype=np.float32)
        phase = np.linspace(0.0, 8.0 * np.pi, 1024, endpoint=False, dtype=np.float32)
        for window, amplitude in enumerate((1.0, 2.0, 3.0, 4.0)):
            groups[0, window, 0] = amplitude * np.sin(phase)
            groups[0, window, 1] = amplitude * np.cos(phase)
        transformed = selection.transform_group_batch(groups)
        capture = transformed["four_window_capture_unit_rms"].reshape(1, 4, 2, 1024)
        group_rms = np.sqrt(np.mean(np.square(capture, dtype=np.float64)) * 2.0)
        row_rms = selection.complex_rms_rows(capture.reshape(-1, 2, 1024))
        self.assertAlmostEqual(float(group_rms), 1.0, places=6)
        self.assertGreater(float(row_rms.max() - row_rms.min()), 0.5)

    def test_frozen_spec_and_golden_bytes_match_reference_transform(self) -> None:
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        fixture = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(spec["status"], "frozen_for_retraining")
        self.assertFalse(spec["production_enabled"])
        self.assertFalse(spec["recognizer_available"])
        self.assertEqual(spec["amplitude_and_dc"]["normalization"], "four_window_capture_complex_unit_rms")
        self.assertFalse(spec["amplitude_and_dc"]["remove_dc"])
        self.assertEqual(spec["windows"]["count"], 4)
        self.assertEqual(spec["aggregation"]["method"], "arithmetic_mean_logits")
        self.assertEqual(hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest(), fixture["preprocess_sha256"])

        index = np.arange(4096, dtype=np.int64)
        raw = np.empty((4096, 2), dtype="<i2")
        raw[:, 0] = ((index * 37 + 11) % 1901) - 950
        raw[:, 1] = ((index * 53 + 7) % 1799) - 899
        self.assertEqual(hashlib.sha256(raw.tobytes()).hexdigest(), fixture["raw"]["sha256"])
        groups = raw.reshape(1, 4, 1024, 2).transpose(0, 1, 3, 2).astype(np.float32)
        model = selection.transform_group_batch(groups)["four_window_capture_unit_rms"]
        model_bytes = np.asarray(model.reshape(4, 2, 1024), dtype="<f4").tobytes()
        self.assertEqual(hashlib.sha256(model_bytes).hexdigest(), fixture["model"]["sha256"])
        capture_rms = float(np.sqrt(np.mean(np.square(model, dtype=np.float64)) * 2.0))
        self.assertAlmostEqual(capture_rms, fixture["model"]["capture_complex_rms"], places=12)


class GroupingAndSelectionTests(unittest.TestCase):
    def test_grouping_never_crosses_numeric_label_or_snr(self) -> None:
        labels = np.asarray([0] * 5 + [1] * 9, dtype=np.int64)
        snr = np.asarray([4] * 5 + [6] * 9, dtype=np.float32)
        groups, excluded, summary = selection.build_four_window_groups(labels, snr)
        self.assertEqual(groups.shape, (3, 4))
        self.assertEqual(excluded.tolist(), [4, 13])
        self.assertEqual(summary["tail_rows_excluded"], 2)
        for group in groups:
            self.assertEqual(len(set(labels[group].tolist())), 1)
            self.assertEqual(len(set(snr[group].tolist())), 1)

    def test_window_selection_prefers_smallest_mean_logit_within_tolerance(self) -> None:
        rows = [
            {"window_count": 1, "method": "mean_logit", "primary_snr_accuracy": 0.9000},
            {"window_count": 1, "method": "mean_probability", "primary_snr_accuracy": 0.9005},
            {"window_count": 2, "method": "mean_logit", "primary_snr_accuracy": 0.9020},
            {"window_count": 4, "method": "mean_logit", "primary_snr_accuracy": 0.9024},
            {"window_count": 4, "method": "majority_vote", "primary_snr_accuracy": 0.9999},
        ]
        selected = selection.choose_window_aggregation(rows)
        self.assertEqual(selected["window_count"], 1)
        self.assertEqual(selected["method"], "mean_logit")

    def test_transform_selection_excludes_raw_and_applies_preserve_ties(self) -> None:
        metrics = {
            "raw_identity": {"primary_snr_accuracy": 0.99},
            "per_window_unit_rms": {"primary_snr_accuracy": 0.90},
            "per_window_dc_unit_rms": {"primary_snr_accuracy": 0.901},
            "four_window_capture_unit_rms": {"primary_snr_accuracy": 0.899},
            "four_window_capture_dc_unit_rms": {"primary_snr_accuracy": 0.80},
        }
        table = {
            name: [
                {"window_count": 1, "method": "mean_logit", "primary_snr_accuracy": score["primary_snr_accuracy"]},
                {"window_count": 1, "method": "mean_probability", "primary_snr_accuracy": score["primary_snr_accuracy"]},
            ]
            for name, score in metrics.items()
        }
        selected = selection.choose_transform(metrics, table)
        self.assertEqual(selected["selected_transform"], "per_window_unit_rms")
        self.assertFalse(selected["raw_identity_eligible"])


class CalibrationTests(unittest.TestCase):
    def test_temperature_fit_reduces_overconfident_nll(self) -> None:
        logits = np.asarray(
            [
                [8.0, 0.0, 0.0],
                [8.0, 0.0, 0.0],
                [0.0, 8.0, 0.0],
                [0.0, 8.0, 0.0],
            ],
            dtype=np.float32,
        )
        padded = np.full((4, selection.NUM_CLASSES), -8.0, dtype=np.float32)
        padded[:, :3] = logits
        labels = np.asarray([0, 1, 1, 0], dtype=np.int64)
        before = selection.negative_log_likelihood(
            selection.calibration_probabilities(padded, 1, "mean_logit", 1.0), labels
        )
        temperature, after = selection.fit_scalar_temperature(padded, labels, 1, "mean_logit")
        self.assertGreater(temperature, 1.0)
        self.assertLess(after, before)


if __name__ == "__main__":
    unittest.main()
