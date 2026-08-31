#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdr_fpga_offload_test.sdr_kernel_client import (  # noqa: E402
    AGG8_BUILD_ID,
    AGG8_CAPABILITY,
    AGG8_VERSION,
    QUA8_BUILD_ID,
    QUA8_CAPABILITY,
    QUA8_VERSION,
    SUM8_ABI_VERSION,
    SUM8_BUILD_ID,
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
from sdr_fpga_offload_test.sdr_kernel_contract import MAX_V8_AGG_FRAMES, SummaryVersion, signed96, unsigned96  # noqa: E402


TAP_BASE = 0x43C00000


READ_OFFSETS = {
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


def _shell_script(frame_len: int, agg_frames: int, poll_ms: int, max_polls: int) -> str:
    read_lines = "\n".join(
        f"echo {name}=$(devmem 0x{TAP_BASE + offset:08x} 32)"
        for name, offset in READ_OFFSETS.items()
    )
    return f"""
set -eu
devmem 0x{TAP_BASE + 0x004:08x} 32 0x{frame_len:08x} >/dev/null
devmem 0x{TAP_BASE + 0x188:08x} 32 0x{agg_frames:08x} >/dev/null
devmem 0x{TAP_BASE + 0x184:08x} 32 0x00000003 >/dev/null
devmem 0x{TAP_BASE + 0x184:08x} 32 0x00000001 >/dev/null
devmem 0x{TAP_BASE + 0x000:08x} 32 0x00000002 >/dev/null
devmem 0x{TAP_BASE + 0x000:08x} 32 0x00000001 >/dev/null
i=0
while [ "$i" -lt {max_polls} ]; do
  v=$(devmem 0x{TAP_BASE + 0x184:08x} 32)
  if [ $((v & 16)) -ne 0 ]; then
    break
  fi
  i=$((i + 1))
  usleep {max(1000, poll_ms * 1000)} 2>/dev/null || sleep 0.01
done
echo poll_count=$i
{read_lines}
"""


def _parse_kv(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.strip().split("=", 1)
        values[key] = int(value, 0)
    return values


def _derived(rx0_corr: int, rx1_corr: int, cross_re: int, cross_im: int, samples: int) -> dict:
    denom = math.sqrt(float(rx0_corr) * float(rx1_corr)) if rx0_corr > 0 and rx1_corr > 0 else 0.0
    return {
        "coherence": float(math.hypot(cross_re, cross_im) / denom) if denom > 0 else None,
        "phase_deg": float(math.degrees(math.atan2(cross_im, cross_re))) if (cross_re or cross_im) else None,
        "rx0_corr_mean_dbfs": 10.0 * math.log10(float(rx0_corr) / float(samples * samples) / float(32768 * 32768)) if rx0_corr > 0 and samples > 0 else None,
        "rx1_corr_mean_dbfs": 10.0 * math.log10(float(rx1_corr) / float(samples * samples) / float(32768 * 32768)) if rx1_corr > 0 and samples > 0 else None,
    }


def capture_once(client: paramiko.SSHClient, frame_len: int, agg_frames: int, poll_ms: int, max_polls: int) -> dict:
    t0 = time.perf_counter()
    stdin, stdout, stderr = client.exec_command(_shell_script(frame_len, agg_frames, poll_ms, max_polls))
    try:
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace").strip()
    finally:
        stdin.close()
        stdout.close()
        stderr.close()
    if rc != 0:
        raise RuntimeError(err or out)
    values = _parse_kv(out)
    rx0_corr = signed96(values["rx0_corr_lo"], values["rx0_corr_mid"], values["rx0_corr_hi"])
    rx1_corr = signed96(values["rx1_corr_lo"], values["rx1_corr_mid"], values["rx1_corr_hi"])
    cross_re = signed96(values["cross_re_lo"], values["cross_re_mid"], values["cross_re_hi"])
    cross_im = signed96(values["cross_im_lo"], values["cross_im_mid"], values["cross_im_hi"])
    samples = values["agg_samples"]
    checks = {
        "summary_version_ok": values["summary_version"] == int(SummaryVersion.SUM8),
        "abi_version_ok": values["abi_version"] == SUM8_ABI_VERSION,
        "capability_ok": values["capability"] == SUM8_CAPABILITY,
        "build_id_ok": values["build_id"] in (SUM8_BUILD_ID, V8D0_BUILD_ID, V8L1_BUILD_ID, V8L2_BUILD_ID),
        "quality_version_ok": values["quality_version"] == QUA8_VERSION,
        "quality_capability_ok": values["quality_capability"] == QUA8_CAPABILITY,
        "quality_build_id_ok": values["quality_build_id"] in (QUA8_BUILD_ID, V8D0_QUA8_BUILD_ID, V8L1_QUA8_BUILD_ID, V8L2_QUA8_BUILD_ID),
        "agg_version_ok": values["agg_version"] == AGG8_VERSION,
        "agg_capability_ok": values["agg_capability"] in (AGG8_CAPABILITY, V8L1_AGG8_CAPABILITY),
        "agg_build_id_ok": values["agg_build_id"] in (AGG8_BUILD_ID, V8D0_AGG8_BUILD_ID, V8L1_AGG8_BUILD_ID, V8L2_AGG8_BUILD_ID),
        "agg_limit_ok": values["agg_limit"] == MAX_V8_AGG_FRAMES,
        "done": bool(values["agg_control"] & (1 << 4)),
        "no_overflow": not bool(values["agg_control"] & (1 << 5)),
        "frames_ok": values["agg_frames"] == agg_frames,
        "samples_ok": samples == frame_len * agg_frames,
    }
    return {
        "requested": {"frame_len": frame_len, "agg_frames": agg_frames},
        "summary": {
            "version_hex": f"0x{values['summary_version']:08X}",
            "quality_version_hex": f"0x{values['quality_version']:08X}",
            "agg_version_hex": f"0x{values['agg_version']:08X}",
        },
        "aggregate": {
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
        },
        "checks": checks,
        "passed": all(checks.values()),
        "timing_sec": {
            "single_ssh_exec_total": time.perf_counter() - t0,
            "poll_count": values.get("poll_count", -1),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fast batched SUM8/AGG8 read: one SSH exec per aggregate capture.")
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--agg-frames", type=int, nargs="+", default=[64])
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--poll-ms", type=int, default=1)
    parser.add_argument("--max-polls", type=int, default=5000)
    parser.add_argument("--out-json", default="logs/sum8_aggregate_batch_ssh_20260608.json")
    args = parser.parse_args()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=args.password, timeout=10, banner_timeout=10, auth_timeout=10)
    try:
        captures = []
        for frame_count in args.agg_frames:
            for iteration in range(max(1, args.repeat)):
                item = capture_once(client, args.frame_len, frame_count, args.poll_ms, args.max_polls)
                item["iteration"] = iteration
                captures.append(item)
    finally:
        client.close()

    payload = {
        "timestamp_sec": time.time(),
        "operation": "sum8_aggregate_batch_ssh",
        "capture_count": len(captures),
        "pass_count": sum(1 for item in captures if item["passed"]),
        "passed": all(item["passed"] for item in captures),
        "captures": captures,
        "notes": [
            "One SSH exec per aggregate capture replaces per-register SSH/devmem calls.",
            "This is still bypass-only and does not start ROS, streaming runtime, robot_control, mapping, RTAB-Map, or motion paths.",
        ],
    }
    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
