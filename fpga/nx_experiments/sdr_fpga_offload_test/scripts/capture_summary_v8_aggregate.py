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

SUM8_VERSION = 0x53554D38
SUM8_ABI_VERSION = 0x00010002
SUM8_CAPABILITY = 0x000003FF
SUM8_BUILD_ID = 0x56380001
V8D0_BUILD_ID = 0x56384430
V8L1_BUILD_ID = 0x56384C31
V8L2_BUILD_ID = 0x56384C32
QUALITY_VERSION = 0x51554138
QUALITY_CAPABILITY = 0x0000000F
QUALITY_BUILD_ID = 0x51380001
V8D0_QUALITY_BUILD_ID = 0x51384430
V8L1_QUALITY_BUILD_ID = 0x51384C31
V8L2_QUALITY_BUILD_ID = 0x51384C32
AGG_VERSION = 0x41474738
AGG_CAPABILITY = 0x0000001F
V8L1_AGG_CAPABILITY = 0x0000003F
AGG_BUILD_ID = 0x41380001
V8D0_AGG_BUILD_ID = 0x41384430
V8L1_AGG_BUILD_ID = 0x41384C31
V8L2_AGG_BUILD_ID = 0x41384C32
AGG_MAX_FRAMES = 65535


def parse_devmem(text: str) -> int:
    text = text.strip()
    if not text:
        raise RuntimeError("empty devmem output")
    return int(text.split()[0], 0)


def signed96(lo: int, mid: int, hi: int) -> int:
    value = ((hi & 0xFFFFFFFF) << 64) | ((mid & 0xFFFFFFFF) << 32) | (lo & 0xFFFFFFFF)
    return value - (1 << 96) if value & (1 << 95) else value


def unsigned96(lo: int, mid: int, hi: int) -> int:
    return ((hi & 0xFFFFFFFF) << 64) | ((mid & 0xFFFFFFFF) << 32) | (lo & 0xFFFFFFFF)


def summarize_elapsed(values: list[float]) -> dict[str, float]:
    return {
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "max": max(values),
    }


def derived_metrics(rx0_corr: int, rx1_corr: int, cross_re: int, cross_im: int, samples: int) -> dict[str, float | None]:
    phase_deg = math.degrees(math.atan2(cross_im, cross_re)) if (cross_re or cross_im) else None
    denom = math.sqrt(float(rx0_corr) * float(rx1_corr)) if rx0_corr > 0 and rx1_corr > 0 else 0.0
    coherence = (math.sqrt(float(cross_re * cross_re + cross_im * cross_im)) / denom) if denom > 0.0 else None
    rx0_rssi = 10.0 * math.log10(float(rx0_corr) / float(samples) / float(32768 * 32768)) if rx0_corr > 0 and samples > 0 else None
    rx1_rssi = 10.0 * math.log10(float(rx1_corr) / float(samples) / float(32768 * 32768)) if rx1_corr > 0 and samples > 0 else None
    return {
        "phase_deg": phase_deg,
        "coherence": coherence,
        "rx0_rssi_dbfs": rx0_rssi,
        "rx1_rssi_dbfs": rx1_rssi,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read SUM8/AGG8 multi-frame FPGA aggregate registers without touching the active NX SDR chain.")
    parser.add_argument("--host", default="192.168.1.10")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--frame-len", type=int, default=64)
    parser.add_argument("--agg-frames", type=int, default=16)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--poll-sec", type=float, default=0.01)
    parser.add_argument("--timeout-sec", type=float, default=3.0)
    parser.add_argument("--skip-sd-hashes", action="store_true")
    parser.add_argument("--out-json", default="logs/summary_v8_aggregate.json")
    args = parser.parse_args()

    frame_len = max(1, min(65535, int(args.frame_len)))
    agg_frames = max(1, min(AGG_MAX_FRAMES, int(args.agg_frames)))
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

    def capture_once(iteration: int) -> dict:
        total_t0 = time.perf_counter()
        write32(0x004, frame_len)
        write32(0x188, agg_frames)
        write32(0x184, 0x00000003)
        write32(0x184, 0x00000001)
        write32(0x000, 0x00000002)
        write32(0x000, 0x00000001)

        polls = 0
        poll_t0 = time.perf_counter()
        while True:
            flags = read32(0x184)
            polls += 1
            if flags & (1 << 4):
                break
            if time.perf_counter() - poll_t0 > float(args.timeout_sec):
                raise TimeoutError(f"AGG8 did not finish in {args.timeout_sec} seconds; last flags=0x{flags:08X}")
            time.sleep(max(0.0, float(args.poll_sec)))

        read_t0 = time.perf_counter()
        summary_version = read32(0x040)
        abi_version = read32(0x0EC)
        capability = read32(0x0F0)
        build_id = read32(0x0FC)
        quality_version = read32(0x100)
        quality_capability = read32(0x138)
        quality_build_id = read32(0x13C)
        agg_version = read32(0x180)
        agg_control = read32(0x184)
        agg_target = read32(0x188)
        agg_frame_count = read32(0x18C)
        agg_sample_count = read32(0x190)
        rx0_corr = signed96(read32(0x194), read32(0x198), read32(0x19C))
        rx1_corr = signed96(read32(0x1A0), read32(0x1A4), read32(0x1A8))
        cross_re = signed96(read32(0x1AC), read32(0x1B0), read32(0x1B4))
        cross_im = signed96(read32(0x1B8), read32(0x1BC), read32(0x1C0))
        rx0_raw = unsigned96(read32(0x1C4), read32(0x1C8), read32(0x1CC))
        rx1_raw = unsigned96(read32(0x1D0), read32(0x1D4), read32(0x1D8))
        rx0_clip = read32(0x1DC)
        rx1_clip = read32(0x1E0)
        rx0_zc = read32(0x1E4)
        rx1_zc = read32(0x1E8)
        sign_same = read32(0x1EC)
        last_frame = read32(0x1F0)
        agg_capability = read32(0x1F4)
        agg_build_id = read32(0x1F8)
        agg_limit = read32(0x1FC)
        read_elapsed = time.perf_counter() - read_t0

        checks = {
            "version_is_sum8": summary_version == SUM8_VERSION,
            "abi_version_ok": abi_version == SUM8_ABI_VERSION,
            "capability_ok": capability == SUM8_CAPABILITY,
            "build_id_ok": build_id in (SUM8_BUILD_ID, V8D0_BUILD_ID, V8L1_BUILD_ID, V8L2_BUILD_ID),
            "quality_version_ok": quality_version == QUALITY_VERSION,
            "quality_capability_ok": quality_capability == QUALITY_CAPABILITY,
            "quality_build_id_ok": quality_build_id in (QUALITY_BUILD_ID, V8D0_QUALITY_BUILD_ID, V8L1_QUALITY_BUILD_ID, V8L2_QUALITY_BUILD_ID),
            "agg_version_ok": agg_version == AGG_VERSION,
            "agg_done": bool(agg_control & (1 << 4)),
            "agg_no_overflow": not bool(agg_control & (1 << 5)),
            "agg_target_ok": agg_target == agg_frames,
            "agg_frames_ok": agg_frame_count == agg_frames,
            "agg_samples_ok": agg_sample_count == agg_frames * frame_len,
            "agg_capability_ok": agg_capability in (AGG_CAPABILITY, V8L1_AGG_CAPABILITY),
            "agg_build_id_ok": agg_build_id in (AGG_BUILD_ID, V8D0_AGG_BUILD_ID, V8L1_AGG_BUILD_ID, V8L2_AGG_BUILD_ID),
            "agg_limit_ok": agg_limit == AGG_MAX_FRAMES,
        }

        return {
            "iteration": iteration,
            "requested": {"frame_len": frame_len, "agg_frames": agg_frames},
            "summary": {
                "version_hex": f"0x{summary_version:08X}",
                "abi_version_hex": f"0x{abi_version:08X}",
                "capability_hex": f"0x{capability:08X}",
                "build_id_hex": f"0x{build_id:08X}",
            },
            "quality": {
                "version_hex": f"0x{quality_version:08X}",
                "capability_hex": f"0x{quality_capability:08X}",
                "build_id_hex": f"0x{quality_build_id:08X}",
            },
            "aggregate": {
                "version_hex": f"0x{agg_version:08X}",
                "control_hex": f"0x{agg_control:08X}",
                "target_frames": agg_target,
                "frame_count": agg_frame_count,
                "sample_count": agg_sample_count,
                "rx0_corr_power_num": rx0_corr,
                "rx1_corr_power_num": rx1_corr,
                "corr_cross_re_num": cross_re,
                "corr_cross_im_num": cross_im,
                "rx0_raw_power": rx0_raw,
                "rx1_raw_power": rx1_raw,
                "rx0_clip_count": rx0_clip,
                "rx1_clip_count": rx1_clip,
                "rx0_zero_cross_count": rx0_zc,
                "rx1_zero_cross_count": rx1_zc,
                "same_sign_count": sign_same,
                "last_frame": last_frame,
                "capability_hex": f"0x{agg_capability:08X}",
                "build_id_hex": f"0x{agg_build_id:08X}",
                "max_frames": agg_limit,
                "derived": derived_metrics(rx0_corr, rx1_corr, cross_re, cross_im, agg_sample_count),
            },
            "checks": checks,
            "passed": all(checks.values()),
            "timing_sec": {
                "poll_until_done": time.perf_counter() - poll_t0,
                "register_read": read_elapsed,
                "total_capture": time.perf_counter() - total_t0,
                "poll_count": polls,
            },
        }

    captures = [capture_once(iteration) for iteration in range(repeat)]
    client.close()

    timing_summary = {
        key: summarize_elapsed([float(item["timing_sec"][key]) for item in captures])
        for key in ["poll_until_done", "register_read", "total_capture"]
    }
    payload = {
        "timestamp_sec": time.time(),
        "operation": "summary_v8_aggregate",
        "connect_elapsed_sec": connect_elapsed,
        "sd_hashes": sd_hashes,
        "capture_count": len(captures),
        "pass_count": sum(1 for item in captures if item["passed"]),
        "passed": all(item["passed"] for item in captures),
        "captures": captures,
        "timing_summary_sec": timing_summary,
        "notes": [
            "SUM8/AGG8 keeps V7 pages compatible and adds a hardware multi-frame aggregate page.",
            "FPGA aggregates fixed-shape power, cross, and quality primitives; NX performs divide, sqrt, atan2, calibration, and publication later.",
            "This script stays inside the independent experiment path and does not start ROS, SDR streaming runtime, robot_control, mapping, RTAB-Map, or motion paths.",
        ],
    }
    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
