#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compare_sum8_fpga_assisted_metrics import ParamikoDevmemTransport, capture_raw_i16  # noqa: E402
from sdr_fpga_offload_test.feature_flag_assist import (  # noqa: E402
    AssistQualityGate,
    ExplicitArmReadSum8Assist,
)
from sdr_fpga_offload_test.fpga_assisted_metrics import dual_rx_cpu_primitives  # noqa: E402
from sdr_fpga_offload_test.sdr_kernel_client import Sum8AggregateClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Independent feature-flag assist probe using explicit SUM8/AGG8 arm/read.")
    parser.add_argument("--mode", choices=("off", "shadow", "assist"), default="shadow")
    parser.add_argument("--sdr-host", default="192.168.1.10")
    parser.add_argument("--sdr-user", default="root")
    parser.add_argument("--sdr-password", default="")
    parser.add_argument("--uri", default="ip:192.168.1.10")
    parser.add_argument("--phy-device", default="ad9361-phy")
    parser.add_argument("--rx-device", default="")
    parser.add_argument("--center-freq-hz", type=int, default=2_452_000_000)
    parser.add_argument("--sample-rate-hz", type=int, default=2_000_000)
    parser.add_argument("--baseline-m", type=float, default=0.02)
    parser.add_argument("--phase-calibration-deg", type=float, default=0.0)
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--agg-frames", type=int, default=64)
    parser.add_argument("--channels", default="voltage0,voltage1,voltage2,voltage3")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--poll-sec", type=float, default=0.005)
    parser.add_argument("--timeout-sec", type=float, default=5.0)
    parser.add_argument("--min-coherence", type=float, default=0.2)
    parser.add_argument("--min-rssi-dbfs", type=float, default=-90.0)
    parser.add_argument("--max-total-clip-count", type=int, default=0)
    parser.add_argument("--allow-aoa-phase-clipped", action="store_true")
    parser.add_argument("--out-json", default="logs/feature_flag_assist_probe.json")
    args = parser.parse_args()

    channels = [token.strip() for token in args.channels.split(",") if token.strip()]
    if len(channels) != 4:
        raise ValueError("This probe expects four voltage lanes: I0,Q0,I1,Q1")

    transport = ParamikoDevmemTransport(args.sdr_host, args.sdr_user, args.sdr_password, timeout_sec=10.0)
    decisions = []
    try:
        client = Sum8AggregateClient(transport)
        client.assert_sum8()
        assist = ExplicitArmReadSum8Assist(
            client,
            frame_len=args.frame_len,
            agg_frames=args.agg_frames,
            quality_gate=AssistQualityGate(
                min_coherence=args.min_coherence,
                min_rssi_dbfs=args.min_rssi_dbfs,
                max_total_clip_count=args.max_total_clip_count,
                allow_aoa_phase_clipped=bool(args.allow_aoa_phase_clipped),
            ),
            poll_sec=args.poll_sec,
            timeout_sec=args.timeout_sec,
        )
        for iteration in range(max(1, args.repeat)):
            iter_start = time.perf_counter()
            raw_start = time.perf_counter()
            raw = capture_raw_i16(
                args.uri,
                args.phy_device,
                args.rx_device,
                args.sample_rate_hz,
                args.center_freq_hz,
                args.frame_len * args.agg_frames,
                channels,
            )
            cpu_metrics = dual_rx_cpu_primitives(raw)
            decision = assist.decide(
                mode=args.mode,
                cpu_metrics=cpu_metrics,
                center_freq_hz=args.center_freq_hz,
                baseline_m=args.baseline_m,
                phase_calibration_deg=args.phase_calibration_deg,
            ).to_dict()
            decision["iteration"] = iteration
            decision["timing_sec"] = {
                "raw_iio_capture_plus_cpu": time.perf_counter() - raw_start,
                "iteration_total": time.perf_counter() - iter_start,
            }
            decisions.append(decision)
    finally:
        transport.close()

    payload = {
        "timestamp_sec": time.time(),
        "operation": "feature_flag_assist_probe_explicit_arm_read",
        "mode": args.mode,
        "requested": {
            "frame_len": args.frame_len,
            "agg_frames": args.agg_frames,
            "repeat": args.repeat,
            "channels": channels,
        },
        "quality_gate": {
            "min_coherence": args.min_coherence,
            "min_rssi_dbfs": args.min_rssi_dbfs,
            "max_total_clip_count": args.max_total_clip_count,
            "allow_aoa_phase_clipped": bool(args.allow_aoa_phase_clipped),
        },
        "capture_count": len(decisions),
        "fpga_read_ok_count": sum(1 for item in decisions if item.get("fpga") and item["fpga"].get("error") is None),
        "usable_for_assist_count": sum(1 for item in decisions if item["usable_for_assist"]),
        "selected_fpga_count": sum(1 for item in decisions if item["selected_source"] == "fpga"),
        "selected_cpu_count": sum(1 for item in decisions if item["selected_source"] == "cpu"),
        "fallback_count": sum(1 for item in decisions if item["reason"] == "assist_cpu_fallback"),
        "passed": bool(decisions) and all(item["selected_source"] in ("cpu", "fpga") for item in decisions),
        "decisions": decisions,
        "safety": {
            "directory": str(ROOT),
            "no_ros": True,
            "no_streaming_runtime": True,
            "no_robot_control": True,
            "no_cmd_vel_or_motion": True,
            "explicit_arm_read_only": True,
            "auto_roll_required": False,
        },
        "notes": [
            "Shadow mode selects CPU output and logs FPGA sidecar eligibility.",
            "Assist mode selects FPGA only when explicit arm/read AGG8 quality gates pass; otherwise it falls back to CPU.",
            "CPU raw-IQ and FPGA AGG8 windows are adjacent/nearby, not hardware-synchronized.",
        ],
    }
    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
