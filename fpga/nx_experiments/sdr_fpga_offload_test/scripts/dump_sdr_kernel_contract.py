#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdr_fpga_offload_test.sdr_kernel_contract import (  # noqa: E402
    FUTURE_KERNEL_ROUTE,
    MAX_V5_CORRECTED_FRAME_LEN,
    MAX_V6_CORRECTED_FRAME_LEN,
    MAX_V7_CORRECTED_FRAME_LEN,
    MAX_V8_AGG_FRAMES,
    TAP_BASE,
    SummaryVersion,
    as_fft_shadow_register_dict,
    as_register_dict,
    as_sum6_register_dict,
    as_sum7_register_dict,
    as_sum8_register_dict,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump machine-readable SDR FPGA kernel contract.")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    payload = {
        "tap_base_hex": f"0x{TAP_BASE:08X}",
        "max_v5_corrected_frame_len": MAX_V5_CORRECTED_FRAME_LEN,
        "max_v6_corrected_frame_len": MAX_V6_CORRECTED_FRAME_LEN,
        "max_v7_corrected_frame_len": MAX_V7_CORRECTED_FRAME_LEN,
        "max_v8_agg_frames": MAX_V8_AGG_FRAMES,
        "summary_versions": {item.name: f"0x{int(item):08X}" for item in SummaryVersion},
        "sum5_registers": as_register_dict(),
        "sum6_registers": as_sum6_register_dict(),
        "sum7_registers": as_sum7_register_dict(),
        "sum8_registers": as_sum8_register_dict(),
        "fft_shadow_registers": as_fft_shadow_register_dict(),
        "future_kernel_route": FUTURE_KERNEL_ROUTE,
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
