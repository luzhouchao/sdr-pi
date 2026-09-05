#!/usr/bin/env python3
"""Negative and positive tests for AMC split-isolation auditing."""

from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path
from typing import Any

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
AUDITOR_PATH = (
    REPO_ROOT / "jetson-agx" / "sdrharness" / "scripts" / "audit-amc-split-isolation.py"
)
SPEC = importlib.util.spec_from_file_location("amc_split_isolation", AUDITOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import auditor from {AUDITOR_PATH}")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def partition() -> dict[str, np.ndarray]:
    return {
        "train": np.asarray([0, 3, 6, 9], dtype=np.int64),
        "val": np.asarray([1, 4, 7], dtype=np.int64),
        "test": np.asarray([2, 5, 8], dtype=np.int64),
        "num_samples": np.asarray([10], dtype=np.int64),
        "train_ratio": np.asarray([0.4], dtype=np.float64),
        "val_ratio": np.asarray([0.3], dtype=np.float64),
        "test_ratio": np.asarray([0.3], dtype=np.float64),
        "seed": np.asarray([7], dtype=np.int64),
    }


def audit_partition(value: dict[str, np.ndarray]) -> dict[str, Any]:
    return audit.audit_partition_arrays(
        value,
        dataset_id="fixture-dataset-v1",
        dataset_sha256="a" * 64,
        num_samples=10,
        expected_seed=7,
        expected_ratios=(0.4, 0.3, 0.3),
    )


def lineage_record(
    record_id: str,
    split: str,
    source_sample_id: str,
    *,
    session: str | None = None,
    day: str | None = None,
    source_kind: str = "offline_dataset",
    provenance: str = "dataset_ground_truth",
    parent: str | None = None,
    transforms: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "split": split,
        "lineage": {
            "source_sample_id": source_sample_id,
            "capture_session_id": session,
            "capture_day": day,
            "parent_record_id": parent,
            "transforms": transforms or [],
        },
        "source": {"kind": source_kind},
        "label": {"provenance": provenance},
    }


class PartitionTests(unittest.TestCase):
    def test_complete_partition_has_stable_global_row_identity(self) -> None:
        summary = audit_partition(partition())
        self.assertEqual(summary["union_count"], 10)
        self.assertEqual(summary["missing_count"], 0)
        self.assertEqual(summary["splits"]["train"]["count"], 4)
        self.assertEqual(summary["pairwise_intersection_counts"]["train_test"], 0)
        self.assertEqual(
            summary["source_identity"]["first"],
            "fixture-dataset-v1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-X-row-0000000000",
        )
        self.assertTrue(summary["source_identity"]["derivatives_must_inherit_source_sample_id"])

    def test_duplicate_inside_one_split_fails(self) -> None:
        value = partition()
        value["train"] = np.asarray([0, 3, 3, 9], dtype=np.int64)
        with self.assertRaisesRegex(audit.IsolationError, "split_duplicate"):
            audit_partition(value)

    def test_row_crossing_two_splits_fails(self) -> None:
        value = partition()
        value["test"] = np.asarray([2, 5, 7], dtype=np.int64)
        with self.assertRaisesRegex(audit.IsolationError, "split_leak"):
            audit_partition(value)

    def test_missing_global_row_fails(self) -> None:
        value = partition()
        value["test"] = np.asarray([2, 5], dtype=np.int64)
        with self.assertRaisesRegex(audit.IsolationError, "split_coverage"):
            audit_partition(value)

    def test_out_of_range_global_row_fails(self) -> None:
        value = partition()
        value["test"] = np.asarray([2, 5, 10], dtype=np.int64)
        with self.assertRaisesRegex(audit.IsolationError, "split_range"):
            audit_partition(value)


class LineageTests(unittest.TestCase):
    def test_calibration_acceptance_groups_are_exclusive(self):
        for key in ("source_sample_id", "capture_session_id", "capture_day"):
            a = lineage_record("cal", "calibration", "source-a", session="session-a", day="2026-09-01", source_kind="p201_receive", provenance="independent_annotation")
            b = lineage_record("accept", "acceptance", "source-b", session="session-b", day="2026-09-02", source_kind="p201_receive", provenance="independent_annotation")
            audit.audit_lineage_records([a,b])
            b["lineage"][key] = a["lineage"][key]
            with self.assertRaises(audit.IsolationError):
                audit.audit_lineage_records([a,b])

    def test_valid_derivative_inherits_source_session_and_day(self) -> None:
        parent = lineage_record(
            "capture-0",
            "train",
            "schedule-item-0",
            session="session-0",
            day="2026-09-05",
            source_kind="p201_receive",
            provenance="independent_annotation",
        )
        child = lineage_record(
            "capture-0-crop-0",
            "train",
            "schedule-item-0",
            session="session-0",
            day="2026-09-05",
            source_kind="p201_receive",
            provenance="independent_annotation",
            parent="capture-0",
            transforms=["crop-v1"],
        )
        summary = audit.audit_lineage_records([parent, child])
        self.assertEqual(summary["evaluation_record_count"], 2)
        self.assertEqual(summary["derived_lineage_inheritance"], "verified")

    def test_source_sample_collision_fails(self) -> None:
        records = [
            lineage_record("row-a", "train", "source-0"),
            lineage_record("row-b", "test", "source-0"),
        ]
        with self.assertRaisesRegex(audit.IsolationError, "source_sample_id"):
            audit.audit_lineage_records(records)

    def test_capture_session_collision_fails(self) -> None:
        records = [
            lineage_record(
                "row-a",
                "train",
                "source-a",
                session="session-0",
                source_kind="p201_receive",
                provenance="independent_annotation",
            ),
            lineage_record(
                "row-b",
                "validation",
                "source-b",
                session="session-0",
                source_kind="p201_receive",
                provenance="independent_annotation",
            ),
        ]
        with self.assertRaisesRegex(audit.IsolationError, "capture_session_id"):
            audit.audit_lineage_records(records)

    def test_capture_day_collision_fails(self) -> None:
        records = [
            lineage_record(
                "row-a",
                "validation",
                "source-a",
                day="2026-09-05",
                source_kind="p201_receive",
                provenance="independent_annotation",
            ),
            lineage_record(
                "row-b",
                "test",
                "source-b",
                day="2026-09-05",
                source_kind="p201_receive",
                provenance="independent_annotation",
            ),
        ]
        with self.assertRaisesRegex(audit.IsolationError, "capture_day"):
            audit.audit_lineage_records(records)

    def test_derived_crop_cannot_change_source_identity(self) -> None:
        parent = lineage_record("row-a", "train", "source-a")
        child = lineage_record(
            "row-a-crop",
            "train",
            "source-b",
            parent="row-a",
            transforms=["crop-v1"],
        )
        with self.assertRaisesRegex(audit.IsolationError, "must inherit source_sample_id"):
            audit.audit_lineage_records([parent, child])

    def test_unknown_p201_record_cannot_enter_accuracy_split(self) -> None:
        record = lineage_record(
            "unknown-rx",
            "test",
            "unknown-rx-source",
            session="session-0",
            day="2026-09-05",
            source_kind="p201_receive",
            provenance="unknown",
        )
        with self.assertRaisesRegex(audit.IsolationError, "accuracy_leak"):
            audit.audit_lineage_records([record])

    def test_unknown_p201_receive_domain_record_is_not_accuracy_eligible(self) -> None:
        record = lineage_record(
            "unknown-rx",
            "receive_domain",
            "unknown-rx-source",
            session="session-0",
            day="2026-09-05",
            source_kind="p201_receive",
            provenance="unknown",
        )
        summary = audit.audit_lineage_records([record])
        self.assertEqual(summary["receive_domain_unknown_count"], 1)
        self.assertEqual(summary["evaluation_record_count"], 0)

    def test_parent_cycle_fails(self) -> None:
        first = lineage_record("row-a", "train", "source-a", parent="row-b", transforms=["crop-v1"])
        second = copy.deepcopy(first)
        second["record_id"] = "row-b"
        second["lineage"]["parent_record_id"] = "row-a"
        with self.assertRaisesRegex(audit.IsolationError, "lineage_cycle"):
            audit.audit_lineage_records([first, second])


if __name__ == "__main__":
    unittest.main()
