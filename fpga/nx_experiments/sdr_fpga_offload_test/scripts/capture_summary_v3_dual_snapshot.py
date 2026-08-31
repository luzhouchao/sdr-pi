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


def signed48_from_parts(lo: int, hi: int) -> int:
    value = ((hi & 0xFFFF) << 32) | (lo & 0xFFFFFFFF)
    return value - (1 << 48) if value & (1 << 47) else value


def unsigned48_from_parts(lo: int, hi: int) -> int:
    return ((hi & 0xFFFF) << 32) | (lo & 0xFFFFFFFF)


def unpack_snapshot(words: list[int]) -> np.ndarray:
    raw = []
    for word in words:
        raw.extend([signed16(word), signed16(word >> 16)])
    return np.asarray(raw, dtype=np.int16).reshape(-1, 2).astype(np.int64)


def dual_reference(words0: list[int], words1: list[int]) -> dict:
    rx0 = unpack_snapshot(words0)
    rx1 = unpack_snapshot(words1)
    n = int(min(rx0.shape[0], rx1.shape[0]))
    rx0 = rx0[:n]
    rx1 = rx1[:n]
    i0 = rx0[:, 0]
    q0 = rx0[:, 1]
    i1 = rx1[:, 0]
    q1 = rx1[:, 1]

    power0 = i0 * i0 + q0 * q0
    power1 = i1 * i1 + q1 * q1
    cross_re = i0 * i1 + q0 * q1
    cross_im = q0 * i1 - i0 * q1
    sum0 = int(np.sum(power0, dtype=np.int64))
    sum1 = int(np.sum(power1, dtype=np.int64))
    cross_re_sum = int(np.sum(cross_re, dtype=np.int64))
    cross_im_sum = int(np.sum(cross_im, dtype=np.int64))
    peak0_index = int(np.argmax(power0)) if n else 0
    peak1_index = int(np.argmax(power1)) if n else 0
    peak0_power = int(power0[peak0_index]) if n else 0
    peak1_power = int(power1[peak1_index]) if n else 0
    mean0 = float(sum0) / float(max(1, n)) / float(32768.0 * 32768.0)
    mean1 = float(sum1) / float(max(1, n)) / float(32768.0 * 32768.0)
    cross_mag = math.hypot(float(cross_re_sum), float(cross_im_sum))
    coherence = cross_mag / max(1e-12, math.sqrt(float(max(1, sum0)) * float(max(1, sum1))))
    phase_deg = math.degrees(math.atan2(float(cross_im_sum), float(cross_re_sum)))
    return {
        "sample_count": n,
        "rx0_power_raw": sum0,
        "rx1_power_raw": sum1,
        "cross_re_raw": cross_re_sum,
        "cross_im_raw": cross_im_sum,
        "rx0_peak_power_raw": peak0_power,
        "rx0_peak_index": peak0_index,
        "rx1_peak_power_raw": peak1_power,
        "rx1_peak_index": peak1_index,
        "rx0_rssi_dbfs": float(10.0 * math.log10(mean0 + 1e-12)),
        "rx1_rssi_dbfs": float(10.0 * math.log10(mean1 + 1e-12)),
        "coherence": float(coherence),
        "cross_phase_deg": float(phase_deg),
        "rx0_iq_i16": rx0.astype(np.int16),
        "rx1_iq_i16": rx1.astype(np.int16),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture Summary V3 dual-RX FPGA frame and compare same-frame snapshot math.")
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--settle-sec", type=float, default=0.05)
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--out-json", default="logs/summary_v3_dual_snapshot_compare.json")
    parser.add_argument("--out-npz", default="samples/summary_v3_dual_snapshot_iq.npz")
    args = parser.parse_args()

    frame_len = max(1, min(64, int(args.frame_len)))
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=args.password, timeout=10, banner_timeout=10, auth_timeout=10)

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
    rx0_sum = unsigned48_from_parts(read32(TAP_BASE + 0x50), read32(TAP_BASE + 0x54))
    rx0_peak_power = read32(TAP_BASE + 0x58)
    rx0_peak_index = read32(TAP_BASE + 0x5C)
    snapshot_count = read32(TAP_BASE + 0x60)
    dual_samples = read32(TAP_BASE + 0x70)
    rx0_power = unsigned48_from_parts(read32(TAP_BASE + 0x74), read32(TAP_BASE + 0x78))
    rx1_power = unsigned48_from_parts(read32(TAP_BASE + 0x7C), read32(TAP_BASE + 0x80))
    cross_re = signed48_from_parts(read32(TAP_BASE + 0x84), read32(TAP_BASE + 0x88))
    cross_im = signed48_from_parts(read32(TAP_BASE + 0x8C), read32(TAP_BASE + 0x90))
    rx1_peak_power = read32(TAP_BASE + 0x94)
    rx1_peak_index = read32(TAP_BASE + 0x98)

    words0 = []
    words1 = []
    for index in range(min(64, snapshot_count)):
        write32(TAP_BASE + 0x64, index)
        words0.append(read32(TAP_BASE + 0x68))
        words1.append(read32(TAP_BASE + 0x6C))
    client.close()

    ref = dual_reference(words0, words1)
    rx0_iq = ref.pop("rx0_iq_i16")
    rx1_iq = ref.pop("rx1_iq_i16")
    out_npz = ROOT / args.out_npz
    out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_npz,
        rx0_iq_i16=rx0_iq,
        rx1_iq_i16=rx1_iq,
        snapshot0_words=np.asarray(words0, dtype=np.uint32),
        snapshot1_words=np.asarray(words1, dtype=np.uint32),
    )

    fpga = {
        "summary_version_hex": f"0x{version:08X}",
        "summary_flags_hex": f"0x{flags:08X}",
        "frame_counter": frame_counter,
        "sample_count": sample_count,
        "snapshot_count": snapshot_count,
        "dual_samples": dual_samples,
        "rx0_power_raw": rx0_power,
        "rx0_summary_sum_raw": rx0_sum,
        "rx0_peak_power_raw": rx0_peak_power,
        "rx0_peak_index": rx0_peak_index,
        "rx1_power_raw": rx1_power,
        "rx1_peak_power_raw": rx1_peak_power,
        "rx1_peak_index": rx1_peak_index,
        "cross_re_raw": cross_re,
        "cross_im_raw": cross_im,
    }
    checks = {
        "version_is_sum3": version == 0x53554D33,
        "sample_count_match": sample_count == ref["sample_count"],
        "dual_samples_match": dual_samples == ref["sample_count"],
        "rx0_power_match": rx0_power == ref["rx0_power_raw"],
        "rx0_v2_sum_match": rx0_sum == ref["rx0_power_raw"],
        "rx1_power_match": rx1_power == ref["rx1_power_raw"],
        "cross_re_match": cross_re == ref["cross_re_raw"],
        "cross_im_match": cross_im == ref["cross_im_raw"],
        "rx0_peak_power_match": rx0_peak_power == ref["rx0_peak_power_raw"],
        "rx0_peak_index_match": rx0_peak_index == ref["rx0_peak_index"],
        "rx1_peak_power_match": rx1_peak_power == ref["rx1_peak_power_raw"],
        "rx1_peak_index_match": rx1_peak_index == ref["rx1_peak_index"],
    }
    payload = {
        "timestamp_sec": time.time(),
        "operation": "summary_v3_dual_rx_same_frame_snapshot_compare",
        "fpga_summary": fpga,
        "snapshot_reference": ref,
        "checks": checks,
        "passed": all(checks.values()),
        "npz": str(out_npz),
        "snapshot0_words_hex": [f"0x{word:08X}" for word in words0],
        "snapshot1_words_hex": [f"0x{word:08X}" for word in words1],
    }
    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
