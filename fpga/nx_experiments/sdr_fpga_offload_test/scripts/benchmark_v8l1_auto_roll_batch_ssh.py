#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import posixpath
import statistics
import sys
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdr_fpga_offload_test.sdr_kernel_client import (  # noqa: E402
    AGG8_VERSION,
    QUA8_VERSION,
    SUM8_ABI_VERSION,
    SUM8_CAPABILITY,
    V8D0_AGG8_BUILD_ID,
    V8D0_BUILD_ID,
    V8D0_QUA8_BUILD_ID,
    V8L1_AGG8_BUILD_ID,
    V8L1_AGG8_CAPABILITY,
    V8L1_BUILD_ID,
    V8L1_QUA8_BUILD_ID,
    V8L2_AGG8_BUILD_ID,
    V8L2_BUILD_ID,
    V8L2_QUA8_BUILD_ID,
)
from sdr_fpga_offload_test.sdr_kernel_contract import MAX_V8L1_AGG_FRAMES, SummaryVersion, signed96, unsigned96  # noqa: E402


TAP_BASE = 0x43C00000

READ_OFFSETS = {
    "agg_sequence": 0x17C,
    "summary_version": 0x040,
    "abi_version": 0x0EC,
    "capability": 0x0F0,
    "build_id": 0x0FC,
    "quality_version": 0x100,
    "quality_capability": 0x138,
    "quality_build_id": 0x13C,
    "agg_version": 0x180,
    "agg_control": 0x184,
    "agg_target": 0x188,
    "agg_frames": 0x18C,
    "agg_samples": 0x190,
    "rx0_corr_lo": 0x194,
    "rx0_corr_mid": 0x198,
    "rx0_corr_hi": 0x19C,
    "rx1_corr_lo": 0x1A0,
    "rx1_corr_mid": 0x1A4,
    "rx1_corr_hi": 0x1A8,
    "cross_re_lo": 0x1AC,
    "cross_re_mid": 0x1B0,
    "cross_re_hi": 0x1B4,
    "cross_im_lo": 0x1B8,
    "cross_im_mid": 0x1BC,
    "cross_im_hi": 0x1C0,
    "rx0_raw_lo": 0x1C4,
    "rx0_raw_mid": 0x1C8,
    "rx0_raw_hi": 0x1CC,
    "rx1_raw_lo": 0x1D0,
    "rx1_raw_mid": 0x1D4,
    "rx1_raw_hi": 0x1D8,
    "rx0_clip_count": 0x1DC,
    "rx1_clip_count": 0x1E0,
    "rx0_zero_cross_count": 0x1E4,
    "rx1_zero_cross_count": 0x1E8,
    "same_sign_count": 0x1EC,
    "last_frame": 0x1F0,
    "agg_capability": 0x1F4,
    "agg_build_id": 0x1F8,
    "agg_limit": 0x1FC,
}


def _run(client: paramiko.SSHClient, script: str, timeout: float = 30.0) -> tuple[str, float]:
    t0 = time.perf_counter()
    stdin, stdout, stderr = client.exec_command(script, timeout=timeout)
    try:
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace").strip()
    finally:
        stdin.close()
        stdout.close()
        stderr.close()
    elapsed = time.perf_counter() - t0
    if rc != 0:
        raise RuntimeError(err or out)
    return out, elapsed


def _parse_kv(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.strip().split("=", 1)
        values[key] = int(value, 0)
    return values


def _read_script() -> str:
    read_lines = "\n".join(
        f"echo {name}=$(devmem 0x{TAP_BASE + offset:08x} 32)"
        for name, offset in READ_OFFSETS.items()
    )
    return f"""
set -eu
{read_lines}
"""


def _start_script(frame_len: int, agg_frames: int) -> str:
    return f"""
set -eu
devmem 0x{TAP_BASE + 0x004:08x} 32 0x{frame_len:08x} >/dev/null
devmem 0x{TAP_BASE + 0x188:08x} 32 0x{agg_frames:08x} >/dev/null
devmem 0x{TAP_BASE + 0x184:08x} 32 0x00000007 >/dev/null
devmem 0x{TAP_BASE + 0x184:08x} 32 0x00000005 >/dev/null
devmem 0x{TAP_BASE + 0x000:08x} 32 0x00000002 >/dev/null
devmem 0x{TAP_BASE + 0x000:08x} 32 0x00000001 >/dev/null
echo started=1
"""


def _stop_script() -> str:
    return f"""
set -eu
devmem 0x{TAP_BASE + 0x184:08x} 32 0x00000000 >/dev/null
echo stopped=1
"""


def _derived(rx0_corr: int, rx1_corr: int, cross_re: int, cross_im: int, samples: int) -> dict:
    denom = math.sqrt(float(rx0_corr) * float(rx1_corr)) if rx0_corr > 0 and rx1_corr > 0 else 0.0
    return {
        "coherence": float(math.hypot(cross_re, cross_im) / denom) if denom > 0 else None,
        "phase_deg": float(math.degrees(math.atan2(cross_im, cross_re))) if (cross_re or cross_im) else None,
        "rx0_avg_power": float(rx0_corr) / float(samples) if rx0_corr > 0 and samples > 0 else None,
        "rx1_avg_power": float(rx1_corr) / float(samples) if rx1_corr > 0 and samples > 0 else None,
    }


def _decode(values: dict[str, int], elapsed: float, prior_sequence: int | None, requested: dict[str, int]) -> dict:
    rx0_corr = signed96(values["rx0_corr_lo"], values["rx0_corr_mid"], values["rx0_corr_hi"])
    rx1_corr = signed96(values["rx1_corr_lo"], values["rx1_corr_mid"], values["rx1_corr_hi"])
    cross_re = signed96(values["cross_re_lo"], values["cross_re_mid"], values["cross_re_hi"])
    cross_im = signed96(values["cross_im_lo"], values["cross_im_mid"], values["cross_im_hi"])
    samples = values["agg_samples"]
    sequence = values["agg_sequence"]
    sequence_delta = None if prior_sequence is None else ((sequence - prior_sequence) & 0xFFFFFFFF)
    checks = {
        "summary_version_ok": values["summary_version"] == int(SummaryVersion.SUM8),
        "abi_version_ok": values["abi_version"] == SUM8_ABI_VERSION,
        "capability_ok": values["capability"] == SUM8_CAPABILITY,
        "build_id_ok": values["build_id"] in (V8D0_BUILD_ID, V8L1_BUILD_ID, V8L2_BUILD_ID),
        "quality_version_ok": values["quality_version"] == QUA8_VERSION,
        "quality_capability_ok": values["quality_capability"] == 0x0000000F,
        "quality_build_id_ok": values["quality_build_id"] in (V8D0_QUA8_BUILD_ID, V8L1_QUA8_BUILD_ID, V8L2_QUA8_BUILD_ID),
        "agg_version_ok": values["agg_version"] == AGG8_VERSION,
        "agg_capability_ok": values["agg_capability"] == V8L1_AGG8_CAPABILITY,
        "agg_build_id_ok": values["agg_build_id"] in (V8D0_AGG8_BUILD_ID, V8L1_AGG8_BUILD_ID, V8L2_AGG8_BUILD_ID),
        "agg_limit_ok": values["agg_limit"] == MAX_V8L1_AGG_FRAMES,
        "auto_roll_enabled": bool(values["agg_control"] & (1 << 2)),
        "enabled": bool(values["agg_control"] & 1),
        "no_overflow": not bool(values["agg_control"] & (1 << 5)),
        "target_ok": values["agg_target"] == requested["agg_frames"],
        "frames_ok": values["agg_frames"] == requested["agg_frames"],
        "samples_ok": samples == requested["frame_len"] * requested["agg_frames"],
        "sequence_advanced": sequence_delta is None or sequence_delta >= 1,
        "sequence_delta_observed": sequence_delta is None or sequence_delta >= 1,
    }
    return {
        "requested": requested,
        "build_ids": {
            "summary": f"0x{values['build_id']:08X}",
            "quality": f"0x{values['quality_build_id']:08X}",
            "aggregate": f"0x{values['agg_build_id']:08X}",
        },
        "sequence": sequence,
        "sequence_delta": sequence_delta,
        "control_hex": f"0x{values['agg_control']:08X}",
        "frame_count": values["agg_frames"],
        "sample_count": samples,
        "rx0_corr_power_num": rx0_corr,
        "rx1_corr_power_num": rx1_corr,
        "corr_cross_re_num": cross_re,
        "corr_cross_im_num": cross_im,
        "rx0_raw_power": unsigned96(values["rx0_raw_lo"], values["rx0_raw_mid"], values["rx0_raw_hi"]),
        "rx1_raw_power": unsigned96(values["rx1_raw_lo"], values["rx1_raw_mid"], values["rx1_raw_hi"]),
        "rx0_clip_count": values["rx0_clip_count"],
        "rx1_clip_count": values["rx1_clip_count"],
        "rx0_zero_cross_count": values["rx0_zero_cross_count"],
        "rx1_zero_cross_count": values["rx1_zero_cross_count"],
        "same_sign_count": values["same_sign_count"],
        "last_frame": values["last_frame"],
        "derived": _derived(rx0_corr, rx1_corr, cross_re, cross_im, samples),
        "checks": checks,
        "passed": all(checks.values()),
        "timing_sec": {"read_latest_batch_exec": elapsed},
    }


def _stats(values: list[float]) -> dict[str, float]:
    return {
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "max": max(values),
    }


def _sleep_interval(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _connect_direct(args: argparse.Namespace) -> tuple[paramiko.SSHClient, paramiko.SSHClient | None]:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.host,
        username=args.user,
        password=args.password,
        timeout=args.timeout_sec,
        banner_timeout=args.timeout_sec,
        auth_timeout=args.timeout_sec,
    )
    return client, None


def _connect_via_nx(args: argparse.Namespace) -> tuple[paramiko.SSHClient, paramiko.SSHClient]:
    key = paramiko.Ed25519Key.from_private_key_file(str(args.nx_key))
    nx = paramiko.SSHClient()
    nx.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    nx.connect(
        args.nx_host,
        username=args.nx_user,
        pkey=key,
        timeout=args.timeout_sec,
        banner_timeout=args.timeout_sec,
        auth_timeout=args.timeout_sec,
    )
    transport = nx.get_transport()
    if transport is None:
        nx.close()
        raise RuntimeError("NX SSH transport is not available")
    channel = transport.open_channel("direct-tcpip", (args.host, args.port), ("127.0.0.1", 0))
    sdr = paramiko.SSHClient()
    sdr.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    sdr.connect(
        args.host,
        port=args.port,
        username=args.user,
        password=args.password,
        sock=channel,
        timeout=args.timeout_sec,
        banner_timeout=args.timeout_sec,
        auth_timeout=args.timeout_sec,
    )
    return sdr, nx


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark V8L1 auto-roll aggregate reads with one batched SSH exec per latest-window read.")
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--via-nx", action="store_true", help="Reach SDR by opening an SSH direct-tcpip channel through the NX.")
    parser.add_argument("--nx-host", default="192.168.2.193")
    parser.add_argument("--nx-user", default="wheeltec")
    parser.add_argument("--nx-key", type=Path, default=Path.home() / ".ssh" / "codex_nx_ed25519")
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--agg-frames", type=int, default=16)
    parser.add_argument("--reads", type=int, default=8)
    parser.add_argument("--interval-sec", type=float, default=2.0)
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    parser.add_argument("--out-json", default="logs/v8l1_auto_roll_batch_ssh.json")
    args = parser.parse_args()

    frame_len = max(1, min(65535, int(args.frame_len)))
    agg_frames = max(1, min(MAX_V8L1_AGG_FRAMES, int(args.agg_frames)))
    requested = {"frame_len": frame_len, "agg_frames": agg_frames}

    client, nx_client = _connect_via_nx(args) if args.via_nx else _connect_direct(args)
    captures = []
    start_elapsed = 0.0
    stop_elapsed = 0.0
    try:
        _, start_elapsed = _run(client, _start_script(frame_len, agg_frames), timeout=args.timeout_sec)
        prior_sequence = None
        _sleep_interval(float(args.interval_sec))
        for iteration in range(max(1, int(args.reads))):
            out, elapsed = _run(client, _read_script(), timeout=args.timeout_sec)
            item = _decode(_parse_kv(out), elapsed, prior_sequence, requested)
            item["iteration"] = iteration
            captures.append(item)
            prior_sequence = item["sequence"]
            _sleep_interval(float(args.interval_sec))
    finally:
        try:
            _, stop_elapsed = _run(client, _stop_script(), timeout=args.timeout_sec)
        finally:
            client.close()
            if nx_client is not None:
                nx_client.close()

    read_times = [float(item["timing_sec"]["read_latest_batch_exec"]) for item in captures]
    sequence_deltas = [item["sequence_delta"] for item in captures if item["sequence_delta"] is not None]
    payload = {
        "timestamp_sec": time.time(),
        "operation": "v8l1_auto_roll_batch_ssh",
        "requested": requested,
        "transport": {
            "sdr_host": args.host,
            "sdr_port": args.port,
            "via_nx": bool(args.via_nx),
            "nx_host": args.nx_host if args.via_nx else None,
            "nx_experiment_scope": posixpath.join("/home/wheeltec/ros2_ws/src/robot_control", "sdr_fpga_offload_test"),
        },
        "safety": {
            "no_ros": True,
            "no_streaming_runtime": True,
            "no_robot_control": True,
            "no_cmd_vel_or_motion": True,
            "devmem_only": True,
        },
        "transport_model": {
            "start_devmem_commands_once": 6,
            "read_devmem_commands_per_latest_window": len(READ_OFFSETS),
            "read_ssh_execs_per_latest_window": 1,
            "classic_v8_batched_devmem_commands_per_window": 46,
            "classic_v8_batched_ssh_execs_per_window": 1,
            "v8l1_steady_state_devmem_reduction_vs_classic_v8_percent": 100.0 * (1.0 - (len(READ_OFFSETS) / 46.0)),
        },
        "start_elapsed_sec": start_elapsed,
        "stop_elapsed_sec": stop_elapsed,
        "capture_count": len(captures),
        "pass_count": sum(1 for item in captures if item["passed"]),
        "passed": bool(captures) and all(item["passed"] for item in captures),
        "sequence_deltas": sequence_deltas,
        "skipped_window_count": sum(1 for value in sequence_deltas if value != 1),
        "read_timing_sec": _stats(read_times) if read_times else None,
        "captures": captures,
        "notes": [
            "V8L1 auto-roll configures AGG once, then NX polls/reads latest aggregate pages by sequence.",
            "This benchmark does not start ROS, SDR streaming runtime, robot_control, mapping, RTAB-Map, or motion paths.",
        ],
    }
    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))

    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
