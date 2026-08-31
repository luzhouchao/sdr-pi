#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdr_fpga_offload_test.fpga_regs import write_json  # noqa: E402
from sdr_fpga_offload_test.reference_compute import (  # noqa: E402
    dataclass_to_dict,
    load_raw_i16_npz,
    spectrum_reference,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline timing profile for NX SDR reference math.")
    parser.add_argument("--raw-npz", required=True)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--center-freq-hz", type=float, default=2_452_000_000.0)
    parser.add_argument("--sample-rate-hz", type=float, default=2_000_000.0)
    parser.add_argument("--nfft", type=int, default=2048)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    raw = load_raw_i16_npz(args.raw_npz)
    elapsed = []
    last = None
    for _ in range(max(1, int(args.iterations))):
        t0 = time.perf_counter()
        last = spectrum_reference(
            raw,
            nfft=args.nfft,
            center_freq_hz=args.center_freq_hz,
            sample_rate_hz=args.sample_rate_hz,
        )
        elapsed.append(time.perf_counter() - t0)

    payload = {
        "iterations": len(elapsed),
        "elapsed_sec": {
            "min": min(elapsed),
            "median": statistics.median(elapsed),
            "mean": statistics.fmean(elapsed),
            "max": max(elapsed),
        },
        "last_reference": dataclass_to_dict(last),
    }
    if args.out:
        write_json(args.out, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
