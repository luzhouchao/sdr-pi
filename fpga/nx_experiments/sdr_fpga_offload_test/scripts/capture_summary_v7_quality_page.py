#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
TAP_BASE = 0x43C00000
SUM7_VERSION = 0x53554D37
SUM7_ABI_VERSION = 0x00010001
SUM7_CAPABILITY = 0x000001FF
SUM7_MAX_CORR_FRAME = 0x0000FFFF
SUM7_BUILD_ID = 0x56370001
QUALITY_VERSION = 0x51554137
QUALITY_CAPABILITY = 0x0000000F
QUALITY_BUILD_ID = 0x51370001


def parse_devmem(text: str) -> int:
    text = text.strip()
    if not text:
        raise RuntimeError("empty devmem output")
    return int(text.split()[0], 0)


def parse_frame_lens(text: str) -> list[int]:
    values: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part, 0)
        if value < 1 or value > SUM7_MAX_CORR_FRAME:
            raise ValueError("SUM7 frame_len must be in 1..65535")
        values.append(value)
    return values or [64]


def unsigned48(lo: int, hi: int) -> int:
    return ((hi & 0xFFFF) << 32) | (lo & 0xFFFFFFFF)


def signed48(lo: int, hi: int) -> int:
    value = unsigned48(lo, hi)
    return value - (1 << 48) if value & (1 << 47) else value


def decode_pair(value: int) -> dict[str, int]:
    return {"i": value & 0xFFFF, "q": (value >> 16) & 0xFFFF}


def decode_quality_capability(value: int) -> dict[str, bool]:
    return {
        "clip_counts": bool(value & (1 << 0)),
        "zero_cross_counts": bool(value & (1 << 1)),
        "sign_same_counts": bool(value & (1 << 2)),
        "reserved_abs_sum_regs_read_zero": bool(value & (1 << 3)),
    }


def summarize_elapsed(values: list[float]) -> dict[str, float]:
    return {
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "max": max(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read SUM7/QUA7 quality-page registers without touching the active NX SDR chain.")
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--frame-lens", default="", help="Comma list for repeated validation. Default uses --frame-len.")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--settle-sec", type=float, default=0.05)
    parser.add_argument("--skip-sd-hashes", action="store_true")
    parser.add_argument("--out-json", default="logs/summary_v7_quality_page.json")
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
        write32(0x04, frame_len)
        write32(0x00, 0x00000002)
        write32(0x00, 0x00000001)
        time.sleep(max(0.0, float(args.settle_sec)))

        read_t0 = time.perf_counter()
        summary_version = read32(0x40)
        summary_flags = read32(0x44)
        frame_counter = read32(0x48)
        sample_count = read32(0x4C)
        snapshot_count = read32(0x60)
        dual_samples = read32(0x70)
        rx0_power = unsigned48(read32(0x74), read32(0x78))
        rx1_power = unsigned48(read32(0x7C), read32(0x80))
        cross_re = signed48(read32(0x84), read32(0x88))
        cross_im = signed48(read32(0x8C), read32(0x90))
        abi_version = read32(0xEC)
        capability = read32(0xF0)
        max_corr_frame = read32(0xF8)
        build_id = read32(0xFC)

        quality_version = read32(0x100)
        quality_flags = read32(0x104)
        quality_frame = read32(0x108)
        quality_samples = read32(0x10C)
        rx0_clip = decode_pair(read32(0x110))
        rx1_clip = decode_pair(read32(0x114))
        rx0_zc = decode_pair(read32(0x118))
        rx1_zc = decode_pair(read32(0x11C))
        sign_same = decode_pair(read32(0x120))
        quad_same = decode_pair(read32(0x124))
        reserved_abs = {
            "rx0_i": read32(0x128),
            "rx0_q": read32(0x12C),
            "rx1_i": read32(0x130),
            "rx1_q": read32(0x134),
        }
        quality_capability = read32(0x138)
        quality_build_id = read32(0x13C)
        read_elapsed = time.perf_counter() - read_t0

        checks = {
            "version_is_sum7": summary_version == SUM7_VERSION,
            "abi_version_ok": abi_version == SUM7_ABI_VERSION,
            "capability_ok": capability == SUM7_CAPABILITY,
            "max_corr_frame_ok": max_corr_frame == SUM7_MAX_CORR_FRAME,
            "build_id_ok": build_id == SUM7_BUILD_ID,
            "snapshot_disabled": snapshot_count == 0,
            "sample_count_matches_frame_len": sample_count == frame_len,
            "dual_samples_match": dual_samples == sample_count,
            "quality_version_ok": quality_version == QUALITY_VERSION,
            "quality_capability_ok": quality_capability == QUALITY_CAPABILITY,
            "quality_build_id_ok": quality_build_id == QUALITY_BUILD_ID,
            "quality_frame_matches_summary": quality_frame == frame_counter,
            "quality_samples_match_summary": quality_samples == sample_count,
            "reserved_abs_regs_read_zero": all(value == 0 for value in reserved_abs.values()),
        }

        return {
            "frame_len_requested": frame_len,
            "iteration": iteration,
            "summary": {
                "version_hex": f"0x{summary_version:08X}",
                "flags_hex": f"0x{summary_flags:08X}",
                "frame_counter": frame_counter,
                "sample_count": sample_count,
                "snapshot_count": snapshot_count,
                "dual_samples": dual_samples,
                "rx0_power_raw": rx0_power,
                "rx1_power_raw": rx1_power,
                "cross_re_raw": cross_re,
                "cross_im_raw": cross_im,
                "abi_version_hex": f"0x{abi_version:08X}",
                "capability_hex": f"0x{capability:08X}",
                "max_corr_frame": max_corr_frame,
                "build_id_hex": f"0x{build_id:08X}",
            },
            "quality": {
                "version_hex": f"0x{quality_version:08X}",
                "flags_hex": f"0x{quality_flags:08X}",
                "frame_counter": quality_frame,
                "sample_count": quality_samples,
                "rx0_clip_counts": rx0_clip,
                "rx1_clip_counts": rx1_clip,
                "rx0_zero_cross_counts": rx0_zc,
                "rx1_zero_cross_counts": rx1_zc,
                "sign_same_counts": sign_same,
                "quadrature_same_sign_counts": quad_same,
                "reserved_abs_sum_regs": reserved_abs,
                "capability_hex": f"0x{quality_capability:08X}",
                "capability": decode_quality_capability(quality_capability),
                "build_id_hex": f"0x{quality_build_id:08X}",
            },
            "checks": checks,
            "passed": all(checks.values()),
            "timing_sec": {
                "register_read": read_elapsed,
                "total_capture": time.perf_counter() - total_t0,
            },
        }

    captures = []
    for frame_len in frame_lens:
        for iteration in range(repeat):
            captures.append(capture_once(frame_len, iteration))
    client.close()

    timing_summary = {
        key: summarize_elapsed([float(item["timing_sec"][key]) for item in captures])
        for key in ["register_read", "total_capture"]
    }
    payload = {
        "timestamp_sec": time.time(),
        "operation": "summary_v7_quality_page",
        "connect_elapsed_sec": connect_elapsed,
        "sd_hashes": sd_hashes,
        "frame_lens": frame_lens,
        "repeat": repeat,
        "captures": captures,
        "pass_count": sum(1 for item in captures if item["passed"]),
        "capture_count": len(captures),
        "passed": all(item["passed"] for item in captures),
        "timing_summary_sec": timing_summary,
        "notes": [
            "SUM7A keeps SUM6-compatible reductions and adds a light quality page.",
            "Reserved abs-sum registers intentionally read zero in this timing-clean build.",
            "This script does not start ROS, robot_control, SDR streaming runtime, mapping, RTAB-Map, or motion paths.",
        ],
    }
    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
