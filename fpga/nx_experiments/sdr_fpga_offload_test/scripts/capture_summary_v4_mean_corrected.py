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
TAP_BASE = 0x43C00000


def parse_devmem(text: str) -> int:
    text = text.strip()
    if not text:
        raise RuntimeError("empty devmem output")
    return int(text.split()[0], 0)


def signed16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def unsigned48(lo: int, hi: int) -> int:
    return ((hi & 0xFFFF) << 32) | (lo & 0xFFFFFFFF)


def signed48(lo: int, hi: int) -> int:
    value = unsigned48(lo, hi)
    return value - (1 << 48) if value & (1 << 47) else value


def unpack_snapshot(words: list[int]) -> tuple[np.ndarray, np.ndarray]:
    iq = []
    for word in words:
        iq.append((signed16(word), signed16(word >> 16)))
    arr = np.asarray(iq, dtype=np.int64)
    return arr[:, 0], arr[:, 1]


def mean_corrected_metrics(
    n: int,
    i0_sum: int,
    q0_sum: int,
    i1_sum: int,
    q1_sum: int,
    rx0_power: int,
    rx1_power: int,
    cross_re: int,
    cross_im: int,
) -> dict:
    if n <= 0:
        raise RuntimeError("sample count must be positive")
    s0 = complex(float(i0_sum), float(q0_sum))
    s1 = complex(float(i1_sum), float(q1_sum))
    raw_cross = complex(float(cross_re), float(cross_im))
    rx0_corr = float(rx0_power) - ((float(i0_sum) ** 2 + float(q0_sum) ** 2) / float(n))
    rx1_corr = float(rx1_power) - ((float(i1_sum) ** 2 + float(q1_sum) ** 2) / float(n))
    cross_corr = raw_cross - (np.conjugate(s1) * s0 / float(n))
    coherence = abs(cross_corr) / max(1e-12, math.sqrt(max(0.0, rx0_corr) * max(0.0, rx1_corr)))
    scale = float(n) * float(32768.0 * 32768.0)
    return {
        "rx0_power_mean_corrected": rx0_corr,
        "rx1_power_mean_corrected": rx1_corr,
        "cross_re_mean_corrected": float(cross_corr.real),
        "cross_im_mean_corrected": float(cross_corr.imag),
        "coherence_mean_corrected": float(coherence),
        "phase_mean_corrected_deg": float(math.degrees(math.atan2(cross_corr.imag, cross_corr.real))),
        "rx0_rssi_mean_corrected_dbfs": float(10.0 * math.log10(max(rx0_corr / scale, 1e-12))),
        "rx1_rssi_mean_corrected_dbfs": float(10.0 * math.log10(max(rx1_corr / scale, 1e-12))),
    }


def snapshot_reference(words0: list[int], words1: list[int]) -> dict:
    i0, q0 = unpack_snapshot(words0)
    i1, q1 = unpack_snapshot(words1)
    n = int(min(i0.size, i1.size))
    i0 = i0[:n]
    q0 = q0[:n]
    i1 = i1[:n]
    q1 = q1[:n]
    rx0_power_vec = i0 * i0 + q0 * q0
    rx1_power_vec = i1 * i1 + q1 * q1
    cross_re_vec = i0 * i1 + q0 * q1
    cross_im_vec = q0 * i1 - i0 * q1
    raw = {
        "sample_count": n,
        "i0_sum": int(np.sum(i0, dtype=np.int64)),
        "q0_sum": int(np.sum(q0, dtype=np.int64)),
        "i1_sum": int(np.sum(i1, dtype=np.int64)),
        "q1_sum": int(np.sum(q1, dtype=np.int64)),
        "rx0_power_raw": int(np.sum(rx0_power_vec, dtype=np.int64)),
        "rx1_power_raw": int(np.sum(rx1_power_vec, dtype=np.int64)),
        "cross_re_raw": int(np.sum(cross_re_vec, dtype=np.int64)),
        "cross_im_raw": int(np.sum(cross_im_vec, dtype=np.int64)),
        "rx0_peak_power_raw": int(np.max(rx0_power_vec)) if n else 0,
        "rx0_peak_index": int(np.argmax(rx0_power_vec)) if n else 0,
        "rx1_peak_power_raw": int(np.max(rx1_power_vec)) if n else 0,
        "rx1_peak_index": int(np.argmax(rx1_power_vec)) if n else 0,
    }
    return raw | mean_corrected_metrics(
        raw["sample_count"],
        raw["i0_sum"],
        raw["q0_sum"],
        raw["i1_sum"],
        raw["q1_sum"],
        raw["rx0_power_raw"],
        raw["rx1_power_raw"],
        raw["cross_re_raw"],
        raw["cross_im_raw"],
    )


def close_float(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(float(a) - float(b)) <= tol


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture Summary V4 and validate mean-corrected dual-RX AoA metrics.")
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--settle-sec", type=float, default=0.05)
    parser.add_argument("--out-json", default="logs/summary_v4_mean_corrected_compare.json")
    parser.add_argument("--out-npz", default="samples/summary_v4_dual_snapshot_iq.npz")
    args = parser.parse_args()

    frame_len = max(1, min(64, int(args.frame_len)))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=args.password, timeout=10, banner_timeout=10, auth_timeout=10)

    def run(cmd: str) -> str:
        stdin, stdout, stderr = client.exec_command(cmd)
        try:
            rc = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            if rc != 0:
                raise RuntimeError(f"{cmd!r} failed: {err or out}")
            return out
        finally:
            stdin.close()
            stdout.close()
            stderr.close()

    def read32(offset: int) -> int:
        return parse_devmem(run(f"devmem 0x{TAP_BASE + offset:08x} 32"))

    def write32(offset: int, value: int) -> None:
        run(f"devmem 0x{TAP_BASE + offset:08x} 32 0x{value & 0xFFFFFFFF:08x}")

    write32(0x04, frame_len)
    write32(0x00, 0x00000002)
    write32(0x00, 0x00000001)
    time.sleep(max(0.0, float(args.settle_sec)))

    version = read32(0x40)
    flags = read32(0x44)
    frame_counter = read32(0x48)
    sample_count = read32(0x4C)
    snapshot_count = read32(0x60)
    fpga = {
        "summary_version_hex": f"0x{version:08X}",
        "summary_flags_hex": f"0x{flags:08X}",
        "frame_counter": frame_counter,
        "sample_count": sample_count,
        "snapshot_count": snapshot_count,
        "dual_samples": read32(0x70),
        "rx0_power_raw": unsigned48(read32(0x74), read32(0x78)),
        "rx1_power_raw": unsigned48(read32(0x7C), read32(0x80)),
        "cross_re_raw": signed48(read32(0x84), read32(0x88)),
        "cross_im_raw": signed48(read32(0x8C), read32(0x90)),
        "rx0_peak_power_raw": read32(0x58),
        "rx0_peak_index": read32(0x5C),
        "rx1_peak_power_raw": read32(0x94),
        "rx1_peak_index": read32(0x98),
        "i0_sum": signed48(read32(0x9C), read32(0xA0)),
        "q0_sum": signed48(read32(0xA4), read32(0xA8)),
        "i1_sum": signed48(read32(0xAC), read32(0xB0)),
        "q1_sum": signed48(read32(0xB4), read32(0xB8)),
    }
    fpga |= mean_corrected_metrics(
        int(fpga["sample_count"]),
        int(fpga["i0_sum"]),
        int(fpga["q0_sum"]),
        int(fpga["i1_sum"]),
        int(fpga["q1_sum"]),
        int(fpga["rx0_power_raw"]),
        int(fpga["rx1_power_raw"]),
        int(fpga["cross_re_raw"]),
        int(fpga["cross_im_raw"]),
    )

    words0: list[int] = []
    words1: list[int] = []
    for index in range(min(64, int(snapshot_count))):
        write32(0x64, index)
        words0.append(read32(0x68))
        words1.append(read32(0x6C))
    client.close()

    ref = snapshot_reference(words0, words1)
    i0, q0 = unpack_snapshot(words0)
    i1, q1 = unpack_snapshot(words1)
    out_npz = ROOT / args.out_npz
    out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_npz,
        rx0_iq_i16=np.column_stack([i0, q0]).astype(np.int16),
        rx1_iq_i16=np.column_stack([i1, q1]).astype(np.int16),
        snapshot0_words=np.asarray(words0, dtype=np.uint32),
        snapshot1_words=np.asarray(words1, dtype=np.uint32),
    )

    checks = {
        "version_is_sum4": version == 0x53554D34,
        "sample_count_match": fpga["sample_count"] == ref["sample_count"],
        "dual_samples_match": fpga["dual_samples"] == ref["sample_count"],
        "rx0_power_match": fpga["rx0_power_raw"] == ref["rx0_power_raw"],
        "rx1_power_match": fpga["rx1_power_raw"] == ref["rx1_power_raw"],
        "cross_re_match": fpga["cross_re_raw"] == ref["cross_re_raw"],
        "cross_im_match": fpga["cross_im_raw"] == ref["cross_im_raw"],
        "rx0_peak_power_match": fpga["rx0_peak_power_raw"] == ref["rx0_peak_power_raw"],
        "rx0_peak_index_match": fpga["rx0_peak_index"] == ref["rx0_peak_index"],
        "rx1_peak_power_match": fpga["rx1_peak_power_raw"] == ref["rx1_peak_power_raw"],
        "rx1_peak_index_match": fpga["rx1_peak_index"] == ref["rx1_peak_index"],
        "i0_sum_match": fpga["i0_sum"] == ref["i0_sum"],
        "q0_sum_match": fpga["q0_sum"] == ref["q0_sum"],
        "i1_sum_match": fpga["i1_sum"] == ref["i1_sum"],
        "q1_sum_match": fpga["q1_sum"] == ref["q1_sum"],
        "mean_corrected_phase_match": close_float(fpga["phase_mean_corrected_deg"], ref["phase_mean_corrected_deg"]),
        "mean_corrected_coherence_match": close_float(fpga["coherence_mean_corrected"], ref["coherence_mean_corrected"]),
    }
    payload = {
        "timestamp_sec": time.time(),
        "operation": "summary_v4_mean_corrected_dual_rx_compare",
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
