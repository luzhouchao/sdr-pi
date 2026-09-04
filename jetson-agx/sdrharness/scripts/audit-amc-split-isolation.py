#!/usr/bin/env python3
"""Audit frozen AMC splits and P201 corpus lineage without training a model."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ASSET_ROOT = REPO_ROOT / "local-assets" / "amc-eval"
DEFAULT_ASSET_MANIFEST = DEFAULT_ASSET_ROOT / "ASSET_MANIFEST.json"
DEFAULT_CORPUS_ROOT = Path("/var/lib/sdrharness/web-console/p201-corpus")
DEFAULT_CONTRACT_VALIDATOR = (
    REPO_ROOT / "jetson-agx" / "sdrharness" / "scripts" / "validate-amc-corpus-manifest.py"
)
DEFAULT_CORPUS_SCHEMA = (
    REPO_ROOT
    / "jetson-agx"
    / "sdrharness"
    / "config"
    / "amc"
    / "amc-corpus-manifest-v1.schema.json"
)

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_RECORD_LINE_BYTES = 64 * 1024
EVALUATION_SPLITS = ("train", "validation", "test")
NPZ_SPLIT_KEYS = ("train", "val", "test")
NPZ_TO_CANONICAL = {"train": "train", "val": "validation", "test": "test"}
SPLIT_CODES = {"train": 1, "validation": 2, "test": 3}

DATASET_SPECS: dict[str, dict[str, Any]] = {
    "rml2018a": {
        "dataset_id": "rml2018a-2018.01a",
        "dataset_asset": "rml2018a_dataset",
        "split_asset": "rml2018a_split",
        "checkpoint_config": "checkpoints/rml2018a/seed44/config.json",
        "num_samples": 2_555_904,
        "seed": 44,
        "ratios": (0.7, 0.15, 0.15),
        "hdf5": {
            "X": ((2_555_904, 1024, 2), "float32"),
            "Y": ((2_555_904, 24), "int64"),
            "Z": ((2_555_904, 1), "int64"),
        },
    },
    "hisarmod2019": {
        "dataset_id": "hisarmod2019-2019.01",
        "dataset_asset": "hisarmod2019_dataset",
        "split_asset": "hisarmod2019_split",
        "checkpoint_config": "checkpoints/hisarmod2019/seed43/config.json",
        "num_samples": 780_000,
        "seed": 43,
        "ratios": (0.7, 0.15, 0.15),
        "hdf5": {
            "X": ((780_000, 2, 1024), "float32"),
            "Y": ((780_000,), "int64"),
            "Z": ((780_000,), "float32"),
            "classes": ((26,), "object"),
        },
    },
}


class IsolationError(Exception):
    """A fail-closed split or lineage audit error."""

    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(f"{code}: {path}: {message}")
        self.code = code
        self.path = path
        self.message = message


def fail(code: str, path: str, message: str) -> None:
    raise IsolationError(code, path, message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        fail("file", str(path), str(error))
    return digest.hexdigest()


def strict_json(payload: bytes, path: str) -> Any:
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
        return strict_json(path.read_bytes(), str(path))
    except OSError as error:
        fail("file", str(path), str(error))


def resolve_asset(root: Path, relative: str, field: str) -> Path:
    if not isinstance(relative, str):
        fail("manifest", field, "path must be text")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != relative:
        fail("path", field, "must be a normalized relative path without traversal")
    lexical = root / candidate
    try:
        metadata = lexical.lstat()
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        fail("path", field, str(error))
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        fail("file", field, "must resolve to a non-symlink regular file")
    return resolved


def load_asset_manifest(path: Path, asset_root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    value = read_json(path)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        fail("manifest", str(path), "unsupported asset manifest")
    assets = value.get("assets")
    if not isinstance(assets, dict):
        fail("manifest", "assets", "must be an object")
    required = {
        spec[field]
        for spec in DATASET_SPECS.values()
        for field in ("dataset_asset", "split_asset")
    }
    if missing := sorted(required - set(assets)):
        fail("manifest", "assets", f"missing required entries {missing}")
    selected: dict[str, dict[str, Any]] = {}
    for name in sorted(required):
        descriptor = assets[name]
        if not isinstance(descriptor, dict) or set(descriptor) != {"path", "bytes", "sha256"}:
            fail("manifest", f"assets.{name}", "must contain exactly path/bytes/sha256")
        expected_bytes = descriptor["bytes"]
        expected_hash = descriptor["sha256"]
        if type(expected_bytes) is not int or expected_bytes <= 0:
            fail("manifest", f"assets.{name}.bytes", "must be a positive integer")
        if (
            not isinstance(expected_hash, str)
            or len(expected_hash) != 64
            or any(character not in "0123456789abcdef" for character in expected_hash)
        ):
            fail("manifest", f"assets.{name}.sha256", "must be a lowercase SHA-256")
        resolved = resolve_asset(asset_root, descriptor["path"], f"assets.{name}.path")
        if resolved.stat().st_size != expected_bytes:
            fail("asset", f"assets.{name}.bytes", "file size differs from the manifest")
        selected[name] = {**descriptor, "resolved": resolved}
    return selected, {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def verify_selected_assets(
    assets: dict[str, dict[str, Any]], verify_dataset_hashes: bool
) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for name, descriptor in assets.items():
        is_dataset = name.endswith("_dataset")
        if is_dataset and not verify_dataset_hashes:
            results[name] = False
            continue
        actual = sha256_file(descriptor["resolved"])
        if actual != descriptor["sha256"]:
            fail("asset", f"assets.{name}.sha256", f"expected {descriptor['sha256']}, got {actual}")
        results[name] = True
    return results


def inspect_hdf5(path: Path, expected: dict[str, tuple[tuple[int, ...], str]]) -> dict[str, Any]:
    try:
        import h5py  # type: ignore
    except ImportError as error:
        fail("dependency", "h5py", f"use the AMC runtime environment: {error}")
    datasets: dict[str, Any] = {}
    try:
        with h5py.File(path, "r") as container:
            if set(container.keys()) != set(expected):
                fail(
                    "dataset",
                    str(path),
                    f"top-level keys differ: expected {sorted(expected)}, got {sorted(container.keys())}",
                )
            for name, (shape, dtype) in expected.items():
                item = container[name]
                actual_shape = tuple(int(value) for value in item.shape)
                actual_dtype = str(item.dtype)
                if actual_shape != shape or actual_dtype != dtype:
                    fail(
                        "dataset",
                        f"{path}:{name}",
                        f"expected shape/dtype {shape}/{dtype}, got {actual_shape}/{actual_dtype}",
                    )
                datasets[name] = {"shape": list(actual_shape), "dtype": actual_dtype}
    except OSError as error:
        fail("dataset", str(path), str(error))
    return datasets


def _one_scalar(array: np.ndarray, field: str, kind: str) -> int | float:
    if array.shape != (1,) or array.dtype.kind not in kind:
        fail("split_metadata", field, f"must be one scalar with dtype kind {kind!r}")
    value = array[0]
    return int(value) if array.dtype.kind in "iu" else float(value)


def audit_partition_arrays(
    arrays: dict[str, np.ndarray],
    *,
    dataset_id: str,
    dataset_sha256: str,
    num_samples: int,
    expected_seed: int,
    expected_ratios: tuple[float, float, float],
) -> dict[str, Any]:
    required = set(NPZ_SPLIT_KEYS) | {
        "num_samples",
        "train_ratio",
        "val_ratio",
        "test_ratio",
        "seed",
    }
    if set(arrays) != required:
        fail("split_keys", dataset_id, f"expected {sorted(required)}, got {sorted(arrays)}")
    declared_samples = _one_scalar(arrays["num_samples"], f"{dataset_id}.num_samples", "iu")
    declared_seed = _one_scalar(arrays["seed"], f"{dataset_id}.seed", "iu")
    if declared_samples != num_samples or declared_seed != expected_seed:
        fail(
            "split_metadata",
            dataset_id,
            f"expected samples/seed {num_samples}/{expected_seed}, got {declared_samples}/{declared_seed}",
        )
    actual_ratios = tuple(
        float(_one_scalar(arrays[name], f"{dataset_id}.{name}", "f"))
        for name in ("train_ratio", "val_ratio", "test_ratio")
    )
    if any(
        not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12)
        for actual, expected in zip(actual_ratios, expected_ratios)
    ):
        fail("split_metadata", dataset_id, f"unexpected ratios {actual_ratios}")

    assignment = np.zeros(num_samples, dtype=np.uint8)
    split_summaries: dict[str, Any] = {}
    for npz_name in NPZ_SPLIT_KEYS:
        canonical = NPZ_TO_CANONICAL[npz_name]
        indices = arrays[npz_name]
        field = f"{dataset_id}.{npz_name}"
        if indices.ndim != 1 or indices.dtype != np.dtype("int64"):
            fail("split_shape", field, f"must be a one-dimensional int64 array, got {indices.shape}/{indices.dtype}")
        if indices.size == 0:
            fail("split_shape", field, "must not be empty")
        if int(indices[0]) < 0 or int(indices[-1]) >= num_samples:
            fail("split_range", field, f"indices must be in [0, {num_samples})")
        if np.any(indices[1:] <= indices[:-1]):
            fail("split_duplicate", field, "indices must be unique and strictly increasing")
        occupied = assignment[indices]
        if np.any(occupied != 0):
            first_position = int(np.flatnonzero(occupied != 0)[0])
            row = int(indices[first_position])
            prior_code = int(occupied[first_position])
            prior = next(name for name, code in SPLIT_CODES.items() if code == prior_code)
            fail("split_leak", field, f"global row {row} appears in both {prior} and {canonical}")
        assignment[indices] = SPLIT_CODES[canonical]
        canonical_i64 = np.asarray(indices, dtype="<i8")
        split_summaries[canonical] = {
            "count": int(indices.size),
            "first_global_row": int(indices[0]),
            "last_global_row": int(indices[-1]),
            "indices_le_i64_sha256": hashlib.sha256(canonical_i64.tobytes()).hexdigest(),
            "internal_duplicate_count": 0,
        }

    missing = np.flatnonzero(assignment == 0)
    if missing.size:
        fail(
            "split_coverage",
            dataset_id,
            f"{missing.size} global rows are absent; first missing row is {int(missing[0])}",
        )
    identity_prefix = f"{dataset_id}-{dataset_sha256}-X-row"
    lineage_digest = hashlib.sha256()
    lineage_digest.update(b"amc-offline-lineage-assignment-v1\0")
    lineage_digest.update(dataset_sha256.encode("ascii"))
    lineage_digest.update(b"\0/X\0")
    lineage_digest.update(assignment.tobytes())
    return {
        "num_samples": num_samples,
        "seed": expected_seed,
        "declared_ratios": list(actual_ratios),
        "splits": split_summaries,
        "pairwise_intersection_counts": {
            "train_validation": 0,
            "train_test": 0,
            "validation_test": 0,
        },
        "union_count": int(np.count_nonzero(assignment)),
        "missing_count": 0,
        "assignment_u8_codes": SPLIT_CODES,
        "assignment_sha256": hashlib.sha256(assignment.tobytes()).hexdigest(),
        "lineage_assignment_sha256": lineage_digest.hexdigest(),
        "source_identity": {
            "scheme": "dataset_sha256+hdf5_dataset_path+global_row_v1",
            "hdf5_dataset_path": "/X",
            "template": identity_prefix + "-{global_row:010d}",
            "first": identity_prefix + "-0000000000",
            "last": identity_prefix + f"-{num_samples - 1:010d}",
            "derivatives_must_inherit_source_sample_id": True,
        },
    }


def audit_split_file(path: Path, spec: dict[str, Any], dataset_sha256: str) -> dict[str, Any]:
    try:
        with np.load(path, allow_pickle=False) as archive:
            arrays = {name: np.asarray(archive[name]) for name in archive.files}
    except (OSError, ValueError, KeyError) as error:
        fail("split_file", str(path), str(error))
    return audit_partition_arrays(
        arrays,
        dataset_id=spec["dataset_id"],
        dataset_sha256=dataset_sha256,
        num_samples=spec["num_samples"],
        expected_seed=spec["seed"],
        expected_ratios=spec["ratios"],
    )


def audit_training_config(path: Path, dataset_name: str, spec: dict[str, Any]) -> dict[str, Any]:
    value = read_json(path)
    try:
        data = value["train_constants"]["data"]
        train = value["train_constants"]["training_strategy"]
    except (KeyError, TypeError) as error:
        fail("training_config", str(path), f"missing field {error}")
    expected_data = {
        "dataset_name": dataset_name,
        "seq_len": 1024,
        "seed": spec["seed"],
        "train_ratio": spec["ratios"][0],
        "val_ratio": spec["ratios"][1],
        "test_ratio": spec["ratios"][2],
    }
    for field, expected in expected_data.items():
        if data.get(field) != expected:
            fail("training_config", f"{path}.{field}", f"expected {expected!r}, got {data.get(field)!r}")
    disabled = {
        "denoise_enabled": data.get("denoise_enabled"),
        "iq_aug_enabled": train.get("iq_aug_enabled"),
        "low_snr_vcreg_enabled": train.get("use_low_snr_vcreg_loss"),
        "low_snr_view_consistency_enabled": train.get("use_low_snr_view_consistency_loss"),
        "ss_enabled": train.get("ss_enabled"),
        "time_mask_enabled": train.get("time_mask_enabled"),
    }
    if any(value is not False for value in disabled.values()):
        fail("training_config", str(path), f"retained baseline enables a derived view: {disabled}")
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "sequence_samples": 1024,
        "declared_derived_view_flags": disabled,
        "declared_derived_views_enabled": [],
    }


def audit_lineage_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_id: dict[str, dict[str, Any]] = {}
    group_owners: dict[str, dict[str, str]] = {
        "source_sample_id": {},
        "capture_session_id": {},
        "capture_day": {},
    }
    split_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    provenance_counts: dict[str, int] = {}
    receive_domain_unknown_count = 0
    evaluation_record_count = 0
    derived_record_count = 0

    for index, record in enumerate(records):
        path = f"records[{index}]"
        try:
            record_id = record["record_id"]
            split = record["split"]
            lineage = record["lineage"]
            source_kind = record["source"]["kind"]
            provenance = record["label"]["provenance"]
        except (KeyError, TypeError) as error:
            fail("lineage", path, f"missing field {error}")
        if not isinstance(record_id, str) or not record_id:
            fail("lineage", f"{path}.record_id", "must be non-empty text")
        if record_id in by_id:
            fail("duplicate", f"{path}.record_id", f"record {record_id!r} is duplicated across packages")
        by_id[record_id] = record
        split_counts[split] = split_counts.get(split, 0) + 1
        source_counts[source_kind] = source_counts.get(source_kind, 0) + 1
        provenance_counts[provenance] = provenance_counts.get(provenance, 0) + 1

        if source_kind == "p201_receive" and provenance == "unknown":
            if split != "receive_domain":
                fail(
                    "accuracy_leak",
                    f"{path}.split",
                    "an unknown P201 reception must remain receive_domain and cannot enter train/validation/test",
                )
            receive_domain_unknown_count += 1
        if split in EVALUATION_SPLITS:
            evaluation_record_count += 1
            for group_key, owners in group_owners.items():
                group_value = lineage.get(group_key)
                if group_value is None:
                    continue
                if not isinstance(group_value, str) or not group_value:
                    fail("lineage", f"{path}.lineage.{group_key}", "must be null or non-empty text")
                prior = owners.setdefault(group_value, split)
                if prior != split:
                    fail(
                        "split_leak",
                        f"{path}.lineage.{group_key}",
                        f"group {group_value!r} appears in both {prior} and {split}",
                    )

    for record_id, record in by_id.items():
        lineage = record["lineage"]
        parent_id = lineage.get("parent_record_id")
        if parent_id is None:
            continue
        derived_record_count += 1
        if parent_id not in by_id:
            fail("lineage", f"{record_id}.parent_record_id", f"parent {parent_id!r} is absent")
        if not lineage.get("transforms"):
            fail("lineage", f"{record_id}.transforms", "a derived record must name at least one transform")
        parent_lineage = by_id[parent_id]["lineage"]
        for key in ("source_sample_id", "capture_session_id", "capture_day"):
            if lineage.get(key) != parent_lineage.get(key):
                fail(
                    "lineage",
                    f"{record_id}.{key}",
                    f"derived record must inherit {key} from parent {parent_id!r}",
                )

    for start in by_id:
        seen: set[str] = set()
        cursor: str | None = start
        while cursor is not None:
            if cursor in seen:
                fail("lineage_cycle", start, f"parent cycle reaches {cursor!r}")
            seen.add(cursor)
            parent = by_id[cursor]["lineage"].get("parent_record_id")
            cursor = parent

    return {
        "record_count": len(records),
        "evaluation_record_count": evaluation_record_count,
        "derived_record_count": derived_record_count,
        "split_counts": dict(sorted(split_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "label_provenance_counts": dict(sorted(provenance_counts.items())),
        "receive_domain_unknown_count": receive_domain_unknown_count,
        "unknown_p201_evaluation_count": 0,
        "cross_split_group_collision_counts": {
            "source_sample_id": 0,
            "capture_session_id": 0,
            "capture_day": 0,
        },
        "derived_lineage_inheritance": "verified",
    }


def load_contract_validator(path: Path):
    specification = importlib.util.spec_from_file_location("amc_corpus_contract_for_isolation", path)
    if specification is None or specification.loader is None:
        fail("dependency", str(path), "cannot load corpus contract validator")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def read_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("rb") as stream:
            for index, line in enumerate(stream):
                if len(line) > MAX_RECORD_LINE_BYTES:
                    fail("record_index", f"{path}:{index + 1}", "line exceeds 64 KiB")
                value = strict_json(line, f"{path}:{index + 1}")
                if not isinstance(value, dict):
                    fail("record_index", f"{path}:{index + 1}", "record must be an object")
                records.append(value)
    except OSError as error:
        fail("record_index", str(path), str(error))
    return records


def audit_p201_corpus(
    root: Path,
    validator_path: Path,
    schema_path: Path,
    verify_assets: bool,
) -> dict[str, Any]:
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as error:
        fail("p201_corpus", str(root), str(error))
    if not resolved_root.is_dir():
        fail("p201_corpus", str(root), "must be a directory")
    contract = load_contract_validator(validator_path)
    schema = contract.read_bounded_json(schema_path, contract.MAX_SCHEMA_BYTES, "schema")

    def snapshot() -> list[str]:
        names: list[str] = []
        for child in resolved_root.iterdir():
            metadata = child.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                fail("p201_corpus", str(child), "root children must be non-symlink package directories")
            names.append(child.name)
        return sorted(names)

    package_names = snapshot()
    packages: list[dict[str, Any]] = []
    all_records: list[dict[str, Any]] = []
    for name in package_names:
        package = resolved_root / name
        manifest_path = package / "manifest.json"
        manifest = contract.read_bounded_json(manifest_path, contract.MAX_MANIFEST_BYTES, "manifest")
        try:
            contract_summary = contract.validate_manifest(manifest, schema, package, verify_assets)
        except contract.ContractError as error:
            fail("corpus_contract", str(manifest_path), str(error))
        if contract_summary["status"] != "frozen" or contract_summary["corpus_kind"] != "p201_receive":
            fail("p201_corpus", str(manifest_path), "stored packages must be frozen p201_receive corpora")
        records_path = package / manifest["record_index"]["path"]
        records = read_records(records_path)
        if len(records) != contract_summary["record_count"]:
            fail("record_index", str(records_path), "record count changed after contract validation")
        all_records.extend(records)
        packages.append(
            {
                "package": name,
                "manifest_id": contract_summary["manifest_id"],
                "manifest_sha256": sha256_file(manifest_path),
                "record_index_sha256": manifest["record_index"]["sha256"],
                "record_count": contract_summary["record_count"],
                "assets_verified": contract_summary["assets_verified"],
            }
        )
    if snapshot() != package_names:
        fail("p201_corpus", str(root), "package set changed during the audit")
    lineage = audit_lineage_records(all_records)
    return {
        "root": str(resolved_root),
        "package_count": len(packages),
        "packages": packages,
        "all_package_assets_verified": verify_assets,
        **lineage,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", type=Path, default=DEFAULT_ASSET_ROOT)
    parser.add_argument("--asset-manifest", type=Path, default=DEFAULT_ASSET_MANIFEST)
    parser.add_argument("--p201-corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    parser.add_argument("--corpus-validator", type=Path, default=DEFAULT_CONTRACT_VALIDATOR)
    parser.add_argument("--corpus-schema", type=Path, default=DEFAULT_CORPUS_SCHEMA)
    parser.add_argument("--audit-id", default="amc-split-isolation-20260905")
    parser.add_argument("--verify-dataset-hashes", action="store_true")
    parser.add_argument("--skip-p201-asset-hashes", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    try:
        asset_root = args.asset_root.resolve(strict=True)
    except OSError as error:
        fail("asset_root", str(args.asset_root), str(error))
    if not asset_root.is_dir():
        fail("asset_root", str(asset_root), "must be a directory")
    assets, asset_manifest_summary = load_asset_manifest(args.asset_manifest, asset_root)
    verified = verify_selected_assets(assets, args.verify_dataset_hashes)
    datasets: list[dict[str, Any]] = []
    for name, spec in DATASET_SPECS.items():
        dataset = assets[spec["dataset_asset"]]
        split = assets[spec["split_asset"]]
        dataset_summary = {
            "name": name,
            "dataset_id": spec["dataset_id"],
            "dataset_asset": {
                "path": dataset["path"],
                "bytes": dataset["bytes"],
                "sha256": dataset["sha256"],
                "hash_verified_now": verified[spec["dataset_asset"]],
                "hdf5_datasets": inspect_hdf5(dataset["resolved"], spec["hdf5"]),
                "latent_generator_parent_id_available": False,
                "auditable_source_boundary": "one immutable /X global row",
            },
            "split_asset": {
                "path": split["path"],
                "bytes": split["bytes"],
                "sha256": split["sha256"],
                "hash_verified_now": verified[spec["split_asset"]],
                **audit_split_file(split["resolved"], spec, dataset["sha256"]),
            },
            "retained_training_config": audit_training_config(
                resolve_asset(asset_root, spec["checkpoint_config"], f"{name}.checkpoint_config"),
                name,
                spec,
            ),
        }
        datasets.append(dataset_summary)
    p201 = audit_p201_corpus(
        args.p201_corpus_root,
        args.corpus_validator,
        args.corpus_schema,
        not args.skip_p201_asset_hashes,
    )
    return {
        "schema_version": 1,
        "schema_id": "amc_split_isolation_audit_v1",
        "audit_id": args.audit_id,
        "audited_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "status": "pass",
        "scope": {
            "training_performed": False,
            "checkpoint_changed": False,
            "radio_capture_performed": False,
            "transmission_performed": False,
            "fpga_used": False,
        },
        "policy": {
            "evaluation_splits": list(EVALUATION_SPLITS),
            "exclusive_group_keys": ["source_sample_id", "capture_session_id", "capture_day"],
            "capture_day_timezone": "UTC",
            "derived_records_inherit_all_lineage_keys": True,
            "unknown_p201_split": "receive_domain",
            "unknown_p201_accuracy_allowed": False,
        },
        "asset_manifest": asset_manifest_summary,
        "dataset_hashes_verified_now": args.verify_dataset_hashes,
        "datasets": datasets,
        "p201_corpus": p201,
        "conclusion": {
            "offline_train_validation_test_complete_and_disjoint": True,
            "offline_source_identity_frozen_by_global_row": True,
            "retained_training_configs_enable_no_derived_views": True,
            "p201_cross_package_group_isolation": True,
            "p201_unknown_rows_excluded_from_accuracy_splits": True,
        },
    }


def main() -> int:
    os.umask(0o077)
    args = parse_args()
    try:
        summary = run(args)
        payload = json.dumps(summary, sort_keys=True, indent=2) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if args.output.exists():
                fail("output", str(args.output), "refusing to overwrite an existing audit")
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(payload)
            args.output.chmod(0o600)
        else:
            print(payload, end="")
    except IsolationError as error:
        print(f"isolation_error={error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
