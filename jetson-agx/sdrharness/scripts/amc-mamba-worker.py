#!/usr/bin/env python3
"""Persistent experimental RML2018A D8 recognizer for bounded AGX IQ files."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import math
import os
import signal
import socket
import stat
import sys
import time
import types
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "jetson-agx"
    / "sdrharness"
    / "config"
    / "amc"
    / "rml2018a-d8-seed44.experimental.json"
)
DEFAULT_SOCKET = Path("/run/sdr-agent/recognizer.sock")
DEFAULT_SPOOL_ROOT = Path("/run/sdr-agent/iq")
MAX_FRAME_BYTES = 16 * 1024

# Triton reads this during the Torch/Mamba import chain. Keep its generated
# kernels with the ignored machine-local runtime unless the operator explicitly
# supplies a diagnostic override.
os.environ.setdefault(
    "TRITON_CACHE_DIR",
    str(REPO_ROOT / "local-assets" / "amc-eval" / "runtime" / "triton-cache"),
)

import numpy as np  # noqa: E402
import torch  # noqa: E402


class WorkerError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def require_exact_keys(value: Any, expected: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkerError("request_shape", f"{field} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise WorkerError(
            "request_shape",
            f"{field} keys mismatch; missing={missing}, unknown={unknown}",
        )
    return value


def require_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise WorkerError(
            "request_value", f"{field} must be an integer in [{minimum}, {maximum}]"
        )
    return value


def require_text(value: Any, field: str, maximum_bytes: int) -> str:
    if not isinstance(value, str):
        raise WorkerError("request_value", f"{field} must be text")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as error:
        raise WorkerError("request_value", f"{field} is not valid UTF-8") from error
    if not encoded or len(encoded) > maximum_bytes or not value.isprintable():
        raise WorkerError(
            "request_value",
            f"{field} must contain 1 to {maximum_bytes} printable UTF-8 bytes",
        )
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, expected_hash: str, expected_bytes: int | None = None) -> None:
    if not path.is_file() or path.is_symlink():
        raise WorkerError("asset_missing", f"required regular file is absent: {path}")
    if expected_bytes is not None and path.stat().st_size != expected_bytes:
        raise WorkerError("asset_size", f"asset byte count mismatch: {path}")
    if sha256_file(path) != expected_hash:
        raise WorkerError("asset_hash", f"asset SHA-256 mismatch: {path}")


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise WorkerError("manifest_read", str(error)) from error
    manifest = require_exact_keys(
        payload,
        {
            "schema_version",
            "admission",
            "model_id",
            "asset_root",
            "model_source_commit",
            "model_source_files",
            "checkpoint",
            "checkpoint_config",
            "labels",
            "inference",
            "validation",
            "limitations",
        },
        "manifest",
    )
    if manifest["schema_version"] != 1 or manifest["admission"] != "experimental_rf_only":
        raise WorkerError("manifest_admission", "manifest is not the experimental RF v1 contract")
    require_text(manifest["model_id"], "manifest.model_id", 128)
    if "experimental" not in manifest["model_id"]:
        raise WorkerError("manifest_admission", "experimental model id must be self-describing")

    inference = require_exact_keys(
        manifest["inference"],
        {
            "model_class",
            "model_variant",
            "precision",
            "samples_per_channel",
            "sample_rate_hz",
            "normalization",
            "remove_dc",
            "resample",
            "alternatives",
            "threads",
        },
        "manifest.inference",
    )
    if inference != {
        "model_class": "AMCMambaD8",
        "model_variant": "amc_mamba_d8",
        "precision": "fp32",
        "samples_per_channel": 1024,
        "sample_rate_hz": 2_100_000,
        "normalization": "complex_unit_rms",
        "remove_dc": False,
        "resample": False,
        "alternatives": 8,
        "threads": 1,
    }:
        raise WorkerError("manifest_inference", "manifest inference contract is not supported")
    validation = require_exact_keys(
        manifest["validation"],
        {
            "normalization_rms_tolerance",
            "minimum_raw_complex_rms_adc",
            "reject_clipped_adc_samples",
        },
        "manifest.validation",
    )
    tolerance = validation["normalization_rms_tolerance"]
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool):
        raise WorkerError("manifest_validation", "normalization tolerance must be numeric")
    if not 0.0 < float(tolerance) <= 0.01:
        raise WorkerError("manifest_validation", "normalization tolerance is outside limits")
    if validation["minimum_raw_complex_rms_adc"] != 1.0:
        raise WorkerError("manifest_validation", "unsupported raw RMS floor")
    if validation["reject_clipped_adc_samples"] is not True:
        raise WorkerError("manifest_validation", "clipped-sample rejection must remain enabled")
    return manifest


class MambaBackend:
    def __init__(self, manifest_path: Path) -> None:
        self.manifest_path = manifest_path.resolve(strict=True)
        self.manifest = load_manifest(self.manifest_path)
        asset_root = (REPO_ROOT / self.manifest["asset_root"]).resolve(strict=True)
        expected_asset_root = (REPO_ROOT / "local-assets" / "amc-eval").resolve(strict=True)
        if asset_root != expected_asset_root:
            raise WorkerError("asset_root", "manifest asset root is not the pinned AMC directory")

        commit = require_text(
            self.manifest["model_source_commit"], "manifest.model_source_commit", 40
        )
        if len(commit) != 40 or any(value not in "0123456789abcdef" for value in commit):
            raise WorkerError("source_commit", "model source commit must be lowercase SHA-1")
        source_root = asset_root / "model-source" / commit
        source_files = self.manifest["model_source_files"]
        if not isinstance(source_files, dict) or len(source_files) != 11:
            raise WorkerError("source_manifest", "exactly 11 model source files are required")
        for relative, expected_hash in source_files.items():
            require_text(relative, "model source path", 256)
            require_text(expected_hash, "model source SHA-256", 64)
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise WorkerError("source_path", "model source path escaped its root")
            verify_file(source_root / relative_path, expected_hash)

        checkpoint = require_exact_keys(
            self.manifest["checkpoint"], {"path", "bytes", "sha256"}, "manifest.checkpoint"
        )
        checkpoint_config = require_exact_keys(
            self.manifest["checkpoint_config"],
            {"path", "bytes", "sha256"},
            "manifest.checkpoint_config",
        )
        self.checkpoint_path = self._asset_path(asset_root, checkpoint["path"])
        config_path = self._asset_path(asset_root, checkpoint_config["path"])
        verify_file(self.checkpoint_path, checkpoint["sha256"], checkpoint["bytes"])
        verify_file(config_path, checkpoint_config["sha256"], checkpoint_config["bytes"])

        labels_spec = require_exact_keys(
            self.manifest["labels"], {"path", "sha256", "wire_prefix"}, "manifest.labels"
        )
        label_path = (REPO_ROOT / labels_spec["path"]).resolve(strict=True)
        if not label_path.is_relative_to(REPO_ROOT):
            raise WorkerError("label_path", "label file escaped the repository")
        verify_file(label_path, labels_spec["sha256"])
        label_payload = json.loads(label_path.read_text(encoding="utf-8"))
        raw_labels = label_payload.get("classes")
        if not isinstance(raw_labels, list) or len(raw_labels) != 24:
            raise WorkerError("labels", "RML2018A label file must contain 24 classes")
        prefix = require_text(labels_spec["wire_prefix"], "labels.wire_prefix", 32)
        self.labels = [f"{prefix}{index:02d}:{name}" for index, name in enumerate(raw_labels)]
        if len(set(self.labels)) != 24 or any(len(value.encode("utf-8")) > 128 for value in self.labels):
            raise WorkerError("labels", "wire labels are duplicate or oversized")

        config = json.loads(config_path.read_text(encoding="utf-8"))
        if (
            config.get("selected_model_class") != "AMCMambaD8"
            or config.get("selected_model_variant") != "amc_mamba_d8"
            or config.get("git", {}).get("commit") != commit
            or config.get("git", {}).get("dirty") is not False
        ):
            raise WorkerError("checkpoint_config", "checkpoint config is not the pinned clean D8 run")
        model_config = config["resolved_config"]["model"]
        if model_config.get("num_classes") != 24:
            raise WorkerError("checkpoint_config", "checkpoint class count is not 24")

        for package_name, package_path in (
            ("models", source_root / "models"),
            ("utils", source_root / "utils"),
        ):
            if package_name in sys.modules:
                raise WorkerError("model_import", f"unexpected preloaded package: {package_name}")
            package = types.ModuleType(package_name)
            package.__path__ = [str(package_path)]  # type: ignore[attr-defined]
            package.__package__ = package_name
            sys.modules[package_name] = package
        model_class = importlib.import_module("models.d8.model").AMCMambaD8

        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.manual_seed(0)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
        torch.set_grad_enabled(False)
        if not torch.cuda.is_available():
            raise WorkerError("cuda_unavailable", "CUDA is unavailable")
        constructor_fields = (
            "d_model",
            "dropout",
            "use_real_mamba",
            "mamba_d_state",
            "mamba_d_conv",
            "mamba_expand",
            "mamba_headdim",
        )
        self.model = model_class(
            model_variant="amc_mamba_d8",
            num_classes=24,
            **{name: model_config[name] for name in constructor_fields},
        )
        checkpoint_payload = torch.load(
            self.checkpoint_path, map_location="cpu", weights_only=True
        )
        if (
            checkpoint_payload.get("selected_model_class") != "AMCMambaD8"
            or checkpoint_payload.get("selected_model_variant") != "amc_mamba_d8"
        ):
            raise WorkerError("checkpoint_metadata", "checkpoint metadata does not match D8")
        self.model.load_state_dict(checkpoint_payload["model_state"], strict=True)
        if sum(parameter.numel() for parameter in self.model.parameters()) != config["model_parameters"]:
            raise WorkerError("checkpoint_parameters", "checkpoint parameter count mismatch")
        if not self.model.encoder.real_mamba_available() or not self.model.encoder.backend.startswith(
            "real_mamba2_weight_tied_bidirectional_d8"
        ):
            raise WorkerError("mamba_backend", "real Mamba2 backend is unavailable")
        self.model = self.model.eval().cuda()
        self.model_sha256 = checkpoint["sha256"]
        self.model_id = self.manifest["model_id"]
        self.sample_rate_hz = self.manifest["inference"]["sample_rate_hz"]
        self.samples_per_channel = self.manifest["inference"]["samples_per_channel"]
        self.rms_tolerance = float(
            self.manifest["validation"]["normalization_rms_tolerance"]
        )
        self._warm_up()

    @staticmethod
    def _asset_path(asset_root: Path, relative: Any) -> Path:
        relative_text = require_text(relative, "asset path", 256)
        relative_path = Path(relative_text)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise WorkerError("asset_path", "asset path escaped its root")
        path = (asset_root / relative_path).resolve(strict=True)
        if not path.is_relative_to(asset_root):
            raise WorkerError("asset_path", "resolved asset path escaped its root")
        return path

    def _warm_up(self) -> None:
        phase = torch.arange(self.samples_per_channel, dtype=torch.float32)
        phase *= 2.0 * math.pi / 32.0
        sample = torch.stack((torch.cos(phase), torch.sin(phase))).unsqueeze(0).cuda()
        for _ in range(2):
            self.model(sample)
        torch.cuda.synchronize()

    def classify(self, iq: np.ndarray) -> tuple[list[tuple[str, float]], int]:
        started = time.perf_counter_ns()
        tensor = torch.from_numpy(iq).unsqueeze(0).cuda(non_blocking=False)
        logits = self.model(tensor)
        probabilities = torch.softmax(logits.float(), dim=1)
        values, indices = torch.topk(probabilities, k=9, dim=1)
        torch.cuda.synchronize()
        inference_us = (time.perf_counter_ns() - started) // 1_000
        ranked = [
            (self.labels[int(index)], float(confidence))
            for confidence, index in zip(values[0].cpu().tolist(), indices[0].cpu().tolist())
        ]
        return ranked, inference_us


class RfV1Backend(MambaBackend):
    def __init__(self, profile_path: Path) -> None:
        helper_path = Path(__file__).with_name("amc-rf-v1-runtime.py")
        spec = importlib.util.spec_from_file_location("amc_rf_v1_runtime", helper_path)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        self.profile, candidate, self.model, _ = helper.load_model(profile_path)
        self.profile_sha256 = helper.PROFILE_SHA256
        self.preprocess_sha256 = candidate["preprocess"]["sha256"]
        self.model_sha256 = candidate["checkpoint"]["sha256"]
        self.model_id = self.profile["model"]["model_id"]
        self.samples_per_channel = 1024
        self.sample_rate_hz = 2_100_000
        self.rms_tolerance = 0.000001
        self.labels = [f"provisional:{index:02d}" for index in range(24)]
        self.active_batch = None
        self.completed_generation = 0
        self.completed_request = 0
        sample = np.stack((np.ones(1024, dtype=np.float32), np.zeros(1024, dtype=np.float32)))
        for _ in range(2):
            self.classify_logits(sample)

    def classify_logits(self, iq):
        started = time.perf_counter_ns()
        tensor = torch.from_numpy(iq).unsqueeze(0).cuda(non_blocking=False)
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
            logits = self.model(tensor)
        values = logits.float().cpu().numpy()[0]
        if values.shape != (24,) or not np.isfinite(values).all():
            raise WorkerError("logits", "expected 24 finite FP32 logits")
        return values.tolist(), (time.perf_counter_ns() - started) // 1_000

    def classify(self, iq):
        logits, elapsed = self.classify_logits(iq)
        values = np.asarray(logits, dtype=np.float64)
        probabilities = np.exp(values - values.max())
        probabilities /= probabilities.sum()
        indices = np.argsort(-probabilities, kind="stable")[:9]
        return [(self.labels[index], float(probabilities[index])) for index in indices], elapsed

    def accept_window(self, request):
        contract = request["rf_v1"]
        identity = {key: value for key, value in contract.items() if key != "window_index"}
        identity.update(session_generation=request["session_generation"], candidate_id=request["candidate_id"],
                        path=request["iq"]["storage"]["path"], center_hz=request["iq"]["center_hz"])
        index = contract["window_index"]
        now = time.monotonic()
        if self.active_batch is not None and now > self.active_batch[2]:
            self.active_batch = None
        if index == 0:
            if self.active_batch is not None:
                raise WorkerError("window_order", "another batch is active")
            if (request["session_generation"], contract["batch_request_id"]) <= (self.completed_generation, self.completed_request):
                raise WorkerError("window_order", "stale or replayed batch")
            self.completed_generation = request["session_generation"]
            self.completed_request = contract["batch_request_id"]
        elif self.active_batch is None or self.active_batch[:2] != (identity, index):
            raise WorkerError("window_order", "missing, reordered or unrelated window")
        self.active_batch = (identity, index + 1, now + 5.0) if index < 3 else None


def validate_rf_v1(request, backend):
    contract = require_exact_keys(request["rf_v1"], {
        "profile_sha256", "preprocess_sha256", "checkpoint_sha256", "batch_sha256",
        "batch_request_id", "source_sweep_id", "source_request_id", "source_session_generation",
        "source_sequence", "capture_request_id", "capture_sequence", "window_index",
    }, "rf_v1")
    for key, expected in (("profile_sha256", backend.profile_sha256),
                          ("preprocess_sha256", backend.preprocess_sha256),
                          ("checkpoint_sha256", backend.model_sha256)):
        if contract[key] != expected:
            raise WorkerError("rf_v1_hash", f"{key} differs from loaded assets")
    digest = contract["batch_sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(v not in "0123456789abcdef" for v in digest):
        raise WorkerError("rf_v1_hash", "invalid batch hash")
    for key in ("batch_request_id", "source_request_id", "source_session_generation", "source_sequence", "capture_request_id", "capture_sequence"):
        require_int(contract[key], key, 1, 2**64 - 1)
    require_text(contract["source_sweep_id"], "source_sweep_id", 128)
    index = require_int(contract["window_index"], "window_index", 0, 3)
    if request["request_id"] != contract["batch_request_id"] + index or request["iq"]["storage"]["offset_bytes"] != index * 8192:
        raise WorkerError("window_order", "request/offset does not match capture order")


def prepare_spool_root(path: Path) -> Path:
    if not path.is_absolute():
        raise WorkerError("spool_root", "spool root must be absolute")
    if not path.exists():
        try:
            path.mkdir(mode=0o700)
        except OSError as error:
            raise WorkerError("spool_root", str(error)) from error
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise WorkerError("spool_root", "spool root must be a real directory")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
        raise WorkerError("spool_root", "spool root must be owned by this user with mode 0700")
    return path.resolve(strict=True)


def validate_request(payload: Any, backend: MambaBackend) -> dict[str, Any]:
    request = require_exact_keys(
        payload,
        {
            "protocol_version",
            "request_id",
            "session_generation",
            "candidate_id",
            "iq",
            "max_latency_ms",
        } | ({"rf_v1"} if hasattr(backend, "profile_sha256") else set()),
        "request",
    )
    if request["protocol_version"] != 1:
        raise WorkerError("protocol_version", "unsupported recognizer protocol version")
    require_int(request["request_id"], "request_id", 1, 2**64 - 1)
    require_int(request["session_generation"], "session_generation", 1, 2**64 - 1)
    require_text(request["candidate_id"], "candidate_id", 64)
    require_int(request["max_latency_ms"], "max_latency_ms", 1, 5_000)
    iq = require_exact_keys(
        request["iq"],
        {
            "storage",
            "sample_format",
            "layout",
            "normalization",
            "samples_per_channel",
            "sample_rate_hz",
            "center_hz",
        },
        "request.iq",
    )
    storage = require_exact_keys(
        iq["storage"], {"path", "offset_bytes", "length_bytes"}, "request.iq.storage"
    )
    require_text(storage["path"], "request.iq.storage.path", 1024)
    require_int(storage["offset_bytes"], "offset_bytes", 0, 2**63 - 1)
    expected_bytes = backend.samples_per_channel * 2 * 4
    if storage["length_bytes"] != expected_bytes:
        raise WorkerError("iq_length", "IQ byte length does not match the model contract")
    if storage["offset_bytes"] % 4:
        raise WorkerError("iq_offset", "IQ byte offset must be float32 aligned")
    if iq["sample_format"] != "f32_le" or iq["layout"] != "planar_iq":
        raise WorkerError("iq_format", "worker requires little-endian planar float32 IQ")
    expected_normalization = "capture_unit_rms" if hasattr(backend, "profile_sha256") else "unit_rms"
    if iq["normalization"] != expected_normalization:
        raise WorkerError("iq_normalization", "worker requires complex unit-RMS IQ")
    if iq["samples_per_channel"] != backend.samples_per_channel:
        raise WorkerError("iq_samples", "worker requires exactly 1024 samples per channel")
    if iq["sample_rate_hz"] != backend.sample_rate_hz:
        raise WorkerError("iq_sample_rate", "worker requires exactly 2.1 MS/s")
    require_int(iq["center_hz"], "center_hz", 70_000_000, 6_000_000_000)
    if hasattr(backend, "profile_sha256"):
        validate_rf_v1(request, backend)
    return request


def load_iq(request: dict[str, Any], spool_root: Path, tolerance: float) -> np.ndarray:
    storage = request["iq"]["storage"]
    requested = Path(storage["path"])
    if not requested.is_absolute():
        raise WorkerError("iq_path", "IQ path must be absolute")
    try:
        metadata = requested.lstat()
        resolved = requested.resolve(strict=True)
    except OSError as error:
        raise WorkerError("iq_path", str(error)) from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise WorkerError("iq_path", "IQ path must be a non-symlink regular file")
    if not resolved.is_relative_to(spool_root):
        raise WorkerError("iq_path_escape", "IQ path is outside the configured spool root")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
        raise WorkerError("iq_permissions", "IQ file must be private and owned by this user")
    offset = storage["offset_bytes"]
    length = storage["length_bytes"]
    rf = request.get("rf_v1")
    if rf is not None:
        if metadata.st_size != 32768:
            raise WorkerError("iq_length", "RF-v1 needs the exact complete 32-KiB capture")
        offset, length = 0, 32768
    if offset + length > metadata.st_size:
        raise WorkerError("iq_range", "IQ range exceeds the file length")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(requested, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            metadata.st_dev,
            metadata.st_ino,
        ):
            raise WorkerError("iq_race", "IQ file changed while it was being opened")
        chunks = []
        cursor = 0
        while cursor < length:
            chunk = os.pread(descriptor, length - cursor, offset + cursor)
            if not chunk:
                raise WorkerError("iq_short_read", "IQ file ended before the declared range")
            chunks.append(chunk)
            cursor += len(chunk)
    except OSError as error:
        raise WorkerError("iq_read", str(error)) from error
    finally:
        if "descriptor" in locals():
            os.close(descriptor)
    data = b"".join(chunks)
    if rf is not None and hashlib.sha256(data).hexdigest() != rf["batch_sha256"]:
        raise WorkerError("iq_hash", "model-ready capture hash changed")
    iq = np.frombuffer(data, dtype="<f4").copy().reshape((-1, 2, 1024) if rf is not None else (2, -1))
    if not np.isfinite(iq).all():
        raise WorkerError("iq_non_finite", "IQ contains a non-finite float32 value")
    if rf is not None:
        rms = float(np.sqrt(np.square(iq.astype(np.float64)).sum() / 4096.0))
    else:
        rms = float(np.sqrt(np.mean(np.square(iq[0]) + np.square(iq[1]))))
    if not math.isfinite(rms) or abs(rms - 1.0) > tolerance:
        raise WorkerError("iq_normalization", f"complex IQ RMS {rms:.9f} is outside tolerance")
    return iq[rf["window_index"]] if rf is not None else iq


def classify_request(
    payload: Any, backend: MambaBackend, spool_root: Path
) -> dict[str, Any]:
    total_started = time.perf_counter_ns()
    request = validate_request(payload, backend)
    map_started = time.perf_counter_ns()
    iq = load_iq(request, spool_root, backend.rms_tolerance)
    map_us = (time.perf_counter_ns() - map_started) // 1_000
    preprocess_started = time.perf_counter_ns()
    iq = np.ascontiguousarray(iq, dtype=np.float32)
    preprocess_us = (time.perf_counter_ns() - preprocess_started) // 1_000
    rf_output = None
    if request.get("rf_v1") is not None:
        backend.accept_window(request)
        logits, inference_us = backend.classify_logits(iq)
        values = np.asarray(logits, dtype=np.float64)
        probabilities = np.exp(values - values.max())
        probabilities /= probabilities.sum()
        indices = np.argsort(-probabilities, kind="stable")[:9]
        ranked = [(backend.labels[index], float(probabilities[index])) for index in indices]
        rf_output = {"contract": request["rf_v1"], "request_id": request["request_id"],
                     "session_generation": request["session_generation"],
                     "compute": "cuda_fp16_autocast", "logits": logits}
    else:
        ranked, inference_us = backend.classify(iq)
    total_us = (time.perf_counter_ns() - total_started) // 1_000
    if total_us > request["max_latency_ms"] * 1_000:
        raise WorkerError("deadline", "recognition exceeded the requested latency limit")
    primary = ranked[0]
    return {
        "protocol_version": 1,
        "request_id": request["request_id"],
        "session_generation": request["session_generation"],
        "status": "ok",
        "output": {
            **({"rf_v1": rf_output} if rf_output is not None else {}),
            "candidate_id": request["candidate_id"],
            "label": primary[0],
            "confidence": primary[1],
            "alternatives": [
                {"label": label, "confidence": confidence} for label, confidence in ranked[1:]
            ],
            "backend": {
                "runtime": "pytorch-cuda-mamba2",
                "runtime_version": f"torch-{torch.__version__}",
                "model_id": backend.model_id,
                "model_sha256": backend.model_sha256,
                "threads": 1,
            },
            "timing": {
                "map_us": map_us,
                "preprocess_us": preprocess_us,
                "inference_us": inference_us,
                "total_us": total_us,
            },
        },
    }


def health_response(backend: MambaBackend) -> dict[str, Any]:
    return {
        "protocol_version": 1,
        "status": "ok",
        "readiness": "experimental",
        "model_id": backend.model_id,
        "model_sha256": backend.model_sha256,
        "samples_per_channel": backend.samples_per_channel,
        "sample_rate_hz": backend.sample_rate_hz,
        "normalization": "four_window_capture_complex_unit_rms" if hasattr(backend, "profile_sha256") else "complex_unit_rms",
        "production_enabled": False,
    }


def read_frame(connection: socket.socket) -> bytes:
    frame = bytearray()
    while b"\n" not in frame:
        chunk = connection.recv(MAX_FRAME_BYTES + 1 - len(frame))
        if not chunk:
            raise WorkerError("request_framing", "connection closed before newline")
        frame.extend(chunk)
        if len(frame) > MAX_FRAME_BYTES:
            raise WorkerError("request_too_large", "request exceeds 16 KiB")
    newline = frame.index(b"\n")
    if newline != len(frame) - 1:
        raise WorkerError("request_framing", "one connection must contain exactly one frame")
    return bytes(frame[:newline])


def write_frame(connection: socket.socket, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_FRAME_BYTES:
        raise WorkerError("response_too_large", "response exceeds 16 KiB")
    connection.sendall(encoded + b"\n")


def try_write_frame(connection: socket.socket, payload: dict[str, Any]) -> bool:
    """Best-effort response delivery; a vanished client must not kill the worker."""
    try:
        write_frame(connection, payload)
    except OSError:
        return False
    return True


def serve(
    backend: MambaBackend,
    socket_path: Path,
    spool_root: Path,
    max_requests: int,
) -> None:
    if not socket_path.is_absolute():
        raise WorkerError("socket_path", "socket path must be absolute")
    socket_parent = socket_path.parent.resolve(strict=True)
    socket_path = socket_parent / socket_path.name
    if socket_path.exists() or socket_path.is_symlink():
        metadata = socket_path.lstat()
        if not stat.S_ISSOCK(metadata.st_mode):
            raise WorkerError("socket_path", "refusing to replace a non-socket path")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.2)
            probe.connect(str(socket_path))
        except (ConnectionRefusedError, FileNotFoundError, socket.timeout):
            current = socket_path.lstat()
            if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise WorkerError("socket_race", "socket path changed during stale check")
            socket_path.unlink()
        else:
            raise WorkerError("already_running", "recognizer socket already accepts connections")
        finally:
            probe.close()

    stop_requested = False

    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    os.chmod(socket_path, 0o600)
    socket_identity = socket_path.lstat()
    listener.listen(1)
    listener.settimeout(0.5)
    handled = 0
    print(
        json.dumps(
            {
                "event": "ready",
                "socket": str(socket_path),
                "spool_root": str(spool_root),
                "model_id": backend.model_id,
                "production_enabled": False,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )
    try:
        while not stop_requested and (max_requests == 0 or handled < max_requests):
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            with connection:
                connection.settimeout(6.0)
                request_id = 0
                session_generation = 0
                try:
                    payload = json.loads(read_frame(connection))
                    if isinstance(payload, dict):
                        if type(payload.get("request_id")) is int:
                            request_id = payload["request_id"]
                        if type(payload.get("session_generation")) is int:
                            session_generation = payload["session_generation"]
                    if isinstance(payload, dict) and "operation" in payload:
                        health = require_exact_keys(
                            payload, {"protocol_version", "operation"}, "health request"
                        )
                        if health != {"protocol_version": 1, "operation": "health"}:
                            raise WorkerError("health_request", "unsupported health request")
                        response = health_response(backend)
                    else:
                        response = classify_request(payload, backend, spool_root)
                except (WorkerError, json.JSONDecodeError, UnicodeError, OSError) as error:
                    if isinstance(error, WorkerError):
                        code, message = error.code, error.message
                    else:
                        code, message = "worker_error", str(error)
                    response = {
                        "protocol_version": 1,
                        "request_id": request_id,
                        "session_generation": session_generation,
                        "status": "error",
                        "error": f"{code}: {message}"[:512],
                    }
                try_write_frame(connection, response)
                handled += 1
    finally:
        listener.close()
        try:
            current = socket_path.lstat()
            if (current.st_dev, current.st_ino) == (
                socket_identity.st_dev,
                socket_identity.st_ino,
            ):
                socket_path.unlink()
        except FileNotFoundError:
            pass


def probe_socket(socket_path: Path, timeout_ms: int) -> int:
    deadline = time.monotonic() + timeout_ms / 1_000.0
    last_error: OSError | WorkerError | None = None
    while time.monotonic() < deadline:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.settimeout(min(1.0, max(0.1, deadline - time.monotonic())))
            client.connect(str(socket_path))
            client.sendall(b'{"protocol_version":1,"operation":"health"}\n')
            response = json.loads(read_frame(client))
            expected = {
                "protocol_version",
                "status",
                "readiness",
                "model_id",
                "model_sha256",
                "samples_per_channel",
                "sample_rate_hz",
                "normalization",
                "production_enabled",
            }
            health = require_exact_keys(response, expected, "health response")
            if (
                health["protocol_version"] != 1
                or health["status"] != "ok"
                or health["readiness"] != "experimental"
                or health["samples_per_channel"] != 1024
                or health["sample_rate_hz"] != 2_100_000
                or health["normalization"] not in ("complex_unit_rms", "four_window_capture_complex_unit_rms")
                or health["production_enabled"] is not False
            ):
                raise WorkerError("health_response", "worker health contract mismatch")
            print(json.dumps(health, ensure_ascii=False, sort_keys=True))
            return 0
        except (OSError, WorkerError, json.JSONDecodeError) as error:
            last_error = error
            time.sleep(0.1)
        finally:
            client.close()
    raise WorkerError("probe_timeout", str(last_error or "worker did not become ready"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rf-v1-profile", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--socket", type=Path, default=DEFAULT_SOCKET)
    parser.add_argument("--spool-root", type=Path, default=DEFAULT_SPOOL_ROOT)
    parser.add_argument("--max-requests", type=int, default=0)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--probe-socket", type=Path)
    parser.add_argument("--probe-timeout-ms", type=int, default=10_000)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.max_requests < 0:
        raise WorkerError("arguments", "max requests must be non-negative")
    if not 100 <= args.probe_timeout_ms <= 120_000:
        raise WorkerError("arguments", "probe timeout must be between 100 and 120000 ms")
    if args.probe_socket is not None:
        return probe_socket(args.probe_socket, args.probe_timeout_ms)
    os.umask(0o077)
    if args.rf_v1_profile is not None and args.max_requests <= 0:
        raise WorkerError("arguments", "RF-v1 candidate requires a finite positive max-requests")
    backend = RfV1Backend(args.rf_v1_profile) if args.rf_v1_profile is not None else MambaBackend(args.manifest)
    if args.self_test:
        phase = np.arange(backend.samples_per_channel, dtype=np.float32)
        phase *= np.float32(2.0 * math.pi / 32.0)
        iq = np.stack((np.cos(phase), np.sin(phase))).astype(np.float32)
        ranked, inference_us = backend.classify(iq)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "model_id": backend.model_id,
                    "model_sha256": backend.model_sha256,
                    "label": ranked[0][0],
                    "confidence": ranked[0][1],
                    "inference_us": inference_us,
                    "production_enabled": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    spool_root = prepare_spool_root(args.spool_root)
    serve(backend, args.socket, spool_root, args.max_requests)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WorkerError as error:
        print(
            json.dumps(
                {"status": "error", "code": error.code, "error": error.message},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from error
