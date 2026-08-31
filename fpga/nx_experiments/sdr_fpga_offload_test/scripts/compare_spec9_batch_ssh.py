#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdr_fpga_offload_test.sdr_kernel_contract import TAP_BASE  # noqa: E402
from sdr_fpga_offload_test.spec9_client import (  # noqa: E402
    AGG9_BUILD_ID,
    AGG9_CAPABILITY,
    AGG9_VERSION,
    QUA9_BUILD_ID,
    QUA9_CAPABILITY,
    QUA9_VERSION,
    SPEC9_ABI_VERSION,
    SPEC9_BIN_COUNT,
    SPEC9_BUILD_ID,
    SPEC9_CAPABILITY,
    SPEC9_VERSION,
    SUM9_ABI_VERSION,
    SUM9_BUILD_ID,
    SUM9_CAPABILITY,
    SUM9_VERSION,
)


READ_OFFSETS = {
    "summary_version": 0x040,
    "abi_version": 0x0EC,
    "capability": 0x0F0,
    "build_id": 0x0FC,
    "quality_version": 0x100,
    "quality_capability": 0x138,
    "quality_build_id": 0x13C,
    "agg_version": 0x180,
    "agg_capability": 0x1F4,
    "agg_build_id": 0x1F8,
    "spec_version": 0x200,
    "spec_flags": 0x204,
    "spec_frame_id": 0x208,
    "spec_samples": 0x20C,
    "spec_peak_bin": 0x210,
    "spec_peak_power": 0x214,
    "spec_total_power": 0x218,
    "spec_noise_floor": 0x21C,
    "spec_prominence": 0x220,
    "spec_bin0_power": 0x224,
    "spec_bin1_power": 0x228,
    "spec_bin2_power": 0x22C,
    "spec_bin3_power": 0x230,
    "spec_limit_flags": 0x234,
    "spec_rx_mask": 0x238,
    "spec_reserved0": 0x23C,
    "spec_bin_count": 0x2F0,
    "spec_capability": 0x2F4,
    "spec_build_id": 0x2F8,
    "spec_abi_version": 0x2FC,
}


def _shell_script(frame_len: int, poll_ms: int, max_polls: int) -> str:
    read_lines = "\n".join(
        f"echo {name}=$(devmem 0x{TAP_BASE + offset:08x} 32)"
        for name, offset in READ_OFFSETS.items()
    )
    return f"""
set -eu
devmem 0x{TAP_BASE + 0x004:08x} 32 0x{frame_len:08x} >/dev/null
devmem 0x{TAP_BASE + 0x000:08x} 32 0x00000002 >/dev/null
devmem 0x{TAP_BASE + 0x000:08x} 32 0x00000001 >/dev/null
i=0
while [ "$i" -lt {max_polls} ]; do
  v=$(devmem 0x{TAP_BASE + 0x204:08x} 32)
  if [ $((v & 1)) -ne 0 ] && [ $((v & 2)) -eq 0 ]; then
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


def capture_once(client: paramiko.SSHClient, frame_len: int, poll_ms: int, max_polls: int) -> dict:
    t0 = time.perf_counter()
    stdin, stdout, stderr = client.exec_command(_shell_script(frame_len, poll_ms, max_polls))
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
    flags = values["spec_flags"]
    checks = {
        "summary_version_ok": values["summary_version"] == SUM9_VERSION,
        "abi_version_ok": values["abi_version"] == SUM9_ABI_VERSION,
        "capability_ok": values["capability"] == SUM9_CAPABILITY,
        "build_id_ok": values["build_id"] == SUM9_BUILD_ID,
        "quality_version_ok": values["quality_version"] == QUA9_VERSION,
        "quality_capability_ok": values["quality_capability"] == QUA9_CAPABILITY,
        "quality_build_id_ok": values["quality_build_id"] == QUA9_BUILD_ID,
        "agg_version_ok": values["agg_version"] == AGG9_VERSION,
        "agg_capability_ok": values["agg_capability"] == AGG9_CAPABILITY,
        "agg_build_id_ok": values["agg_build_id"] == AGG9_BUILD_ID,
        "spec_version_ok": values["spec_version"] == SPEC9_VERSION,
        "spec_capability_ok": values["spec_capability"] == SPEC9_CAPABILITY,
        "spec_build_id_ok": values["spec_build_id"] == SPEC9_BUILD_ID,
        "spec_abi_version_ok": values["spec_abi_version"] == SPEC9_ABI_VERSION,
        "spec_bin_count_ok": values["spec_bin_count"] == SPEC9_BIN_COUNT,
        "valid": bool(flags & 1),
        "not_busy": not bool(flags & 2),
        "samples_ok": values["spec_samples"] == frame_len,
        "peak_bin_range": 0 <= values["spec_peak_bin"] < SPEC9_BIN_COUNT,
        "total_ge_peak": values["spec_total_power"] >= values["spec_peak_power"],
    }
    return {
        "requested": {"frame_len": frame_len},
        "registers": {name: {"value": value, "hex": f"0x{value & 0xFFFFFFFF:08X}"} for name, value in values.items()},
        "spec": {
            "flags_hex": f"0x{flags:08X}",
            "frame_id": values["spec_frame_id"],
            "samples": values["spec_samples"],
            "peak_bin": values["spec_peak_bin"],
            "peak_power": values["spec_peak_power"],
            "total_power": values["spec_total_power"],
            "noise_floor": values["spec_noise_floor"],
            "prominence": values["spec_prominence"],
            "bins": [values["spec_bin0_power"], values["spec_bin1_power"], values["spec_bin2_power"], values["spec_bin3_power"]],
            "limit_flags_hex": f"0x{values['spec_limit_flags']:08X}",
        },
        "checks": checks,
        "passed": all(checks.values()),
        "timing_sec": {
            "single_ssh_exec_total": time.perf_counter() - t0,
            "poll_count": values.get("poll_count", -1),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fast batched V9A/SPEC9 read: one SSH exec per capture.")
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--repeat", type=int, default=100)
    parser.add_argument("--poll-ms", type=int, default=1)
    parser.add_argument("--max-polls", type=int, default=5000)
    parser.add_argument("--out-json", default="logs/spec9_batch_ssh.json")
    args = parser.parse_args()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=args.password, timeout=10, banner_timeout=10, auth_timeout=10)
    try:
        captures = []
        for iteration in range(max(1, args.repeat)):
            item = capture_once(client, args.frame_len, args.poll_ms, args.max_polls)
            item["iteration"] = iteration
            captures.append(item)
    finally:
        client.close()

    frame_ids = [item["spec"]["frame_id"] for item in captures]
    monotonic = all(b > a for a, b in zip(frame_ids, frame_ids[1:]))
    payload = {
        "timestamp_sec": time.time(),
        "operation": "spec9_batch_ssh",
        "capture_count": len(captures),
        "pass_count": sum(1 for item in captures if item["passed"]),
        "frame_id_monotonic": monotonic,
        "passed": all(item["passed"] for item in captures) and monotonic,
        "captures": captures,
        "notes": [
            "One SSH exec per SPEC9 capture replaces per-register SSH/devmem calls.",
            "Bypass-only; no ROS, streaming runtime, robot_control, mapping, RTAB-Map, or motion paths are started.",
        ],
    }
    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
