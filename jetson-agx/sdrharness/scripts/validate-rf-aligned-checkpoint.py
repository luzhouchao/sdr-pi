#!/usr/bin/env python3
"""Validate the selected RF-aligned D8 checkpoint on RML2018A validation only."""

from __future__ import annotations

import argparse
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
MANIFEST_PATH = (
    REPO_ROOT
    / "jetson-agx"
    / "sdrharness"
    / "config"
    / "amc"
    / "rml2018a-d8-rf-v1-ft-batched-seed44.candidate.json"
)
SELECTION_SCRIPT = (
    REPO_ROOT / "jetson-agx" / "sdrharness" / "scripts" / "select-rf-preprocess-validation.py"
)
EVALUATOR_SCRIPT = REPO_ROOT / "jetson-agx" / "sdrharness" / "scripts" / "evaluate-amc-mamba.py"
TEMPORARY_ROOT = Path("/var/tmp/sdrharness-dev/rf-v1-checkpoint-agx-validation-20260905")
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
NUM_CLASSES = 24
GROUP_WINDOWS = 4
WINDOW_SAMPLES = 1024


class ValidationError(Exception):
    """Fail-closed checkpoint validation error."""


def fail(message: str) -> None:
    raise ValidationError(message)


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


def resolve_regular(root: Path, relative: str, expected_hash: str, expected_bytes: int | None = None) -> Path:
    candidate = root / relative
    try:
        metadata = candidate.lstat()
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        fail(f"invalid asset path {relative}: {error}")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        fail(f"asset must be a non-symlink regular file: {relative}")
    if expected_bytes is not None and resolved.stat().st_size != expected_bytes:
        fail(f"asset byte mismatch for {relative}")
    actual = sha256_file(resolved)
    if actual != expected_hash:
        fail(f"asset SHA-256 mismatch for {relative}: {actual}")
    return resolved


def resolve_repo_file(relative: str, expected_hash: str) -> Path:
    return resolve_regular(REPO_ROOT, relative, expected_hash)


def strict_json(path: Path) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite constant {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            path.read_text(encoding="utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        fail(f"invalid JSON {path}: {error}")


def load_manifest() -> dict[str, Any]:
    manifest = strict_json(MANIFEST_PATH)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("schema_id") != "rf_aligned_checkpoint_candidate_v1"
        or manifest.get("status") != "candidate_validation_only"
        or manifest.get("production_enabled") is not False
        or manifest.get("recognizer_available") is not False
    ):
        fail("candidate manifest identity or fail-closed status changed")
    data = manifest.get("data", {})
    if data.get("allowed_split_members") != ["train", "val"]:
        fail("only train and val may be allowed")
    if data.get("forbidden_split_members") != ["test"]:
        fail("test must remain explicitly forbidden")
    if manifest.get("training", {}).get("test_loader_enabled") is not False:
        fail("training delivery did not keep the test loader disabled")
    return manifest


def verify_delivery(manifest: dict[str, Any]) -> dict[str, Any]:
    assets: dict[str, Any] = {}
    for name in (
        "training_result",
        "completion_hashes",
        "selected_checkpoint",
        "input_hashes",
        "training_config",
        "numeric_labels",
        "training_script",
        "smoke_script",
        "launch_script",
        "training_status",
    ):
        descriptor = manifest["delivery"][name]
        path = resolve_regular(ASSET_ROOT, descriptor["path"], descriptor["sha256"])
        assets[name] = {"path": str(path), "bytes": path.stat().st_size, "sha256": descriptor["sha256"]}

    training_result = strict_json(Path(assets["training_result"]["path"]))
    selected = strict_json(Path(assets["selected_checkpoint"]["path"]))
    training_config = strict_json(Path(assets["training_config"]["path"]))
    labels = strict_json(Path(assets["numeric_labels"]["path"]))
    provenance = strict_json(Path(assets["input_hashes"]["path"]))
    expected = manifest["training"]
    if (
        training_result.get("status") != "completed"
        or training_result.get("test_loader_enabled") is not False
        or training_result.get("production_enabled") is not False
        or training_result.get("checkpoint_sha256") != manifest["checkpoint"]["sha256"]
        or training_result.get("selected", {}).get("epoch") != expected["selected_epoch"]
        or selected.get("checkpoint_sha256") != manifest["checkpoint"]["sha256"]
        or selected.get("test_loader_enabled") is not False
        or selected.get("production_enabled") is not False
    ):
        fail("training result or selected-checkpoint delivery identity changed")
    if training_config.get("test_enabled") is not False or training_config.get("preprocess_id") != "rf_preprocess_v1":
        fail("training config no longer pins validation-only rf_preprocess_v1")
    if labels != {"numeric_class_ids": list(range(NUM_CLASSES)), "display_names": "provisional_not_used"}:
        fail("numeric label identity changed")
    if not isinstance(provenance, dict) or len(provenance) != 147:
        fail("expected the complete 147-entry training provenance map")
    assets["training_result_parsed"] = training_result
    assets["training_config_parsed"] = training_config
    assets["provenance_parsed"] = provenance
    return assets


def verify_checkpoint_and_model(manifest: dict[str, Any], delivery: dict[str, Any]):
    evaluator = load_module("rf_aligned_agx_evaluator", EVALUATOR_SCRIPT)
    try:
        import torch
    except ImportError as error:
        fail(f"PyTorch unavailable: {error}")

    checkpoint_descriptor = manifest["checkpoint"]
    checkpoint_path = resolve_regular(
        ASSET_ROOT,
        checkpoint_descriptor["path"],
        checkpoint_descriptor["sha256"],
        checkpoint_descriptor["bytes"],
    )
    source_descriptor = manifest["model"]["source_identity_manifest"]
    source_manifest_path = resolve_repo_file(source_descriptor["path"], source_descriptor["sha256"])
    source_manifest = strict_json(source_manifest_path)
    source_root = ASSET_ROOT / "model-source" / manifest["model"]["model_source_commit"]
    source_assets = evaluator.verify_model_source(source_root)
    if source_manifest.get("model_source_commit") != manifest["model"]["model_source_commit"]:
        fail("source manifest commit changed")
    source_hashes = {item["relative_path"]: item["sha256"] for item in source_assets}
    if source_hashes != source_manifest.get("model_source_files"):
        fail("AGX inference-source hashes differ from the pinned source manifest")

    architecture_descriptor = manifest["model"]["architecture_config"]
    architecture_path = resolve_regular(
        ASSET_ROOT, architecture_descriptor["path"], architecture_descriptor["sha256"]
    )
    architecture = strict_json(architecture_path)
    model_config = architecture["resolved_config"]["model"]
    model_class = evaluator.load_model_class(source_root)
    fields = (
        "d_model",
        "dropout",
        "use_real_mamba",
        "mamba_d_state",
        "mamba_d_conv",
        "mamba_expand",
        "mamba_headdim",
    )
    model = model_class(
        model_variant=manifest["model"]["variant"],
        num_classes=NUM_CLASSES,
        **{name: model_config[name] for name in fields},
    )
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if (
        checkpoint.get("selected_model_class") != manifest["model"]["class"]
        or checkpoint.get("selected_model_variant") != manifest["model"]["variant"]
        or checkpoint.get("model_backend") != manifest["model"]["backend"]
        or checkpoint.get("epoch") != manifest["training"]["selected_epoch"]
        or checkpoint.get("config") != delivery["training_config_parsed"]
        or checkpoint.get("provenance") != delivery["provenance_parsed"]
    ):
        fail("checkpoint envelope, config or complete provenance map changed")
    model.load_state_dict(checkpoint["model_state"], strict=True)
    parameters = sum(parameter.numel() for parameter in model.parameters())
    if parameters != manifest["model"]["parameters"]:
        fail(f"model parameter count changed: {parameters}")
    if model.encoder.backend != manifest["model"]["backend"] or not model.encoder.real_mamba_available():
        fail(f"real Mamba backend unavailable: {model.encoder.backend}")
    if not torch.cuda.is_available():
        fail("CUDA is unavailable")
    torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    torch.set_grad_enabled(False)
    model = model.eval().float().cuda()
    return model, torch, {
        "checkpoint": {
            "path": str(checkpoint_path),
            "bytes": checkpoint_path.stat().st_size,
            "sha256": checkpoint_descriptor["sha256"],
        },
        "strict_state_dict_load": True,
        "checkpoint_config_exact": True,
        "checkpoint_provenance_entries": len(checkpoint["provenance"]),
        "source_files_verified": len(source_assets),
        "source_commit": manifest["model"]["model_source_commit"],
        "parameters": parameters,
        "backend": model.encoder.backend,
        "precision": "fp32",
        "cuda_device": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
    }


def infer_validation(
    model: Any,
    torch: Any,
    selection: Any,
    validation_x: np.ndarray,
    validation_labels: np.ndarray,
    validation_snr: np.ndarray,
    validation_indices: np.ndarray,
    groups: np.ndarray,
    groups_per_batch: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    group_count = len(groups)
    mean_logits = np.empty((group_count, NUM_CLASSES), dtype=np.float32)
    agreement = np.empty(group_count, dtype=np.float32)
    labels = validation_labels[groups[:, 0]]
    snr = validation_snr[groups[:, 0]]
    first_rows = validation_indices[groups[:, 0]]
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    cursor = 0
    batch_count = math.ceil(group_count / groups_per_batch)
    for batch_number, start in enumerate(range(0, group_count, groups_per_batch), start=1):
        batch_groups = groups[start : start + groups_per_batch]
        transformed = selection.transform_group_batch(validation_x[batch_groups])[
            "four_window_capture_unit_rms"
        ]
        with torch.inference_mode():
            logits = model(torch.from_numpy(transformed).cuda(non_blocking=False)).float().cpu().numpy()
        if logits.shape != (len(batch_groups) * GROUP_WINDOWS, NUM_CLASSES) or not np.isfinite(logits).all():
            fail(f"non-finite or malformed logits in batch {batch_number}")
        grouped = logits.reshape(-1, GROUP_WINDOWS, NUM_CLASSES)
        next_cursor = cursor + len(batch_groups)
        mean_logits[cursor:next_cursor] = grouped.mean(axis=1, dtype=np.float64)
        top1 = np.argmax(grouped, axis=2)
        for local_index, row in enumerate(top1):
            counts = np.bincount(row, minlength=NUM_CLASSES)
            agreement[cursor + local_index] = float(counts.max() / GROUP_WINDOWS)
        cursor = next_cursor
        if batch_number % 100 == 0 or batch_number == batch_count:
            print(
                f"validation batches={batch_number}/{batch_count} groups={cursor}/{group_count}",
                flush=True,
            )
    torch.cuda.synchronize()
    metrics = selection.classification_metrics(mean_logits, labels, snr)

    fit_mask = np.asarray(
        [
            hashlib.sha256(f"rf-v1-final-calibration-candidate:{int(row)}".encode()).digest()[0] & 1 == 0
            for row in first_rows
        ],
        dtype=bool,
    )
    temperature, fit_nll = selection.fit_scalar_temperature(
        mean_logits[fit_mask], labels[fit_mask], 1, "mean_logit"
    )
    identity = selection.softmax(mean_logits[~fit_mask])
    calibrated = selection.softmax(mean_logits[~fit_mask], temperature)
    audit_labels = labels[~fit_mask]
    calibration = {
        "status": "validation_candidate_only_not_production",
        "partition": "sha256(rf-v1-final-calibration-candidate:first-global-row) low bit",
        "fit_groups": int(fit_mask.sum()),
        "audit_groups": int((~fit_mask).sum()),
        "temperature": temperature,
        "fit_nll": fit_nll,
        "audit_identity_nll": selection.negative_log_likelihood(identity, audit_labels),
        "audit_calibrated_nll": selection.negative_log_likelihood(calibrated, audit_labels),
        "audit_identity_ece_15_bin": selection.expected_calibration_error(identity, audit_labels, 15),
        "audit_calibrated_ece_15_bin": selection.expected_calibration_error(calibrated, audit_labels, 15),
        "production_temperature_frozen": False,
        "production_acceptance_threshold_frozen": False,
        "blocker": "Independently labeled known-RF/OOD evidence is absent.",
    }
    agreement_summary = {
        "mean": float(agreement.mean()),
        "p01": float(np.quantile(agreement, 0.01)),
        "p50": float(np.quantile(agreement, 0.50)),
        "p95": float(np.quantile(agreement, 0.95)),
        "all_four_equal_fraction": float((agreement == 1.0).mean()),
        "production_threshold": None,
    }
    performance = {
        "elapsed_seconds": time.perf_counter() - started,
        "groups_per_batch": groups_per_batch,
        "groups": group_count,
        "source_rows": int(groups.size),
        "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
        "cuda_peak_reserved_bytes": int(torch.cuda.max_memory_reserved()),
    }
    return metrics, calibration, {"agreement": agreement_summary, "performance": performance}


def parity_report(manifest: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    reference_accuracy = float(manifest["training"]["reference_validation_accuracy"])
    reference_nll = float(manifest["training"]["reference_validation_nll"])
    accuracy_delta = metrics["accuracy"] - reference_accuracy
    nll_delta = metrics["negative_log_likelihood"] - reference_nll
    accuracy_tolerance = float(manifest["agx_validation"]["accuracy_absolute_tolerance"])
    nll_tolerance = float(manifest["agx_validation"]["nll_absolute_tolerance"])
    if abs(accuracy_delta) > accuracy_tolerance:
        fail(f"AGX/4090 validation accuracy delta {accuracy_delta} exceeds {accuracy_tolerance}")
    if abs(nll_delta) > nll_tolerance:
        fail(f"AGX/4090 validation NLL delta {nll_delta} exceeds {nll_tolerance}")
    return {
        "status": "pass",
        "reference_accuracy": reference_accuracy,
        "agx_accuracy": metrics["accuracy"],
        "accuracy_delta": accuracy_delta,
        "accuracy_absolute_tolerance": accuracy_tolerance,
        "reference_nll": reference_nll,
        "agx_nll": metrics["negative_log_likelihood"],
        "nll_delta": nll_delta,
        "nll_absolute_tolerance": nll_tolerance,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--groups-per-batch", type=int, default=64)
    return parser.parse_args()


def execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.groups_per_batch <= 0 or args.groups_per_batch > 256:
        fail("groups-per-batch must be in [1, 256]")
    output = args.output.resolve(strict=False)
    try:
        output.relative_to(TEMPORARY_ROOT)
    except ValueError:
        fail(f"output must be below {TEMPORARY_ROOT}")
    TEMPORARY_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = TEMPORARY_ROOT.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        fail("temporary root must be a non-symlink directory")
    if TEMPORARY_ROOT.resolve(strict=True) != TEMPORARY_ROOT or output.exists():
        fail("temporary root changed or output already exists")
    running = TEMPORARY_ROOT / "RUNNING"
    if running.exists():
        fail("another or interrupted validation run exists")
    running.write_text(f"pid={os.getpid()}\n", encoding="ascii")
    running.chmod(0o600)
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    wall_started = time.perf_counter()

    manifest = load_manifest()
    delivery = verify_delivery(manifest)
    selection = load_module("rf_aligned_validation_selection_helpers", SELECTION_SCRIPT)
    plan_descriptor = manifest["data"]["selection_plan"]
    plan_path = resolve_repo_file(plan_descriptor["path"], plan_descriptor["sha256"])
    plan = selection.read_json(plan_path)
    split_descriptor = manifest["data"]["split"]
    split_path = resolve_regular(
        ASSET_ROOT, split_descriptor["path"], split_descriptor["sha256"], split_descriptor["bytes"]
    )
    train_indices, validation_indices, split_access = selection.load_allowed_indices(split_path, plan)
    dataset_descriptor = manifest["data"]["dataset"]
    dataset_path = resolve_regular(
        ASSET_ROOT,
        dataset_descriptor["path"],
        dataset_descriptor["sha256"],
        dataset_descriptor["bytes"],
    )
    preprocess_descriptor = manifest["preprocess"]
    resolve_repo_file(preprocess_descriptor["path"], preprocess_descriptor["sha256"])

    try:
        import h5py
    except ImportError as error:
        fail(f"h5py unavailable: {error}")
    with h5py.File(dataset_path, "r") as h5_file:
        validation_x, validation_labels, validation_snr, validation_load = selection.load_validation_arrays(
            h5_file, validation_indices, 4096
        )
    groups, excluded, grouping = selection.build_four_window_groups(validation_labels, validation_snr)
    if (
        len(groups) != manifest["agx_validation"]["complete_groups_required"]
        or groups.size != manifest["agx_validation"]["source_rows_required"]
    ):
        fail("complete validation grouping differs from the pinned delivery")

    model, torch, model_summary = verify_checkpoint_and_model(manifest, delivery)
    metrics, calibration, inference = infer_validation(
        model,
        torch,
        selection,
        validation_x,
        validation_labels,
        validation_snr,
        validation_indices,
        groups,
        args.groups_per_batch,
    )
    parity = parity_report(manifest, metrics)
    del model, validation_x
    summary = {
        "schema_version": 1,
        "schema_id": "rf_aligned_checkpoint_agx_validation_v1",
        "status": "pass",
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "manifest": {"path": str(MANIFEST_PATH), "sha256": sha256_file(MANIFEST_PATH)},
        "governance": {
            "split_members_loaded": split_access["split_members_loaded"],
            "test_member_loaded": False,
            "test_result_path_opened": False,
            "production_enabled": False,
            "recognizer_available": False,
            "raw_iq_written": False,
        },
        "assets": {
            "dataset": {
                "path": str(dataset_path),
                "bytes": dataset_path.stat().st_size,
                "sha256": dataset_descriptor["sha256"],
                "hash_reverified_now": True,
            },
            "split": {
                "path": str(split_path),
                "bytes": split_path.stat().st_size,
                "sha256": split_descriptor["sha256"],
            },
            "delivery": {name: value for name, value in delivery.items() if not name.endswith("_parsed")},
        },
        "model": model_summary,
        "data": {
            "train_indices_verified_not_used_for_updates": int(len(train_indices)),
            "validation_load": validation_load,
            "grouping": {
                "complete_groups": grouping["complete_groups"],
                "included_rows": grouping["included_rows"],
                "tail_rows_excluded": int(len(excluded)),
            },
        },
        "validation_metrics": metrics,
        "agx_4090_parity": parity,
        "calibration_candidate": calibration,
        "window_agreement": inference["agreement"],
        "performance": {
            **inference["performance"],
            "total_wall_seconds": time.perf_counter() - wall_started,
            "process_max_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        },
        "production": {
            "checkpoint_agx_fp32_validation_passed": True,
            "production_calibration_frozen": False,
            "production_acceptance_threshold_frozen": False,
            "precision_selected": False,
            "runtime_profile_admitted": False,
            "locked_test_opened": False,
            "recognizer_available": False,
        },
    }
    payload = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(payload) > MAX_OUTPUT_BYTES:
        fail("validation summary exceeds output bound")
    with output.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    output.chmod(0o600)
    running.unlink()
    return summary


def main() -> int:
    os.umask(0o077)
    args = parse_args()
    try:
        summary = execute(args)
    except (ValidationError, OSError, KeyError, TypeError, ValueError) as error:
        print(f"validation_error={error}", file=os.sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": summary["status"],
                "accuracy": summary["validation_metrics"]["accuracy"],
                "nll": summary["validation_metrics"]["negative_log_likelihood"],
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
