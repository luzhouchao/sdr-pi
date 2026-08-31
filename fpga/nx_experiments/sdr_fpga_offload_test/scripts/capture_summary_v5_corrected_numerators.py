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


def signed96(lo: int, mid: int, hi: int) -> int:
    value = (lo & 0xFFFFFFFF) | ((mid & 0xFFFFFFFF) << 32) | ((hi & 0xFFFFFFFF) << 64)
    return value - (1 << 96) if value & (1 << 95) else value


def unpack_snapshot(words: list[int]) -> tuple[np.ndarray, np.ndarray]:
    iq = [(signed16(word), signed16(word >> 16)) for word in words]
    arr = np.asarray(iq, dtype=np.int64)
    return arr[:, 0], arr[:, 1]


def snapshot_reference(words0: list[int], words1: list[int]) -> dict:
    i0, q0 = unpack_snapshot(words0)
    i1, q1 = unpack_snapshot(words1)
    n = int(min(i0.size, i1.size))
    i0 = i0[:n]
    q0 = q0[:n]
    i1 = i1[:n]
    q1 = q1[:n]
    rx0_power = i0 * i0 + q0 * q0
    rx1_power = i1 * i1 + q1 * q1
    cross_re = i0 * i1 + q0 * q1
    cross_im = q0 * i1 - i0 * q1
    raw = {
        "sample_count": n,
        "i0_sum": int(np.sum(i0, dtype=np.int64)),
        "q0_sum": int(np.sum(q0, dtype=np.int64)),
        "i1_sum": int(np.sum(i1, dtype=np.int64)),
        "q1_sum": int(np.sum(q1, dtype=np.int64)),
        "rx0_power_raw": int(np.sum(rx0_power, dtype=np.int64)),
        "rx1_power_raw": int(np.sum(rx1_power, dtype=np.int64)),
        "cross_re_raw": int(np.sum(cross_re, dtype=np.int64)),
        "cross_im_raw": int(np.sum(cross_im, dtype=np.int64)),
        "rx0_peak_power_raw": int(np.max(rx0_power)) if n else 0,
        "rx0_peak_index": int(np.argmax(rx0_power)) if n else 0,
        "rx1_peak_power_raw": int(np.max(rx1_power)) if n else 0,
        "rx1_peak_index": int(np.argmax(rx1_power)) if n else 0,
    }
    raw["rx0_corr_power_num"] = raw["sample_count"] * raw["rx0_power_raw"] - raw["i0_sum"] * raw["i0_sum"] - raw["q0_sum"] * raw["q0_sum"]
    raw["rx1_corr_power_num"] = raw["sample_count"] * raw["rx1_power_raw"] - raw["i1_sum"] * raw["i1_sum"] - raw["q1_sum"] * raw["q1_sum"]
    raw["corr_cross_re_num"] = raw["sample_count"] * raw["cross_re_raw"] - raw["i0_sum"] * raw["i1_sum"] - raw["q0_sum"] * raw["q1_sum"]
    raw["corr_cross_im_num"] = raw["sample_count"] * raw["cross_im_raw"] - raw["q0_sum"] * raw["i1_sum"] + raw["i0_sum"] * raw["q1_sum"]
    denom = max(1e-12, math.sqrt(max(0, raw["rx0_corr_power_num"]) * max(0, raw["rx1_corr_power_num"])))
    raw["coherence_from_num"] = float(math.hypot(raw["corr_cross_re_num"], raw["corr_cross_im_num"]) / denom)
    raw["phase_from_num_deg"] = float(math.degrees(math.atan2(raw["corr_cross_im_num"], raw["corr_cross_re_num"])))
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture Summary V5 corrected numerator registers and validate against same-frame snapshots.")
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--settle-sec", type=float, default=0.05)
    parser.add_argument("--out-json", default="logs/summary_v5_corrected_numerators_compare.json")
    parser.add_argument("--out-npz", default="samples/summary_v5_dual_snapshot_iq.npz")
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
    sample_count = read32(0x4C)
    snapshot_count = read32(0x60)
    fpga = {
        "summary_version_hex": f"0x{version:08X}",
        "summary_flags_hex": f"0x{flags:08X}",
        "frame_counter": read32(0x48),
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
        "rx0_corr_power_num": signed96(read32(0xBC), read32(0xC0), read32(0xC4)),
        "rx1_corr_power_num": signed96(read32(0xC8), read32(0xCC), read32(0xD0)),
        "corr_cross_re_num": signed96(read32(0xD4), read32(0xD8), read32(0xDC)),
        "corr_cross_im_num": signed96(read32(0xE0), read32(0xE4), read32(0xE8)),
    }
    denom = max(1e-12, math.sqrt(max(0, fpga["rx0_corr_power_num"]) * max(0, fpga["rx1_corr_power_num"])))
    fpga["coherence_from_num"] = float(math.hypot(fpga["corr_cross_re_num"], fpga["corr_cross_im_num"]) / denom)
    fpga["phase_from_num_deg"] = float(math.degrees(math.atan2(fpga["corr_cross_im_num"], fpga["corr_cross_re_num"])))

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

    exact_keys = [
        "sample_count",
        "dual_samples",
        "rx0_power_raw",
        "rx1_power_raw",
        "cross_re_raw",
        "cross_im_raw",
        "rx0_peak_power_raw",
        "rx0_peak_index",
        "rx1_peak_power_raw",
        "rx1_peak_index",
        "i0_sum",
        "q0_sum",
        "i1_sum",
        "q1_sum",
        "rx0_corr_power_num",
        "rx1_corr_power_num",
        "corr_cross_re_num",
        "corr_cross_im_num",
    ]
    checks = {"version_is_sum5": version == 0x53554D35}
    for key in exact_keys:
        ref_key = "sample_count" if key == "dual_samples" else key
        checks[f"{key}_match"] = int(fpga[key]) == int(ref[ref_key])
    checks["phase_from_num_match"] = abs(fpga["phase_from_num_deg"] - ref["phase_from_num_deg"]) <= 1e-6
    checks["coherence_from_num_match"] = abs(fpga["coherence_from_num"] - ref["coherence_from_num"]) <= 1e-9

    payload = {
        "timestamp_sec": time.time(),
        "operation": "summary_v5_corrected_numerators_compare",
        "fpga_summary": fpga,
        "snapshot_reference": ref,
        "checks": checks,
        "passed": all(checks.values()),
        "npz": str(out_npz),
    }
    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
