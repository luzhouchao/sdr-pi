#!/usr/bin/env python3
"""Evaluate the pinned AMC-Mamba D8 checkpoints on AGX without training code."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import platform
import resource
import sys
import time
import types
from collections import defaultdict
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import h5py
import numpy as np
import torch


REPO_ROOT = Path(__file__).resolve().parents[3]
ASSET_ROOT = REPO_ROOT / "local-assets" / "amc-eval"
MODEL_COMMIT = "8bc6fb5dc58e1b83338bdebb2624824f1e6b0798"
MODEL_BACKEND = "real_mamba2_weight_tied_bidirectional_d8_length_conditioned_shared_coarse"

MODEL_SOURCE_SHA256 = {
    "models/__init__.py": "d8d02d52268be39de2fe4466dcca8dee9be07407734eebc0f2a6283facb2f135",
    "models/d2/__init__.py": "d3d5223d8b4f5a5f970d34f071e58a14d05e6bbe49c5ea4cbaa7ea41feff42dc",
    "models/d2/model.py": "39bfab76e1819ebc75bbff963b3fe9fc8e91905881140ae27558a88d0d08c272",
    "models/d2/sequence.py": "50dfc6abeb851106c7ead657500b6410ea76d50d26671e4d66edd34e1418c7b7",
    "models/d3_3/__init__.py": "67e2e8ed2a2be0423e47dd88a8dec89b64609f6fbfc4fa23edc1132669c9af8f",
    "models/d3_3/model.py": "a1d7be0d64445f7cdee5a091ab42dedf060f7895c9e8203e106bc1c5d93deca2",
    "models/d3_4/__init__.py": "a2c943333196d308050033cadc8ef679501444d22a55b132a4659f6ed514e10c",
    "models/d3_4/model.py": "30f325cf66ee85528ae46b42496134508ac0e37f477e93ab47a3104d86acabe8",
    "models/d8/__init__.py": "29b1858f8725440c97130c2c82d06e42e8d224f8bb19adb0d457b28485ec7a3a",
    "models/d8/model.py": "4e272a5a9ea62381ecffd17607d418f23d2ebc63c0e5c44dfd54ebb17707ded2",
    "models/d8/sequence.py": "b28961f40f574ccbd890c7396eccda4bad581b16eadd777988e7b5d185632c00",
    "utils/__init__.py": "fe3d47499fc6c3e0fac498c9a4860fb9ac876f2ff071e9860769a6d1032aa566",
    "utils/model_defaults.py": "6632270d666d9cf8f28bb3063bd459546028c74f8b096532fba7e73e30dc7474",
}

DATASET_SPECS: dict[str, dict[str, Any]] = {
    "rml2018a": {
        "dataset": ASSET_ROOT / "datasets" / "rml2018a" / "RML2018a.hdf5",
        "dataset_bytes": 21_449_148_312,
        "dataset_sha256": "e3dd0bef66a3426959ee66a1709a8c0a95d4f8395d18aaf6f1214bdbc763bd38",
        "split": ASSET_ROOT / "splits" / "RML2018a_split_seed44_tr700_val150_te150.npz",
        "split_sha256": "5b8ccdc0183455445d5beab20f2ed7e553ff616da76a31114f700929607d0792",
        "checkpoint_dir": ASSET_ROOT / "checkpoints" / "rml2018a" / "seed44",
        "checkpoint_sha256": "e5a1bccdaf4b0290f41b26cb05b8b98565df9d5b07147727d79bbf43f6cb42dd",
        "num_samples": 2_555_904,
        "num_classes": 24,
        "test_samples": 383_387,
        "seed": 44,
        "input_layout": "NT2",
        "labels": REPO_ROOT / "jetson-agx" / "sdrharness" / "config" / "amc" / "rml2018a-labels.json",
    },
    "hisarmod2019": {
        "dataset": ASSET_ROOT / "datasets" / "hisarmod2019" / "HisarMod2019.01.h5",
        "dataset_bytes": 6_399_126_728,
        "dataset_sha256": "b4b2d2dcde17691b09e3d6b1aa91a9fbadd096980d5103a47af18f93ae1b596f",
        "split": ASSET_ROOT / "splits" / "HisarMod2019.01_split_seed43_tr700_val150_te150.npz",
        "split_sha256": "fd79c0ba607b3504180fc0fe4d3cf2bbc367f0a2d4f3cf86691b04d33e518b0a",
        "checkpoint_dir": ASSET_ROOT / "checkpoints" / "hisarmod2019" / "seed43",
        "checkpoint_sha256": "714ac46cfbdb014350bb2f89f18938c612f27a28d0b3e5d1160bd21dd8386191",
        "num_samples": 780_000,
        "num_classes": 26,
        "test_samples": 117_000,
        "seed": 43,
        "input_layout": "N2T",
        "labels": None,
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def read_temperatures() -> dict[str, float]:
    temperatures: dict[str, float] = {}
    for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        try:
            name = (zone / "type").read_text(encoding="utf-8").strip()
            raw = float((zone / "temp").read_text(encoding="utf-8").strip())
        except (OSError, TypeError, ValueError):
            continue
        temperatures[name] = raw / 1000.0 if abs(raw) >= 1000.0 else raw
    return temperatures


def verify_file(path: Path, expected_sha256: str, expected_bytes: int | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if expected_bytes is not None and size != expected_bytes:
        raise RuntimeError(f"size mismatch for {path}: expected {expected_bytes}, got {size}")
    digest = sha256_file(path)
    if digest != expected_sha256:
        raise RuntimeError(f"SHA-256 mismatch for {path}: expected {expected_sha256}, got {digest}")
    return {"path": str(path.resolve()), "bytes": size, "sha256": digest}


def verify_model_source(source_root: Path) -> list[dict[str, Any]]:
    verified = []
    for relative, expected in MODEL_SOURCE_SHA256.items():
        path = source_root / relative
        verified.append({"relative_path": relative, **verify_file(path, expected)})
    return verified


def load_model_class(source_root: Path):
    # Importing the upstream top-level packages would pull the training registry
    # and utilities. Synthetic namespace packages intentionally expose only the
    # frozen inference files listed in MODEL_SOURCE_SHA256.
    for package_name, package_path in (("models", source_root / "models"), ("utils", source_root / "utils")):
        if package_name in sys.modules:
            raise RuntimeError(f"unexpected preloaded package: {package_name}")
        package = types.ModuleType(package_name)
        package.__path__ = [str(package_path)]  # type: ignore[attr-defined]
        package.__package__ = package_name
        sys.modules[package_name] = package
    module = importlib.import_module("models.d8.model")
    return module.AMCMambaD8


def load_labels(
    dataset_name: str,
    h5_file: h5py.File,
    label_path: Path | None,
    num_classes: int,
) -> tuple[list[str], dict[str, Any], np.ndarray | None]:
    if "classes" in h5_file:
        labels = [item.decode("utf-8") if isinstance(item, bytes) else str(item) for item in h5_file["classes"][...]]
        source = {"kind": "hdf5_dataset", "key": "classes"}
    elif label_path is not None:
        payload = json.loads(label_path.read_text(encoding="utf-8"))
        labels = [str(item) for item in payload["classes"]]
        source = {
            "kind": "json",
            "path": str(label_path.resolve()),
            "sha256": sha256_file(label_path),
            "provenance": payload.get("provenance"),
            "caveat": payload.get("caveat"),
        }
    else:
        labels = [str(index) for index in range(num_classes)]
        source = {"kind": "numeric_fallback"}
    if len(labels) != num_classes or len(set(labels)) != num_classes:
        raise RuntimeError(f"invalid labels for {dataset_name}: expected {num_classes} unique names")
    label_dataset = h5_file["Y"]
    raw_label_values: np.ndarray | None = None
    if label_dataset.ndim == 1 or (label_dataset.ndim == 2 and label_dataset.shape[1] == 1):
        raw_label_values = np.unique(np.asarray(label_dataset[...], dtype=np.int64).reshape(-1))
        if len(raw_label_values) != num_classes:
            raise RuntimeError(
                f"scalar label mapping has {len(raw_label_values)} values, expected {num_classes}"
            )
        source["raw_label_values"] = raw_label_values.tolist()
        source["mapping"] = "sorted unique raw value -> zero-based class index"
    return labels, source, raw_label_values


def validate_split(split_path: Path, spec: dict[str, Any], limit: int) -> np.ndarray:
    with np.load(split_path, allow_pickle=False) as split:
        required = {"train", "val", "test", "num_samples", "train_ratio", "val_ratio", "test_ratio", "seed"}
        if set(split.files) != required:
            raise RuntimeError(f"unexpected split keys: {split.files}")
        if int(split["num_samples"][0]) != spec["num_samples"] or int(split["seed"][0]) != spec["seed"]:
            raise RuntimeError("split metadata does not match the pinned dataset")
        ratios = [float(split[name][0]) for name in ("train_ratio", "val_ratio", "test_ratio")]
        if not all(math.isclose(actual, expected) for actual, expected in zip(ratios, (0.7, 0.15, 0.15))):
            raise RuntimeError(f"unexpected split ratios: {ratios}")
        indices = np.asarray(split["test"], dtype=np.int64)
    if indices.ndim != 1 or len(indices) != spec["test_samples"]:
        raise RuntimeError(f"unexpected test split shape: {indices.shape}")
    if indices.size and (indices[0] < 0 or indices[-1] >= spec["num_samples"] or np.any(indices[1:] <= indices[:-1])):
        raise RuntimeError("test indices must be unique, strictly increasing, and in range")
    if limit and limit < len(indices):
        # A head slice is strongly biased because both reference HDF5 files are
        # ordered by class/SNR. Even spacing gives a deterministic smoke subset
        # across the complete pinned test split while keeping indices sorted.
        positions = np.linspace(0, len(indices) - 1, num=limit, dtype=np.int64)
        return indices[positions]
    return indices


def iter_h5_batches(
    h5_file: h5py.File,
    indices: np.ndarray,
    input_layout: str,
    raw_label_values: np.ndarray | None,
    batch_size: int,
    read_block_rows: int,
    io_stats: dict[str, float],
) -> Iterator[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    x_dataset, y_dataset, snr_dataset = h5_file["X"], h5_file["Y"], h5_file["Z"]
    cursor = 0
    carry: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None
    while cursor < len(indices):
        block_start = (int(indices[cursor]) // read_block_rows) * read_block_rows
        block_end = min(block_start + read_block_rows, int(x_dataset.shape[0]))
        end_cursor = int(np.searchsorted(indices, block_end, side="left"))
        selected_ids = indices[cursor:end_cursor]
        relative = selected_ids - block_start
        started = time.perf_counter()
        raw_x = np.asarray(x_dataset[block_start:block_end])
        raw_y = np.asarray(y_dataset[block_start:block_end])
        raw_snr = np.asarray(snr_dataset[block_start:block_end])
        io_stats["hdf5_read_seconds"] += time.perf_counter() - started
        started = time.perf_counter()
        selected_x = raw_x[relative]
        if input_layout == "NT2":
            selected_x = selected_x.transpose(0, 2, 1)
        elif input_layout != "N2T":
            raise RuntimeError(f"unsupported input layout: {input_layout}")
        selected_x = np.ascontiguousarray(selected_x, dtype=np.float32)
        selected_y = raw_y[relative]
        if selected_y.ndim >= 2 and selected_y.shape[-1] > 1:
            selected_y = np.argmax(selected_y, axis=-1)
        selected_y = np.asarray(selected_y, dtype=np.int64).reshape(-1)
        if raw_label_values is not None:
            mapped_y = np.searchsorted(raw_label_values, selected_y)
            if np.any(mapped_y >= len(raw_label_values)) or np.any(raw_label_values[mapped_y] != selected_y):
                raise RuntimeError("encountered a scalar label outside the frozen mapping")
            selected_y = mapped_y.astype(np.int64, copy=False)
        selected_snr = np.asarray(raw_snr[relative], dtype=np.float32).reshape(-1)
        selected_ids = np.asarray(selected_ids, dtype=np.int64)
        io_stats["preprocess_seconds"] += time.perf_counter() - started
        if carry is not None:
            selected_x = np.concatenate((carry[0], selected_x), axis=0)
            selected_y = np.concatenate((carry[1], selected_y), axis=0)
            selected_snr = np.concatenate((carry[2], selected_snr), axis=0)
            selected_ids = np.concatenate((carry[3], selected_ids), axis=0)
            carry = None
        batch_cursor = 0
        while batch_cursor + batch_size <= len(selected_y):
            next_cursor = batch_cursor + batch_size
            yield (
                selected_x[batch_cursor:next_cursor],
                selected_y[batch_cursor:next_cursor],
                selected_snr[batch_cursor:next_cursor],
                selected_ids[batch_cursor:next_cursor],
            )
            batch_cursor = next_cursor
        if batch_cursor < len(selected_y):
            carry = (
                selected_x[batch_cursor:].copy(),
                selected_y[batch_cursor:].copy(),
                selected_snr[batch_cursor:].copy(),
                selected_ids[batch_cursor:].copy(),
            )
        cursor = end_cursor
    if carry is not None:
        yield carry


def precision_context(precision: str):
    if precision == "fp32":
        return nullcontext()
    dtype = torch.float16 if precision == "fp16" else torch.bfloat16
    return torch.autocast(device_type="cuda", dtype=dtype)


def confusion_metrics(confusion: np.ndarray, labels: list[str]) -> tuple[list[dict[str, Any]], dict[str, float], list[dict[str, Any]]]:
    true_count = confusion.sum(axis=1)
    predicted_count = confusion.sum(axis=0)
    true_positive = np.diag(confusion)
    precision = np.divide(true_positive, predicted_count, out=np.zeros_like(true_positive, dtype=np.float64), where=predicted_count != 0)
    recall = np.divide(true_positive, true_count, out=np.zeros_like(true_positive, dtype=np.float64), where=true_count != 0)
    f1 = np.divide(2.0 * precision * recall, precision + recall, out=np.zeros_like(precision), where=(precision + recall) != 0)
    rows = [
        {
            "class_index": index,
            "class_name": labels[index],
            "support": int(true_count[index]),
            "predicted": int(predicted_count[index]),
            "precision": float(precision[index]),
            "recall": float(recall[index]),
            "f1": float(f1[index]),
        }
        for index in range(len(labels))
    ]
    total = int(true_count.sum())
    aggregate = {
        "accuracy": float(true_positive.sum() / total) if total else 0.0,
        "macro_precision": float(precision.mean()),
        "macro_recall": float(recall.mean()),
        "macro_f1": float(f1.mean()),
        "weighted_f1": float(np.dot(f1, true_count) / total) if total else 0.0,
    }
    off_diagonal = confusion.copy()
    np.fill_diagonal(off_diagonal, 0)
    top = []
    for flat_index in np.argsort(off_diagonal, axis=None)[::-1][:20]:
        true_index, predicted_index = np.unravel_index(flat_index, off_diagonal.shape)
        count = int(off_diagonal[true_index, predicted_index])
        if count == 0:
            break
        top.append(
            {
                "true_index": int(true_index),
                "true_name": labels[true_index],
                "predicted_index": int(predicted_index),
                "predicted_name": labels[predicted_index],
                "count": count,
                "fraction_of_true_class": float(count / true_count[true_index]),
            }
        )
    return rows, aggregate, top


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_confusion(path: Path, confusion: np.ndarray, labels: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["true\\pred", *labels])
        for label, row in zip(labels, confusion.tolist()):
            writer.writerow([label, *row])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, choices=sorted(DATASET_SPECS))
    parser.add_argument("--precision", choices=("fp32", "fp16", "bf16"), default="fp32")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--read-block-rows", type=int, default=4096)
    parser.add_argument("--warmup-batches", type=int, default=5)
    parser.add_argument("--single-sample-repeats", type=int, default=100)
    parser.add_argument("--limit", type=int, default=0, help="Evaluate an evenly spaced N-row subset of the pinned test split")
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument("--hash-dataset", action="store_true", help="Also rehash the multi-GB HDF5 file")
    parser.add_argument("--save-predictions", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.batch_size <= 0 or args.read_block_rows <= 0 or args.warmup_batches < 0 or args.limit < 0:
        raise ValueError("batch size/read block must be positive; warmup/limit must be non-negative")
    if args.single_sample_repeats < 0:
        raise ValueError("single-sample repeats must be non-negative")
    spec = DATASET_SPECS[args.dataset]
    source_root = ASSET_ROOT / "model-source" / MODEL_COMMIT
    checkpoint_dir = Path(spec["checkpoint_dir"])
    checkpoint_path = checkpoint_dir / "best.pt"
    config_path = checkpoint_dir / "config.json"
    reference_metrics_path = checkpoint_dir / "metrics_test.json"
    split_path = Path(spec["split"])
    dataset_path = Path(spec["dataset"])

    print(f"verify model source: {source_root}", flush=True)
    source_manifest = verify_model_source(source_root)
    checkpoint_asset = verify_file(checkpoint_path, spec["checkpoint_sha256"])
    split_asset = verify_file(split_path, spec["split_sha256"])
    if not dataset_path.is_file() or dataset_path.stat().st_size != spec["dataset_bytes"]:
        raise RuntimeError(f"missing or wrong-size dataset: {dataset_path}")
    dataset_asset = {
        "path": str(dataset_path.resolve()),
        "bytes": dataset_path.stat().st_size,
        "expected_sha256": spec["dataset_sha256"],
        "sha256": sha256_file(dataset_path) if args.hash_dataset else None,
        "sha256_recomputed": bool(args.hash_dataset),
    }
    if args.hash_dataset and dataset_asset["sha256"] != spec["dataset_sha256"]:
        raise RuntimeError("dataset SHA-256 mismatch")
    indices = validate_split(split_path, spec, args.limit)

    output_dir = args.output_dir
    if output_dir is None:
        stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
        suffix = f"-{len(indices)}" if args.limit else "-full"
        output_dir = ASSET_ROOT / "results" / args.dataset / f"{stamp}-{args.precision}{suffix}"
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    running_marker = output_dir / "RUNNING"
    running_marker.write_text(f"pid={os.getpid()}\nstarted={datetime.now().astimezone().isoformat()}\n", encoding="utf-8")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    reference_metrics = json.loads(reference_metrics_path.read_text(encoding="utf-8"))
    model_config = config["resolved_config"]["model"]
    if config["selected_model_class"] != "AMCMambaD8" or config["selected_model_variant"] != "amc_mamba_d8":
        raise RuntimeError("checkpoint config is not the pinned D8 model")
    if config["git"]["commit"] != MODEL_COMMIT or config["git"].get("dirty"):
        raise RuntimeError("checkpoint does not point to the pinned clean model commit")
    if int(model_config["num_classes"]) != spec["num_classes"]:
        raise RuntimeError("class count mismatch between dataset and checkpoint")

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    torch.set_grad_enabled(False)

    print("load strict checkpoint", flush=True)
    model_class = load_model_class(source_root)
    constructor_fields = (
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
        num_classes=spec["num_classes"],
        **{name: model_config[name] for name in constructor_fields},
    )
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if checkpoint.get("selected_model_class") != "AMCMambaD8" or checkpoint.get("selected_model_variant") != "amc_mamba_d8":
        raise RuntimeError("checkpoint metadata mismatch")
    model.load_state_dict(checkpoint["model_state"], strict=True)
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    if parameter_count != int(config["model_parameters"]):
        raise RuntimeError(f"parameter count mismatch: {parameter_count} != {config['model_parameters']}")
    if model.encoder.backend != MODEL_BACKEND or not model.encoder.real_mamba_available():
        raise RuntimeError(f"real Mamba backend unavailable: {model.encoder.backend}")
    model = model.eval().cuda()

    confusion = np.zeros((spec["num_classes"], spec["num_classes"]), dtype=np.int64)
    snr_counts: dict[float, list[int]] = defaultdict(lambda: [0, 0])
    confidence_values: list[np.ndarray] = []
    calibration_count = np.zeros(15, dtype=np.int64)
    calibration_correct = np.zeros(15, dtype=np.int64)
    calibration_confidence = np.zeros(15, dtype=np.float64)
    batch_total_ms: list[float] = []
    transfer_ms: list[float] = []
    inference_ms: list[float] = []
    postprocess_ms: list[float] = []
    batch_per_sample_ms: list[float] = []
    all_ids: list[np.ndarray] = []
    all_labels: list[np.ndarray] = []
    all_predictions: list[np.ndarray] = []
    all_snrs: list[np.ndarray] = []
    all_confidence: list[np.ndarray] = []
    io_stats = {"hdf5_read_seconds": 0.0, "preprocess_seconds": 0.0}
    iq_sum = np.zeros(2, dtype=np.float64)
    iq_sum_squares = np.zeros(2, dtype=np.float64)
    iq_min = np.full(2, np.inf, dtype=np.float64)
    iq_max = np.full(2, -np.inf, dtype=np.float64)
    iq_values_per_channel = 0
    sample_for_latency: torch.Tensor | None = None
    total_loss = 0.0
    evaluated = 0
    timed_samples = 0
    batch_index = 0
    temperatures_before = read_temperatures()
    free_cuda_before, total_cuda_memory = torch.cuda.mem_get_info()
    torch.cuda.reset_peak_memory_stats()
    evaluation_started_at = datetime.now().astimezone().isoformat()
    wall_started = time.perf_counter()
    cpu_started = time.process_time()

    with h5py.File(dataset_path, "r") as h5_file:
        labels, label_source, raw_label_values = load_labels(
            args.dataset, h5_file, spec["labels"], spec["num_classes"]
        )
        expected_x_shape = (spec["num_samples"], 1024, 2) if spec["input_layout"] == "NT2" else (spec["num_samples"], 2, 1024)
        if tuple(h5_file["X"].shape) != expected_x_shape or h5_file["X"].dtype != np.dtype("float32"):
            raise RuntimeError(f"unexpected X dataset: {h5_file['X'].shape} {h5_file['X'].dtype}")
        for x_numpy, y_numpy, snr_numpy, ids_numpy in iter_h5_batches(
            h5_file,
            indices,
            spec["input_layout"],
            raw_label_values,
            args.batch_size,
            args.read_block_rows,
            io_stats,
        ):
            if not np.isfinite(x_numpy).all():
                raise RuntimeError("non-finite IQ value encountered")
            iq_sum += x_numpy.sum(axis=(0, 2), dtype=np.float64)
            iq_sum_squares += np.square(x_numpy, dtype=np.float64).sum(axis=(0, 2), dtype=np.float64)
            iq_min = np.minimum(iq_min, x_numpy.min(axis=(0, 2)))
            iq_max = np.maximum(iq_max, x_numpy.max(axis=(0, 2)))
            iq_values_per_channel += int(x_numpy.shape[0] * x_numpy.shape[2])
            cpu_x = torch.from_numpy(x_numpy)
            cpu_y = torch.from_numpy(y_numpy)
            if y_numpy.size == 0 or int(y_numpy.min()) < 0 or int(y_numpy.max()) >= spec["num_classes"]:
                raise RuntimeError("mapped class index is outside the model output range")
            if sample_for_latency is None:
                sample_for_latency = cpu_x[:1].clone()
            batch_started = time.perf_counter()
            start_event = torch.cuda.Event(enable_timing=True)
            transfer_event = torch.cuda.Event(enable_timing=True)
            model_event = torch.cuda.Event(enable_timing=True)
            postprocess_event = torch.cuda.Event(enable_timing=True)
            start_event.record()
            gpu_x = cpu_x.cuda(non_blocking=False)
            gpu_y = cpu_y.cuda(non_blocking=False)
            transfer_event.record()
            with precision_context(args.precision):
                logits = model(gpu_x)
            model_event.record()
            with precision_context(args.precision):
                loss = torch.nn.functional.cross_entropy(logits.float(), gpu_y, reduction="sum")
            probabilities = torch.softmax(logits.float(), dim=1)
            confidence, predictions = probabilities.max(dim=1)
            postprocess_event.record()
            postprocess_event.synchronize()
            current_total_ms = (time.perf_counter() - batch_started) * 1000.0
            current_transfer_ms = float(start_event.elapsed_time(transfer_event))
            current_inference_ms = float(transfer_event.elapsed_time(model_event))
            current_postprocess_ms = float(model_event.elapsed_time(postprocess_event))
            predictions_numpy = predictions.cpu().numpy().astype(np.int64, copy=False)
            confidence_numpy = confidence.cpu().numpy().astype(np.float32, copy=False)
            total_loss += float(loss.item())
            np.add.at(confusion, (y_numpy, predictions_numpy), 1)
            correct_numpy = predictions_numpy == y_numpy
            for snr in np.unique(snr_numpy):
                mask = snr_numpy == snr
                counts = snr_counts[float(snr)]
                counts[0] += int(mask.sum())
                counts[1] += int(correct_numpy[mask].sum())
            bins = np.minimum((confidence_numpy * 15).astype(np.int64), 14)
            np.add.at(calibration_count, bins, 1)
            np.add.at(calibration_correct, bins, correct_numpy.astype(np.int64))
            np.add.at(calibration_confidence, bins, confidence_numpy.astype(np.float64))
            confidence_values.append(confidence_numpy.copy())
            if args.save_predictions:
                all_ids.append(ids_numpy.copy())
                all_labels.append(y_numpy.copy())
                all_predictions.append(predictions_numpy.copy())
                all_snrs.append(snr_numpy.copy())
                all_confidence.append(confidence_numpy.copy())
            if batch_index >= args.warmup_batches:
                batch_total_ms.append(current_total_ms)
                transfer_ms.append(current_transfer_ms)
                inference_ms.append(current_inference_ms)
                postprocess_ms.append(current_postprocess_ms)
                batch_per_sample_ms.append(current_total_ms / len(y_numpy))
                timed_samples += len(y_numpy)
            evaluated += len(y_numpy)
            batch_index += 1
            if args.progress_every and (batch_index % args.progress_every == 0 or evaluated == len(indices)):
                accuracy_so_far = float(np.trace(confusion) / evaluated)
                print(f"progress batches={batch_index} samples={evaluated}/{len(indices)} accuracy={accuracy_so_far:.6f}", flush=True)

    torch.cuda.synchronize()
    evaluation_wall_seconds = time.perf_counter() - wall_started
    process_cpu_seconds = time.process_time() - cpu_started
    single_sample_ms: list[float] = []
    if sample_for_latency is not None and args.single_sample_repeats:
        latency_input = sample_for_latency.cuda(non_blocking=False)
        for _ in range(min(10, args.single_sample_repeats)):
            with precision_context(args.precision):
                model(latency_input)
        torch.cuda.synchronize()
        for _ in range(args.single_sample_repeats):
            started = torch.cuda.Event(enable_timing=True)
            ended = torch.cuda.Event(enable_timing=True)
            started.record()
            with precision_context(args.precision):
                model(latency_input)
            ended.record()
            ended.synchronize()
            single_sample_ms.append(float(started.elapsed_time(ended)))

    temperatures_after = read_temperatures()
    free_cuda_after, _ = torch.cuda.mem_get_info()
    peak_allocated = torch.cuda.max_memory_allocated()
    peak_reserved = torch.cuda.max_memory_reserved()

    per_class, aggregate, top_confusions = confusion_metrics(confusion, labels)
    confidence_flat = np.concatenate(confidence_values) if confidence_values else np.empty(0, dtype=np.float32)
    expected_calibration_error = 0.0
    for count, correct, confidence_sum in zip(calibration_count, calibration_correct, calibration_confidence):
        if count:
            expected_calibration_error += (count / evaluated) * abs((correct / count) - (confidence_sum / count))
    per_snr = [
        {"snr_db": snr, "num_samples": counts[0], "num_correct": counts[1], "accuracy": counts[1] / counts[0]}
        for snr, counts in sorted(snr_counts.items())
    ]
    reference_accuracy = float(reference_metrics["overall_accuracy"])
    reference_macro_f1 = float(reference_metrics["macro_f1"])
    full_split = evaluated == spec["test_samples"]
    report = {
        "schema_version": 1,
        "status": "complete",
        "started_at": evaluation_started_at,
        "completed_at": datetime.now().astimezone().isoformat(),
        "dataset": args.dataset,
        "split": "test",
        "full_split": full_split,
        "num_samples": evaluated,
        "subset_selection": "full" if full_split else "evenly_spaced_test_indices",
        "batch_size": args.batch_size,
        "precision": args.precision,
        "input_contract": {
            "shape": ["batch", 2, 1024],
            "dtype": "float32",
            "source_layout": spec["input_layout"],
            "normalization": "none",
            "denoise": "none",
            "augmentation": "none",
        },
        "model": {
            "class": "AMCMambaD8",
            "variant": "amc_mamba_d8",
            "backend": model.encoder.backend,
            "parameters": parameter_count,
            "source_commit": MODEL_COMMIT,
            "checkpoint": checkpoint_asset,
            "strict_load": True,
        },
        "assets": {
            "dataset": dataset_asset,
            "split": split_asset,
            "model_source": source_manifest,
            "config": {"path": str(config_path.resolve()), "sha256": sha256_file(config_path)},
            "reference_metrics": {"path": str(reference_metrics_path.resolve()), "sha256": sha256_file(reference_metrics_path)},
        },
        "labels": labels,
        "label_source": label_source,
        "metrics": {
            **aggregate,
            "cross_entropy": total_loss / evaluated,
            "top1_confidence_mean": float(confidence_flat.mean()),
            "top1_confidence_p05": float(np.percentile(confidence_flat, 5)),
            "top1_confidence_p50": float(np.percentile(confidence_flat, 50)),
            "top1_confidence_p95": float(np.percentile(confidence_flat, 95)),
            "expected_calibration_error_15_bin": float(expected_calibration_error),
        },
        "reference_comparison": {
            "applicable": full_split and args.precision == "fp32",
            "training_reference_accuracy": reference_accuracy,
            "training_reference_macro_f1": reference_macro_f1,
            "accuracy_delta": aggregate["accuracy"] - reference_accuracy if full_split else None,
            "macro_f1_delta": aggregate["macro_f1"] - reference_macro_f1 if full_split else None,
        },
        "per_class": per_class,
        "per_snr": per_snr,
        "top_confusions": top_confusions,
        "performance": {
            "evaluation_wall_seconds": evaluation_wall_seconds,
            "process_cpu_seconds": process_cpu_seconds,
            "process_cpu_percent_of_one_core": 100.0 * process_cpu_seconds / evaluation_wall_seconds,
            "end_to_end_samples_per_second": evaluated / evaluation_wall_seconds,
            "hdf5_read_seconds": io_stats["hdf5_read_seconds"],
            "preprocess_seconds": io_stats["preprocess_seconds"],
            "timed_batches": len(batch_total_ms),
            "batch_total_ms_p50": percentile(batch_total_ms, 50),
            "batch_total_ms_p99": percentile(batch_total_ms, 99),
            "batch_per_sample_ms_p50": percentile(batch_per_sample_ms, 50),
            "batch_per_sample_ms_p99": percentile(batch_per_sample_ms, 99),
            "h2d_ms_p50": percentile(transfer_ms, 50),
            "h2d_ms_p99": percentile(transfer_ms, 99),
            "inference_ms_p50": percentile(inference_ms, 50),
            "inference_ms_p99": percentile(inference_ms, 99),
            "postprocess_ms_p50": percentile(postprocess_ms, 50),
            "postprocess_ms_p99": percentile(postprocess_ms, 99),
            "inference_samples_per_second": 0.0,
            "single_sample_repeats": len(single_sample_ms),
            "single_sample_inference_ms_p50": percentile(single_sample_ms, 50),
            "single_sample_inference_ms_p99": percentile(single_sample_ms, 99),
        },
        "resources": {
            "cuda_peak_allocated_bytes": peak_allocated,
            "cuda_peak_reserved_bytes": peak_reserved,
            "cuda_global_free_bytes_before": free_cuda_before,
            "cuda_global_free_bytes_after": free_cuda_after,
            "cuda_global_total_bytes": total_cuda_memory,
            "process_max_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "temperatures_c_before": temperatures_before,
            "temperatures_c_after": temperatures_after,
            "load_average_after": list(os.getloadavg()),
        },
        "input_statistics": {
            "channel_mean": (iq_sum / iq_values_per_channel).tolist(),
            "channel_rms": np.sqrt(iq_sum_squares / iq_values_per_channel).tolist(),
            "channel_min": iq_min.tolist(),
            "channel_max": iq_max.tolist(),
        },
        "runtime": {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "torch": torch.__version__,
            "torch_cuda": torch.version.cuda,
            "cudnn": torch.backends.cudnn.version(),
            "mamba_ssm": package_version("mamba-ssm"),
            "causal_conv1d": package_version("causal-conv1d"),
            "triton": package_version("triton"),
            "transformers": package_version("transformers"),
            "huggingface_hub": package_version("huggingface-hub"),
            "cuda_device": torch.cuda.get_device_name(0),
            "cuda_capability": list(torch.cuda.get_device_capability(0)),
            "tf32_enabled": torch.backends.cuda.matmul.allow_tf32,
        },
    }
    if inference_ms and sum(inference_ms) > 0:
        report["performance"]["inference_samples_per_second"] = timed_samples / (sum(inference_ms) / 1000.0)

    (output_dir / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(output_dir / "per-class.csv", per_class)
    write_csv(output_dir / "per-snr.csv", per_snr)
    write_csv(output_dir / "top-confusions.csv", top_confusions)
    write_confusion(output_dir / "confusion-matrix.csv", confusion, labels)
    if args.save_predictions:
        np.savez_compressed(
            output_dir / "predictions.npz",
            sample_id=np.concatenate(all_ids),
            expected=np.concatenate(all_labels),
            predicted=np.concatenate(all_predictions),
            snr_db=np.concatenate(all_snrs),
            confidence=np.concatenate(all_confidence),
        )
    running_marker.unlink()
    print(json.dumps({"output_dir": str(output_dir), "metrics": report["metrics"], "performance": report["performance"]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
