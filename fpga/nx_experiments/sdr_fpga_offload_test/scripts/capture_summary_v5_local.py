#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import mmap
import os
import statistics
import struct
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path


TAP_BASE = 0x43C00000
PAGE_SIZE = mmap.PAGESIZE


def unsigned48(lo: int, hi: int) -> int:
    return ((hi & 0xFFFF) << 32) | (lo & 0xFFFFFFFF)


def signed48(lo: int, hi: int) -> int:
    value = unsigned48(lo, hi)
    return value - (1 << 48) if value & (1 << 47) else value


def signed96_from_64_signext(lo: int, mid: int, hi: int) -> int:
    value64 = (lo & 0xFFFFFFFF) | ((mid & 0xFFFFFFFF) << 32)
    return value64 - (1 << 64) if value64 & (1 << 63) else value64


def parse_frame_lens(text: str) -> list[int]:
    values: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part, 0)
        if value < 1 or value > 256:
            raise ValueError("V5 local validation keeps frame_len in 1..256 because corrected sums are 24-bit in HDL")
        values.append(value)
    return values or [64]


def summarize_elapsed(values: list[float]) -> dict:
    return {
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "max": max(values),
    }


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


class RegAccess(ABC):
    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def read32(self, offset: int) -> int:
        raise NotImplementedError

    @abstractmethod
    def write32(self, offset: int, value: int) -> None:
        raise NotImplementedError


class MmapRegs(RegAccess):
    def __init__(self, base: int, span: int = 0x1000) -> None:
        page_base = base & ~(PAGE_SIZE - 1)
        self._page_delta = base - page_base
        self._fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self._mem = mmap.mmap(self._fd, span + self._page_delta, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=page_base)

    def close(self) -> None:
        self._mem.close()
        os.close(self._fd)

    def read32(self, offset: int) -> int:
        pos = self._page_delta + offset
        return struct.unpack_from("<I", self._mem, pos)[0]

    def write32(self, offset: int, value: int) -> None:
        pos = self._page_delta + offset
        struct.pack_into("<I", self._mem, pos, value & 0xFFFFFFFF)


class DevmemRegs(RegAccess):
    def __init__(self, base: int) -> None:
        self._base = base

    def close(self) -> None:
        return

    def read32(self, offset: int) -> int:
        address = self._base + offset
        result = subprocess.run(["devmem", f"0x{address:08x}", "32"], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        text = result.stdout.strip()
        if not text:
            raise RuntimeError(f"empty devmem output for 0x{address:08x}")
        return int(text.split()[0], 0)

    def write32(self, offset: int, value: int) -> None:
        address = self._base + offset
        subprocess.run(["devmem", f"0x{address:08x}", "32", f"0x{value & 0xFFFFFFFF:08x}"], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def read_sd_hashes() -> str:
    cmd = ["sha256sum", "/sd/BOOT.bin", "/sd/devicetree.dtb", "/sd/uEnv.txt", "/sd/uImage", "/sd/uramdisk.image.gz"]
    result = subprocess.run(cmd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip()


def wait_for_frame(regs: RegAccess, initial_frame: int, timeout_sec: float, settle_sec: float) -> dict:
    wait_t0 = time.perf_counter()
    polls = 0
    while True:
        polls += 1
        current_frame = regs.read32(0x48)
        sample_count = regs.read32(0x4C)
        if current_frame != initial_frame and sample_count > 0:
            return {
                "mode": "poll",
                "polls": polls,
                "elapsed": time.perf_counter() - wait_t0,
            }
        if time.perf_counter() - wait_t0 >= timeout_sec:
            break
        time.sleep(0.001)
    sleep_t0 = time.perf_counter()
    time.sleep(max(0.0, settle_sec))
    return {
        "mode": "timeout_then_sleep",
        "polls": polls,
        "elapsed": time.perf_counter() - wait_t0,
        "fallback_sleep": time.perf_counter() - sleep_t0,
    }


def capture_once(regs: RegAccess, frame_len: int, iteration: int, settle_sec: float, poll_timeout_sec: float) -> dict:
    total_t0 = time.perf_counter()
    initial_frame = regs.read32(0x48)
    trigger_t0 = time.perf_counter()
    regs.write32(0x04, frame_len)
    regs.write32(0x00, 0x00000002)
    regs.write32(0x00, 0x00000001)
    trigger_elapsed = time.perf_counter() - trigger_t0

    wait_info = wait_for_frame(regs, initial_frame, max(0.0, poll_timeout_sec), settle_sec)

    read_t0 = time.perf_counter()
    read_count = 0

    def r(offset: int) -> int:
        nonlocal read_count
        read_count += 1
        return regs.read32(offset)

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
        "derived_on_local_cpu": derived,
        "checks": checks,
        "passed": all(checks.values()),
        "timing_sec": {
            "trigger_write": trigger_elapsed,
            "wait_for_frame": wait_info["elapsed"],
            "register_read_mmap": read_elapsed,
            "local_postprocess": post_elapsed,
            "total_capture": time.perf_counter() - total_t0,
        },
        "wait_info": wait_info,
        "io_shape": {
            "register_reads": read_count,
            "summary_bytes_read": summary_bytes,
            "raw_iq_bytes_equivalent": raw_iq_bytes_equivalent,
            "raw_iq_bytes_avoided_vs_summary": raw_iq_bytes_equivalent - summary_bytes,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Summary V5 validation locally on the SDR using /dev/mem mmap.")
    parser.add_argument("--base", default="0x43c00000")
    parser.add_argument("--mode", choices=["mmap", "devmem"], default="mmap")
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--frame-lens", default="64,128,256")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--settle-sec", type=float, default=0.05)
    parser.add_argument("--poll-timeout-sec", type=float, default=0.05)
    parser.add_argument("--skip-sd-hashes", action="store_true")
    parser.add_argument("--out-json", default="summary_v5_local_sweep.json")
    args = parser.parse_args()

    base = int(str(args.base), 0)
    frame_lens = parse_frame_lens(args.frame_lens) if args.frame_lens else parse_frame_lens(str(args.frame_len))
    repeat = max(1, int(args.repeat))
    sd_hashes = "" if args.skip_sd_hashes else read_sd_hashes()

    regs: RegAccess = MmapRegs(base) if args.mode == "mmap" else DevmemRegs(base)
    try:
        captures = []
        for frame_len in frame_lens:
            for iteration in range(repeat):
                captures.append(capture_once(regs, frame_len, iteration, max(0.0, float(args.settle_sec)), max(0.0, float(args.poll_timeout_sec))))
    finally:
        regs.close()

    elapsed_by_key: dict[str, dict] = {}
    for key in ["trigger_write", "wait_for_frame", "register_read_mmap", "local_postprocess", "total_capture"]:
        elapsed_by_key[key] = summarize_elapsed([float(item["timing_sec"][key]) for item in captures])

    payload = {
        "timestamp_sec": time.time(),
        "operation": "summary_v5_local_mmap_no_snapshot",
        "mode": args.mode,
        "base_hex": f"0x{base:08X}",
        "sd_hashes": sd_hashes,
        "frame_lens": frame_lens,
        "repeat": repeat,
        "captures": captures,
        "pass_count": sum(1 for item in captures if item["passed"]),
        "capture_count": len(captures),
        "passed": all(item["passed"] for item in captures),
        "timing_summary_sec": elapsed_by_key,
        "notes": [
            "Run this script as root on the SDR after booting V5.",
            "This uses /dev/mem mmap to avoid SSH-per-devmem timing overhead.",
            "V5 validates production summary consistency, not raw same-frame equivalence because snapshot is disabled.",
            "Frame length sweep is kept <=256 because V5 corrected-sum post-processing uses 24-bit narrowed I/Q sums.",
        ],
    }

    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True) if out_path.parent != Path(".") else None
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
