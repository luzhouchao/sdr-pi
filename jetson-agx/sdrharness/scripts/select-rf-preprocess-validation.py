#!/usr/bin/env python3
"""Run the preregistered RML2018A RF-preprocessing study on train/validation only."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import math
import os
import platform
import resource
import stat
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = (
    REPO_ROOT
    / "jetson-agx"
    / "sdrharness"
    / "config"
    / "amc"
    / "rf-preprocess-v1-selection-plan.json"
)
EXPECTED_PLAN_SHA256 = "52320186d17dbd2dade4c8452c0538ea8d3b7a6a55c1caed199fa35d323842bc"
EVALUATOR_PATH = REPO_ROOT / "jetson-agx" / "sdrharness" / "scripts" / "evaluate-amc-mamba.py"
TEMPORARY_ROOT = Path("/var/tmp/sdrharness-dev/rf-preprocess-v1-selection-20260905")
MAX_TEMPORARY_BYTES = 512 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MIN_AVAILABLE_MEMORY_BYTES = 12 * 1024 * 1024 * 1024
NUM_SAMPLES = 2_555_904
NUM_CLASSES = 24
WINDOW_SAMPLES = 1024
GROUP_WINDOWS = 4
TRANSFORM_IDS = (
    "raw_identity",
    "per_window_unit_rms",
    "per_window_dc_unit_rms",
    "four_window_capture_unit_rms",
    "four_window_capture_dc_unit_rms",
)
RF_TRANSFORM_IDS = TRANSFORM_IDS[1:]
ALLOWED_SPLIT_MEMBERS = {"train", "val"}
METADATA_MEMBERS = {"num_samples", "train_ratio", "val_ratio", "test_ratio", "seed"}
EXPECTED_ARCHIVE_MEMBERS = {
    "train.npy",
    "val.npy",
    "test.npy",
    "num_samples.npy",
    "train_ratio.npy",
    "val_ratio.npy",
    "test_ratio.npy",
    "seed.npy",
}
class SelectionError(Exception):
    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(f"{code}: {path}: {message}")
        self.code = code
        self.path = path
        self.message = message


def fail(code: str, path: str, message: str) -> None:
    raise SelectionError(code, path, message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        fail("file", str(path), str(error))
    return digest.hexdigest()


def strict_json_bytes(payload: bytes, path: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        fail("json", path, str(error))


def read_json(path: Path, maximum_bytes: int = MAX_JSON_BYTES) -> Any:
    try:
        metadata = path.lstat()
    except OSError as error:
        fail("file", str(path), str(error))
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        fail("file", str(path), "must be a non-symlink regular file")
    if not 0 < metadata.st_size <= maximum_bytes:
        fail("file", str(path), f"size must be in [1, {maximum_bytes}]")
    try:
        return strict_json_bytes(path.read_bytes(), str(path))
    except OSError as error:
        fail("file", str(path), str(error))


def resolve_regular(path_text: str, field: str) -> Path:
    path = Path(path_text)
    lexical = path if path.is_absolute() else REPO_ROOT / path
    try:
        metadata = lexical.lstat()
        resolved = lexical.resolve(strict=True)
    except OSError as error:
        fail("path", field, str(error))
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        fail("path", field, "must resolve to a non-symlink regular file")
    if not path.is_absolute():
        try:
            resolved.relative_to(REPO_ROOT)
        except ValueError:
            fail("path", field, "repository-relative asset escaped the repository")
    return resolved


def verify_hash(path: Path, expected: str, field: str, expected_bytes: int | None = None) -> dict[str, Any]:
    if expected_bytes is not None and path.stat().st_size != expected_bytes:
        fail("asset", field, f"expected {expected_bytes} bytes, got {path.stat().st_size}")
    actual = sha256_file(path)
    if actual != expected:
        fail("asset", field, f"expected SHA-256 {expected}, got {actual}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": actual}


def load_plan() -> tuple[dict[str, Any], dict[str, Any]]:
    plan_asset = verify_hash(PLAN_PATH, EXPECTED_PLAN_SHA256, "selection_plan")
    plan = read_json(PLAN_PATH)
    if (
        not isinstance(plan, dict)
        or plan.get("schema_version") != 1
        or plan.get("schema_id") != "rf_preprocess_selection_plan_v1"
        or plan.get("status") != "preregistered"
    ):
        fail("plan", str(PLAN_PATH), "unexpected schema identity or status")
    access = plan.get("data_access")
    if not isinstance(access, dict) or set(access.get("allowed_split_members", [])) != ALLOWED_SPLIT_MEMBERS:
        fail("plan", "data_access.allowed_split_members", "must contain only train and val")
    if access.get("forbidden_split_members") != ["test"]:
        fail("plan", "data_access.forbidden_split_members", "test must remain forbidden")
    candidates = plan.get("transform_candidates")
    if not isinstance(candidates, list) or tuple(item.get("id") for item in candidates) != TRANSFORM_IDS:
        fail("plan", "transform_candidates", "candidate IDs or order changed")
    if plan.get("resource_and_cleanup", {}).get("maximum_temporary_bytes") != MAX_TEMPORARY_BYTES:
        fail("plan", "resource_and_cleanup.maximum_temporary_bytes", "temporary bound changed")
    return plan, plan_asset


def read_npz_member(path: Path, member: str, access_log: list[str]) -> np.ndarray:
    if member == "test" or member not in ALLOWED_SPLIT_MEMBERS | METADATA_MEMBERS:
        fail("test_lock", f"split.{member}", "the selection process may not read this NPZ member")
    archive_name = f"{member}.npy"
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = {entry.filename for entry in archive.infolist()}
            if names != EXPECTED_ARCHIVE_MEMBERS:
                fail("split", str(path), f"unexpected archive members {sorted(names)}")
            payload = archive.read(archive_name)
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        fail("split", f"{path}:{archive_name}", str(error))
    try:
        array = np.load(io.BytesIO(payload), allow_pickle=False)
    except (OSError, ValueError) as error:
        fail("split", f"{path}:{archive_name}", str(error))
    access_log.append(member)
    return np.asarray(array)


def load_allowed_indices(
    split_path: Path, plan: dict[str, Any]
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    access_log: list[str] = []
    metadata = {
        name: read_npz_member(split_path, name, access_log)
        for name in ("num_samples", "train_ratio", "val_ratio", "test_ratio", "seed")
    }
    expected_scalars = {
        "num_samples": NUM_SAMPLES,
        "train_ratio": 0.7,
        "val_ratio": 0.15,
        "test_ratio": 0.15,
        "seed": 44,
    }
    for name, expected in expected_scalars.items():
        array = metadata[name]
        if array.shape != (1,) or not math.isclose(float(array[0]), float(expected), rel_tol=0.0, abs_tol=1e-12):
            fail("split", f"metadata.{name}", f"expected scalar {expected}, got {array!r}")
    train = read_npz_member(split_path, "train", access_log)
    validation = read_npz_member(split_path, "val", access_log)
    expected_hashes = plan["data_access"]["allowed_split_member_sha256"]
    for name, indices, count, expected_hash in (
        ("train", train, 1_789_132, expected_hashes["train_le_i64"]),
        ("val", validation, 383_385, expected_hashes["val_le_i64"]),
    ):
        if indices.dtype != np.dtype("int64") or indices.shape != (count,):
            fail("split", name, f"expected int64[{count}], got {indices.dtype}{indices.shape}")
        if int(indices[0]) < 0 or int(indices[-1]) >= NUM_SAMPLES or np.any(indices[1:] <= indices[:-1]):
            fail("split", name, "indices must be sorted, unique and in range")
        digest = hashlib.sha256(np.asarray(indices, dtype="<i8").tobytes()).hexdigest()
        if digest != expected_hash:
            fail("split", name, f"membership hash mismatch: {digest}")
    occupancy = np.zeros(NUM_SAMPLES, dtype=np.uint8)
    occupancy[train] = 1
    if np.any(occupancy[validation] != 0):
        fail("split_leak", "train/val", "a validation source row also appears in train")
    return train, validation, {
        "archive_members_listed": sorted(EXPECTED_ARCHIVE_MEMBERS),
        "members_loaded_in_order": access_log,
        "split_members_loaded": [name for name in access_log if name in ALLOWED_SPLIT_MEMBERS],
        "test_member_loaded": False,
        "train_count": int(train.size),
        "validation_count": int(validation.size),
        "train_validation_intersection_count": 0,
        "train_indices_le_i64_sha256": expected_hashes["train_le_i64"],
        "validation_indices_le_i64_sha256": expected_hashes["val_le_i64"],
    }


def available_memory_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError) as error:
        fail("memory", "/proc/meminfo", str(error))
    fail("memory", "/proc/meminfo", "MemAvailable is absent")


def free_space_bytes(path: Path) -> int:
    stats = os.statvfs(path)
    return stats.f_bavail * stats.f_frsize


def quantile_summary(values: np.ndarray) -> dict[str, float]:
    quantiles = (0.0, 0.01, 0.05, 0.5, 0.95, 0.99, 1.0)
    result = np.quantile(values.astype(np.float64, copy=False), quantiles)
    return {f"p{int(q * 100):02d}": float(value) for q, value in zip(quantiles, result)}


def selected_block_ranges(indices: np.ndarray, block_rows: int) -> Iterator[tuple[int, int, np.ndarray]]:
    cursor = 0
    while cursor < len(indices):
        block_start = (int(indices[cursor]) // block_rows) * block_rows
        block_end = min(block_start + block_rows, NUM_SAMPLES)
        end_cursor = int(np.searchsorted(indices, block_end, side="left"))
        yield block_start, block_end, indices[cursor:end_cursor] - block_start
        cursor = end_cursor


def to_planar(raw: np.ndarray) -> np.ndarray:
    if raw.ndim != 3 or raw.shape[1:] != (WINDOW_SAMPLES, 2):
        fail("dataset", "X", f"unexpected selected shape {raw.shape}")
    return np.ascontiguousarray(raw.transpose(0, 2, 1), dtype=np.float32)


def labels_from_one_hot(raw: np.ndarray) -> np.ndarray:
    if raw.ndim != 2 or raw.shape[1] != NUM_CLASSES:
        fail("dataset", "Y", f"unexpected selected shape {raw.shape}")
    labels = np.argmax(raw, axis=1).astype(np.int64, copy=False)
    if np.any(raw.sum(axis=1) != 1) or int(labels.min()) < 0 or int(labels.max()) >= NUM_CLASSES:
        fail("dataset", "Y", "labels are not valid one-hot rows")
    return labels


def scan_train_statistics(h5_file: Any, train_indices: np.ndarray, block_rows: int) -> dict[str, Any]:
    rms = np.empty(len(train_indices), dtype=np.float32)
    dc_fraction = np.empty(len(train_indices), dtype=np.float32)
    snr_values = np.empty(len(train_indices), dtype=np.float32)
    cursor = 0
    started = time.perf_counter()
    for block_index, (start, end, relative) in enumerate(selected_block_ranges(train_indices, block_rows)):
        x = to_planar(np.asarray(h5_file["X"][start:end])[relative])
        snr = np.asarray(h5_file["Z"][start:end])[relative].reshape(-1).astype(np.float32, copy=False)
        power = np.mean(np.square(x, dtype=np.float64), axis=(1, 2)) * 2.0
        row_rms = np.sqrt(power)
        means = x.mean(axis=2, dtype=np.float64)
        row_dc = np.linalg.norm(means, axis=1) / np.maximum(row_rms, 1e-30)
        next_cursor = cursor + len(relative)
        rms[cursor:next_cursor] = row_rms
        dc_fraction[cursor:next_cursor] = row_dc
        snr_values[cursor:next_cursor] = snr
        cursor = next_cursor
        if block_index and block_index % 100 == 0:
            print(f"train_stats rows={cursor}/{len(train_indices)}", flush=True)
    if cursor != len(train_indices) or not np.isfinite(rms).all() or np.any(rms <= 0):
        fail("dataset", "train", "statistics scan was incomplete or non-finite")
    per_snr: dict[str, Any] = {}
    for snr in np.unique(snr_values):
        mask = snr_values == snr
        per_snr[str(int(snr))] = {
            "count": int(mask.sum()),
            "complex_rms_p50": float(np.median(rms[mask])),
            "dc_fraction_p50": float(np.median(dc_fraction[mask])),
        }
    return {
        "rows": len(train_indices),
        "elapsed_seconds": time.perf_counter() - started,
        "complex_rms": quantile_summary(rms),
        "dc_fraction": quantile_summary(dc_fraction),
        "per_snr": per_snr,
    }


def load_validation_arrays(
    h5_file: Any, validation_indices: np.ndarray, block_rows: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    required_bytes = len(validation_indices) * WINDOW_SAMPLES * 2 * 4
    memory_before = available_memory_bytes()
    if memory_before < max(MIN_AVAILABLE_MEMORY_BYTES, required_bytes * 3):
        fail(
            "memory",
            "validation",
            f"need at least {max(MIN_AVAILABLE_MEMORY_BYTES, required_bytes * 3)} available bytes, got {memory_before}",
        )
    x = np.empty((len(validation_indices), 2, WINDOW_SAMPLES), dtype=np.float32)
    labels = np.empty(len(validation_indices), dtype=np.int64)
    snr = np.empty(len(validation_indices), dtype=np.float32)
    cursor = 0
    started = time.perf_counter()
    for block_index, (start, end, relative) in enumerate(selected_block_ranges(validation_indices, block_rows)):
        count = len(relative)
        next_cursor = cursor + count
        x[cursor:next_cursor] = to_planar(np.asarray(h5_file["X"][start:end])[relative])
        labels[cursor:next_cursor] = labels_from_one_hot(np.asarray(h5_file["Y"][start:end])[relative])
        snr[cursor:next_cursor] = (
            np.asarray(h5_file["Z"][start:end])[relative].reshape(-1).astype(np.float32, copy=False)
        )
        cursor = next_cursor
        if block_index and block_index % 100 == 0:
            print(f"validation_load rows={cursor}/{len(validation_indices)}", flush=True)
    if cursor != len(validation_indices) or not np.isfinite(x).all() or not np.isfinite(snr).all():
        fail("dataset", "validation", "validation load was incomplete or non-finite")
    return x, labels, snr, {
        "selected_rows": cursor,
        "selected_iq_bytes_in_memory": x.nbytes,
        "elapsed_seconds": time.perf_counter() - started,
        "memory_available_before_bytes": memory_before,
        "memory_available_after_bytes": available_memory_bytes(),
    }


def build_four_window_groups(labels: np.ndarray, snr: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if labels.shape != snr.shape or labels.ndim != 1:
        fail("grouping", "labels/snr", "must be aligned one-dimensional arrays")
    buckets: dict[tuple[int, float], list[int]] = {}
    for position, (label, level) in enumerate(zip(labels.tolist(), snr.tolist())):
        buckets.setdefault((int(label), float(level)), []).append(position)
    groups: list[list[int]] = []
    excluded: list[int] = []
    bucket_summary: dict[str, Any] = {}
    for key, positions in sorted(buckets.items()):
        complete = len(positions) - (len(positions) % GROUP_WINDOWS)
        for cursor in range(0, complete, GROUP_WINDOWS):
            groups.append(positions[cursor : cursor + GROUP_WINDOWS])
        excluded.extend(positions[complete:])
        bucket_summary[f"class-{key[0]:02d}-snr-{int(key[1]):+03d}"] = {
            "rows": len(positions),
            "complete_groups": complete // GROUP_WINDOWS,
            "tail_rows_excluded": len(positions) - complete,
        }
    group_array = np.asarray(groups, dtype=np.int64)
    excluded_array = np.asarray(sorted(excluded), dtype=np.int64)
    if group_array.ndim != 2 or group_array.shape[1] != GROUP_WINDOWS:
        fail("grouping", "validation", "no complete four-window groups")
    flat = group_array.reshape(-1)
    if len(np.unique(flat)) != len(flat) or np.intersect1d(flat, excluded_array).size:
        fail("grouping", "validation", "group rows are duplicated or overlap excluded tails")
    for group in group_array:
        if len(set(labels[group].tolist())) != 1 or len(set(snr[group].tolist())) != 1:
            fail("grouping", "validation", "a pseudo session crosses class or SNR")
    return group_array, excluded_array, {
        "strategy": "same numeric class and nominal SNR ordered by immutable validation global row",
        "group_windows": GROUP_WINDOWS,
        "complete_groups": int(len(group_array)),
        "included_rows": int(flat.size),
        "tail_rows_excluded": int(excluded_array.size),
        "bucket_count": len(buckets),
        "buckets": bucket_summary,
    }


def transform_group_batch(raw_groups: np.ndarray) -> dict[str, np.ndarray]:
    if raw_groups.ndim != 4 or raw_groups.shape[1:] != (GROUP_WINDOWS, 2, WINDOW_SAMPLES):
        fail("transform", "raw_groups", f"unexpected shape {raw_groups.shape}")
    raw = np.ascontiguousarray(raw_groups.reshape(-1, 2, WINDOW_SAMPLES), dtype=np.float32)
    power = np.mean(np.square(raw, dtype=np.float64), axis=(1, 2)) * 2.0
    rms = np.sqrt(power)
    if not np.isfinite(rms).all() or np.any(rms <= 0):
        fail("transform", "raw_groups", "zero or non-finite RMS")
    per_window = np.ascontiguousarray(raw / rms[:, None, None], dtype=np.float32)
    centered = np.ascontiguousarray(raw - raw.mean(axis=2, keepdims=True, dtype=np.float64), dtype=np.float32)
    centered_power = np.mean(np.square(centered, dtype=np.float64), axis=(1, 2)) * 2.0
    centered_rms = np.sqrt(centered_power)
    if np.any(centered_rms <= 0) or not np.isfinite(centered_rms).all():
        fail("transform", "centered_groups", "DC removal produced zero or non-finite RMS")
    per_window_dc = np.ascontiguousarray(centered / centered_rms[:, None, None], dtype=np.float32)

    capture_raw = raw.reshape(-1, GROUP_WINDOWS, 2, WINDOW_SAMPLES)
    capture_rms = np.sqrt(np.mean(np.square(capture_raw, dtype=np.float64), axis=(1, 2, 3)) * 2.0)
    capture = np.ascontiguousarray(
        (capture_raw / capture_rms[:, None, None, None]).reshape(-1, 2, WINDOW_SAMPLES),
        dtype=np.float32,
    )
    capture_centered = centered.reshape(-1, GROUP_WINDOWS, 2, WINDOW_SAMPLES)
    capture_centered_rms = np.sqrt(
        np.mean(np.square(capture_centered, dtype=np.float64), axis=(1, 2, 3)) * 2.0
    )
    capture_dc = np.ascontiguousarray(
        (capture_centered / capture_centered_rms[:, None, None, None]).reshape(-1, 2, WINDOW_SAMPLES),
        dtype=np.float32,
    )
    return {
        "raw_identity": raw,
        "per_window_unit_rms": per_window,
        "per_window_dc_unit_rms": per_window_dc,
        "four_window_capture_unit_rms": capture,
        "four_window_capture_dc_unit_rms": capture_dc,
    }


def complex_rms_rows(values: np.ndarray) -> np.ndarray:
    return np.sqrt(np.mean(np.square(values, dtype=np.float64), axis=(1, 2)) * 2.0)


def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    if not math.isfinite(temperature) or temperature <= 0:
        fail("calibration", "temperature", "must be positive and finite")
    scaled = logits.astype(np.float64, copy=False) / temperature
    scaled = scaled - scaled.max(axis=-1, keepdims=True)
    exponent = np.exp(scaled)
    return exponent / exponent.sum(axis=-1, keepdims=True)


def classification_metrics(logits: np.ndarray, labels: np.ndarray, snr: np.ndarray) -> dict[str, Any]:
    probabilities = softmax(logits).astype(np.float32)
    predictions = np.argmax(probabilities, axis=1)
    confidence = probabilities[np.arange(len(labels)), predictions]
    true_probability = probabilities[np.arange(len(labels)), labels]
    correct = predictions == labels
    primary = snr >= 4.0
    if not np.any(primary):
        fail("metrics", "primary_snr", "no validation rows at or above 4 dB")
    return {
        "rows": int(len(labels)),
        "accuracy": float(correct.mean()),
        "primary_snr_accuracy": float(correct[primary].mean()),
        "primary_snr_rows": int(primary.sum()),
        "negative_log_likelihood": float(-np.log(np.maximum(true_probability, 1e-30)).mean()),
        "top1_confidence_mean": float(confidence.mean()),
        "top1_confidence_p50": float(np.median(confidence)),
        "ece_15_bin": expected_calibration_error(probabilities, labels, 15),
        "per_snr_accuracy": {
            str(int(level)): float(correct[snr == level].mean()) for level in np.unique(snr)
        },
    }


def expected_calibration_error(probabilities: np.ndarray, labels: np.ndarray, bins: int) -> float:
    predictions = np.argmax(probabilities, axis=1)
    confidence = probabilities[np.arange(len(labels)), predictions]
    correct = predictions == labels
    bin_ids = np.minimum((confidence * bins).astype(np.int64), bins - 1)
    result = 0.0
    for bin_id in range(bins):
        mask = bin_ids == bin_id
        if np.any(mask):
            result += float(mask.mean()) * abs(float(correct[mask].mean()) - float(confidence[mask].mean()))
    return result


def aggregate_scores(
    logits: np.ndarray, labels: np.ndarray, snr: np.ndarray, window_count: int, method: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if window_count not in (1, 2, 4) or GROUP_WINDOWS % window_count:
        fail("aggregation", "window_count", "must be one of 1, 2 or 4")
    grouped_logits = logits.reshape(-1, window_count, NUM_CLASSES)
    grouped_labels = labels.reshape(-1, window_count)
    grouped_snr = snr.reshape(-1, window_count)
    if np.any(grouped_labels != grouped_labels[:, :1]) or np.any(grouped_snr != grouped_snr[:, :1]):
        fail("aggregation", method, "aggregation group crosses label or SNR")
    probabilities = softmax(grouped_logits).astype(np.float32)
    if method == "mean_logit":
        scores = grouped_logits.mean(axis=1, dtype=np.float64)
        calibrated_shape = scores
    elif method == "mean_probability":
        scores = probabilities.mean(axis=1, dtype=np.float64)
        calibrated_shape = np.log(np.maximum(scores, 1e-30))
    elif method == "majority_vote":
        top1 = np.argmax(grouped_logits, axis=2)
        votes = np.eye(NUM_CLASSES, dtype=np.float32)[top1].sum(axis=1)
        scores = votes * 2.0 + probabilities.mean(axis=1)
        calibrated_shape = scores
    else:
        fail("aggregation", "method", f"unsupported method {method!r}")
    return scores, grouped_labels[:, 0], grouped_snr[:, 0], calibrated_shape


def aggregation_metric(scores: np.ndarray, labels: np.ndarray, snr: np.ndarray) -> dict[str, Any]:
    predictions = np.argmax(scores, axis=1)
    correct = predictions == labels
    primary = snr >= 4.0
    return {
        "groups": int(len(labels)),
        "accuracy": float(correct.mean()),
        "primary_snr_accuracy": float(correct[primary].mean()),
        "primary_snr_groups": int(primary.sum()),
    }


def choose_window_aggregation(rows: list[dict[str, Any]], tolerance: float = 0.0025) -> dict[str, Any]:
    eligible = [row for row in rows if row["method"] in {"mean_probability", "mean_logit"}]
    if not eligible:
        fail("selection", "aggregation", "no calibration-eligible rows")
    best_accuracy = max(row["primary_snr_accuracy"] for row in eligible)
    contenders = [row for row in eligible if row["primary_snr_accuracy"] >= best_accuracy - tolerance]
    minimum_windows = min(row["window_count"] for row in contenders)
    contenders = [row for row in contenders if row["window_count"] == minimum_windows]
    contenders.sort(key=lambda row: (0 if row["method"] == "mean_logit" else 1, -row["primary_snr_accuracy"]))
    selected = dict(contenders[0])
    selected["best_primary_snr_accuracy"] = best_accuracy
    selected["within_absolute_tolerance"] = tolerance
    return selected


def choose_transform(
    transform_metrics: dict[str, dict[str, Any]],
    aggregation: dict[str, list[dict[str, Any]]],
    tolerance: float = 0.0025,
) -> dict[str, Any]:
    def dc_choice(preserve: str, remove: str) -> tuple[str, dict[str, Any]]:
        preserve_accuracy = transform_metrics[preserve]["primary_snr_accuracy"]
        remove_accuracy = transform_metrics[remove]["primary_snr_accuracy"]
        selected = preserve if preserve_accuracy >= remove_accuracy - tolerance else remove
        return selected, {
            "preserve": preserve_accuracy,
            "remove": remove_accuracy,
            "selected": selected,
            "preserve_preferred_within_tolerance": tolerance,
        }

    per_window, per_window_dc = dc_choice("per_window_unit_rms", "per_window_dc_unit_rms")
    per_capture, per_capture_dc = dc_choice(
        "four_window_capture_unit_rms", "four_window_capture_dc_unit_rms"
    )
    per_window_aggregation = choose_window_aggregation(aggregation[per_window], tolerance)
    per_capture_aggregation = choose_window_aggregation(aggregation[per_capture], tolerance)
    per_window_accuracy = per_window_aggregation["primary_snr_accuracy"]
    per_capture_accuracy = per_capture_aggregation["primary_snr_accuracy"]
    selected = per_window if per_window_accuracy >= per_capture_accuracy - tolerance else per_capture
    selected_aggregation = per_window_aggregation if selected == per_window else per_capture_aggregation
    return {
        "selected_transform": selected,
        "selected_window_count": selected_aggregation["window_count"],
        "selected_aggregator": selected_aggregation["method"],
        "dc_selection": {
            "per_window_scope": per_window_dc,
            "four_window_capture_scope": per_capture_dc,
        },
        "normalization_scope_selection": {
            "per_window_transform": per_window,
            "per_window_best_primary_accuracy": per_window_accuracy,
            "per_capture_transform": per_capture,
            "per_capture_best_primary_accuracy": per_capture_accuracy,
            "per_window_preferred_within_tolerance": tolerance,
            "selected": selected,
        },
        "window_aggregation_selection": selected_aggregation,
        "raw_identity_eligible": False,
        "old_checkpoint_rf_aligned": False,
    }


def calibration_probabilities(
    logits: np.ndarray, window_count: int, method: str, temperature: float
) -> np.ndarray:
    grouped = logits.reshape(-1, window_count, NUM_CLASSES)
    if method == "mean_logit":
        return softmax(grouped.mean(axis=1, dtype=np.float64), temperature)
    if method == "mean_probability":
        return softmax(grouped, temperature).mean(axis=1)
    fail("calibration", "method", "majority vote cannot supply calibrated probabilities")


def negative_log_likelihood(probabilities: np.ndarray, labels: np.ndarray) -> float:
    return float(-np.log(np.maximum(probabilities[np.arange(len(labels)), labels], 1e-30)).mean())


def fit_scalar_temperature(
    logits: np.ndarray,
    labels: np.ndarray,
    window_count: int,
    method: str,
    minimum: float = 0.25,
    maximum: float = 4.0,
) -> tuple[float, float]:
    left = math.log(minimum)
    right = math.log(maximum)
    ratio = (math.sqrt(5.0) - 1.0) / 2.0

    def objective(log_temperature: float) -> float:
        probabilities = calibration_probabilities(logits, window_count, method, math.exp(log_temperature))
        return negative_log_likelihood(probabilities, labels)

    c = right - ratio * (right - left)
    d = left + ratio * (right - left)
    fc = objective(c)
    fd = objective(d)
    for _ in range(36):
        if fc <= fd:
            right, d, fd = d, c, fc
            c = right - ratio * (right - left)
            fc = objective(c)
        else:
            left, c, fc = c, d, fd
            d = left + ratio * (right - left)
            fd = objective(d)
    selected_log = (left + right) / 2.0
    return math.exp(selected_log), objective(selected_log)


def calibration_report(
    logits: np.ndarray,
    labels: np.ndarray,
    first_source_rows: np.ndarray,
    window_count: int,
    method: str,
) -> dict[str, Any]:
    grouped_labels = labels.reshape(-1, window_count)[:, 0]
    if len(grouped_labels) != len(first_source_rows):
        fail("calibration", "partition", "source rows do not align with aggregated groups")
    fit_mask = np.asarray(
        [hashlib.sha256(f"calibration-group-v1:{int(row)}".encode()).digest()[0] & 1 == 0 for row in first_source_rows],
        dtype=bool,
    )
    if not np.any(fit_mask) or np.all(fit_mask):
        fail("calibration", "partition", "fit/audit partition is empty")
    grouped_logits = logits.reshape(-1, window_count, NUM_CLASSES)
    fit_logits = grouped_logits[fit_mask].reshape(-1, NUM_CLASSES)
    audit_logits = grouped_logits[~fit_mask].reshape(-1, NUM_CLASSES)
    fit_labels = grouped_labels[fit_mask]
    audit_labels = grouped_labels[~fit_mask]
    temperature, fit_nll = fit_scalar_temperature(fit_logits, fit_labels, window_count, method)
    identity = calibration_probabilities(audit_logits, window_count, method, 1.0)
    calibrated = calibration_probabilities(audit_logits, window_count, method, temperature)
    thresholds = (0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 0.975, 0.99)
    prediction = np.argmax(calibrated, axis=1)
    confidence = calibrated[np.arange(len(audit_labels)), prediction]
    correct = prediction == audit_labels
    curve: list[dict[str, Any]] = []
    for threshold in thresholds:
        accepted = confidence >= threshold
        curve.append(
            {
                "threshold": threshold,
                "accepted": int(accepted.sum()),
                "coverage": float(accepted.mean()),
                "accepted_precision": float(correct[accepted].mean()) if np.any(accepted) else None,
            }
        )
    return {
        "status": "experimental_baseline_only_not_frozen",
        "method": "scalar_temperature",
        "aggregator": method,
        "window_count": window_count,
        "partition": "sha256(calibration-group-v1:first-global-row) low bit",
        "fit_groups": int(fit_mask.sum()),
        "audit_groups": int((~fit_mask).sum()),
        "temperature": temperature,
        "fit_negative_log_likelihood": fit_nll,
        "audit_identity_negative_log_likelihood": negative_log_likelihood(identity, audit_labels),
        "audit_calibrated_negative_log_likelihood": negative_log_likelihood(calibrated, audit_labels),
        "audit_identity_ece_15_bin": expected_calibration_error(identity, audit_labels, 15),
        "audit_calibrated_ece_15_bin": expected_calibration_error(calibrated, audit_labels, 15),
        "audit_accuracy": float(correct.mean()),
        "coverage_precision_curve": curve,
        "production_temperature_frozen": False,
        "production_acceptance_threshold_frozen": False,
        "blocker": "A final RF-aligned checkpoint and labeled OOD/known-RF validation evidence are absent.",
    }


def import_evaluator():
    specification = importlib.util.spec_from_file_location("amc_evaluator_for_preprocess_selection", EVALUATOR_PATH)
    if specification is None or specification.loader is None:
        fail("runtime", str(EVALUATOR_PATH), "cannot import evaluator")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def load_model(plan: dict[str, Any]):
    evaluator = import_evaluator()
    try:
        import torch
    except ImportError as error:
        fail("runtime", "torch", str(error))
    pinned = plan["pinned_inputs"]
    manifest_path = resolve_regular(pinned["experimental_model_manifest"]["path"], "model_manifest")
    verify_hash(manifest_path, pinned["experimental_model_manifest"]["sha256"], "model_manifest")
    manifest = read_json(manifest_path)
    config_path = resolve_regular(pinned["checkpoint_config"]["path"], "checkpoint_config")
    verify_hash(config_path, pinned["checkpoint_config"]["sha256"], "checkpoint_config")
    config = read_json(config_path)
    checkpoint_path = resolve_regular(pinned["checkpoint"]["path"], "checkpoint")
    checkpoint_asset = verify_hash(
        checkpoint_path,
        pinned["checkpoint"]["sha256"],
        "checkpoint",
        pinned["checkpoint"]["bytes"],
    )
    source_root = REPO_ROOT / manifest["asset_root"] / "model-source" / manifest["model_source_commit"]
    source_assets = evaluator.verify_model_source(source_root)
    if (
        config.get("selected_model_class") != "AMCMambaD8"
        or config.get("selected_model_variant") != "amc_mamba_d8"
        or config.get("git", {}).get("commit") != manifest["model_source_commit"]
        or config.get("git", {}).get("dirty") is not False
    ):
        fail("runtime", "checkpoint_config", "model class, variant or source revision changed")
    if not torch.cuda.is_available():
        fail("runtime", "cuda", "CUDA is unavailable")
    torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    torch.set_grad_enabled(False)
    model_config = config["resolved_config"]["model"]
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
        model_variant="amc_mamba_d8",
        num_classes=NUM_CLASSES,
        **{name: model_config[name] for name in fields},
    )
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if (
        checkpoint.get("selected_model_class") != "AMCMambaD8"
        or checkpoint.get("selected_model_variant") != "amc_mamba_d8"
    ):
        fail("runtime", "checkpoint", "checkpoint model identity changed")
    model.load_state_dict(checkpoint["model_state"], strict=True)
    if sum(parameter.numel() for parameter in model.parameters()) != 134_798:
        fail("runtime", "model", "parameter count differs from the pinned checkpoint")
    if model.encoder.backend != evaluator.MODEL_BACKEND or not model.encoder.real_mamba_available():
        fail("runtime", "model", f"real Mamba backend unavailable: {model.encoder.backend}")
    model = model.eval().cuda()
    return model, torch, {
        "checkpoint": checkpoint_asset,
        "model_source_commit": manifest["model_source_commit"],
        "model_source_files": source_assets,
        "parameters": 134_798,
        "backend": model.encoder.backend,
        "precision": "fp32",
        "cuda_device": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
    }


def infer_transform_logits(
    model: Any,
    torch: Any,
    validation_x: np.ndarray,
    groups: np.ndarray,
    groups_per_batch: int,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    row_count = int(groups.size)
    outputs = {name: np.empty((row_count, NUM_CLASSES), dtype=np.float32) for name in TRANSFORM_IDS}
    cursor = 0
    started = time.perf_counter()
    torch.cuda.reset_peak_memory_stats()
    warmup_group = validation_x[groups[:1]].astype(np.float32, copy=False)
    warmup = transform_group_batch(warmup_group)["per_window_unit_rms"]
    for _ in range(3):
        model(torch.from_numpy(warmup).cuda(non_blocking=False))
    torch.cuda.synchronize()
    batch_count = math.ceil(len(groups) / groups_per_batch)
    for batch_index, start in enumerate(range(0, len(groups), groups_per_batch), start=1):
        current_groups = groups[start : start + groups_per_batch]
        transformed = transform_group_batch(validation_x[current_groups])
        rows = len(current_groups) * GROUP_WINDOWS
        combined = np.concatenate([transformed[name] for name in TRANSFORM_IDS], axis=0)
        tensor = torch.from_numpy(combined).cuda(non_blocking=False)
        with torch.inference_mode():
            combined_logits = model(tensor).float().cpu().numpy()
        if combined_logits.shape != (rows * len(TRANSFORM_IDS), NUM_CLASSES):
            fail("runtime", "model_output", f"unexpected shape {combined_logits.shape}")
        next_cursor = cursor + rows
        for transform_index, name in enumerate(TRANSFORM_IDS):
            offset = transform_index * rows
            outputs[name][cursor:next_cursor] = combined_logits[offset : offset + rows]
        cursor = next_cursor
        if batch_index % 50 == 0 or batch_index == batch_count:
            elapsed = time.perf_counter() - started
            print(
                f"validation_inference batches={batch_index}/{batch_count} rows={cursor}/{row_count} "
                f"variant_rows={cursor * len(TRANSFORM_IDS)} elapsed_s={elapsed:.1f}",
                flush=True,
            )
    torch.cuda.synchronize()
    if cursor != row_count:
        fail("runtime", "inference", "output row count mismatch")
    return outputs, {
        "elapsed_seconds": time.perf_counter() - started,
        "groups_per_batch": groups_per_batch,
        "base_rows": row_count,
        "variant_rows": row_count * len(TRANSFORM_IDS),
        "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
        "cuda_peak_reserved_bytes": int(torch.cuda.max_memory_reserved()),
    }


def infer_raw_tails(model: Any, torch: Any, validation_x: np.ndarray, positions: np.ndarray) -> np.ndarray:
    output = np.empty((len(positions), NUM_CLASSES), dtype=np.float32)
    cursor = 0
    for start in range(0, len(positions), 512):
        values = np.ascontiguousarray(validation_x[positions[start : start + 512]], dtype=np.float32)
        with torch.inference_mode():
            logits = model(torch.from_numpy(values).cuda(non_blocking=False)).float().cpu().numpy()
        output[cursor : cursor + len(values)] = logits
        cursor += len(values)
    return output


def build_aggregation_tables(
    logits: dict[str, np.ndarray], labels: np.ndarray, snr: np.ndarray
) -> dict[str, list[dict[str, Any]]]:
    tables: dict[str, list[dict[str, Any]]] = {}
    for transform_id in TRANSFORM_IDS:
        rows: list[dict[str, Any]] = []
        for window_count in (1, 2, 4):
            for method in ("majority_vote", "mean_probability", "mean_logit"):
                scores, grouped_labels, grouped_snr, _ = aggregate_scores(
                    logits[transform_id], labels, snr, window_count, method
                )
                rows.append(
                    {
                        "window_count": window_count,
                        "method": method,
                        "calibration_eligible": method != "majority_vote",
                        **aggregation_metric(scores, grouped_labels, grouped_snr),
                    }
                )
        tables[transform_id] = rows
    return tables


def validate_p201_package(plan: dict[str, Any]) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    descriptor = plan["pinned_inputs"]["receive_domain_manifest"]
    manifest_path = resolve_regular(descriptor["path"], "receive_domain_manifest")
    verify_hash(manifest_path, descriptor["sha256"], "receive_domain_manifest")
    manifest = read_json(manifest_path)
    if manifest.get("corpus_kind") != "p201_receive" or manifest.get("status") != "frozen":
        fail("receive_domain", str(manifest_path), "must be a frozen P201 corpus")
    package = manifest_path.parent
    records_path = resolve_regular(str(package / manifest["record_index"]["path"]), "record_index")
    verify_hash(records_path, manifest["record_index"]["sha256"], "record_index")
    records = [strict_json_bytes(line, str(records_path)) for line in records_path.read_bytes().splitlines()]
    if len(records) != 1 or records[0].get("split") != "receive_domain" or records[0]["label"]["provenance"] != "unknown":
        fail("receive_domain", str(records_path), "expected exactly one unknown receive-domain record")
    raw_assets = [asset for asset in manifest["assets"] if asset.get("role") == "raw_iq"]
    if len(raw_assets) != 1:
        fail("receive_domain", "assets", "expected one raw-IQ asset")
    raw_path = resolve_regular(str(package / raw_assets[0]["path"]), "raw_iq")
    raw_asset = verify_hash(raw_path, raw_assets[0]["sha256"], "raw_iq", raw_assets[0]["bytes"])
    return raw_path, records[0], {"manifest": descriptor, "record_index": manifest["record_index"], "raw_iq": raw_asset}


def aggregate_probability_for_observation(
    logits: np.ndarray, window_count: int, method: str, temperature: float = 1.0
) -> np.ndarray:
    if method == "mean_logit":
        return softmax(logits.reshape(-1, window_count, NUM_CLASSES).mean(axis=1), temperature)
    if method == "mean_probability":
        return softmax(logits.reshape(-1, window_count, NUM_CLASSES), temperature).mean(axis=1)
    fail("receive_domain", "aggregator", "selected method is not calibration eligible")


def observe_p201(
    raw_path: Path,
    record: dict[str, Any],
    model: Any,
    torch: Any,
    selection: dict[str, Any],
    temperature: float,
) -> dict[str, Any]:
    payload = raw_path.read_bytes()
    raw_iq = np.frombuffer(payload, dtype="<i2")
    if raw_iq.shape != (GROUP_WINDOWS * WINDOW_SAMPLES * 2,):
        fail("receive_domain", "raw_iq", f"unexpected scalar count {raw_iq.size}")
    groups = raw_iq.reshape(1, GROUP_WINDOWS, WINDOW_SAMPLES, 2).transpose(0, 1, 3, 2).astype(np.float32)
    transformed = transform_group_batch(groups)
    selected_values = transformed[selection["selected_transform"]]
    with torch.inference_mode():
        logits = model(torch.from_numpy(selected_values).cuda(non_blocking=False)).float().cpu().numpy()
    per_window_probability = softmax(logits)
    per_window_top1 = np.argmax(per_window_probability, axis=1)
    window_count = int(selection["selected_window_count"])
    aggregated = aggregate_probability_for_observation(
        logits, window_count, selection["selected_aggregator"], temperature
    )
    aggregated_top1 = np.argmax(aggregated, axis=1)
    raw_rows = groups.reshape(-1, 2, WINDOW_SAMPLES)
    raw_rms = complex_rms_rows(raw_rows)
    means = raw_rows.mean(axis=2, dtype=np.float64)
    dc_fraction = np.linalg.norm(means, axis=1) / raw_rms
    return {
        "label_provenance": "unknown",
        "accuracy": None,
        "correctness": None,
        "record_id": record["record_id"],
        "capture_session_id": record["lineage"]["capture_session_id"],
        "capture_day_utc": record["lineage"]["capture_day"],
        "source_quality": record["source"]["quality"],
        "raw_complex_rms_adc_by_window": raw_rms.tolist(),
        "raw_dc_fraction_by_window": dc_fraction.tolist(),
        "selected_transform": selection["selected_transform"],
        "per_window_numeric_top1": per_window_top1.tolist(),
        "per_window_top1_confidence": per_window_probability[
            np.arange(GROUP_WINDOWS), per_window_top1
        ].tolist(),
        "aggregation_window_count": window_count,
        "aggregation_method": selection["selected_aggregator"],
        "aggregated_numeric_top1": aggregated_top1.tolist(),
        "aggregated_confidence_using_baseline_validation_temperature": aggregated[
            np.arange(len(aggregated_top1)), aggregated_top1
        ].tolist(),
        "baseline_temperature_is_production_calibration": False,
        "model_prediction_used_as_ground_truth": False,
        "raw_iq_copied": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hash-dataset", action="store_true")
    parser.add_argument("--block-rows", type=int, default=4096)
    parser.add_argument("--groups-per-batch", type=int, default=32)
    parser.add_argument("--limit-groups", type=int, default=0, help="Smoke only; zero is the preregistered full run")
    return parser.parse_args()


def execute(args: argparse.Namespace) -> dict[str, Any]:
    """Complete run wrapper kept separate so tests can exercise pure helpers."""
    if args.block_rows <= 0 or args.groups_per_batch <= 0 or args.limit_groups < 0:
        fail("arguments", "batching", "block/batch must be positive and limit non-negative")
    plan, plan_asset = load_plan()
    output = args.output.resolve(strict=False)
    try:
        output.relative_to(TEMPORARY_ROOT)
    except ValueError:
        fail("output", str(output), f"must be below {TEMPORARY_ROOT}")
    TEMPORARY_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary_metadata = TEMPORARY_ROOT.lstat()
    if (
        stat.S_ISLNK(temporary_metadata.st_mode)
        or not stat.S_ISDIR(temporary_metadata.st_mode)
        or TEMPORARY_ROOT.resolve(strict=True) != TEMPORARY_ROOT
    ):
        fail("output", str(TEMPORARY_ROOT), "temporary root must be the exact non-symlink directory")
    if output.exists():
        fail("output", str(output), "refusing to overwrite existing evidence")
    free_before = free_space_bytes(TEMPORARY_ROOT)
    if free_before < MAX_TEMPORARY_BYTES:
        fail("space", str(TEMPORARY_ROOT), f"need {MAX_TEMPORARY_BYTES}, got {free_before}")
    running = TEMPORARY_ROOT / "RUNNING"
    if running.exists():
        fail("running", str(running), "another or interrupted selection run exists")
    running.write_text(f"pid={os.getpid()}\n", encoding="ascii")
    running.chmod(0o600)

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    wall_started = time.perf_counter()
    pinned = plan["pinned_inputs"]
    dataset_path = resolve_regular(pinned["dataset"]["path"], "dataset")
    if dataset_path.stat().st_size != pinned["dataset"]["bytes"]:
        fail("asset", "dataset.bytes", "dataset size mismatch")
    dataset_hash = sha256_file(dataset_path) if args.hash_dataset else None
    if args.hash_dataset and dataset_hash != pinned["dataset"]["sha256"]:
        fail("asset", "dataset.sha256", "dataset hash mismatch")
    split_path = resolve_regular(pinned["split"]["path"], "split")
    split_asset = verify_hash(split_path, pinned["split"]["sha256"], "split", pinned["split"]["bytes"])
    isolation_path = resolve_regular(pinned["split_isolation_evidence"]["path"], "split_isolation")
    isolation_asset = verify_hash(
        isolation_path, pinned["split_isolation_evidence"]["sha256"], "split_isolation"
    )
    metrics_path = resolve_regular(pinned["checkpoint_validation_metrics"]["path"], "validation_metrics")
    metrics_asset = verify_hash(
        metrics_path, pinned["checkpoint_validation_metrics"]["sha256"], "validation_metrics"
    )
    reference_validation = read_json(metrics_path)
    if reference_validation.get("split") != "val" or reference_validation.get("num_samples") != 383_385:
        fail("validation_metrics", str(metrics_path), "not the pinned complete validation result")
    train_indices, validation_indices, split_access = load_allowed_indices(split_path, plan)

    try:
        import h5py
    except ImportError as error:
        fail("runtime", "h5py", str(error))
    with h5py.File(dataset_path, "r") as h5_file:
        if (
            set(h5_file.keys()) != {"X", "Y", "Z"}
            or h5_file["X"].shape != (NUM_SAMPLES, WINDOW_SAMPLES, 2)
            or h5_file["X"].dtype != np.dtype("float32")
            or h5_file["Y"].shape != (NUM_SAMPLES, NUM_CLASSES)
            or h5_file["Z"].shape != (NUM_SAMPLES, 1)
        ):
            fail("dataset", str(dataset_path), "HDF5 shape or key contract changed")
        train_statistics = scan_train_statistics(h5_file, train_indices, args.block_rows)
        validation_x, validation_labels, validation_snr, validation_load = load_validation_arrays(
            h5_file, validation_indices, args.block_rows
        )

    all_groups, excluded_positions, grouping = build_four_window_groups(validation_labels, validation_snr)
    groups = all_groups
    if args.limit_groups and args.limit_groups < len(groups):
        selected_positions = np.linspace(0, len(groups) - 1, args.limit_groups, dtype=np.int64)
        groups = groups[selected_positions]
    full_preregistered_run = args.limit_groups == 0 and len(groups) == len(all_groups)
    group_positions = groups.reshape(-1)
    group_ids = validation_indices[groups]
    group_labels = validation_labels[group_positions]
    group_snr = validation_snr[group_positions]

    model, torch, model_summary = load_model(plan)
    logits, inference = infer_transform_logits(
        model, torch, validation_x, groups, args.groups_per_batch
    )
    transform_metrics = {
        name: classification_metrics(values, group_labels, group_snr) for name, values in logits.items()
    }
    raw_full_parity: dict[str, Any] = {"applicable": False}
    if full_preregistered_run:
        raw_full = np.empty((len(validation_indices), NUM_CLASSES), dtype=np.float32)
        raw_full[group_positions] = logits["raw_identity"]
        raw_full[excluded_positions] = infer_raw_tails(
            model, torch, validation_x, excluded_positions
        )
        full_metrics = classification_metrics(raw_full, validation_labels, validation_snr)
        reference_accuracy = float(reference_validation["overall_accuracy"])
        accuracy_delta = full_metrics["accuracy"] - reference_accuracy
        if abs(accuracy_delta) > 0.0001:
            fail("parity", "raw_identity", f"validation accuracy delta {accuracy_delta} exceeds 0.0001")
        raw_full_parity = {
            "applicable": True,
            "reference_accuracy": reference_accuracy,
            "agx_accuracy": full_metrics["accuracy"],
            "accuracy_delta": accuracy_delta,
            "tolerance": 0.0001,
            "status": "pass",
        }
        del raw_full

    aggregation = build_aggregation_tables(logits, group_labels, group_snr)
    selection = choose_transform(transform_metrics, aggregation)
    selected_logits = logits[selection["selected_transform"]]
    selected_window_count = int(selection["selected_window_count"])
    calibration_group_first_ids = group_ids.reshape(-1, selected_window_count)[:, 0]
    calibration = calibration_report(
        selected_logits,
        group_labels,
        calibration_group_first_ids,
        selected_window_count,
        selection["selected_aggregator"],
    )
    raw_path, receive_record, p201_assets = validate_p201_package(plan)
    receive_domain = observe_p201(
        raw_path,
        receive_record,
        model,
        torch,
        selection,
        calibration["temperature"],
    )
    torch.cuda.synchronize()
    del logits, validation_x, model

    summary = {
        "schema_version": 1,
        "schema_id": "rf_preprocess_validation_selection_v1",
        "run_id": "rf-preprocess-v1-selection-20260905-full" if full_preregistered_run else "rf-preprocess-v1-selection-20260905-smoke",
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "status": "pass" if full_preregistered_run else "smoke_only",
        "full_preregistered_validation_run": full_preregistered_run,
        "implementation": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "governance": {
            "selection_plan": plan_asset,
            "split_isolation_evidence": isolation_asset,
            "split_access": split_access,
            "train_role": "distribution_statistics_only",
            "validation_role": "candidate_ranking_calibration_methodology_and_window_ablation",
            "test_member_loaded": False,
            "test_result_path_opened": False,
            "historical_test_metrics_used_for_ranking": False,
            "p201_ground_truth_available": False,
            "p201_prediction_used_as_accuracy": False,
        },
        "assets": {
            "dataset": {
                "path": str(dataset_path),
                "bytes": dataset_path.stat().st_size,
                "expected_sha256": pinned["dataset"]["sha256"],
                "sha256_recomputed": bool(args.hash_dataset),
                "sha256": dataset_hash,
            },
            "split": split_asset,
            "validation_metrics": metrics_asset,
            "p201": p201_assets,
        },
        "data": {
            "train_statistics": train_statistics,
            "validation_load": validation_load,
            "grouping": grouping,
            "groups_evaluated": int(len(groups)),
            "rows_evaluated_per_transform": int(groups.size),
            "group_first_global_rows_sha256": hashlib.sha256(
                np.asarray(group_ids[:, 0], dtype="<i8").tobytes()
            ).hexdigest(),
        },
        "model": model_summary,
        "transform_metrics": transform_metrics,
        "aggregation_ablation": aggregation,
        "selection": selection,
        "calibration": calibration,
        "receive_domain_observation": receive_domain,
        "raw_identity_full_validation_parity": raw_full_parity,
        "performance": {
            "total_wall_seconds": time.perf_counter() - wall_started,
            "inference": inference,
            "process_max_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "memory_available_after_bytes": available_memory_bytes(),
            "temporary_free_bytes_before": free_before,
            "temporary_maximum_bytes": MAX_TEMPORARY_BYTES,
        },
        "runtime": {
            "hostname": platform.node(),
            "python": platform.python_version(),
            "numpy": np.__version__,
        },
        "production": {
            "rf_preprocess_transform_can_be_frozen_for_retraining": full_preregistered_run,
            "production_checkpoint_available": False,
            "production_calibration_frozen": False,
            "production_acceptance_threshold_frozen": False,
            "recognizer_available": False,
        },
    }
    payload = (json.dumps(summary, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if len(payload) > MAX_TEMPORARY_BYTES:
        fail("output", str(output), "summary exceeds the temporary byte bound")
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
    except SelectionError as error:
        print(f"selection_error={error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": summary["status"],
                "output": str(args.output.resolve()),
                "selection": summary["selection"],
                "calibration_production_frozen": summary["production"]["production_calibration_frozen"],
                "test_member_loaded": summary["governance"]["test_member_loaded"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
