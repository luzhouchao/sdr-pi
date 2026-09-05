#!/usr/bin/env python3
"""Focused tests for validation-only RF-aligned checkpoint admission."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPO_ROOT / "jetson-agx" / "sdrharness" / "scripts" / "validate-rf-aligned-checkpoint.py"
)
SPEC = importlib.util.spec_from_file_location("rf_aligned_checkpoint_validation", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {SCRIPT_PATH}")
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


class ManifestTests(unittest.TestCase):
    def require_local_delivery(self, manifest: dict) -> None:
        descriptor = manifest["delivery"]["training_result"]
        if not (validation.ASSET_ROOT / descriptor["path"]).is_file():
            self.skipTest("ignored AGX RF-aligned checkpoint delivery is not installed")

    def test_manifest_is_validation_only_and_test_locked(self) -> None:
        manifest = validation.load_manifest()
        self.assertEqual(manifest["status"], "candidate_validation_only")
        self.assertFalse(manifest["production_enabled"])
        self.assertFalse(manifest["recognizer_available"])
        self.assertEqual(manifest["data"]["allowed_split_members"], ["train", "val"])
        self.assertEqual(manifest["data"]["forbidden_split_members"], ["test"])
        self.assertFalse(manifest["training"]["test_loader_enabled"])

    def test_downloaded_delivery_hashes_and_numeric_labels_validate(self) -> None:
        manifest = validation.load_manifest()
        self.require_local_delivery(manifest)
        delivery = validation.verify_delivery(manifest)
        self.assertEqual(delivery["training_result_parsed"]["selected"]["epoch"], 10)
        self.assertEqual(len(delivery["provenance_parsed"]), 147)
        self.assertFalse(delivery["training_result_parsed"]["production_enabled"])

    def test_checkpoint_config_cannot_claim_test_or_production(self) -> None:
        manifest = validation.load_manifest()
        self.require_local_delivery(manifest)
        descriptor = manifest["delivery"]["training_config"]
        path = validation.resolve_regular(
            validation.ASSET_ROOT, descriptor["path"], descriptor["sha256"]
        )
        config = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(config["test_enabled"])
        self.assertEqual(config["preprocess_id"], "rf_preprocess_v1")


class ParityTests(unittest.TestCase):
    def test_parity_gate_accepts_values_inside_absolute_tolerances(self) -> None:
        manifest = validation.load_manifest()
        metrics = {
            "accuracy": manifest["training"]["reference_validation_accuracy"] + 0.00001,
            "negative_log_likelihood": manifest["training"]["reference_validation_nll"] - 0.00001,
        }
        report = validation.parity_report(manifest, metrics)
        self.assertEqual(report["status"], "pass")

    def test_parity_gate_rejects_accuracy_outside_tolerance(self) -> None:
        manifest = validation.load_manifest()
        metrics = {
            "accuracy": manifest["training"]["reference_validation_accuracy"] + 0.001,
            "negative_log_likelihood": manifest["training"]["reference_validation_nll"],
        }
        with self.assertRaisesRegex(validation.ValidationError, "accuracy delta"):
            validation.parity_report(manifest, metrics)

    def test_parity_gate_rejects_nll_outside_tolerance(self) -> None:
        manifest = validation.load_manifest()
        metrics = {
            "accuracy": manifest["training"]["reference_validation_accuracy"],
            "negative_log_likelihood": manifest["training"]["reference_validation_nll"] + 0.001,
        }
        with self.assertRaisesRegex(validation.ValidationError, "NLL delta"):
            validation.parity_report(manifest, metrics)


if __name__ == "__main__":
    unittest.main()
