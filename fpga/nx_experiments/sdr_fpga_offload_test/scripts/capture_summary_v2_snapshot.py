#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import paramiko


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
SAMPLE_DIR = ROOT / "samples"
TAP_BASE = 0x43C00000


def parse_devmem(text: str) -> int:
    text = text.strip()
    if not text:
        raise RuntimeError("empty devmem output")
    return int(text.split()[0], 0)


def signed16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def power_reference_from_snapshot(words: list[int]) -> dict:
    raw = []
    for word in words:
        i_value = signed16(word)
        q_value = signed16(word >> 16)
        raw.extend([i_value, q_value])
    raw_i16 = np.asarray(raw, dtype=np.int16)
    lanes = raw_i16.reshape(-1, 2).astype(np.int64)
    power = lanes[:, 0] * lanes[:, 0] + lanes[:, 1] * lanes[:, 1]
    sample_count = int(power.size)
    sum_power = int(np.sum(power, dtype=np.int64))
    peak_index = int(np.argmax(power)) if sample_count else 0
    peak_power = int(power[peak_index]) if sample_count else 0
    mean_power_norm = float(sum_power) / float(max(1, sample_count)) / float(32768.0 * 32768.0)
    return {
        "raw_i16": raw_i16,
        "sample_count": sample_count,
        "sum_power_raw": sum_power,
        "peak_power_raw": peak_power,
        "peak_index": peak_index,
        "rssi_dbfs": float(10.0 * math.log10(mean_power_norm + 1e-12)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture Summary V2 FPGA frame and raw IQ snapshot from the same latched frame."
    )
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--settle-sec", type=float, default=0.05)
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--out-json", default="logs/summary_v2_snapshot_compare.json")
    parser.add_argument("--out-npz", default="samples/summary_v2_snapshot_raw_i16.npz")
    args = parser.parse_args()

    frame_len = max(1, min(64, int(args.frame_len)))
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

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

    write32(TAP_BASE + 0x04, frame_len)
    write32(TAP_BASE + 0x00, 0x00000002)
    write32(TAP_BASE + 0x00, 0x00000001)
    time.sleep(max(0.0, float(args.settle_sec)))

    version = read32(TAP_BASE + 0x40)
    flags = read32(TAP_BASE + 0x44)
    frame_counter = read32(TAP_BASE + 0x48)
    sample_count = read32(TAP_BASE + 0x4C)
    sum_power = read32(TAP_BASE + 0x50) | (read32(TAP_BASE + 0x54) << 32)
    peak_power = read32(TAP_BASE + 0x58)
    peak_index = read32(TAP_BASE + 0x5C)
    snapshot_count = read32(TAP_BASE + 0x60)
    words = []
    for index in range(min(64, snapshot_count)):
        write32(TAP_BASE + 0x64, index)
        words.append(read32(TAP_BASE + 0x68))
    client.close()

    ref = power_reference_from_snapshot(words)
    raw_i16 = ref.pop("raw_i16")
    out_npz = ROOT / args.out_npz
    out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_npz, raw_i16=raw_i16, snapshot_words=np.asarray(words, dtype=np.uint32))

    fpga = {
        "summary_version_hex": f"0x{version:08X}",
        "summary_flags_hex": f"0x{flags:08X}",
        "frame_counter": frame_counter,
        "sample_count": sample_count,
        "sum_power_raw": sum_power,
        "peak_power_raw": peak_power,
        "peak_index": peak_index,
        "snapshot_count": snapshot_count,
    }
    checks = {
        "version_is_sum2": version == 0x53554D32,
        "sample_count_match": sample_count == ref["sample_count"],
        "sum_power_match": sum_power == ref["sum_power_raw"],
        "peak_power_match": peak_power == ref["peak_power_raw"],
        "peak_index_match": peak_index == ref["peak_index"],
    }
    payload = {
        "timestamp_sec": time.time(),
        "operation": "summary_v2_same_frame_snapshot_compare",
        "fpga_summary": fpga,
        "snapshot_reference": ref,
        "checks": checks,
        "passed": all(checks.values()),
        "npz": str(out_npz),
        "snapshot_words_hex": [f"0x{word:08X}" for word in words],
    }
    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
