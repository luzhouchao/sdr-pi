#!/usr/bin/env python3
"""Focused tests for preregistered RF-v1 precision selection."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "jetson-agx" / "sdrharness" / "scripts" / "select-rf-v1-precision.py"
VALIDATOR_PATH = (
    REPO_ROOT / "jetson-agx" / "sdrharness" / "scripts" / "validate-rf-aligned-checkpoint.py"
)
FP16_CANDIDATE_PATH = (
    REPO_ROOT
    / "jetson-agx"
    / "sdrharness"
    / "config"
    / "amc"
    / "rml2018a-d8-rf-v1-fp16.candidate.json"
)
EVIDENCE_PATH = REPO_ROOT / "docs" / "RF_V1_PRECISION_SELECTION_AUDIT_2026-09-05.json"
EXPECTED_FP16_CANDIDATE_SHA256 = (
    "35ff99719ab845f33dc7ca2d0e7b666e4f40721ca64a6dd615a671ec6c084f40"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


precision = load_module("rf_v1_precision_selection", SCRIPT_PATH)
validator = load_module("rf_v1_precision_validator", VALIDATOR_PATH)


class PlanTests(unittest.TestCase):
    def test_plan_is_hash_pinned_and_test_locked(self) -> None:
        plan, candidate, audit = precision.load_plan(validator)
        self.assertEqual(plan["evaluation"]["precisions_in_fixed_order"], ["fp32", "fp16", "bf16"])
        self.assertEqual(plan["governance"]["forbidden_npz_members"], ["test"])
        self.assertTrue(plan["governance"]["recognizer_available_remains_false"])
        self.assertFalse(candidate["recognizer_available"])
        self.assertFalse(audit["governance"]["test_member_loaded"])


class FrozenEvidenceTests(unittest.TestCase):
    def test_fp16_candidate_is_hash_pinned_and_fail_closed(self) -> None:
        self.assertEqual(
            precision.sha256_file(FP16_CANDIDATE_PATH), EXPECTED_FP16_CANDIDATE_SHA256
        )
        candidate = json.loads(FP16_CANDIDATE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(candidate["inference"]["compute"], "cuda_fp16_autocast")
        self.assertTrue(candidate["validation"]["all_preregistered_numeric_gates_passed"])
        self.assertFalse(candidate["validation"]["locked_test_opened"])
        self.assertFalse(candidate["production_enabled"])
        self.assertFalse(candidate["recognizer_available"])

    def test_retained_evidence_selects_fp16_and_rejects_bf16(self) -> None:
        evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(evidence["status"], "pass")
        self.assertEqual(evidence["selection"]["selected"], "fp16")
        self.assertTrue(
            evidence["numeric_comparisons_to_fp32"]["fp16"]["numeric_eligible"]
        )
        self.assertFalse(
            evidence["numeric_comparisons_to_fp32"]["bf16"]["numeric_eligible"]
        )
        self.assertFalse(evidence["governance"]["test_member_loaded"])
        self.assertFalse(evidence["production"]["recognizer_available"])


class DecisionTests(unittest.TestCase):
    @staticmethod
    def plan() -> dict:
        return {
            "performance_benchmark": {
                "maximum_reserved_memory_increase_bytes": 64,
                "minimum_median_throughput_gain_over_fp32": 0.1,
            }
        }

    @staticmethod
    def full_runs() -> dict:
        return {
            "fp32": {"performance": {"cuda_peak_reserved_bytes": 1000}},
            "fp16": {"performance": {"cuda_peak_reserved_bytes": 1020}},
            "bf16": {"performance": {"cuda_peak_reserved_bytes": 1020}},
        }

    def test_fp32_fallback_when_low_precisions_fail_numeric_gates(self) -> None:
        comparisons = {
            "fp16": {"numeric_eligible": False, "argmax_agreement_with_fp32": 1.0},
            "bf16": {"numeric_eligible": False, "argmax_agreement_with_fp32": 1.0},
        }
        benchmark = {
            "fp16": {"median_groups_per_second": 120.0, "median_throughput_ratio_to_fp32": 1.2},
            "bf16": {"median_groups_per_second": 130.0, "median_throughput_ratio_to_fp32": 1.3},
        }
        decision = precision.choose_precision(self.plan(), comparisons, self.full_runs(), benchmark)
        self.assertEqual(decision["selected"], "fp32")

    def test_speed_gate_rejects_numerically_valid_but_slow_precision(self) -> None:
        comparisons = {
            "fp16": {"numeric_eligible": True, "argmax_agreement_with_fp32": 1.0},
            "bf16": {"numeric_eligible": False, "argmax_agreement_with_fp32": 1.0},
        }
        benchmark = {
            "fp16": {"median_groups_per_second": 105.0, "median_throughput_ratio_to_fp32": 1.05},
            "bf16": {"median_groups_per_second": 130.0, "median_throughput_ratio_to_fp32": 1.3},
        }
        decision = precision.choose_precision(self.plan(), comparisons, self.full_runs(), benchmark)
        self.assertEqual(decision["selected"], "fp32")

    def test_bf16_wins_registered_tie_after_all_gates(self) -> None:
        comparisons = {
            "fp16": {"numeric_eligible": True, "argmax_agreement_with_fp32": 0.9990},
            "bf16": {"numeric_eligible": True, "argmax_agreement_with_fp32": 0.9985},
        }
        benchmark = {
            "fp16": {"median_groups_per_second": 120.0, "median_throughput_ratio_to_fp32": 1.2},
            "bf16": {"median_groups_per_second": 118.0, "median_throughput_ratio_to_fp32": 1.18},
        }
        decision = precision.choose_precision(self.plan(), comparisons, self.full_runs(), benchmark)
        self.assertEqual(decision["selected"], "bf16")

    def test_memory_gate_can_leave_only_fp16(self) -> None:
        comparisons = {
            "fp16": {"numeric_eligible": True, "argmax_agreement_with_fp32": 0.999},
            "bf16": {"numeric_eligible": True, "argmax_agreement_with_fp32": 0.999},
        }
        full_runs = self.full_runs()
        full_runs["bf16"]["performance"]["cuda_peak_reserved_bytes"] = 2000
        benchmark = {
            "fp16": {"median_groups_per_second": 120.0, "median_throughput_ratio_to_fp32": 1.2},
            "bf16": {"median_groups_per_second": 130.0, "median_throughput_ratio_to_fp32": 1.3},
        }
        decision = precision.choose_precision(self.plan(), comparisons, full_runs, benchmark)
        self.assertEqual(decision["selected"], "fp16")


if __name__ == "__main__":
    unittest.main()
