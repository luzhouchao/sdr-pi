#!/usr/bin/env python3
"""Contract tests for the versioned AMC corpus manifest and record index."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR_PATH = (
    REPO_ROOT / "jetson-agx" / "sdrharness" / "scripts" / "validate-amc-corpus-manifest.py"
)
SCHEMA_PATH = (
    REPO_ROOT
    / "jetson-agx"
    / "sdrharness"
    / "config"
    / "amc"
    / "amc-corpus-manifest-v1.schema.json"
)
SPEC = importlib.util.spec_from_file_location("amc_corpus_contract", VALIDATOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import validator from {VALIDATOR_PATH}")
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def json_line(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def asset(
    asset_id: str,
    path: str,
    role: str,
    payload: bytes,
    storage_class: str = "repository_metadata",
    manual_delete: str = "not_applicable",
) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "path": path,
        "role": role,
        "bytes": len(payload),
        "sha256": digest(payload),
        "storage_class": storage_class,
        "manual_delete": manual_delete,
    }


def write_records(root: Path, manifest: dict[str, Any], records: list[dict[str, Any]]) -> None:
    payload = b"".join(json_line(record) for record in records)
    (root / "records.jsonl").write_bytes(payload)
    manifest["record_index"] = {
        "schema_id": "amc_corpus_record_v1",
        "format": "jsonl",
        "path": "records.jsonl",
        "count": len(records),
        "bytes": len(payload),
        "sha256": digest(payload),
    }


def build_fixture(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payloads = {
        "profile.json": b'{"profile_id":"fixture-profile"}\n',
        "preprocess.json": b'{"preprocess_id":"fixture-preprocess"}\n',
        "labels.json": b'{"numeric_ids_authoritative":true}\n',
        "dataset.bin": struct.pack("<ffff", 0.25, -0.25, 0.5, -0.5),
        "split.bin": b"fixture split membership\n",
        "plan.json": b'{"plan_id":"fixture-plan-1"}\n',
        "annotation.json": b'{"schedule":"known-waveform-1"}\n',
        "p201.ci16": struct.pack("<hhhh", 10, -10, 20, -20),
        "golden.json": b'{"fixture_id":"fixture-golden"}\n',
    }
    for relative, payload in payloads.items():
        (root / relative).write_bytes(payload)

    assets = [
        asset("fixture-profile", "profile.json", "input_profile", payloads["profile.json"]),
        asset("fixture-preprocess", "preprocess.json", "preprocess_spec", payloads["preprocess.json"]),
        asset("fixture-labels", "labels.json", "label_table", payloads["labels.json"]),
        asset(
            "fixture-dataset",
            "dataset.bin",
            "iq_dataset",
            payloads["dataset.bin"],
            "machine_local_asset",
        ),
        asset("fixture-split", "split.bin", "split_index", payloads["split.bin"]),
        asset("fixture-plan", "plan.json", "capture_plan", payloads["plan.json"]),
        asset(
            "fixture-annotation",
            "annotation.json",
            "annotation_evidence",
            payloads["annotation.json"],
        ),
        asset(
            "fixture-p201-iq",
            "p201.ci16",
            "raw_iq",
            payloads["p201.ci16"],
            "application_result",
            "required",
        ),
        asset("fixture-golden", "golden.json", "golden_fixture", payloads["golden.json"]),
    ]

    offline = {
        "schema_version": 1,
        "schema_id": "amc_corpus_record_v1",
        "record_id": "offline-row-0",
        "split": "train",
        "lineage": {
            "source_sample_id": "rml-row-0",
            "capture_session_id": None,
            "capture_day": None,
            "parent_record_id": None,
            "transforms": [],
        },
        "window": {
            "window_index": 0,
            "sample_offset": 0,
            "samples": 2,
            "bytes": len(payloads["dataset.bin"]),
            "sample_format": "f32_le",
            "layout": "interleaved_iq",
            "endianness": "little",
            "sha256": digest(payloads["dataset.bin"]),
            "storage": {
                "kind": "dataset_row",
                "asset_id": "fixture-dataset",
                "dataset_path": "/X",
                "row_index": 0,
            },
        },
        "label": {
            "provenance": "dataset_ground_truth",
            "numeric_id": 0,
            "raw_value": 0,
            "display_name": "provisional-class-0",
            "display_name_status": "provisional",
            "evidence": {
                "dataset_id": "fixture-dataset-v1",
                "dataset_sha256": digest(payloads["dataset.bin"]),
                "label_field": "Y.argmax",
                "row_index": 0,
            },
        },
        "source": {
            "kind": "offline_dataset",
            "dataset_id": "fixture-dataset-v1",
            "dataset_asset_id": "fixture-dataset",
            "dataset_sha256": digest(payloads["dataset.bin"]),
            "split_asset_id": "fixture-split",
            "split_sha256": digest(payloads["split.bin"]),
            "row_index": 0,
            "nominal_snr_db": 10,
        },
    }

    received = {
        "schema_version": 1,
        "schema_id": "amc_corpus_record_v1",
        "record_id": "p201-session-1-window-0",
        "split": "validation",
        "lineage": {
            "source_sample_id": "waveform-schedule-1-item-0",
            "capture_session_id": "p201-session-1",
            "capture_day": "2026-09-05",
            "parent_record_id": None,
            "transforms": [],
        },
        "window": {
            "window_index": 0,
            "sample_offset": 0,
            "samples": 2,
            "bytes": len(payloads["p201.ci16"]),
            "sample_format": "ci16_le",
            "layout": "interleaved_iq",
            "endianness": "little",
            "sha256": digest(payloads["p201.ci16"]),
            "storage": {
                "kind": "managed_asset",
                "asset_id": "fixture-p201-iq",
                "offset_bytes": 0,
            },
        },
        "label": {
            "provenance": "independent_annotation",
            "numeric_id": 1,
            "display_name": "provisional-class-1",
            "display_name_status": "provisional",
            "evidence": {
                "annotation_id": "waveform-schedule-1",
                "method": "known_waveform_schedule",
                "annotated_at_utc": "2026-09-05T01:00:00Z",
                "evidence_sha256": digest(payloads["annotation.json"]),
            },
        },
        "source": {
            "kind": "p201_receive",
            "capture_session_id": "p201-session-1",
            "captured_at_utc": "2026-09-05T01:00:01Z",
            "capture_day": "2026-09-05",
            "plan_id": "fixture-plan-1",
            "plan_asset_id": "fixture-plan",
            "plan_sha256": digest(payloads["plan.json"]),
            "center_hz": 433920000,
            "sample_rate_hz": 2100000,
            "rf_bandwidth_hz": 1500000,
            "gain_mode": "manual",
            "rx_gain_db": 50,
            "sequence": 7,
            "samples_captured": 2,
            "bytes_transferred": len(payloads["p201.ci16"]),
            "rx_input": {
                "identity_version": 1,
                "verified": True,
                "front_panel_port": "RX1",
                "logical_channel": "RX0",
                "phy_channel": "voltage0",
                "scan_i_channel": "voltage0",
                "scan_q_channel": "voltage1",
                "rf_port_select": "A_BALANCED",
                "source": "iio_channel_attr",
            },
            "quality": {
                "raw_rms_dbfs": -40.0,
                "measured_snr_db": 15.0,
                "clipped_samples": 0,
                "dropped_samples": 0,
                "overflow": False,
                "health_flags": 0,
                "healthy": True,
            },
            "retention": {
                "user_visible": True,
                "result_id": "fixture-result-1",
                "manual_delete_available": True,
                "p201_transient_removed": True,
                "agx_temporary_removed": True,
            },
        },
    }

    generator_bytes = struct.pack("<hhhhhhhh", 1, -1, 2, -2, 3, -3, 4, -4)
    golden = {
        "schema_version": 1,
        "schema_id": "amc_corpus_record_v1",
        "record_id": "golden-window-0",
        "split": "golden",
        "lineage": {
            "source_sample_id": "golden-generator-0",
            "capture_session_id": None,
            "capture_day": None,
            "parent_record_id": None,
            "transforms": ["fixture-preprocess"],
        },
        "window": {
            "window_index": 0,
            "sample_offset": 0,
            "samples": 4,
            "bytes": len(generator_bytes),
            "sample_format": "ci16_le",
            "layout": "interleaved_iq",
            "endianness": "little",
            "sha256": digest(generator_bytes),
            "storage": {
                "kind": "deterministic_generator",
                "generator_id": "fixture-generator-v1",
                "parameters_sha256": digest(b"fixture generator parameters"),
            },
        },
        "label": {"provenance": "unknown", "reason": "out_of_label_space"},
        "source": {
            "kind": "golden_vector",
            "fixture_id": "fixture-golden",
            "fixture_sha256": digest(payloads["golden.json"]),
            "expected_tensor": {
                "sample_format": "f32_le",
                "layout": "planar_iq",
                "shape": [2, 4],
                "bytes": 32,
                "sha256": digest(b"\x00" * 32),
            },
        },
    }
    records = [offline, received, golden]
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "schema_id": "amc_corpus_manifest_v1",
        "manifest_id": "mixed-contract-fixture-v1",
        "created_at_utc": "2026-09-05T01:00:02Z",
        "status": "frozen",
        "corpus_kind": "mixed",
        "contract": {
            "input_profile": {
                "id": "fixture-profile",
                "path": "profile.json",
                "sha256": digest(payloads["profile.json"]),
                "admission": "integration_only",
            },
            "preprocessing": {
                "id": "fixture-preprocess",
                "path": "preprocess.json",
                "sha256": digest(payloads["preprocess.json"]),
                "status": "integration_only",
            },
            "label_space": {
                "id": "fixture-labels",
                "path": "labels.json",
                "sha256": digest(payloads["labels.json"]),
                "numeric_ids_authoritative": True,
                "display_names_status": "provisional",
            },
        },
        "split_policy": {
            "strategy": "group_exclusive",
            "group_keys": ["source_sample_id", "capture_session_id", "capture_day"],
            "allowed_splits": ["train", "validation", "golden"],
            "frozen": True,
            "test_locked": True,
        },
        "assets": assets,
        "record_index": {},
        "governance": {
            "bulk_iq_in_git": False,
            "model_prediction_is_ground_truth": False,
            "unlabeled_accuracy_allowed": False,
            "manual_delete_required_for_user_results": True,
        },
    }
    write_records(root, manifest, records)
    return manifest, records


class AmcCorpusContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = contract.read_bounded_json(
            SCHEMA_PATH, contract.MAX_SCHEMA_BYTES, "schema"
        )

    def validate(
        self,
        root: Path,
        manifest: dict[str, Any],
        *,
        verify_assets: bool = True,
    ) -> dict[str, Any]:
        return contract.validate_manifest(manifest, self.schema, root, verify_assets)

    def test_mixed_manifest_validates_all_three_label_provenance_types(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amc-corpus-contract-") as temporary:
            root = Path(temporary)
            manifest, _ = build_fixture(root)
            summary = self.validate(root, manifest)
            self.assertEqual(summary["record_count"], 3)
            self.assertEqual(
                summary["label_provenance_counts"],
                {
                    "dataset_ground_truth": 1,
                    "independent_annotation": 1,
                    "unknown": 1,
                },
            )
            self.assertTrue(summary["assets_verified"])

    def test_unknown_label_cannot_smuggle_a_prediction_or_numeric_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amc-corpus-contract-") as temporary:
            root = Path(temporary)
            manifest, records = build_fixture(root)
            records[2]["label"]["numeric_id"] = 7
            write_records(root, manifest, records)
            with self.assertRaisesRegex(contract.ContractError, "unknown=.*numeric_id"):
                self.validate(root, manifest)

    def test_p201_record_rejects_dataset_ground_truth_without_independent_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amc-corpus-contract-") as temporary:
            root = Path(temporary)
            manifest, records = build_fixture(root)
            records[1]["label"] = copy.deepcopy(records[0]["label"])
            write_records(root, manifest, records)
            with self.assertRaisesRegex(contract.ContractError, "independent_annotation or unknown"):
                self.validate(root, manifest)

    def test_provisional_label_space_cannot_be_upgraded_by_a_record(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amc-corpus-contract-") as temporary:
            root = Path(temporary)
            manifest, records = build_fixture(root)
            records[0]["label"]["display_name_status"] = "trusted"
            write_records(root, manifest, records)
            with self.assertRaisesRegex(contract.ContractError, "cannot exceed"):
                self.validate(root, manifest)

    def test_train_test_lineage_collision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amc-corpus-contract-") as temporary:
            root = Path(temporary)
            manifest, records = build_fixture(root)
            duplicate = copy.deepcopy(records[0])
            duplicate["record_id"] = "offline-row-0-test-copy"
            duplicate["split"] = "test"
            manifest["split_policy"]["allowed_splits"].append("test")
            records.append(duplicate)
            write_records(root, manifest, records)
            with self.assertRaisesRegex(contract.ContractError, "split_leak"):
                self.validate(root, manifest)

    def test_wrong_p201_front_panel_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amc-corpus-contract-") as temporary:
            root = Path(temporary)
            manifest, records = build_fixture(root)
            records[1]["source"]["rx_input"]["front_panel_port"] = "TRX1"
            write_records(root, manifest, records)
            with self.assertRaisesRegex(contract.ContractError, "fixed verified P201 RX1"):
                self.validate(root, manifest)

    def test_frozen_p201_record_requires_completed_transient_cleanup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amc-corpus-contract-") as temporary:
            root = Path(temporary)
            manifest, records = build_fixture(root)
            records[1]["source"]["retention"]["p201_transient_removed"] = False
            write_records(root, manifest, records)
            with self.assertRaisesRegex(contract.ContractError, "requires completed cleanup"):
                self.validate(root, manifest)

    def test_production_profile_requires_frozen_preprocessing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amc-corpus-contract-") as temporary:
            root = Path(temporary)
            manifest, _ = build_fixture(root)
            manifest["contract"]["input_profile"]["admission"] = "production"
            with self.assertRaisesRegex(contract.ContractError, "requires frozen preprocessing"):
                self.validate(root, manifest)

    def test_record_index_hash_and_traversal_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amc-corpus-contract-") as temporary:
            root = Path(temporary)
            manifest, _ = build_fixture(root)
            manifest["record_index"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(contract.ContractError, "record index hash mismatch"):
                self.validate(root, manifest)

            manifest, _ = build_fixture(root)
            manifest["record_index"]["path"] = "../records.jsonl"
            with self.assertRaisesRegex(contract.ContractError, "without traversal"):
                self.validate(root, manifest)


if __name__ == "__main__":
    os.umask(0o077)
    unittest.main()
