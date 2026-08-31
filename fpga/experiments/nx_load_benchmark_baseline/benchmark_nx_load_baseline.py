#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
NX_EXPERIMENT_ROOT = REPO_ROOT / "nx_experiments" / "sdr_fpga_offload_test"
sys.path.insert(0, str(NX_EXPERIMENT_ROOT))

from sdr_fpga_offload_test.fpga_assisted_metrics import dual_rx_cpu_primitives  # noqa: E402
from sdr_fpga_offload_test.reference_compute import aoa_reference, power_frame_reference, spectrum_reference  # noqa: E402


FRAME_LEN_DEFAULT = 64
AGG_FRAMES_DEFAULT = (16, 64, 256)
FULL_SUMMARY_RESULT_READS = 34
PER_FRAME_TRIGGER_WRITES = 3
PER_FRAME_DONE_POLLS = 1
AGG8_BULK_RESULT_READS = 39
AGG8_ARM_WRITES = 6
AGG8_DONE_POLLS = 1
AGG8_DEVMEM_PER_WINDOW = AGG8_ARM_WRITES + AGG8_DONE_POLLS + AGG8_BULK_RESULT_READS
MMIO_WORD_BYTES = 4
INT16_BYTES = 2
DUAL_RX_LANES = 4


def _percent_reduction(before: float, after: float) -> float | None:
    if before <= 0.0:
        return None
    return float(100.0 * (1.0 - (after / before)))


def _ratio(before: float, after: float) -> float | None:
    if after <= 0.0:
        return None
    return float(before / after)


def _stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "min": float(ordered[0]),
        "median": float(statistics.median(ordered)),
        "mean": float(statistics.fmean(ordered)),
        "max": float(ordered[-1]),
    }


def _time_call(fn: Callable[[], Any], *, iterations: int, warmup: int) -> tuple[dict[str, float], Any]:
    for _ in range(max(0, warmup)):
        fn()
    elapsed: list[float] = []
    last: Any = None
    for _ in range(max(1, iterations)):
        t0 = time.perf_counter()
        last = fn()
        elapsed.append(time.perf_counter() - t0)
    return _stats(elapsed), last


def _synth_dual_rx_raw(sample_count: int, *, seed: int, tone_bin: int = 37, noise_sigma: float = 0.035) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(sample_count, dtype=np.float32)
    phase = 2.0 * np.pi * float(tone_bin) * t / float(max(1, sample_count))
    rx0 = 0.22 * np.exp(1j * phase)
    rx1 = 0.18 * np.exp(1j * (phase + np.deg2rad(37.0)))
    rx0 += noise_sigma * (rng.standard_normal(sample_count) + 1j * rng.standard_normal(sample_count))
    rx1 += noise_sigma * (rng.standard_normal(sample_count) + 1j * rng.standard_normal(sample_count))

    lanes = np.empty((sample_count, DUAL_RX_LANES), dtype=np.int16)
    lanes[:, 0] = np.clip(np.rint(rx0.real * 32767.0), -32768, 32767).astype(np.int16)
    lanes[:, 1] = np.clip(np.rint(rx0.imag * 32767.0), -32768, 32767).astype(np.int16)
    lanes[:, 2] = np.clip(np.rint(rx1.real * 32767.0), -32768, 32767).astype(np.int16)
    lanes[:, 3] = np.clip(np.rint(rx1.imag * 32767.0), -32768, 32767).astype(np.int16)
    return np.ascontiguousarray(lanes.reshape(-1), dtype=np.int16)


def _rx0_iq_from_dual(raw_dual: np.ndarray) -> np.ndarray:
    lanes = raw_dual.reshape(-1, DUAL_RX_LANES)
    return np.ascontiguousarray(lanes[:, 0:2].reshape(-1), dtype=np.int16)


def _fake_fft_summary_consume(summary: dict[str, Any]) -> dict[str, Any]:
    bands = summary["band_power_dbfs"]
    best_band = max(bands, key=bands.get)
    return {
        "peak_freq_hz": float(summary["center_freq_hz"] + summary["peak_offset_hz"]),
        "peak_index": int(summary["peak_index"]),
        "noise_floor_dbfs": float(summary["noise_floor_dbfs"]),
        "peak_prominence_db": float(summary["peak_power_dbfs"] - summary["noise_floor_dbfs"]),
        "best_band": best_band,
        "best_band_power_dbfs": float(bands[best_band]),
        "low_quality": bool(summary["peak_power_dbfs"] < -95.0),
    }


def _fake_summary_consume(sample_count: int) -> dict[str, float]:
    rx0_corr = float(sample_count * sample_count * 4200)
    rx1_corr = float(sample_count * sample_count * 3900)
    cross_re = float(sample_count * sample_count * 3100)
    cross_im = float(sample_count * sample_count * -900)
    denom = math.sqrt(rx0_corr * rx1_corr)
    return {
        "rx0_corr_mean_dbfs": 10.0 * math.log10(rx0_corr / float(sample_count * sample_count) / float(32768 * 32768)),
        "rx1_corr_mean_dbfs": 10.0 * math.log10(rx1_corr / float(sample_count * sample_count) / float(32768 * 32768)),
        "coherence": math.hypot(cross_re, cross_im) / denom,
        "phase_deg": math.degrees(math.atan2(cross_im, cross_re)),
    }


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _transport_evidence(repo_root: Path) -> dict[str, Any]:
    old_client = _load_json(repo_root / "reports" / "sum8_aggregate_client_20260608.json")
    batched = _load_json(repo_root / "reports" / "sum8_aggregate_batch_ssh_20260608.json")

    def timings(payload: dict[str, Any] | None, key: str) -> dict[str, float] | None:
        if not payload:
            return None
        values = [
            float(capture["timing_sec"][key])
            for capture in payload.get("captures", [])
            if key in capture.get("timing_sec", {})
        ]
        return _stats(values) if values else None

    old_total = timings(old_client, "total_capture")
    batched_total = timings(batched, "single_ssh_exec_total")
    return {
        "source_files": {
            "paramiko_per_devmem_client": "reports/sum8_aggregate_client_20260608.json" if old_client else None,
            "batched_single_ssh_exec": "reports/sum8_aggregate_batch_ssh_20260608.json" if batched else None,
        },
        "paramiko_per_devmem_total_capture_sec": old_total,
        "batched_single_ssh_exec_total_sec": batched_total,
        "observed_transport_speedup_median": _ratio(
            old_total["median"], batched_total["median"]
        )
        if old_total and batched_total
        else None,
        "observed_transport_reduction_percent_median": _percent_reduction(
            old_total["median"], batched_total["median"]
        )
        if old_total and batched_total
        else None,
    }


def _burden_model(frame_len: int, agg_frames_values: tuple[int, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    per_frame_devmem = PER_FRAME_TRIGGER_WRITES + PER_FRAME_DONE_POLLS + FULL_SUMMARY_RESULT_READS
    for agg_frames in agg_frames_values:
        per_window = int(agg_frames * per_frame_devmem)
        raw_bytes = int(frame_len * agg_frames * DUAL_RX_LANES * INT16_BYTES)
        agg_payload_bytes = int(AGG8_BULK_RESULT_READS * MMIO_WORD_BYTES)
        rows.append(
            {
                "frame_len": frame_len,
                "agg_frames": agg_frames,
                "per_frame_summary_model": {
                    "devmem_commands": per_window,
                    "ssh_execs_if_one_devmem_per_exec": per_window,
                    "ssh_execs_if_one_batched_exec_per_frame": agg_frames,
                    "raw_iq_payload_bytes_dual_rx": raw_bytes,
                },
                "sum8_agg8_batched_model": {
                    "devmem_commands": AGG8_DEVMEM_PER_WINDOW,
                    "ssh_execs": 1,
                    "mmio_payload_bytes": agg_payload_bytes,
                },
                "reductions": {
                    "devmem_command_ratio": _ratio(per_window, AGG8_DEVMEM_PER_WINDOW),
                    "devmem_command_reduction_percent": _percent_reduction(per_window, AGG8_DEVMEM_PER_WINDOW),
                    "ssh_exec_ratio_vs_per_devmem_exec": _ratio(per_window, 1.0),
                    "ssh_exec_reduction_percent_vs_per_devmem_exec": _percent_reduction(per_window, 1.0),
                    "ssh_exec_ratio_vs_per_frame_batched_exec": _ratio(float(agg_frames), 1.0),
                    "ssh_exec_reduction_percent_vs_per_frame_batched_exec": _percent_reduction(float(agg_frames), 1.0),
                    "payload_ratio_raw_iq_to_agg_mmio": _ratio(raw_bytes, agg_payload_bytes),
                    "payload_reduction_percent_raw_iq_to_agg_mmio": _percent_reduction(raw_bytes, agg_payload_bytes),
                },
            }
        )
    return rows


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    sample_count = int(args.frame_len * max(args.agg_frames))
    raw_dual = _synth_dual_rx_raw(sample_count, seed=args.seed)
    raw_rx0 = _rx0_iq_from_dual(raw_dual)

    timings: dict[str, Any] = {}

    for agg_frames in args.agg_frames:
        n = int(args.frame_len * agg_frames)
        raw_window = raw_dual[: n * DUAL_RX_LANES]
        stats, last = _time_call(
            lambda raw=raw_window: dual_rx_cpu_primitives(raw),
            iterations=args.iterations,
            warmup=args.warmup,
        )
        timings[f"aggregate_cpu_dual_rx_primitives_{agg_frames}x{args.frame_len}"] = {
            "elapsed_sec": stats,
            "sample_count": n,
            "last": last.to_dict(),
            "what_fpga_agg8_removes": [
                "int16 lane reshape and promotion",
                "I/Q sums for both RX lanes",
                "raw power sums for both RX lanes",
                "cross real/imag sums",
                "mean-corrected power/cross numerator accumulation across frames",
                "quality count aggregation across frames",
            ],
        }

    for nfft in args.nfft:
        n = max(nfft, args.frame_len * max(args.agg_frames))
        raw_window = raw_rx0[: n * 2]
        stats, last = _time_call(
            lambda raw=raw_window, nfft=nfft: spectrum_reference(raw, nfft=nfft),
            iterations=args.iterations,
            warmup=args.warmup,
        )
        timings[f"spectrum_fft_psd_reference_nfft_{nfft}"] = {
            "elapsed_sec": stats,
            "last": {
                "rssi_dbfs": last.rssi_dbfs,
                "peak_power_dbfs": last.peak_power_dbfs,
                "peak_index": last.peak_index,
                "peak_freq_hz": last.peak_freq_hz,
                "noise_floor_dbfs": last.noise_floor_dbfs,
                "peak_prominence_db": last.peak_prominence_db,
            },
            "what_fpga_fft_summary_removes": [
                "int16 to float normalization for FFT input",
                "Hanning window generation/application",
                "complex FFT",
                "fftshift",
                "PSD magnitude/log conversion",
                "argmax peak search",
                "median noise floor and peak prominence reduction",
                "optional PSD compression for UI payloads",
            ],
        }

    for nfft in args.nfft:
        n = max(nfft, args.frame_len * max(args.agg_frames))
        raw_window = raw_dual[: n * DUAL_RX_LANES]
        stats, last = _time_call(
            lambda raw=raw_window, nfft=nfft: aoa_reference(raw, nfft=nfft),
            iterations=args.iterations,
            warmup=args.warmup,
        )
        timings[f"aoa_reference_dual_rx_fft_nfft_{nfft}"] = {
            "elapsed_sec": stats,
            "last": {
                "rssi0_dbfs": last.rssi0_dbfs,
                "rssi1_dbfs": last.rssi1_dbfs,
                "coherence": last.coherence,
                "phase_cross_deg": last.phase_cross_deg,
                "phase_used_deg": last.phase_used_deg,
                "aoa_deg": last.aoa_deg,
                "peak_freq_hz": last.peak_freq_hz,
            },
            "what_fpga_fft_summary_removes": [
                "dual-lane mean subtraction and FFT preparation",
                "two-channel FFT",
                "RX0 peak bin search",
                "cross-spectrum summation around the peak bins",
                "peak power conversion",
            ],
        }

    stats, last = _time_call(
        lambda: power_frame_reference(raw_rx0[: args.frame_len * 2]),
        iterations=args.iterations,
        warmup=args.warmup,
    )
    timings["per_frame_power_summary_reference"] = {
        "elapsed_sec": stats,
        "sample_count": args.frame_len,
        "last": {
            "rssi_dbfs": last.rssi_dbfs,
            "sum_power_raw": last.sum_power_raw,
            "peak_power_raw": last.peak_power_raw,
            "peak_index": last.peak_index,
        },
        "what_fpga_summary_removes": [
            "basic power reduction",
            "peak power and peak index search",
            "raw IQ transfer for simple RSSI/peak summaries",
        ],
    }

    fake_summary = {
        "center_freq_hz": 2_452_000_000.0,
        "peak_offset_hz": 1850.0,
        "peak_index": 1031,
        "peak_power_dbfs": -42.0,
        "noise_floor_dbfs": -78.5,
        "band_power_dbfs": {
            "left": -74.0,
            "center": -43.0,
            "right": -71.0,
        },
    }
    stats, last = _time_call(
        lambda: _fake_fft_summary_consume(fake_summary),
        iterations=args.iterations,
        warmup=args.warmup,
    )
    timings["future_fft_summary_consumer_only"] = {
        "elapsed_sec": stats,
        "last": last,
        "meaning": "Approximate NX work if FPGA exposes top-bin/band-power/noise/prominence summary registers.",
    }

    stats, last = _time_call(
        lambda: _fake_summary_consume(args.frame_len * max(args.agg_frames)),
        iterations=args.iterations,
        warmup=args.warmup,
    )
    timings["sum8_summary_consumer_only"] = {
        "elapsed_sec": stats,
        "last": last,
        "meaning": "Approximate NX math left after reading SUM8/AGG8 primitive registers.",
    }

    return {
        "operation": "p201_nx_load_benchmark_baseline_offline",
        "safety": {
            "offline_only": True,
            "started_ros": False,
            "started_sdr_streaming_runtime": False,
            "modified_robot_control": False,
            "touched_sdr_sd": False,
            "used_ssh": False,
        },
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "processor": platform.processor(),
            "numpy": np.__version__,
        },
        "config": {
            "frame_len": args.frame_len,
            "agg_frames": list(args.agg_frames),
            "nfft": list(args.nfft),
            "iterations": args.iterations,
            "warmup": args.warmup,
            "seed": args.seed,
        },
        "timings": timings,
        "sum8_transport_evidence": _transport_evidence(REPO_ROOT),
        "ssh_devmem_burden_model": {
            "assumptions": {
                "full_summary_result_reads_per_frame": FULL_SUMMARY_RESULT_READS,
                "per_frame_trigger_writes": PER_FRAME_TRIGGER_WRITES,
                "per_frame_done_polls": PER_FRAME_DONE_POLLS,
                "agg8_bulk_result_reads": AGG8_BULK_RESULT_READS,
                "agg8_arm_writes": AGG8_ARM_WRITES,
                "agg8_done_polls": AGG8_DONE_POLLS,
                "agg8_devmem_commands_per_window": AGG8_DEVMEM_PER_WINDOW,
            },
            "rows": _burden_model(args.frame_len, args.agg_frames),
        },
        "priority_readout": {
            "recommended_first": "aggregate",
            "reason": (
                "SUM8/AGG8 is already hardware-validated and immediately collapses repeated per-frame "
                "summary polling into one stable aggregate read. It is the safest near-term path to lower NX load."
            ),
            "recommended_second": "fft_summary_top_bin_band_power",
            "reason_second": (
                "FFT/PSD summary removes the largest NX math block, but it needs an isolated timing-safe kernel and "
                "must avoid full-spectrum AXI-Lite readback."
            ),
            "recommended_third": "per_frame_summary",
            "reason_third": (
                "Per-frame summary is the necessary ABI base and fallback, but AGG8 already gives a larger "
                "incremental reduction for scan/AoA windows."
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline P201 NX load benchmark baseline; no SSH, SDR runtime, or ROS.")
    parser.add_argument("--frame-len", type=int, default=FRAME_LEN_DEFAULT)
    parser.add_argument("--agg-frames", type=int, nargs="+", default=list(AGG_FRAMES_DEFAULT))
    parser.add_argument("--nfft", type=int, nargs="+", default=[1024, 2048, 4096])
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--seed", type=int, default=201)
    parser.add_argument("--out-json", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.agg_frames = tuple(int(value) for value in args.agg_frames)
    args.nfft = tuple(int(value) for value in args.nfft)
    payload = run_benchmark(args)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out_json:
        out_path = Path(args.out_json)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
