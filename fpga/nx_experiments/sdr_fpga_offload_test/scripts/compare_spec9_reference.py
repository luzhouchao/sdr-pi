#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdr_fpga_offload_test.spec9_reference import named_test_vectors, spec9_reference  # noqa: E402


EXPECTED_PEAK_BINS = {
    "all_zero": 0,
    "constant_dc": 0,
    "alternating_fs2": 2,
    "fs4_rotation_like": 3,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic integer reference tests for V9A/SPEC9.")
    parser.add_argument("--out-json", default="logs/spec9_reference_selftest.json")
    args = parser.parse_args()

    captures = []
    for name, samples in named_test_vectors().items():
        ref = spec9_reference(samples)
        checks = {
            "valid": bool(ref.flags & 1),
            "samples_match": ref.samples == len(samples),
            "peak_bin_range": 0 <= ref.peak_bin < 4,
            "total_ge_peak": ref.total_power >= ref.peak_power,
            "expected_peak_bin": ref.peak_bin == EXPECTED_PEAK_BINS.get(name, ref.peak_bin),
        }
        captures.append(
            {
                "name": name,
                "reference": ref.to_dict(),
                "checks": checks,
                "passed": all(checks.values()),
            }
        )

    payload = {
        "timestamp_sec": time.time(),
        "operation": "spec9_reference_selftest",
        "capture_count": len(captures),
        "pass_count": sum(1 for item in captures if item["passed"]),
        "passed": all(item["passed"] for item in captures),
        "captures": captures,
        "notes": [
            "This models the V9A 4-bin fixed spectral proxy only.",
            "It intentionally does not call numpy.fft because SPEC9 is not a full FFT or PSD.",
        ],
    }
    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
