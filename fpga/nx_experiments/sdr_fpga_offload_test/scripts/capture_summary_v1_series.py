#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path

import paramiko


LOG_DIR = Path("/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/logs")
TAP_BASE = 0x43C00000


def parse_devmem(text: str) -> int:
    text = text.strip()
    if not text:
        raise RuntimeError("empty devmem output")
    return int(text.split()[0], 0)


def rssi_from_sum_power(sum_power: int, sample_count: int) -> float | None:
    if sample_count <= 0:
        return None
    mean_power_norm = float(sum_power) / float(sample_count) / float(32768.0 * 32768.0)
    return float(10.0 * math.log10(mean_power_norm + 1e-12))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture repeated Summary V1 FPGA frames using register-only tap control."
    )
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--settle-sec", type=float, default=0.05)
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    requested_frames = max(1, int(args.frames))
    frame_len = max(1, min(65535, int(args.frame_len)))
    settle_sec = max(0.0, float(args.settle_sec))

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.host,
        username=args.user,
        password=args.password,
        timeout=10,
        banner_timeout=10,
        auth_timeout=10,
    )

    def run(cmd: str) -> dict:
        stdin, stdout, stderr = client.exec_command(cmd)
        try:
            rc = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            return {"rc": rc, "out": out, "err": err, "cmd": cmd}
        finally:
            stdin.close()
            stdout.close()
            stderr.close()

    def read32(addr: int) -> int:
        result = run(f"devmem 0x{addr:08x} 32")
        if result["rc"] != 0:
            raise RuntimeError(f"devmem read failed at 0x{addr:08x}: {result['err']}")
        return parse_devmem(result["out"])

    def write32(addr: int, value: int) -> None:
        result = run(f"devmem 0x{addr:08x} 32 0x{value & 0xffffffff:08x}")
        if result["rc"] != 0:
            raise RuntimeError(f"devmem write failed at 0x{addr:08x}: {result['err']}")

    frames = []
    for index in range(requested_frames):
        write32(TAP_BASE + 0x04, frame_len)
        write32(TAP_BASE + 0x00, 0x00000002)
        write32(TAP_BASE + 0x00, 0x00000001)
        time.sleep(settle_sec)

        version = read32(TAP_BASE + 0x40)
        flags = read32(TAP_BASE + 0x44)
        hw_frame_counter = read32(TAP_BASE + 0x48)
        sample_count = read32(TAP_BASE + 0x4C)
        sum_power = read32(TAP_BASE + 0x50) | (read32(TAP_BASE + 0x54) << 32)
        peak_power = read32(TAP_BASE + 0x58)
        peak_index = read32(TAP_BASE + 0x5C)
        debug_accept = read32(TAP_BASE + 0x3C)
        frames.append(
            {
                "index": index,
                "summary_version_hex": f"0x{version:08X}",
                "summary_flags_hex": f"0x{flags:08X}",
                "frame_counter": hw_frame_counter,
                "sample_count": sample_count,
                "sum_power_raw": sum_power,
                "peak_power_raw": peak_power,
                "peak_index": peak_index,
                "debug_accept": debug_accept,
                "rssi_dbfs": rssi_from_sum_power(sum_power, sample_count),
            }
        )

    client.close()

    rssis = [float(item["rssi_dbfs"]) for item in frames if item["rssi_dbfs"] is not None]
    sample_counts = [int(item["sample_count"]) for item in frames]
    payload = {
        "timestamp_sec": time.time(),
        "operation": "summary_v1_register_frame_series",
        "frame_len": frame_len,
        "requested_frames": requested_frames,
        "frames": frames,
        "summary": {
            "all_versions_ok": all(item["summary_version_hex"] == "0x53554D31" for item in frames),
            "all_sample_counts_match": all(value == frame_len for value in sample_counts),
            "rssi_dbfs_min": min(rssis) if rssis else None,
            "rssi_dbfs_median": statistics.median(rssis) if rssis else None,
            "rssi_dbfs_max": max(rssis) if rssis else None,
            "sum_power_min": min(int(item["sum_power_raw"]) for item in frames),
            "sum_power_max": max(int(item["sum_power_raw"]) for item in frames),
        },
    }

    out = Path(args.out) if args.out else LOG_DIR / "summary_v1_register_frame_series.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
