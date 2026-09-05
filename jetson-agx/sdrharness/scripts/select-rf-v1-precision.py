#!/usr/bin/env python3
"""Select RF-v1 D8 inference precision on grouped validation only."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import math
import os
import resource
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
ASSET_ROOT = REPO_ROOT / "local-assets" / "amc-eval"
PLAN_PATH = (
    REPO_ROOT / "jetson-agx" / "sdrharness" / "config" / "amc" / "rf-v1-precision-selection-plan.json"
)
EXPECTED_PLAN_SHA256 = "552c2a16505bf9ced2d8ab1190fe2cb1b9b8d104cee2b94d9b8c8f108d287306"
VALIDATOR_PATH = (
    REPO_ROOT / "jetson-agx" / "sdrharness" / "scripts" / "validate-rf-aligned-checkpoint.py"
)
SELECTION_PATH = (
    REPO_ROOT / "jetson-agx" / "sdrharness" / "scripts" / "select-rf-preprocess-validation.py"
)
TEMPORARY_ROOT = Path("/var/tmp/sdrharness-dev/rf-v1-precision-selection-20260905")
MAX_TEMPORARY_BYTES = 64 * 1024 * 1024
PRECISIONS = ("fp32", "fp16", "bf16")
NUM_CLASSES = 24
GROUP_WINDOWS = 4


class PrecisionSelectionError(Exception):
    """Fail-closed precision-selection error."""


def fail(message: str) -> None:
    raise PrecisionSelectionError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        fail(f"cannot import {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def load_plan(validator: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if sha256_file(PLAN_PATH) != EXPECTED_PLAN_SHA256:
        fail("precision selection plan hash changed")
    plan = validator.strict_json(PLAN_PATH)
    if (
        not isinstance(plan, dict)
        or plan.get("schema_version") != 1
        or plan.get("schema_id") != "rf_v1_precision_selection_plan_v1"
        or plan.get("status") != "preregistered"
    ):
        fail("unexpected precision selection plan identity")
    evaluation = plan.get("evaluation", {})
    if (
        evaluation.get("precisions_in_fixed_order") != list(PRECISIONS)
        or evaluation.get("groups") != 95_607
        or evaluation.get("source_rows") != 382_428
        or evaluation.get("groups_per_batch") != 64
        or evaluation.get("warmup_batches_per_precision") != 5
    ):
        fail("fixed precision evaluation population or order changed")
    governance = plan.get("governance", {})
    if governance.get("allowed_npz_members") != ["train", "val"]:
        fail("only train and val may be allowed")
    if governance.get("forbidden_npz_members") != ["test"]:
        fail("test must remain explicitly forbidden")

    candidate_descriptor = plan["pinned_inputs"]["candidate_manifest"]
    validator.resolve_repo_file(candidate_descriptor["path"], candidate_descriptor["sha256"])
    candidate = validator.load_manifest()
    audit_descriptor = plan["pinned_inputs"]["fp32_validation_audit"]
    audit_path = validator.resolve_repo_file(audit_descriptor["path"], audit_descriptor["sha256"])
    audit = validator.strict_json(audit_path)
    if (
        audit.get("status") != "pass"
        or audit.get("governance", {}).get("test_member_loaded") is not False
        or audit.get("production", {}).get("recognizer_available") is not False
    ):
        fail("pinned FP32 validation evidence is not pass/fail-closed")
    if candidate["checkpoint"]["sha256"] != plan["pinned_inputs"]["checkpoint"]["sha256"]:
        fail("candidate checkpoint differs between manifests")
    return plan, candidate, audit


def precision_context(torch: Any, precision: str):
    if precision == "fp32":
        return contextlib.nullcontext()
    if precision == "fp16":
        return torch.autocast(device_type="cuda", dtype=torch.float16)
    if precision == "bf16":
        return torch.autocast(device_type="cuda", dtype=torch.bfloat16)
    fail(f"unsupported precision {precision!r}")


def warmup_precision(
    model: Any,
    torch: Any,
    values: np.ndarray,
    precision: str,
    iterations: int,
) -> None:
    tensor = torch.from_numpy(np.ascontiguousarray(values)).cuda(non_blocking=False)
    for _ in range(iterations):
        with torch.inference_mode(), precision_context(torch, precision):
            output = model(tensor)
        if output.shape != (len(values), NUM_CLASSES):
            fail(f"warmup output shape changed for {precision}")
    torch.cuda.synchronize()


def infer_full_precision(
    model: Any,
    torch: Any,
    selection: Any,
    validation_x: np.ndarray,
    groups: np.ndarray,
    precision: str,
    groups_per_batch: int,
    warmup_iterations: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    warmup_values = selection.transform_group_batch(validation_x[groups[:groups_per_batch]])[
        "four_window_capture_unit_rms"
    ]
    warmup_precision(model, torch, warmup_values, precision, warmup_iterations)
    torch.cuda.reset_peak_memory_stats()
    mean_logits = np.empty((len(groups), NUM_CLASSES), dtype=np.float64)
    cursor = 0
    preprocess_seconds = 0.0
    model_seconds = 0.0
    total_started = time.perf_counter()
    batch_count = math.ceil(len(groups) / groups_per_batch)
    for batch_number, start in enumerate(range(0, len(groups), groups_per_batch), start=1):
        batch_groups = groups[start : start + groups_per_batch]
        preprocess_started = time.perf_counter()
        values = selection.transform_group_batch(validation_x[batch_groups])[
            "four_window_capture_unit_rms"
        ]
        preprocess_seconds += time.perf_counter() - preprocess_started
        tensor = torch.from_numpy(values).cuda(non_blocking=False)
        model_started = time.perf_counter()
        with torch.inference_mode(), precision_context(torch, precision):
            logits = model(tensor).float().cpu().numpy()
        model_seconds += time.perf_counter() - model_started
        if logits.shape != (len(batch_groups) * GROUP_WINDOWS, NUM_CLASSES) or not np.isfinite(logits).all():
            fail(f"non-finite or malformed {precision} logits in batch {batch_number}")
        grouped = logits.reshape(-1, GROUP_WINDOWS, NUM_CLASSES)
        next_cursor = cursor + len(batch_groups)
        mean_logits[cursor:next_cursor] = grouped.mean(axis=1, dtype=np.float64)
        cursor = next_cursor
        if batch_number % 200 == 0 or batch_number == batch_count:
            print(
                f"precision={precision} batches={batch_number}/{batch_count} groups={cursor}/{len(groups)}",
                flush=True,
            )
    torch.cuda.synchronize()
    if cursor != len(groups) or not np.isfinite(mean_logits).all():
        fail(f"incomplete or non-finite full result for {precision}")
    return mean_logits, {
        "total_seconds": time.perf_counter() - total_started,
        "preprocess_seconds": preprocess_seconds,
        "model_transfer_seconds": model_seconds,
        "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
        "cuda_peak_reserved_bytes": int(torch.cuda.max_memory_reserved()),
    }


def build_benchmark_inputs(
    selection: Any,
    validation_x: np.ndarray,
    groups: np.ndarray,
    benchmark_groups: int,
    groups_per_batch: int,
) -> tuple[np.ndarray, np.ndarray]:
    positions = np.linspace(0, len(groups) - 1, benchmark_groups, dtype=np.int64)
    parts: list[np.ndarray] = []
    for start in range(0, benchmark_groups, groups_per_batch):
        selected_groups = groups[positions[start : start + groups_per_batch]]
        parts.append(
            selection.transform_group_batch(validation_x[selected_groups])[
                "four_window_capture_unit_rms"
            ]
        )
    values = np.concatenate(parts, axis=0)
    if values.shape != (benchmark_groups * GROUP_WINDOWS, 2, 1024):
        fail(f"benchmark input shape changed: {values.shape}")
    return values, positions


def benchmark_once(
    model: Any,
    torch: Any,
    values: np.ndarray,
    precision: str,
    groups_per_batch: int,
) -> tuple[float, float]:
    rows_per_batch = groups_per_batch * GROUP_WINDOWS
    checksum = 0.0
    torch.cuda.synchronize()
    started = time.perf_counter()
    for start in range(0, len(values), rows_per_batch):
        tensor = torch.from_numpy(np.ascontiguousarray(values[start : start + rows_per_batch])).cuda(
            non_blocking=False
        )
        with torch.inference_mode(), precision_context(torch, precision):
            output = model(tensor).float().cpu().numpy()
        if not np.isfinite(output).all():
            fail(f"non-finite benchmark output for {precision}")
        checksum += float(output[0, 0])
    torch.cuda.synchronize()
    return time.perf_counter() - started, checksum


def benchmark_precisions(
    plan: dict[str, Any],
    model: Any,
    torch: Any,
    values: np.ndarray,
) -> dict[str, Any]:
    benchmark = plan["performance_benchmark"]
    observations: dict[str, list[dict[str, float]]] = {precision: [] for precision in PRECISIONS}
    for round_index, order in enumerate(benchmark["orders"], start=1):
        for precision in order:
            seconds, checksum = benchmark_once(
                model,
                torch,
                values,
                precision,
                plan["evaluation"]["groups_per_batch"],
            )
            groups_per_second = benchmark["groups"] / seconds
            observations[precision].append(
                {
                    "round": round_index,
                    "seconds": seconds,
                    "groups_per_second": groups_per_second,
                    "checksum": checksum,
                }
            )
            print(
                f"benchmark round={round_index} precision={precision} groups_per_second={groups_per_second:.3f}",
                flush=True,
            )
    summary: dict[str, Any] = {}
    for precision, rows in observations.items():
        throughput = np.asarray([row["groups_per_second"] for row in rows], dtype=np.float64)
        summary[precision] = {
            "rounds": rows,
            "median_groups_per_second": float(np.median(throughput)),
            "minimum_groups_per_second": float(throughput.min()),
            "maximum_groups_per_second": float(throughput.max()),
        }
    fp32_median = summary["fp32"]["median_groups_per_second"]
    for precision in PRECISIONS:
        summary[precision]["median_throughput_ratio_to_fp32"] = (
            summary[precision]["median_groups_per_second"] / fp32_median
        )
    return summary


def numeric_comparison(
    plan: dict[str, Any],
    fp32_logits: np.ndarray,
    candidate_logits: np.ndarray,
    fp32_metrics: dict[str, Any],
    candidate_metrics: dict[str, Any],
) -> dict[str, Any]:
    gates = plan["numeric_eligibility_gates"]
    logit_difference = np.abs(candidate_logits.astype(np.float64) - fp32_logits.astype(np.float64))
    validator = load_module("rf_precision_softmax_helpers", SELECTION_PATH)
    fp32_probability = validator.softmax(fp32_logits)
    candidate_probability = validator.softmax(candidate_logits)
    probability_difference = np.abs(candidate_probability - fp32_probability)
    agreement = float((np.argmax(candidate_logits, axis=1) == np.argmax(fp32_logits, axis=1)).mean())
    values = {
        "accuracy_delta": candidate_metrics["accuracy"] - fp32_metrics["accuracy"],
        "snr_ge_4_accuracy_delta": (
            candidate_metrics["primary_snr_accuracy"] - fp32_metrics["primary_snr_accuracy"]
        ),
        "nll_delta": (
            candidate_metrics["negative_log_likelihood"] - fp32_metrics["negative_log_likelihood"]
        ),
        "argmax_agreement_with_fp32": agreement,
        "mean_logit_absolute_difference_p99": float(np.quantile(logit_difference, 0.99)),
        "mean_logit_absolute_difference_max": float(logit_difference.max()),
        "probability_absolute_difference_p99": float(np.quantile(probability_difference, 0.99)),
        "probability_absolute_difference_max": float(probability_difference.max()),
    }
    checks = {
        "accuracy": values["accuracy_delta"] >= -gates["validation_accuracy_degradation_max"],
        "snr_ge_4_accuracy": (
            values["snr_ge_4_accuracy_delta"] >= -gates["snr_ge_4_accuracy_degradation_max"]
        ),
        "nll": values["nll_delta"] <= gates["negative_log_likelihood_increase_max"],
        "argmax_agreement": agreement >= gates["argmax_agreement_with_fp32_min"],
        "logit_p99": (
            values["mean_logit_absolute_difference_p99"]
            <= gates["mean_logit_absolute_difference_p99_max"]
        ),
        "logit_max": (
            values["mean_logit_absolute_difference_max"]
            <= gates["mean_logit_absolute_difference_max"]
        ),
        "probability_p99": (
            values["probability_absolute_difference_p99"]
            <= gates["probability_absolute_difference_p99_max"]
        ),
        "probability_max": (
            values["probability_absolute_difference_max"]
            <= gates["probability_absolute_difference_max"]
        ),
    }
    return {**values, "numeric_checks": checks, "numeric_eligible": all(checks.values())}


def choose_precision(
    plan: dict[str, Any],
    comparisons: dict[str, dict[str, Any]],
    full_runs: dict[str, dict[str, Any]],
    benchmark: dict[str, Any],
) -> dict[str, Any]:
    performance = plan["performance_benchmark"]
    fp32_reserved = full_runs["fp32"]["performance"]["cuda_peak_reserved_bytes"]
    qualified: list[str] = []
    decision_rows: dict[str, Any] = {}
    for precision in ("fp16", "bf16"):
        memory_increase = full_runs[precision]["performance"]["cuda_peak_reserved_bytes"] - fp32_reserved
        throughput_ratio = benchmark[precision]["median_throughput_ratio_to_fp32"]
        memory_eligible = memory_increase <= performance["maximum_reserved_memory_increase_bytes"]
        speed_eligible = throughput_ratio >= 1.0 + performance["minimum_median_throughput_gain_over_fp32"]
        eligible = comparisons[precision]["numeric_eligible"] and memory_eligible and speed_eligible
        decision_rows[precision] = {
            "numeric_eligible": comparisons[precision]["numeric_eligible"],
            "memory_increase_bytes": memory_increase,
            "memory_eligible": memory_eligible,
            "median_throughput_ratio_to_fp32": throughput_ratio,
            "speed_eligible": speed_eligible,
            "eligible": eligible,
        }
        if eligible:
            qualified.append(precision)
    if not qualified:
        return {"selected": "fp32", "reason": "no low precision passed every gate", "rows": decision_rows}
    fastest = max(benchmark[name]["median_groups_per_second"] for name in qualified)
    near_fastest = [
        name for name in qualified if benchmark[name]["median_groups_per_second"] >= fastest * 0.95
    ]
    best_agreement = max(comparisons[name]["argmax_agreement_with_fp32"] for name in near_fastest)
    agreement_tied = [
        name
        for name in near_fastest
        if comparisons[name]["argmax_agreement_with_fp32"] >= best_agreement - 0.001
    ]
    selected = "bf16" if "bf16" in agreement_tied else "fp16"
    return {
        "selected": selected,
        "reason": "passed all gates; within 5% of fastest; best agreement within 0.001 tie; BF16 tie preference",
        "qualified": qualified,
        "near_fastest": near_fastest,
        "agreement_tied": agreement_tied,
        "rows": decision_rows,
    }


def execute(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.resolve(strict=False)
    try:
        output.relative_to(TEMPORARY_ROOT)
    except ValueError:
        fail(f"output must be below {TEMPORARY_ROOT}")
    TEMPORARY_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = TEMPORARY_ROOT.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or TEMPORARY_ROOT.resolve(strict=True) != TEMPORARY_ROOT
        or output.exists()
    ):
        fail("temporary root changed or output already exists")
    running = TEMPORARY_ROOT / "RUNNING"
    if running.exists():
        fail("another or interrupted precision run exists")
    running.write_text(f"pid={os.getpid()}\n", encoding="ascii")
    running.chmod(0o600)
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    wall_started = time.perf_counter()

    validator = load_module("rf_precision_checkpoint_validator", VALIDATOR_PATH)
    selection = load_module("rf_precision_preprocess_helpers", SELECTION_PATH)
    plan, candidate, fp32_audit = load_plan(validator)
    delivery = validator.verify_delivery(candidate)
    model, torch, model_summary = validator.verify_checkpoint_and_model(candidate, delivery)
    selection_plan_descriptor = candidate["data"]["selection_plan"]
    selection_plan_path = validator.resolve_repo_file(
        selection_plan_descriptor["path"], selection_plan_descriptor["sha256"]
    )
    selection_plan = selection.read_json(selection_plan_path)
    split_descriptor = candidate["data"]["split"]
    split_path = validator.resolve_regular(
        ASSET_ROOT, split_descriptor["path"], split_descriptor["sha256"], split_descriptor["bytes"]
    )
    train_indices, validation_indices, split_access = selection.load_allowed_indices(
        split_path, selection_plan
    )
    dataset_descriptor = candidate["data"]["dataset"]
    dataset_path = validator.resolve_regular(
        ASSET_ROOT,
        dataset_descriptor["path"],
        dataset_descriptor["sha256"],
        dataset_descriptor["bytes"],
    )
    try:
        import h5py
    except ImportError as error:
        fail(f"h5py unavailable: {error}")
    with h5py.File(dataset_path, "r") as h5_file:
        validation_x, validation_labels, validation_snr, validation_load = selection.load_validation_arrays(
            h5_file, validation_indices, 4096
        )
    groups, excluded, grouping = selection.build_four_window_groups(validation_labels, validation_snr)
    if len(groups) != plan["evaluation"]["groups"] or groups.size != plan["evaluation"]["source_rows"]:
        fail("validation grouping differs from the preregistered population")
    labels = validation_labels[groups[:, 0]]
    snr = validation_snr[groups[:, 0]]

    logits_by_precision: dict[str, np.ndarray] = {}
    full_runs: dict[str, dict[str, Any]] = {}
    for precision in PRECISIONS:
        logits, performance = infer_full_precision(
            model,
            torch,
            selection,
            validation_x,
            groups,
            precision,
            plan["evaluation"]["groups_per_batch"],
            plan["evaluation"]["warmup_batches_per_precision"],
        )
        metrics = selection.classification_metrics(logits, labels, snr)
        logits_by_precision[precision] = logits
        full_runs[precision] = {"metrics": metrics, "performance": performance}

    fp32_reference = fp32_audit["validation"]
    if (
        abs(full_runs["fp32"]["metrics"]["accuracy"] - fp32_reference["accuracy"]) > 0.0001
        or abs(
            full_runs["fp32"]["metrics"]["negative_log_likelihood"]
            - fp32_reference["negative_log_likelihood"]
        )
        > 0.0001
    ):
        fail("FP32 rerun no longer matches the pinned validation baseline")

    comparisons = {
        precision: numeric_comparison(
            plan,
            logits_by_precision["fp32"],
            logits_by_precision[precision],
            full_runs["fp32"]["metrics"],
            full_runs[precision]["metrics"],
        )
        for precision in ("fp16", "bf16")
    }
    benchmark_values, benchmark_positions = build_benchmark_inputs(
        selection,
        validation_x,
        groups,
        plan["performance_benchmark"]["groups"],
        plan["evaluation"]["groups_per_batch"],
    )
    benchmark = benchmark_precisions(plan, model, torch, benchmark_values)
    decision = choose_precision(plan, comparisons, full_runs, benchmark)
    del model, validation_x, benchmark_values, logits_by_precision

    summary = {
        "schema_version": 1,
        "schema_id": "rf_v1_precision_selection_result_v1",
        "status": "pass",
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "implementation": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(Path(__file__).resolve())},
        "plan": {"path": str(PLAN_PATH), "sha256": EXPECTED_PLAN_SHA256},
        "governance": {
            "split_members_loaded": split_access["split_members_loaded"],
            "test_member_loaded": False,
            "test_result_path_opened": False,
            "production_calibration_changed": False,
            "recognizer_available": False,
            "per_group_logits_written": False,
            "raw_iq_written": False,
        },
        "assets": {
            "checkpoint_sha256": candidate["checkpoint"]["sha256"],
            "dataset_sha256": dataset_descriptor["sha256"],
            "dataset_hash_reverified_now": True,
            "split_sha256": split_descriptor["sha256"],
            "candidate_manifest_sha256": plan["pinned_inputs"]["candidate_manifest"]["sha256"],
            "fp32_validation_audit_sha256": plan["pinned_inputs"]["fp32_validation_audit"]["sha256"],
        },
        "model": model_summary,
        "data": {
            "train_indices_verified_not_used_for_updates": int(len(train_indices)),
            "validation_load": validation_load,
            "groups": grouping["complete_groups"],
            "source_rows": grouping["included_rows"],
            "tail_rows_excluded": int(len(excluded)),
        },
        "full_validation": full_runs,
        "numeric_comparisons": comparisons,
        "benchmark": {
            "scope": "precomputed host planar float32 through H2D, model, float32 logits and D2H",
            "groups": plan["performance_benchmark"]["groups"],
            "group_positions_sha256": hashlib.sha256(
                np.asarray(benchmark_positions, dtype="<i8").tobytes()
            ).hexdigest(),
            "results": benchmark,
        },
        "selection": decision,
        "production": {
            "candidate_precision_selected": decision["selected"],
            "precision_selection_complete": True,
            "production_calibration_frozen": False,
            "production_acceptance_threshold_frozen": False,
            "runtime_profile_admitted": False,
            "locked_test_opened": False,
            "recognizer_available": False,
        },
        "performance": {
            "total_wall_seconds": time.perf_counter() - wall_started,
            "process_max_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        },
    }
    payload = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(payload) > MAX_TEMPORARY_BYTES:
        fail("precision summary exceeds temporary byte bound")
    with output.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    output.chmod(0o600)
    running.unlink()
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    os.umask(0o077)
    args = parse_args()
    try:
        summary = execute(args)
    except (PrecisionSelectionError, OSError, KeyError, TypeError, ValueError) as error:
        print(f"precision_selection_error={error}", file=os.sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": summary["status"],
                "selected": summary["selection"]["selected"],
                "test_member_loaded": summary["governance"]["test_member_loaded"],
                "recognizer_available": summary["production"]["recognizer_available"],
                "output": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
