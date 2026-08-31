#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
TAP_BASE = 0x43C00000


def parse_devmem(text: str) -> int:
    text = text.strip()
    if not text:
        raise RuntimeError("empty devmem output")
    return int(text.split()[0], 0)


def unsigned48(lo: int, hi: int) -> int:
    return ((hi & 0xFFFF) << 32) | (lo & 0xFFFFFFFF)


def signed48(lo: int, hi: int) -> int:
    value = unsigned48(lo, hi)
    return value - (1 << 48) if value & (1 << 47) else value


def signed96_from_64_signext(lo: int, mid: int, hi: int) -> int:
    value64 = (lo & 0xFFFFFFFF) | ((mid & 0xFFFFFFFF) << 32)
    return value64 - (1 << 64) if value64 & (1 << 63) else value64


def calc_derived(summary: dict) -> dict:
    n = int(summary["sample_count"])
    rx0_corr = n * int(summary["rx0_power_raw"]) - int(summary["i0_sum"]) ** 2 - int(summary["q0_sum"]) ** 2
    rx1_corr = n * int(summary["rx1_power_raw"]) - int(summary["i1_sum"]) ** 2 - int(summary["q1_sum"]) ** 2
    cross_re = n * int(summary["cross_re_raw"]) - int(summary["i0_sum"]) * int(summary["i1_sum"]) - int(summary["q0_sum"]) * int(summary["q1_sum"])
    cross_im = n * int(summary["cross_im_raw"]) - int(summary["q0_sum"]) * int(summary["i1_sum"]) + int(summary["i0_sum"]) * int(summary["q1_sum"])
    denom = math.sqrt(max(0, rx0_corr) * max(0, rx1_corr))
    coherence = float(math.hypot(cross_re, cross_im) / denom) if denom > 0 else 0.0
    phase_deg = float(math.degrees(math.atan2(cross_im, cross_re)))
    return {
        "rx0_corr_power_num_calc": rx0_corr,
        "rx1_corr_power_num_calc": rx1_corr,
        "corr_cross_re_num_calc": cross_re,
        "corr_cross_im_num_calc": cross_im,
        "coherence_from_num": coherence,
        "phase_from_num_deg": phase_deg,
    }


def parse_frame_lens(text: str) -> list[int]:
    values: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part, 0)
        if value < 1 or value > 256:
            raise ValueError("V5 production validation keeps frame_len in 1..256 because corrected sums are 24-bit in HDL")
        values.append(value)
    return values or [64]


def summarize_elapsed(values: list[float]) -> dict:
    return {
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "max": max(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read production Summary V5 registers without snapshot dependency.")
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--frame-lens", default="", help="Comma list for repeated validation. Default uses --frame-len.")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--settle-sec", type=float, default=0.05)
    parser.add_argument("--skip-sd-hashes", action="store_true")
    parser.add_argument("--out-json", default="logs/summary_v5_production.json")
    args = parser.parse_args()

    frame_lens = parse_frame_lens(args.frame_lens) if args.frame_lens else parse_frame_lens(str(args.frame_len))
    repeat = max(1, int(args.repeat))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_t0 = time.perf_counter()
    client.connect(args.host, username=args.user, password=args.password, timeout=10, banner_timeout=10, auth_timeout=10)
    connect_elapsed = time.perf_counter() - connect_t0

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

    sd_hashes = ""
    if not args.skip_sd_hashes:
        sd_hashes = run("sha256sum /sd/BOOT.bin /sd/devicetree.dtb /sd/uEnv.txt /sd/uImage /sd/uramdisk.image.gz")

    def capture_once(frame_len: int, iteration: int) -> dict:
        total_t0 = time.perf_counter()
        trigger_t0 = time.perf_counter()
        write32(0x04, frame_len)
        write32(0x00, 0x00000002)
        write32(0x00, 0x00000001)
        trigger_elapsed = time.perf_counter() - trigger_t0

        settle_t0 = time.perf_counter()
        time.sleep(max(0.0, float(args.settle_sec)))
        settle_elapsed = time.perf_counter() - settle_t0

        read_t0 = time.perf_counter()
        read_count = 0

        def r(offset: int) -> int:
            nonlocal read_count
            read_count += 1
            return read32(offset)

        version = r(0x40)
        summary = {
            "summary_version_hex": f"0x{version:08X}",
            "summary_flags_hex": f"0x{r(0x44):08X}",
            "frame_counter": r(0x48),
            "sample_count": r(0x4C),
            "summary_sum_power_raw": unsigned48(r(0x50), r(0x54)),
            "rx0_peak_power_raw": r(0x58),
            "rx0_peak_index": r(0x5C),
            "snapshot_count": r(0x60),
            "dual_samples": r(0x70),
            "rx0_power_raw": unsigned48(r(0x74), r(0x78)),
            "rx1_power_raw": unsigned48(r(0x7C), r(0x80)),
            "cross_re_raw": signed48(r(0x84), r(0x88)),
            "cross_im_raw": signed48(r(0x8C), r(0x90)),
            "rx1_peak_power_raw": r(0x94),
            "rx1_peak_index": r(0x98),
            "i0_sum": signed48(r(0x9C), r(0xA0)),
            "q0_sum": signed48(r(0xA4), r(0xA8)),
            "i1_sum": signed48(r(0xAC), r(0xB0)),
            "q1_sum": signed48(r(0xB4), r(0xB8)),
            "rx0_corr_power_num": signed96_from_64_signext(r(0xBC), r(0xC0), r(0xC4)),
            "rx1_corr_power_num": signed96_from_64_signext(r(0xC8), r(0xCC), r(0xD0)),
            "corr_cross_re_num": signed96_from_64_signext(r(0xD4), r(0xD8), r(0xDC)),
            "corr_cross_im_num": signed96_from_64_signext(r(0xE0), r(0xE4), r(0xE8)),
        }
        read_elapsed = time.perf_counter() - read_t0

        post_t0 = time.perf_counter()
        derived = calc_derived(summary)
        checks = {
            "version_is_sum5": version == 0x53554D35,
            "snapshot_disabled": int(summary["snapshot_count"]) == 0,
            "sample_count_matches_frame_len": int(summary["sample_count"]) == frame_len,
            "dual_samples_match": int(summary["dual_samples"]) == int(summary["sample_count"]),
            "summary_sum_matches_rx0_power": int(summary["summary_sum_power_raw"]) == int(summary["rx0_power_raw"]),
            "rx0_corr_power_num_match": int(summary["rx0_corr_power_num"]) == int(derived["rx0_corr_power_num_calc"]),
            "rx1_corr_power_num_match": int(summary["rx1_corr_power_num"]) == int(derived["rx1_corr_power_num_calc"]),
            "corr_cross_re_num_match": int(summary["corr_cross_re_num"]) == int(derived["corr_cross_re_num_calc"]),
            "corr_cross_im_num_match": int(summary["corr_cross_im_num"]) == int(derived["corr_cross_im_num_calc"]),
        }
        post_elapsed = time.perf_counter() - post_t0
        summary_bytes = read_count * 4
        raw_iq_bytes_equivalent = int(summary["sample_count"]) * 2 * 2 * 2
        return {
            "frame_len_requested": frame_len,
            "iteration": iteration,
            "fpga_summary": summary,
            "derived_on_nx": derived,
            "checks": checks,
            "passed": all(checks.values()),
            "timing_sec": {
                "trigger_write": trigger_elapsed,
                "settle_sleep": settle_elapsed,
                "register_read": read_elapsed,
                "nx_postprocess": post_elapsed,
                "total_capture": time.perf_counter() - total_t0,
            },
            "io_shape": {
                "register_reads": read_count,
                "summary_bytes_read": summary_bytes,
                "raw_iq_bytes_equivalent": raw_iq_bytes_equivalent,
                "raw_iq_bytes_avoided_vs_summary": raw_iq_bytes_equivalent - summary_bytes,
            },
        }

    captures = []
    for frame_len in frame_lens:
        for iteration in range(repeat):
            captures.append(capture_once(frame_len, iteration))
    client.close()

    elapsed_by_key: dict[str, dict] = {}
    for key in ["trigger_write", "settle_sleep", "register_read", "nx_postprocess", "total_capture"]:
        elapsed_by_key[key] = summarize_elapsed([float(item["timing_sec"][key]) for item in captures])

    payload = {
        "timestamp_sec": time.time(),
        "operation": "summary_v5_production_no_snapshot",
        "connect_elapsed_sec": connect_elapsed,
        "sd_hashes": sd_hashes,
        "frame_lens": frame_lens,
        "repeat": repeat,
        "captures": captures,
        "pass_count": sum(1 for item in captures if item["passed"]),
        "capture_count": len(captures),
        "passed": all(item["passed"] for item in captures),
        "timing_summary_sec": elapsed_by_key,
        "notes": [
            "V5 validates production summary consistency, not raw same-frame equivalence because snapshot is disabled.",
            "SSH-per-devmem timing includes SSH command overhead; use a local SDR helper for fine latency profiling.",
            "Default frame length sweep is kept <=256 because V5 corrected-sum post-processing uses 24-bit narrowed I/Q sums.",
        ],
    }
    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
