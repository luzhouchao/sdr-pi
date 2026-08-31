#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdr_fpga_offload_test.compare_summary import (  # noqa: E402
    checks_to_payload,
    compare_power_frame,
    normalize_power_summary,
)
from sdr_fpga_offload_test.fpga_regs import write_json  # noqa: E402
from sdr_fpga_offload_test.reference_compute import (  # noqa: E402
    dataclass_to_dict,
    load_raw_i16_npz,
    power_frame_reference,
)


def _load_fpga_summary(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data.get("spectrum_summary"), dict):
        return data["spectrum_summary"]
    if isinstance(data.get("summary"), dict):
        return data["summary"]
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare FPGA time-domain power summary against offline NX reference math.")
    parser.add_argument("--raw-npz", required=True, help="NPZ with raw_i16 or raw array")
    parser.add_argument("--fpga-json", required=True, help="FPGA summary JSON")
    parser.add_argument("--db-tol", type=float, default=0.25)
    parser.add_argument("--raw-power-tol", type=float, default=0.0)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    raw = load_raw_i16_npz(args.raw_npz)
    ref = dataclass_to_dict(power_frame_reference(raw))
    fpga_summary = _load_fpga_summary(args.fpga_json)
    normalized_fpga = normalize_power_summary(fpga_summary)
    checks = compare_power_frame(
        ref,
        fpga_summary,
        db_tol=args.db_tol,
        raw_power_tol=args.raw_power_tol,
    )
    payload = {
        "reference": ref,
        "fpga_summary": normalized_fpga,
        "comparison": checks_to_payload(checks),
    }
    if args.out:
        write_json(args.out, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
