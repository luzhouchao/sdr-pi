#!/usr/bin/env python3
"""Validate the versioned AMC corpus manifest and its JSONL window index."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SCHEMA = (
    REPO_ROOT
    / "jetson-agx"
    / "sdrharness"
    / "config"
    / "amc"
    / "amc-corpus-manifest-v1.schema.json"
)
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_SCHEMA_BYTES = 2 * 1024 * 1024
MAX_RECORD_LINE_BYTES = 64 * 1024
MAX_RECORD_INDEX_BYTES = 64 * 1024 * 1024 * 1024
MAX_RECORDS = 10_000_000
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RELATIVE_PATH = re.compile(r"^[A-Za-z0-9._/-]{1,512}$")
DATASET_PATH = re.compile(r"^/[A-Za-z0-9._/-]{1,255}$")
EVALUATION_SPLITS = {"train", "validation", "test", "calibration", "acceptance"}
SPLITS = EVALUATION_SPLITS | {"calibration", "receive_domain", "golden"}
SOURCE_KINDS = {"offline_dataset", "p201_receive", "golden_vector"}
PROVENANCE = {"dataset_ground_truth", "independent_annotation", "unknown"}

MANIFEST_KEYS = {
    "schema_version",
    "schema_id",
    "manifest_id",
    "created_at_utc",
    "status",
    "corpus_kind",
    "contract",
    "split_policy",
    "assets",
    "record_index",
    "governance",
}
RECORD_KEYS = {
    "schema_version",
    "schema_id",
    "record_id",
    "split",
    "lineage",
    "window",
    "label",
    "source",
}


class ContractError(Exception):
    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(f"{code}: {path}: {message}")
        self.code = code
        self.path = path
        self.message = message


def fail(code: str, path: str, message: str) -> None:
    raise ContractError(code, path, message)


def reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def parse_json_bytes(payload: bytes, path: str) -> Any:
    try:
        text = payload.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        fail("json", path, str(error))


def read_bounded_json(path: Path, maximum_bytes: int, field: str) -> Any:
    try:
        metadata = path.lstat()
    except OSError as error:
        fail("file", field, str(error))
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        fail("file", field, "must be a non-symlink regular file")
    if metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
        fail("file", field, f"byte count must be in [1, {maximum_bytes}]")
    try:
        return parse_json_bytes(path.read_bytes(), field)
    except OSError as error:
        fail("file", field, str(error))


def exact_object(value: Any, expected: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail("shape", path, "must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        fail("shape", path, f"keys mismatch; missing={missing}, unknown={unknown}")
    return value


def require_list(value: Any, path: str, minimum: int, maximum: int) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        fail("value", path, f"must be an array with {minimum} to {maximum} entries")
    return value


def require_bool(value: Any, path: str, expected: bool | None = None) -> bool:
    if type(value) is not bool or (expected is not None and value is not expected):
        suffix = "" if expected is None else f" equal to {expected}"
        fail("value", path, f"must be boolean{suffix}")
    return value


def require_int(value: Any, path: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        fail("value", path, f"must be an integer in [{minimum}, {maximum}]")
    return value


def require_number(value: Any, path: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("value", path, "must be numeric")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        fail("value", path, f"must be finite and in [{minimum}, {maximum}]")
    return number


def require_text(value: Any, path: str, maximum_bytes: int = 512) -> str:
    if not isinstance(value, str):
        fail("value", path, "must be text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeError as error:
        fail("value", path, str(error))
    if not encoded or len(encoded) > maximum_bytes or not value.isprintable():
        fail("value", path, f"must contain 1 to {maximum_bytes} printable UTF-8 bytes")
    return value


def require_enum(value: Any, choices: set[str], path: str) -> str:
    text = require_text(value, path, 128)
    if text not in choices:
        fail("value", path, f"must be one of {sorted(choices)}")
    return text


def require_id(value: Any, path: str) -> str:
    text = require_text(value, path, 128)
    if SAFE_ID.fullmatch(text) is None:
        fail("value", path, "must be a safe identifier")
    return text


def require_sha256(value: Any, path: str) -> str:
    text = require_text(value, path, 64)
    if SHA256.fullmatch(text) is None:
        fail("value", path, "must be a lowercase SHA-256")
    return text


def require_relative_path(value: Any, path: str) -> str:
    text = require_text(value, path, 512)
    candidate = Path(text)
    if (
        RELATIVE_PATH.fullmatch(text) is None
        or candidate.is_absolute()
        or ".." in candidate.parts
        or "." in candidate.parts
        or candidate.as_posix() != text
    ):
        fail("path", path, "must be a normalized relative path without traversal")
    return text


def require_utc_timestamp(value: Any, path: str) -> str:
    text = require_text(value, path, 64)
    if not text.endswith("Z"):
        fail("value", path, "must use an explicit UTC Z suffix")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        fail("value", path, str(error))
    if parsed.tzinfo != timezone.utc:
        fail("value", path, "must be UTC")
    return text


def require_date(value: Any, path: str) -> str:
    text = require_text(value, path, 10)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        fail("value", path, str(error))
    if parsed.isoformat() != text:
        fail("value", path, "must be YYYY-MM-DD")
    return text


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        fail("asset", str(path), str(error))
    return digest.hexdigest()


def resolve_regular_file(root: Path, relative: str, field: str) -> Path:
    lexical = root / relative
    try:
        metadata = lexical.lstat()
        resolved = lexical.resolve(strict=True)
    except OSError as error:
        fail("asset", field, str(error))
    try:
        resolved.relative_to(root)
    except ValueError:
        fail("path", field, "resolved outside the asset root")
    if stat.S_ISLNK(metadata.st_mode) or not resolved.is_file():
        fail("asset", field, "must resolve to a non-symlink regular file")
    return resolved


def validate_schema(schema: Any) -> None:
    if not isinstance(schema, dict):
        fail("schema", "schema", "must be an object")
    if schema.get("$id") != "https://sdrharness.local/schemas/amc-corpus-manifest-v1.schema.json":
        fail("schema", "schema.$id", "unexpected schema identity")
    if schema.get("additionalProperties") is not False:
        fail("schema", "schema.additionalProperties", "must remain false")
    if set(schema.get("required", [])) != MANIFEST_KEYS:
        fail("schema", "schema.required", "manifest keys drifted from the validator")
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        fail("schema", "schema.$defs", "definitions are absent")
    record = definitions.get("record")
    if not isinstance(record, dict) or set(record.get("required", [])) != RECORD_KEYS:
        fail("schema", "schema.$defs.record", "record keys drifted from the validator")
    schema_provenance = {
        definitions.get(name, {}).get("properties", {}).get("provenance", {}).get("const")
        for name in ("datasetGroundTruth", "independentAnnotation", "unknownLabel")
    }
    if schema_provenance != PROVENANCE:
        fail("schema", "schema.$defs.label", "label provenance values drifted")


def validate_contract(value: Any) -> dict[str, dict[str, Any]]:
    contract = exact_object(value, {"input_profile", "preprocessing", "label_space"}, "contract")
    profile = exact_object(
        contract["input_profile"], {"id", "path", "sha256", "admission"}, "contract.input_profile"
    )
    require_id(profile["id"], "contract.input_profile.id")
    require_relative_path(profile["path"], "contract.input_profile.path")
    require_sha256(profile["sha256"], "contract.input_profile.sha256")
    require_enum(profile["admission"], {"integration_only", "production"}, "contract.input_profile.admission")

    preprocessing = exact_object(
        contract["preprocessing"], {"id", "path", "sha256", "status"}, "contract.preprocessing"
    )
    require_id(preprocessing["id"], "contract.preprocessing.id")
    require_relative_path(preprocessing["path"], "contract.preprocessing.path")
    require_sha256(preprocessing["sha256"], "contract.preprocessing.sha256")
    require_enum(preprocessing["status"], {"integration_only", "frozen"}, "contract.preprocessing.status")

    labels = exact_object(
        contract["label_space"],
        {"id", "path", "sha256", "numeric_ids_authoritative", "display_names_status"},
        "contract.label_space",
    )
    require_id(labels["id"], "contract.label_space.id")
    require_relative_path(labels["path"], "contract.label_space.path")
    require_sha256(labels["sha256"], "contract.label_space.sha256")
    require_bool(labels["numeric_ids_authoritative"], "contract.label_space.numeric_ids_authoritative", True)
    require_enum(labels["display_names_status"], {"trusted", "provisional"}, "contract.label_space.display_names_status")
    return contract


def validate_split_policy(value: Any, status: str) -> set[str]:
    policy = exact_object(
        value,
        {"strategy", "group_keys", "allowed_splits", "frozen", "test_locked"},
        "split_policy",
    )
    if policy["strategy"] != "group_exclusive":
        fail("value", "split_policy.strategy", "must be group_exclusive")
    if policy["group_keys"] != ["source_sample_id", "capture_session_id", "capture_day"]:
        fail("value", "split_policy.group_keys", "must contain the three frozen lineage keys in order")
    allowed_list = require_list(policy["allowed_splits"], "split_policy.allowed_splits", 1, 7)
    allowed = {require_enum(value, SPLITS, "split_policy.allowed_splits[]") for value in allowed_list}
    if len(allowed) != len(allowed_list):
        fail("value", "split_policy.allowed_splits", "must not contain duplicates")
    frozen = require_bool(policy["frozen"], "split_policy.frozen")
    test_locked = require_bool(policy["test_locked"], "split_policy.test_locked")
    if status == "frozen" and (not frozen or not test_locked):
        fail("governance", "split_policy", "a frozen manifest must freeze splits and lock test")
    return allowed


def validate_assets(value: Any, root: Path, verify_assets: bool) -> dict[str, dict[str, Any]]:
    assets: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(require_list(value, "assets", 1, 256)):
        path = f"assets[{index}]"
        asset = exact_object(
            item,
            {"asset_id", "path", "role", "bytes", "sha256", "storage_class", "manual_delete"},
            path,
        )
        asset_id = require_id(asset["asset_id"], f"{path}.asset_id")
        if asset_id in assets:
            fail("duplicate", f"{path}.asset_id", "asset ID is duplicated")
        relative = require_relative_path(asset["path"], f"{path}.path")
        require_enum(
            asset["role"],
            {
                "iq_dataset",
                "split_index",
                "input_profile",
                "preprocess_spec",
                "label_table",
                "capture_plan",
                "capture_report",
                "annotation_evidence",
                "lineage_evidence",
                "golden_fixture",
                "raw_iq",
                "model_tensor",
            },
            f"{path}.role",
        )
        expected_bytes = require_int(asset["bytes"], f"{path}.bytes", 1, 1 << 63)
        expected_hash = require_sha256(asset["sha256"], f"{path}.sha256")
        require_enum(
            asset["storage_class"],
            {"repository_metadata", "machine_local_asset", "application_result"},
            f"{path}.storage_class",
        )
        require_enum(asset["manual_delete"], {"not_applicable", "available", "required"}, f"{path}.manual_delete")
        if asset["storage_class"] == "application_result" and asset["manual_delete"] != "required":
            fail("governance", f"{path}.manual_delete", "application results require manual deletion")
        if verify_assets:
            resolved = resolve_regular_file(root, relative, f"{path}.path")
            if resolved.stat().st_size != expected_bytes:
                fail("asset", f"{path}.bytes", "asset byte count mismatch")
            if file_sha256(resolved) != expected_hash:
                fail("asset", f"{path}.sha256", "asset hash mismatch")
        assets[asset_id] = asset
    return assets


def require_contract_asset(
    artifact: dict[str, Any], role: str, assets: dict[str, dict[str, Any]], field: str
) -> None:
    matches = [
        asset
        for asset in assets.values()
        if asset["role"] == role
        and asset["path"] == artifact["path"]
        and asset["sha256"] == artifact["sha256"]
    ]
    if len(matches) != 1:
        fail("reference", field, f"must match exactly one {role} asset by path and hash")


def validate_lineage(value: Any, path: str) -> dict[str, Any]:
    lineage = exact_object(
        value,
        {"source_sample_id", "capture_session_id", "capture_day", "parent_record_id", "transforms"},
        path,
    )
    require_id(lineage["source_sample_id"], f"{path}.source_sample_id")
    for field in ("capture_session_id", "parent_record_id"):
        if lineage[field] is not None:
            require_id(lineage[field], f"{path}.{field}")
    if lineage["capture_day"] is not None:
        require_date(lineage["capture_day"], f"{path}.capture_day")
    transforms = require_list(lineage["transforms"], f"{path}.transforms", 0, 32)
    for index, transform in enumerate(transforms):
        require_id(transform, f"{path}.transforms[{index}]")
    return lineage


def validate_window(value: Any, assets: dict[str, dict[str, Any]], path: str) -> dict[str, Any]:
    window = exact_object(
        value,
        {
            "window_index",
            "sample_offset",
            "samples",
            "bytes",
            "sample_format",
            "layout",
            "endianness",
            "sha256",
            "storage",
        },
        path,
    )
    require_int(window["window_index"], f"{path}.window_index", 0, 10_000_000)
    require_int(window["sample_offset"], f"{path}.sample_offset", 0, 1 << 63)
    samples = require_int(window["samples"], f"{path}.samples", 1, 16_777_216)
    sample_format = require_enum(window["sample_format"], {"ci16_le", "f32_le"}, f"{path}.sample_format")
    require_enum(window["layout"], {"interleaved_iq", "planar_iq"}, f"{path}.layout")
    if window["endianness"] != "little":
        fail("value", f"{path}.endianness", "must be little")
    expected_bytes = samples * (4 if sample_format == "ci16_le" else 8)
    if require_int(window["bytes"], f"{path}.bytes", 4, 268_435_456) != expected_bytes:
        fail("shape", f"{path}.bytes", f"must equal {expected_bytes} for the declared IQ shape")
    require_sha256(window["sha256"], f"{path}.sha256")

    storage = window["storage"]
    if not isinstance(storage, dict):
        fail("shape", f"{path}.storage", "must be an object")
    kind = storage.get("kind")
    if kind == "dataset_row":
        storage = exact_object(storage, {"kind", "asset_id", "dataset_path", "row_index"}, f"{path}.storage")
        asset_id = require_id(storage["asset_id"], f"{path}.storage.asset_id")
        if asset_id not in assets or assets[asset_id]["role"] != "iq_dataset":
            fail("reference", f"{path}.storage.asset_id", "must reference an IQ dataset asset")
        dataset_path = require_text(storage["dataset_path"], f"{path}.storage.dataset_path", 256)
        if DATASET_PATH.fullmatch(dataset_path) is None or ".." in Path(dataset_path).parts:
            fail("path", f"{path}.storage.dataset_path", "must be an absolute in-container dataset path")
        require_int(storage["row_index"], f"{path}.storage.row_index", 0, 1 << 63)
    elif kind == "managed_asset":
        storage = exact_object(storage, {"kind", "asset_id", "offset_bytes"}, f"{path}.storage")
        asset_id = require_id(storage["asset_id"], f"{path}.storage.asset_id")
        if asset_id not in assets or assets[asset_id]["role"] not in {"raw_iq", "model_tensor"}:
            fail("reference", f"{path}.storage.asset_id", "must reference a raw-IQ or tensor asset")
        offset = require_int(storage["offset_bytes"], f"{path}.storage.offset_bytes", 0, 1 << 63)
        if offset + expected_bytes > assets[asset_id]["bytes"]:
            fail("shape", f"{path}.storage", "window extends beyond its managed asset")
    elif kind == "deterministic_generator":
        storage = exact_object(storage, {"kind", "generator_id", "parameters_sha256"}, f"{path}.storage")
        require_id(storage["generator_id"], f"{path}.storage.generator_id")
        require_sha256(storage["parameters_sha256"], f"{path}.storage.parameters_sha256")
    else:
        fail("value", f"{path}.storage.kind", "unsupported storage kind")
    return window


def validate_label(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail("shape", path, "must be an object")
    provenance = require_enum(value.get("provenance"), PROVENANCE, f"{path}.provenance")
    if provenance == "dataset_ground_truth":
        label = exact_object(
            value,
            {"provenance", "numeric_id", "raw_value", "display_name", "display_name_status", "evidence"},
            path,
        )
        require_int(label["numeric_id"], f"{path}.numeric_id", 0, 65_535)
        if type(label["raw_value"]) is int:
            pass
        elif isinstance(label["raw_value"], str):
            require_text(label["raw_value"], f"{path}.raw_value", 128)
        else:
            fail("value", f"{path}.raw_value", "must be an integer or string")
        evidence = exact_object(
            label["evidence"], {"dataset_id", "dataset_sha256", "label_field", "row_index"}, f"{path}.evidence"
        )
        require_id(evidence["dataset_id"], f"{path}.evidence.dataset_id")
        require_sha256(evidence["dataset_sha256"], f"{path}.evidence.dataset_sha256")
        require_text(evidence["label_field"], f"{path}.evidence.label_field", 128)
        require_int(evidence["row_index"], f"{path}.evidence.row_index", 0, 1 << 63)
    elif provenance == "independent_annotation":
        label = exact_object(
            value,
            {"provenance", "numeric_id", "display_name", "display_name_status", "evidence"} | ({"category"} if "category" in value else set()),
            path,
        )
        if "category" in label:
            category = require_enum(label["category"], {"known_class", "noise_idle", "out_of_label_space", "mixed", "low_quality", "ambiguous"}, f"{path}.category")
            if category == "known_class":
                require_int(label["numeric_id"], f"{path}.numeric_id", 0, 23)
            elif label["numeric_id"] is not None:
                fail("label", path, "OOD/ambiguous evidence cannot force a numeric class")
        else:
            require_int(label["numeric_id"], f"{path}.numeric_id", 0, 65_535)
        evidence = exact_object(
            label["evidence"], {"annotation_id", "method", "annotated_at_utc", "evidence_sha256"}, f"{path}.evidence"
        )
        require_id(evidence["annotation_id"], f"{path}.evidence.annotation_id")
        require_enum(
            evidence["method"],
            {"known_waveform_schedule", "external_decoder", "instrument_reference", "human_review"},
            f"{path}.evidence.method",
        )
        require_utc_timestamp(evidence["annotated_at_utc"], f"{path}.evidence.annotated_at_utc")
        require_sha256(evidence["evidence_sha256"], f"{path}.evidence.evidence_sha256")
    else:
        label = exact_object(value, {"provenance", "reason"}, path)
        require_enum(
            label["reason"],
            {
                "no_independent_label",
                "noise_or_idle",
                "ambiguous_annotation",
                "out_of_label_space",
                "quality_failure",
            },
            f"{path}.reason",
        )
        return label

    display_status = require_enum(
        label["display_name_status"], {"trusted", "provisional", "absent"}, f"{path}.display_name_status"
    )
    display_name = label["display_name"]
    if display_status == "absent":
        if display_name is not None:
            fail("label", f"{path}.display_name", "must be null when name status is absent")
    else:
        require_text(display_name, f"{path}.display_name", 128)
    return label


def validate_rx_input(value: Any, path: str) -> None:
    identity = exact_object(
        value,
        {
            "identity_version",
            "verified",
            "front_panel_port",
            "logical_channel",
            "phy_channel",
            "scan_i_channel",
            "scan_q_channel",
            "rf_port_select",
            "source",
        },
        path,
    )
    expected = {
        "identity_version": 1,
        "verified": True,
        "front_panel_port": "RX1",
        "logical_channel": "RX0",
        "phy_channel": "voltage0",
        "scan_i_channel": "voltage0",
        "scan_q_channel": "voltage1",
        "rf_port_select": "A_BALANCED",
        "source": "iio_channel_attr",
    }
    if identity != expected:
        fail("rx_input", path, "must equal the fixed verified P201 RX1 identity")


def validate_quality(value: Any, path: str) -> dict[str, Any]:
    quality = exact_object(
        value,
        {"raw_rms_dbfs", "measured_snr_db", "clipped_samples", "dropped_samples", "overflow", "health_flags", "healthy"},
        path,
    )
    require_number(quality["raw_rms_dbfs"], f"{path}.raw_rms_dbfs", -400, 100)
    require_number(quality["measured_snr_db"], f"{path}.measured_snr_db", -400, 400)
    require_int(quality["clipped_samples"], f"{path}.clipped_samples", 0, 1 << 63)
    require_int(quality["dropped_samples"], f"{path}.dropped_samples", 0, 1 << 63)
    require_bool(quality["overflow"], f"{path}.overflow")
    require_int(quality["health_flags"], f"{path}.health_flags", 0, 0xFFFF_FFFF)
    require_bool(quality["healthy"], f"{path}.healthy")
    if quality["healthy"] != (quality["health_flags"] == 0):
        fail("quality", path, "healthy must agree with the Adapter health flags")
    if quality["healthy"] and (quality["overflow"] or quality["dropped_samples"] != 0):
        fail("quality", path, "healthy capture metadata cannot report overflow or drops")
    return quality


def validate_retention(value: Any, path: str) -> dict[str, Any]:
    retention = exact_object(
        value,
        {"user_visible", "result_id", "manual_delete_available", "p201_transient_removed", "agx_temporary_removed"},
        path,
    )
    visible = require_bool(retention["user_visible"], f"{path}.user_visible")
    if retention["result_id"] is not None:
        require_id(retention["result_id"], f"{path}.result_id")
    manual = require_bool(retention["manual_delete_available"], f"{path}.manual_delete_available")
    require_bool(retention["p201_transient_removed"], f"{path}.p201_transient_removed")
    require_bool(retention["agx_temporary_removed"], f"{path}.agx_temporary_removed")
    if visible and (retention["result_id"] is None or not manual):
        fail("governance", path, "user-visible P201 data requires a result ID and manual delete")
    return retention


def validate_source(
    value: Any,
    label: dict[str, Any],
    lineage: dict[str, Any],
    window: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    manifest_status: str,
    path: str,
) -> str:
    if not isinstance(value, dict):
        fail("shape", path, "must be an object")
    kind = require_enum(value.get("kind"), SOURCE_KINDS, f"{path}.kind")
    storage = window["storage"]
    if kind == "offline_dataset":
        source = exact_object(
            value,
            {"kind", "dataset_id", "dataset_asset_id", "dataset_sha256", "split_asset_id", "split_sha256", "row_index", "nominal_snr_db"},
            path,
        )
        dataset_id = require_id(source["dataset_id"], f"{path}.dataset_id")
        dataset_asset_id = require_id(source["dataset_asset_id"], f"{path}.dataset_asset_id")
        split_asset_id = require_id(source["split_asset_id"], f"{path}.split_asset_id")
        dataset_hash = require_sha256(source["dataset_sha256"], f"{path}.dataset_sha256")
        split_hash = require_sha256(source["split_sha256"], f"{path}.split_sha256")
        row_index = require_int(source["row_index"], f"{path}.row_index", 0, 1 << 63)
        require_number(source["nominal_snr_db"], f"{path}.nominal_snr_db", -200, 200)
        if dataset_asset_id not in assets or assets[dataset_asset_id]["role"] != "iq_dataset":
            fail("reference", f"{path}.dataset_asset_id", "must reference an IQ dataset")
        if split_asset_id not in assets or assets[split_asset_id]["role"] != "split_index":
            fail("reference", f"{path}.split_asset_id", "must reference a split index")
        if assets[dataset_asset_id]["sha256"] != dataset_hash or assets[split_asset_id]["sha256"] != split_hash:
            fail("reference", path, "source hashes must match their asset descriptors")
        if storage.get("kind") != "dataset_row" or storage.get("asset_id") != dataset_asset_id or storage.get("row_index") != row_index:
            fail("reference", "window.storage", "offline window must reference the same dataset row")
        if label["provenance"] != "dataset_ground_truth":
            fail("label", "label.provenance", "offline records require dataset_ground_truth")
        evidence = label["evidence"]
        if evidence["dataset_id"] != dataset_id or evidence["dataset_sha256"] != dataset_hash or evidence["row_index"] != row_index:
            fail("label", "label.evidence", "dataset label evidence must match the source row")
        if lineage["capture_session_id"] is not None or lineage["capture_day"] is not None:
            fail("lineage", "lineage", "offline records cannot claim a receive session or day")
    elif kind == "p201_receive":
        source = exact_object(
            value,
            {
                "kind",
                "capture_session_id",
                "captured_at_utc",
                "capture_day",
                "plan_id",
                "plan_asset_id",
                "plan_sha256",
                "center_hz",
                "sample_rate_hz",
                "rf_bandwidth_hz",
                "gain_mode",
                "rx_gain_db",
                "sequence",
                "samples_captured",
                "bytes_transferred",
                "rx_input",
                "quality",
                "retention",
            },
            path,
        )
        session = require_id(source["capture_session_id"], f"{path}.capture_session_id")
        captured_at = require_utc_timestamp(source["captured_at_utc"], f"{path}.captured_at_utc")
        capture_day = require_date(source["capture_day"], f"{path}.capture_day")
        if not captured_at.startswith(capture_day):
            fail("lineage", path, "capture timestamp and day disagree")
        require_id(source["plan_id"], f"{path}.plan_id")
        plan_asset_id = require_id(source["plan_asset_id"], f"{path}.plan_asset_id")
        plan_hash = require_sha256(source["plan_sha256"], f"{path}.plan_sha256")
        if (
            plan_asset_id not in assets
            or assets[plan_asset_id]["role"] != "capture_plan"
            or assets[plan_asset_id]["sha256"] != plan_hash
        ):
            fail("reference", f"{path}.plan_asset_id", "must reference the content-hashed capture plan")
        require_int(source["center_hz"], f"{path}.center_hz", 70_000_000, 6_000_000_000)
        sample_rate = require_int(source["sample_rate_hz"], f"{path}.sample_rate_hz", 2_100_000, 30_720_000)
        bandwidth = require_int(source["rf_bandwidth_hz"], f"{path}.rf_bandwidth_hz", 200_000, 30_720_000)
        if bandwidth > sample_rate:
            fail("radio_profile", f"{path}.rf_bandwidth_hz", "cannot exceed sample rate")
        require_enum(source["gain_mode"], {"manual", "slow_attack"}, f"{path}.gain_mode")
        require_number(source["rx_gain_db"], f"{path}.rx_gain_db", 0, 73)
        require_int(source["sequence"], f"{path}.sequence", 1, 1 << 63)
        if source["samples_captured"] != window["samples"] or source["bytes_transferred"] != window["bytes"]:
            fail("shape", path, "capture samples/bytes must match the indexed window")
        if window["sample_format"] != "ci16_le" or window["layout"] != "interleaved_iq" or storage.get("kind") != "managed_asset":
            fail("shape", "window", "P201 records require managed interleaved ci16 IQ")
        validate_rx_input(source["rx_input"], f"{path}.rx_input")
        validate_quality(source["quality"], f"{path}.quality")
        retention = validate_retention(source["retention"], f"{path}.retention")
        if manifest_status == "frozen" and (
            not retention["p201_transient_removed"] or not retention["agx_temporary_removed"]
        ):
            fail("governance", f"{path}.retention", "a frozen P201 record requires completed cleanup")
        if lineage["capture_session_id"] != session or lineage["capture_day"] != capture_day:
            fail("lineage", "lineage", "P201 lineage must match capture session and day")
        if label["provenance"] == "dataset_ground_truth":
            fail("label", "label.provenance", "received IQ needs independent_annotation or unknown")
        if label["provenance"] == "independent_annotation":
            evidence_hash = label["evidence"]["evidence_sha256"]
            if not any(asset["role"] == "annotation_evidence" and asset["sha256"] == evidence_hash for asset in assets.values()):
                fail("reference", "label.evidence.evidence_sha256", "must match an annotation-evidence asset")
    else:
        source = exact_object(value, {"kind", "fixture_id", "fixture_sha256", "expected_tensor"}, path)
        fixture_id = require_id(source["fixture_id"], f"{path}.fixture_id")
        fixture_hash = require_sha256(source["fixture_sha256"], f"{path}.fixture_sha256")
        if fixture_id not in assets or assets[fixture_id]["role"] != "golden_fixture" or assets[fixture_id]["sha256"] != fixture_hash:
            fail("reference", path, "golden fixture identity/hash must match its asset")
        tensor = exact_object(source["expected_tensor"], {"sample_format", "layout", "shape", "bytes", "sha256"}, f"{path}.expected_tensor")
        if tensor["sample_format"] != "f32_le":
            fail("shape", f"{path}.expected_tensor.sample_format", "must be little-endian float32")
        layout = require_enum(
            tensor["layout"],
            {"planar_iq", "window_major_planar_iq"},
            f"{path}.expected_tensor.layout",
        )
        shape = require_list(tensor["shape"], f"{path}.expected_tensor.shape", 2, 3)
        for dimension, size in enumerate(shape):
            require_int(size, f"{path}.expected_tensor.shape[{dimension}]", 1, 16_777_216)
        if layout == "planar_iq":
            shape_valid = len(shape) == 2 and shape[0] == 2 and shape[1] == window["samples"]
        else:
            shape_valid = (
                len(shape) == 3
                and shape[1] == 2
                and shape[0] * shape[2] == window["samples"]
            )
        if not shape_valid:
            fail(
                "shape",
                f"{path}.expected_tensor.shape",
                "does not match the layout or raw sample count",
            )
        if require_int(tensor["bytes"], f"{path}.expected_tensor.bytes", 8, 268_435_456) != window["samples"] * 8:
            fail("shape", f"{path}.expected_tensor.bytes", "does not match float32 IQ")
        require_sha256(tensor["sha256"], f"{path}.expected_tensor.sha256")
    return kind


def validate_record(
    value: Any,
    index: int,
    allowed_splits: set[str],
    assets: dict[str, dict[str, Any]],
    display_names_status: str,
    manifest_status: str,
) -> tuple[str, str, dict[str, Any]]:
    path = f"records[{index}]"
    record = exact_object(value, RECORD_KEYS, path)
    if record["schema_version"] != 1 or record["schema_id"] != "amc_corpus_record_v1":
        fail("schema", path, "record schema identity mismatch")
    record_id = require_id(record["record_id"], f"{path}.record_id")
    split = require_enum(record["split"], SPLITS, f"{path}.split")
    if split not in allowed_splits:
        fail("split", f"{path}.split", "is not declared by the manifest")
    lineage = validate_lineage(record["lineage"], f"{path}.lineage")
    window = validate_window(record["window"], assets, f"{path}.window")
    label = validate_label(record["label"], f"{path}.label")
    if (
        label["provenance"] != "unknown"
        and display_names_status == "provisional"
        and label["display_name_status"] == "trusted"
    ):
        fail("label", f"{path}.label.display_name_status", "cannot exceed the manifest label-space status")
    source_kind = validate_source(
        record["source"],
        label,
        lineage,
        window,
        assets,
        manifest_status,
        f"{path}.source",
    )
    if "category" in label and not any(a["role"] == "lineage_evidence" for a in assets.values()):
        fail("label",path,"RF-v1 annotation categories require versioned lineage evidence")
    if source_kind == "p201_receive" and label["provenance"] == "unknown" and split != "receive_domain":
        fail("label", path, "unknown P201 rows cannot enter evaluation splits")
    return record_id, source_kind, {"split": split, "lineage": lineage, "provenance": label["provenance"]}


def validate_governance(value: Any) -> None:
    governance = exact_object(
        value,
        {"bulk_iq_in_git", "model_prediction_is_ground_truth", "unlabeled_accuracy_allowed", "manual_delete_required_for_user_results"},
        "governance",
    )
    for field, expected in {
        "bulk_iq_in_git": False,
        "model_prediction_is_ground_truth": False,
        "unlabeled_accuracy_allowed": False,
        "manual_delete_required_for_user_results": True,
    }.items():
        require_bool(governance[field], f"governance.{field}", expected)


def validate_record_index(
    descriptor_value: Any,
    root: Path,
    allowed_splits: set[str],
    assets: dict[str, dict[str, Any]],
    corpus_kind: str,
    display_names_status: str,
    manifest_status: str,
) -> dict[str, Any]:
    descriptor = exact_object(
        descriptor_value,
        {"schema_id", "format", "path", "count", "bytes", "sha256"},
        "record_index",
    )
    if descriptor["schema_id"] != "amc_corpus_record_v1" or descriptor["format"] != "jsonl":
        fail("schema", "record_index", "must select AMC record v1 JSONL")
    relative = require_relative_path(descriptor["path"], "record_index.path")
    expected_count = require_int(descriptor["count"], "record_index.count", 1, MAX_RECORDS)
    expected_bytes = require_int(descriptor["bytes"], "record_index.bytes", 2, MAX_RECORD_INDEX_BYTES)
    expected_hash = require_sha256(descriptor["sha256"], "record_index.sha256")
    index_path = resolve_regular_file(root, relative, "record_index.path")
    if index_path.stat().st_size != expected_bytes:
        fail("index", "record_index.bytes", "record index byte count mismatch")

    digest = hashlib.sha256()
    record_ids: set[str] = set()
    split_groups: dict[str, dict[str, str]] = {
        "source_sample_id": {},
        "capture_session_id": {},
        "capture_day": {},
    }
    split_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    count = 0
    try:
        stream: BinaryIO
        with index_path.open("rb") as stream:
            for raw_line in stream:
                digest.update(raw_line)
                if len(raw_line) > MAX_RECORD_LINE_BYTES:
                    fail("index", f"records[{count}]", "JSONL line exceeds 64 KiB")
                if not raw_line.endswith(b"\n"):
                    fail("index", f"records[{count}]", "JSONL records must end with LF")
                if not raw_line.strip():
                    fail("index", f"records[{count}]", "blank JSONL records are forbidden")
                record = parse_json_bytes(raw_line, f"records[{count}]")
                record_id, source_kind, metadata = validate_record(
                    record,
                    count,
                    allowed_splits,
                    assets,
                    display_names_status,
                    manifest_status,
                )
                if record_id in record_ids:
                    fail("duplicate", f"records[{count}].record_id", "record ID is duplicated")
                record_ids.add(record_id)
                split_name = metadata["split"]
                if split_name in EVALUATION_SPLITS:
                    for group_key, group_splits in split_groups.items():
                        group_value = metadata["lineage"][group_key]
                        if group_value is None:
                            continue
                        prior = group_splits.setdefault(group_value, split_name)
                        if prior != split_name:
                            fail(
                                "split_leak",
                                f"records[{count}].lineage.{group_key}",
                                f"group {group_value!r} appears in both {prior} and {split_name}",
                            )
                split_counts[split_name] += 1
                source_counts[source_kind] += 1
                label_counts[metadata["provenance"]] += 1
                count += 1
    except OSError as error:
        fail("index", "record_index.path", str(error))

    if count != expected_count:
        fail("index", "record_index.count", f"expected {expected_count}, decoded {count}")
    if digest.hexdigest() != expected_hash:
        fail("index", "record_index.sha256", "record index hash mismatch")
    expected_source = {
        "labeled_offline": {"offline_dataset"},
        "p201_receive": {"p201_receive"},
        "golden_vectors": {"golden_vector"},
        "mixed": SOURCE_KINDS,
    }[corpus_kind]
    if not source_counts or not set(source_counts).issubset(expected_source):
        fail("source", "corpus_kind", "record source kinds do not match the manifest")
    return {
        "record_count": count,
        "split_counts": dict(sorted(split_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "label_provenance_counts": dict(sorted(label_counts.items())),
    }


def validate_rf_v1_derivation(manifest, root, assets, verify_assets):
    """Validate the versioned sidecar without rewriting historical v1 records."""
    profile_hash = "6c1dac991b45e3738e19a6a55a9f3a1b6d3db8510ceef35ee77cdd34e2982dab"
    preprocess_hash = "18428d72beb8c0e7e83d24d57a02d5f6b68f3428cb3f096a219a87b67dbc900f"
    label_hash = "0c269924bb74cf23584ad7584808d1bb263cdf03680f723f4cc40f165e6eafc8"
    contract = manifest["contract"]
    if (contract["input_profile"] != {"id": "rml2018a-d8-rf-v1-epoch010-fp16-runtime-v1", "path": "input-profile.json", "sha256": profile_hash, "admission": "integration_only"}
        or contract["preprocessing"] != {"id": "rf_preprocess_v1", "path": "preprocess.json", "sha256": preprocess_hash, "status": "frozen"}
        or contract["label_space"]["sha256"] != label_hash
        or contract["label_space"]["display_names_status"] != "provisional"):
        fail("rf_v1", "contract", "RF-v1 identity is not the frozen candidate")

    def document(value, field, maximum):
        if not isinstance(value,str) or not value.strip() or len(value.encode()) > maximum or any(ord(c)<32 and c not in "\n\t" for c in value):
            fail("value",field,"invalid bounded evidence document")
        return value

    def checked_asset(role, maximum):
        matches = [a for a in assets.values() if a["role"] == role]
        if len(matches) != 1:
            fail("rf_v1", role, "requires exactly one asset")
        a = matches[0]
        p = resolve_regular_file(root, a["path"], role)
        if p.stat().st_size > maximum or p.stat().st_size != a["bytes"] or file_sha256(p) != a["sha256"]:
            fail("rf_v1", role, "asset size/hash mismatch")
        return read_bounded_json(p, maximum, role)

    d = exact_object(checked_asset("lineage_evidence", 256 * 1024), {
        "schema_version", "schema_id", "parent_result_id", "parent_manifest_sha256", "parent_manifest_utf8",
        "parent_record_sha256", "parent_record_utf8", "source_report", "request_correlation", "raw_iq_sha256", "transform", "iq_storage",
        "profile_sha256", "preprocess_sha256"}, "derivation")
    if (d["schema_version"] != 1 or d["schema_id"] != "rf_v1_corpus_derivation_v1" or d["transform"] != "rf_v1_profile_binding_v1"
        or d["iq_storage"] != "shared_inode_no_copy" or d["profile_sha256"] != profile_hash or d["preprocess_sha256"] != preprocess_hash):
        fail("rf_v1", "derivation", "unsupported derivation identity")
    require_id(d["parent_result_id"], "parent_result_id")
    parent_objects = []
    for prefix, maximum in [("parent_manifest",128*1024),("parent_record",64*1024)]:
        text = document(d[prefix+"_utf8"], prefix, maximum)
        if hashlib.sha256(text.encode()).hexdigest() != d[prefix+"_sha256"]:
            fail("lineage", prefix, "parent snapshot hash mismatch")
        parent_objects.append(parse_json_bytes(text.encode(),prefix))
    pm, parent = parent_objects
    exact_object(pm, MANIFEST_KEYS, "parent_manifest")
    if (pm["manifest_id"] != d["parent_result_id"] or pm["status"] != "frozen" or pm["corpus_kind"] != "p201_receive"
        or pm["contract"]["input_profile"]["sha256"] != "7d2347550939be13d3ccde84add514ca5b4e549783fbc8e724124b4f0f4358ba"
        or pm["record_index"]["sha256"] != d["parent_record_sha256"] or pm["record_index"]["count"] != 1
        or pm["record_index"]["bytes"] != len(d["parent_record_utf8"].encode())):
        fail("lineage", "parent_manifest", "not an original frozen capture")
    parent_assets = validate_assets(pm["assets"], root, False)
    validate_record(parent,0,{"receive_domain"},parent_assets,"provisional","frozen")
    if parent["lineage"]["parent_record_id"] is not None or parent["label"]["provenance"] != "unknown":
        fail("lineage", "parent_record", "derive revisions from the original unknown root")
    if manifest["record_index"]["count"] != 1:
        fail("rf_v1", "record_index", "one complete four-window capture required")
    record = read_bounded_json(resolve_regular_file(root, manifest["record_index"]["path"], "records"), MAX_RECORD_LINE_BYTES, "records")
    if record["record_id"] == parent["record_id"] or record["lineage"]["parent_record_id"] != parent["record_id"] or record["lineage"]["transforms"] != [d["transform"]]:
        fail("lineage", "record", "parent or transform mismatch")
    for key in ("source_sample_id", "capture_session_id", "capture_day"):
        if record["lineage"][key] != parent["lineage"][key]:
            fail("lineage", key, "derived groups must retain parent identity")
    if record["window"] != parent["window"] or record["window"]["sha256"] != d["raw_iq_sha256"]:
        fail("lineage", "window", "raw content changed during metadata derivation")
    source = record["source"]
    if any(source[k] != parent["source"][k] for k in source if k != "retention"):
        fail("lineage", "source", "original source cannot be changed")
    if source["retention"]["result_id"] != manifest["manifest_id"]:
        fail("lineage", "retention", "wrong application result")
    raw = assets[record["window"]["storage"]["asset_id"]]
    if raw["sha256"] != d["raw_iq_sha256"] or raw["bytes"] != 16384 or record["window"]["samples"] != 4096 or record["window"]["storage"]["offset_bytes"] != 0:
        fail("rf_v1", "raw_iq", "expected complete finite capture and original hash")
    plan = checked_asset("capture_plan",128*1024)
    report = d["source_report"]
    exact_object(report, {"sweep_id","session_generation","backend","backend_version","estimated_duration_ms","elapsed_ms","noise_floor_dbfs","points","candidates","dataset"}, "source_report")
    if len(report["points"]) != 1 or report["dataset"] is not None or report["backend"] != "agx_iq_software_aggregate" or report["backend_version"] != 1:
        fail("rf_v1", "source_report", "not a bounded software RX capture")
    p = report["points"][0]
    if (report["session_generation"] != plan["sweep"]["session_generation"] or p["session_generation"] != report["session_generation"]
        or report["sweep_id"] != source["plan_id"] or p["sequence"] != source["sequence"]
        or p["actual_center_hz"] != source["center_hz"] or p["rx_input"] != source["rx_input"]
        or p["sample_rate_hz"] != 2100000 or p["rf_bandwidth_hz"] != 1500000
        or p["captured_samples"] != 4096 or p["dropped_samples"] != 0 or p["overflow"]
        or not p["health"]["healthy"] or p["health"]["flags"] != 0 or p["timeout"]["timed_out"]):
        fail("rf_v1", "source_report", "capture/request/session/RX correlation mismatch")
    require_int(p["request_id"],"request_id",1,1<<63)
    require_int(p["session_generation"],"session_generation",1,1<<63)
    original_reports = [a for a in assets.values() if a["role"] == "capture_report"]
    if original_reports:
        original = checked_asset("capture_report",128*1024)
        if original != report or d["request_correlation"] != "original_report_hash_verified":
            fail("rf_v1","source_report","original report correlation mismatch")
        if original_reports[0] not in pm["assets"]:
            fail("rf_v1","source_report","report was not pinned by the original parent")
    elif d["request_correlation"] != "legacy_reconstructed" or record["label"]["provenance"] != "unknown":
        fail("rf_v1","source_report","old packages without original request evidence remain unknown")
    label = record["label"]
    if label["provenance"] == "unknown":
        if record["split"] != "receive_domain" or any(a["role"] == "annotation_evidence" for a in assets.values()):
            fail("label", "unknown", "unknown is not independent evidence")
        return
    if label["provenance"] != "independent_annotation" or "category" not in label:
        fail("label", "provenance", "RF-v1 P201 requires independent evidence or unknown")
    e = exact_object(checked_asset("annotation_evidence",32*1024), {
        "schema_version","schema_id","annotation_id","method","reviewer","annotated_at_utc","independent_of_model","ambiguity","basis_report","basis_report_sha256",
        "source_sample_id","capture_session_id","capture_day","iq_sha256","request_id","session_generation","sequence","profile_sha256","preprocess_sha256","label_space_sha256","category","numeric_id"}, "annotation")
    if e["schema_version"] != 1 or e["schema_id"] != "rf_v1_independent_annotation_v1" or e["independent_of_model"] is not True:
        fail("label", "annotation", "requires independently reviewed evidence")
    require_id(e["reviewer"],"reviewer")
    require_enum(e["method"],{"external_decoder","instrument_reference","human_review"},"method")
    document(e["basis_report"],"basis_report",16384)
    if hashlib.sha256(e["basis_report"].encode()).hexdigest() != e["basis_report_sha256"]:
        fail("label", "basis_report", "evidence content hash mismatch")
    for k in ("source_sample_id","capture_session_id","capture_day"):
        if e[k] != record["lineage"][k]: fail("label",k,"evidence lineage mismatch")
    for k in ("request_id","session_generation","sequence"):
        if e[k] != p[k]: fail("label",k,"evidence capture mismatch")
    for k, expected in [("iq_sha256",d["raw_iq_sha256"]),("profile_sha256",profile_hash),("preprocess_sha256",preprocess_hash),("label_space_sha256",label_hash),("category",label["category"]),("numeric_id",label["numeric_id"])]:
        if e[k] != expected: fail("label",k,"annotation identity mismatch")
    for k in ("annotation_id","method","annotated_at_utc"):
        if e[k] != label["evidence"][k]: fail("label",k,"annotation reference mismatch")
    if e["ambiguity"] is not None:
        document(e["ambiguity"],"ambiguity",1024)
        if record["split"] != "receive_domain": fail("label","ambiguity","ambiguous evidence cannot enter calibration/acceptance")
    elif e["category"] == "ambiguous":
        fail("label","ambiguity","must explain ambiguity")


def validate_manifest(
    manifest: Any,
    schema: Any,
    asset_root: Path,
    verify_assets: bool = False,
) -> dict[str, Any]:
    validate_schema(schema)
    value = exact_object(manifest, MANIFEST_KEYS, "manifest")
    if value["schema_version"] != 1 or value["schema_id"] != "amc_corpus_manifest_v1":
        fail("schema", "manifest", "manifest schema identity mismatch")
    manifest_id = require_id(value["manifest_id"], "manifest_id")
    require_utc_timestamp(value["created_at_utc"], "created_at_utc")
    status = require_enum(value["status"], {"draft", "frozen"}, "status")
    corpus_kind = require_enum(
        value["corpus_kind"], {"labeled_offline", "p201_receive", "golden_vectors", "mixed"}, "corpus_kind"
    )
    try:
        root = asset_root.resolve(strict=True)
    except OSError as error:
        fail("asset_root", "asset_root", str(error))
    if not root.is_dir():
        fail("asset_root", "asset_root", "must be a directory")
    contract = validate_contract(value["contract"])
    if (
        contract["input_profile"]["admission"] == "production"
        and contract["preprocessing"]["status"] != "frozen"
    ):
        fail("governance", "contract.preprocessing.status", "a production profile requires frozen preprocessing")
    allowed_splits = validate_split_policy(value["split_policy"], status)
    if corpus_kind == "p201_receive" and contract["preprocessing"]["id"] == "rf_preprocess_v1":
        roles = [a.get("role") for a in require_list(value["assets"],"assets",6,8) if isinstance(a,dict)]
        base_roles = ["input_profile","preprocess_spec","label_table","capture_plan","raw_iq","lineage_evidence"]
        if sorted(roles) not in [sorted(base_roles + extras) for extras in [[], ["capture_report"], ["capture_report","annotation_evidence"]]]:
            fail("rf_v1","assets","unexpected asset roles")
        if any(type(a.get("bytes")) is not int or not 0 < a["bytes"] <= 256*1024 for a in value["assets"]):
            fail("rf_v1","assets","unbounded evidence asset")
    assets = validate_assets(value["assets"], root, verify_assets)
    require_contract_asset(contract["input_profile"], "input_profile", assets, "contract.input_profile")
    require_contract_asset(contract["preprocessing"], "preprocess_spec", assets, "contract.preprocessing")
    require_contract_asset(contract["label_space"], "label_table", assets, "contract.label_space")
    validate_governance(value["governance"])
    summary = validate_record_index(
        value["record_index"],
        root,
        allowed_splits,
        assets,
        corpus_kind,
        contract["label_space"]["display_names_status"],
        status,
    )
    if any(a["role"] == "lineage_evidence" for a in assets.values()) and (corpus_kind != "p201_receive" or contract["preprocessing"]["id"] != "rf_preprocess_v1"):
        fail("rf_v1","lineage_evidence","requires RF-v1 P201 derivation")
    if corpus_kind == "p201_receive" and contract["preprocessing"]["id"] == "rf_preprocess_v1":
        validate_rf_v1_derivation(value, root, assets, verify_assets)
    summary.update(
        {
            "schema_id": "amc_corpus_manifest_v1",
            "manifest_id": manifest_id,
            "status": status,
            "corpus_kind": corpus_kind,
            "asset_count": len(assets),
            "assets_verified": verify_assets,
        }
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--verify-assets", action="store_true")
    return parser.parse_args()


def main() -> int:
    os.umask(0o077)
    args = parse_args()
    try:
        schema = read_bounded_json(args.schema, MAX_SCHEMA_BYTES, "schema")
        manifest = read_bounded_json(args.manifest, MAX_MANIFEST_BYTES, "manifest")
        summary = validate_manifest(manifest, schema, args.asset_root, args.verify_assets)
    except ContractError as error:
        print(f"contract_error={error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
