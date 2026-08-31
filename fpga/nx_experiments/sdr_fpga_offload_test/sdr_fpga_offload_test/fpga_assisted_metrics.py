from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass

import numpy as np

from .sdr_kernel_client import Sum8Aggregate


@dataclass(frozen=True)
class DualRxPrimitiveMetrics:
    sample_count: int
    rx0_rssi_dbfs: float | None
    rx1_rssi_dbfs: float | None
    coherence: float | None
    phase_deg: float | None
    rx0_legacy_numerator_dbfs: float | None = None
    rx1_legacy_numerator_dbfs: float | None = None
    rx0_clip_count: int | None = None
    rx1_clip_count: int | None = None
    rx0_zero_cross_count: int | None = None
    rx1_zero_cross_count: int | None = None
    same_sign_count: int | None = None
    elapsed_sec: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MetricDelta:
    name: str
    cpu: float | int | None
    fpga: float | int | None
    delta: float | None
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class FpgaAssistedAoaEstimate:
    rssi0_dbfs: float | None
    rssi1_dbfs: float | None
    coherence: float | None
    phase_cross_deg: float | None
    phase_used_deg: float | None
    phase_corrected_deg: float | None
    aoa_deg: float | None
    peak_freq_hz: float
    peak_power_dbfs: float | None
    clipped: bool
    ambiguity_risk: bool
    source: str = "fpga_sum8_agg8"
    primitive_only: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _dbfs_from_power(power_sum: float, sample_count: int) -> float | None:
    if power_sum <= 0.0 or sample_count <= 0:
        return None
    return float(10.0 * math.log10(power_sum / float(sample_count) / float(32768 * 32768)))


def _dbfs_from_corrected_numerator(numerator: float, sample_count: int) -> float | None:
    if numerator <= 0.0 or sample_count <= 0:
        return None
    return float(10.0 * math.log10(numerator / float(sample_count * sample_count) / float(32768 * 32768)))


def dual_rx_cpu_primitives(raw_i16: np.ndarray, *, lane_count: int = 4, lane_map: tuple[int, int, int, int] = (0, 1, 2, 3)) -> DualRxPrimitiveMetrics:
    start = time.perf_counter()
    raw = np.ascontiguousarray(raw_i16.reshape(-1), dtype=np.int16)
    usable = int(raw.size - (raw.size % lane_count))
    if usable <= 0:
        raise RuntimeError("empty raw_i16 buffer")
    lanes = raw[:usable].reshape(-1, lane_count).astype(np.int64, copy=False)
    i0 = lanes[:, lane_map[0]]
    q0 = lanes[:, lane_map[1]]
    i1 = lanes[:, lane_map[2]]
    q1 = lanes[:, lane_map[3]]
    n = int(lanes.shape[0])

    i0_sum = int(np.sum(i0, dtype=np.int64))
    q0_sum = int(np.sum(q0, dtype=np.int64))
    i1_sum = int(np.sum(i1, dtype=np.int64))
    q1_sum = int(np.sum(q1, dtype=np.int64))
    rx0_raw = int(np.sum(i0 * i0 + q0 * q0, dtype=np.int64))
    rx1_raw = int(np.sum(i1 * i1 + q1 * q1, dtype=np.int64))
    cross_re_raw = int(np.sum(i0 * i1 + q0 * q1, dtype=np.int64))
    cross_im_raw = int(np.sum(q0 * i1 - i0 * q1, dtype=np.int64))

    rx0_corr = int(n * rx0_raw - i0_sum * i0_sum - q0_sum * q0_sum)
    rx1_corr = int(n * rx1_raw - i1_sum * i1_sum - q1_sum * q1_sum)
    corr_re = int(n * cross_re_raw - i0_sum * i1_sum - q0_sum * q1_sum)
    corr_im = int(n * cross_im_raw - q0_sum * i1_sum + i0_sum * q1_sum)
    denom = math.sqrt(float(rx0_corr) * float(rx1_corr)) if rx0_corr > 0 and rx1_corr > 0 else 0.0
    coherence = float(math.hypot(corr_re, corr_im) / denom) if denom > 0.0 else None
    phase_deg = float(math.degrees(math.atan2(corr_im, corr_re))) if (corr_re or corr_im) else None

    return DualRxPrimitiveMetrics(
        sample_count=n,
        rx0_rssi_dbfs=_dbfs_from_corrected_numerator(float(rx0_corr), n),
        rx1_rssi_dbfs=_dbfs_from_corrected_numerator(float(rx1_corr), n),
        coherence=coherence,
        phase_deg=phase_deg,
        elapsed_sec=float(time.perf_counter() - start),
    )


def sum8_aggregate_primitives(aggregate: Sum8Aggregate) -> DualRxPrimitiveMetrics:
    return DualRxPrimitiveMetrics(
        sample_count=aggregate.sample_count,
        rx0_rssi_dbfs=aggregate.rx0_corr_mean_dbfs,
        rx1_rssi_dbfs=aggregate.rx1_corr_mean_dbfs,
        rx0_legacy_numerator_dbfs=aggregate.rx0_rssi_dbfs,
        rx1_legacy_numerator_dbfs=aggregate.rx1_rssi_dbfs,
        coherence=aggregate.coherence,
        phase_deg=aggregate.phase_deg,
        rx0_clip_count=aggregate.rx0_clip_count,
        rx1_clip_count=aggregate.rx1_clip_count,
        rx0_zero_cross_count=aggregate.rx0_zero_cross_count,
        rx1_zero_cross_count=aggregate.rx1_zero_cross_count,
        same_sign_count=aggregate.same_sign_count,
    )


def compare_primitive_metrics(cpu: DualRxPrimitiveMetrics, fpga: DualRxPrimitiveMetrics) -> list[MetricDelta]:
    deltas: list[MetricDelta] = []
    for name in ("sample_count", "rx0_rssi_dbfs", "rx1_rssi_dbfs", "coherence", "phase_deg"):
        cpu_value = getattr(cpu, name)
        fpga_value = getattr(fpga, name)
        if cpu_value is None or fpga_value is None:
            deltas.append(MetricDelta(name, cpu_value, fpga_value, None, "missing"))
        else:
            deltas.append(MetricDelta(name, cpu_value, fpga_value, abs(float(cpu_value) - float(fpga_value)), "not_same_window"))
    return deltas


def wrap_to_pi(rad: float) -> float:
    return float((rad + math.pi) % (2.0 * math.pi) - math.pi)


def fpga_assisted_aoa_estimate(
    aggregate: Sum8Aggregate,
    *,
    center_freq_hz: float,
    baseline_m: float,
    phase_calibration_deg: float,
) -> FpgaAssistedAoaEstimate:
    phase_used_deg = aggregate.phase_deg
    if phase_used_deg is None or baseline_m <= 1e-4:
        return FpgaAssistedAoaEstimate(
            rssi0_dbfs=aggregate.rx0_corr_mean_dbfs,
            rssi1_dbfs=aggregate.rx1_corr_mean_dbfs,
            coherence=aggregate.coherence,
            phase_cross_deg=phase_used_deg,
            phase_used_deg=phase_used_deg,
            phase_corrected_deg=None,
            aoa_deg=None,
            peak_freq_hz=float(center_freq_hz),
            peak_power_dbfs=None,
            clipped=False,
            ambiguity_risk=False,
        )

    corrected_phase = wrap_to_pi(math.radians(phase_used_deg - phase_calibration_deg))
    wavelength = 299_792_458.0 / max(1.0, float(center_freq_hz))
    sin_arg = corrected_phase * wavelength / (2.0 * math.pi * baseline_m)
    sin_arg_clip = max(-1.0, min(1.0, sin_arg))
    clipped = abs(sin_arg - sin_arg_clip) > 1e-6
    ambiguity_risk = bool(baseline_m > (wavelength / 2.0))
    return FpgaAssistedAoaEstimate(
        rssi0_dbfs=aggregate.rx0_corr_mean_dbfs,
        rssi1_dbfs=aggregate.rx1_corr_mean_dbfs,
        coherence=aggregate.coherence,
        phase_cross_deg=phase_used_deg,
        phase_used_deg=phase_used_deg,
        phase_corrected_deg=float(math.degrees(corrected_phase)),
        aoa_deg=float(math.degrees(math.asin(sin_arg_clip))),
        peak_freq_hz=float(center_freq_hz),
        peak_power_dbfs=None,
        clipped=clipped,
        ambiguity_risk=ambiguity_risk,
    )
