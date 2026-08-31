#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdr_fpga_offload_test.native_transport import NativeMmioTransport  # noqa: E402
from sdr_fpga_offload_test.sdr_kernel_contract import TAP_BASE  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe SUM8/AGG8 through the local C mmap/UIO backend.")
    parser.add_argument("--mode", choices=["devmem", "uio", "file"], default="devmem")
    parser.add_argument("--device", default="/dev/mem")
    parser.add_argument("--library", default=None)
    parser.add_argument("--base", type=lambda text: int(text, 0), default=TAP_BASE)
    parser.add_argument("--span", type=lambda text: int(text, 0), default=0x10000)
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--agg-frames", type=int, default=64)
    parser.add_argument("--arm", action="store_true", help="Perform explicit SUM8/AGG8 arm/read before snapshot.")
    parser.add_argument("--timeout-us", type=int, default=500_000)
    parser.add_argument("--poll-sleep-us", type=int, default=1_000)
    parser.add_argument("--out-json", default=None)
    args = parser.parse_args()

    with NativeMmioTransport(
        mode=args.mode,
        device=args.device,
        library_path=args.library,
        base=args.base,
        span=args.span,
        read_only=False,
    ) as transport:
        poll_elapsed_ns = None
        if args.arm:
            transport.arm_aggregate(frame_len=args.frame_len, agg_frames=args.agg_frames)
            poll_elapsed_ns = transport.poll_done(timeout_us=args.timeout_us, poll_sleep_us=args.poll_sleep_us)
        snapshot = transport.read_sum8_snapshot(
            expected_frame_len=args.frame_len if args.arm else 0,
            expected_agg_frames=args.agg_frames if args.arm else 0,
        )

    payload = {
        "timestamp_sec": time.time(),
        "operation": "sum8_native_mmap_transport_probe",
        "mode": args.mode,
        "device": args.device,
        "base": f"0x{args.base:08X}",
        "span": args.span,
        "armed": bool(args.arm),
        "requested": {
            "frame_len": args.frame_len,
            "agg_frames": args.agg_frames,
        },
        "poll_elapsed_ns": poll_elapsed_ns,
        "snapshot": snapshot.to_dict(),
        "passed": snapshot.passed,
        "notes": [
            "This script uses the local C mmap/UIO backend; it does not fork devmem or use SSH in the hot path.",
            "It does not start ROS, SDR streaming runtime, robot_control, mapping, RTAB-Map, navigation, cmd_vel, or motion.",
            "Without --arm it is read-only. With --arm it only writes SUM8/AGG8 explicit arm/read control registers.",
        ],
    }

    if args.out_json:
        out_path = ROOT / args.out_json
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
