#!/usr/bin/env python3
"""Focused protocol and containment tests for the experimental AMC worker."""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import struct
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKER_PATH = REPO_ROOT / "jetson-agx" / "sdrharness" / "scripts" / "amc-mamba-worker.py"
SPEC = importlib.util.spec_from_file_location("amc_mamba_worker", WORKER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import worker from {WORKER_PATH}")
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


class FakeBackend:
    samples_per_channel = 1024
    sample_rate_hz = 2_100_000


def request(path: Path, *, normalization: str = "unit_rms") -> dict[str, object]:
    return {
        "protocol_version": 1,
        "request_id": 7,
        "session_generation": 9,
        "candidate_id": "candidate-1",
        "iq": {
            "storage": {
                "path": str(path),
                "offset_bytes": 0,
                "length_bytes": 8192,
            },
            "sample_format": "f32_le",
            "layout": "planar_iq",
            "normalization": normalization,
            "samples_per_channel": 1024,
            "sample_rate_hz": 2_100_000,
            "center_hz": 433_920_000,
        },
        "max_latency_ms": 5000,
    }


class WorkerContractTests(unittest.TestCase):
    def test_manifest_and_request_contracts_are_strict(self) -> None:
        manifest = worker.load_manifest(worker.DEFAULT_MANIFEST)
        self.assertEqual(manifest["admission"], "experimental_rf_only")
        self.assertEqual(
            worker.validate_request(request(Path("/run/sdr-agent/iq/test.f32")), FakeBackend)[
                "request_id"
            ],
            7,
        )
        with self.assertRaisesRegex(worker.WorkerError, "iq_normalization"):
            worker.validate_request(
                request(Path("/run/sdr-agent/iq/test.f32"), normalization="none"),
                FakeBackend,
            )

    def test_iq_loader_requires_private_in_root_unit_rms_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="amc-worker-test-") as temporary:
            root = Path(temporary)
            root.chmod(0o700)
            iq_path = root / "window.f32"
            values = [0.6] * 1024 + [0.8] * 1024
            iq_path.write_bytes(b"".join(struct.pack("<f", value) for value in values))
            iq_path.chmod(0o600)
            loaded = worker.load_iq(request(iq_path), root.resolve(), 0.001)
            self.assertEqual(loaded.shape, (2, 1024))

            iq_path.chmod(0o644)
            with self.assertRaisesRegex(worker.WorkerError, "iq_permissions"):
                worker.load_iq(request(iq_path), root.resolve(), 0.001)

    def test_response_is_newline_framed_and_broken_pipe_is_contained(self) -> None:
        sender, receiver = socket.socketpair()
        try:
            self.assertTrue(worker.try_write_frame(sender, {"status": "ok"}))
            self.assertEqual(json.loads(receiver.recv(4096)), {"status": "ok"})
        finally:
            sender.close()
            receiver.close()

        sender, receiver = socket.socketpair()
        receiver.close()
        try:
            self.assertFalse(worker.try_write_frame(sender, {"status": "ok"}))
        finally:
            sender.close()


if __name__ == "__main__":
    os.umask(0o077)
    unittest.main()
