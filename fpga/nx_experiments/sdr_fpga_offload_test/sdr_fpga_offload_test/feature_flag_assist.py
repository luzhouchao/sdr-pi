from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Literal

from .fpga_assisted_metrics import (
    DualRxPrimitiveMetrics,
    FpgaAssistedAoaEstimate,
    fpga_assisted_aoa_estimate,
    sum8_aggregate_primitives,
)
from .sdr_kernel_client import Sum8Aggregate, Sum8AggregateClient


AssistMode = Literal["off", "shadow", "assist"]
SelectedSource = Literal["cpu", "fpga", "none"]


@dataclass(frozen=True)
class AssistQualityGate:
    min_coherence: float = 0.2
    min_rssi_dbfs: float = -90.0
    max_total_clip_count: int = 0
    allow_aoa_phase_clipped: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class FpgaAssistRead:
    requested_frame_len: int
    requested_agg_frames: int
    aggregate: Sum8Aggregate | None
    metrics: DualRxPrimitiveMetrics | None
    estimate: FpgaAssistedAoaEstimate | None
    elapsed_sec: float
    poll_count: int
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "requested_frame_len": self.requested_frame_len,
            "requested_agg_frames": self.requested_agg_frames,
            "aggregate": self.aggregate.to_dict() if self.aggregate is not None else None,
            "metrics": self.metrics.to_dict() if self.metrics is not None else None,
            "estimate": self.estimate.to_dict() if self.estimate is not None else None,
            "elapsed_sec": self.elapsed_sec,
            "poll_count": self.poll_count,
            "error": self.error,
        }


@dataclass(frozen=True)
class AssistDecision:
    mode: AssistMode
    selected_source: SelectedSource
    usable_for_assist: bool
    reason: str
    gate_failures: tuple[str, ...]
    cpu_metrics: DualRxPrimitiveMetrics | None
    fpga: FpgaAssistRead | None
    quality_gate: AssistQualityGate

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "selected_source": self.selected_source,
            "usable_for_assist": self.usable_for_assist,
            "reason": self.reason,
            "gate_failures": list(self.gate_failures),
            "cpu_metrics": self.cpu_metrics.to_dict() if self.cpu_metrics is not None else None,
            "fpga": self.fpga.to_dict() if self.fpga is not None else None,
            "quality_gate": self.quality_gate.to_dict(),
        }


class ExplicitArmReadSum8Assist:
    def __init__(
        self,
        client: Sum8AggregateClient,
        *,
        frame_len: int = 64,
        agg_frames: int = 64,
        quality_gate: AssistQualityGate | None = None,
        poll_sec: float = 0.005,
        timeout_sec: float = 5.0,
    ) -> None:
        self.client = client
        self.frame_len = int(frame_len)
        self.agg_frames = int(agg_frames)
        self.quality_gate = quality_gate or AssistQualityGate()
        self.poll_sec = float(poll_sec)
        self.timeout_sec = float(timeout_sec)

    def read_fpga(
        self,
        *,
        center_freq_hz: float,
        baseline_m: float,
        phase_calibration_deg: float,
    ) -> FpgaAssistRead:
        start = time.perf_counter()
        polls = 0
        try:
            self.client.arm_aggregate(frame_len=self.frame_len, agg_frames=self.agg_frames)
            poll_start = time.perf_counter()
            while True:
                polls += 1
                if self.client.aggregate_done():
                    break
                if time.perf_counter() - poll_start > self.timeout_sec:
                    raise TimeoutError("SUM8 aggregate did not finish before timeout")
                time.sleep(max(0.0, self.poll_sec))
            aggregate = self.client.read_aggregate()
            metrics = sum8_aggregate_primitives(aggregate)
            estimate = fpga_assisted_aoa_estimate(
                aggregate,
                center_freq_hz=center_freq_hz,
                baseline_m=baseline_m,
                phase_calibration_deg=phase_calibration_deg,
            )
            return FpgaAssistRead(
                requested_frame_len=self.frame_len,
                requested_agg_frames=self.agg_frames,
                aggregate=aggregate,
                metrics=metrics,
                estimate=estimate,
                elapsed_sec=float(time.perf_counter() - start),
                poll_count=polls,
            )
        except Exception as exc:
            return FpgaAssistRead(
                requested_frame_len=self.frame_len,
                requested_agg_frames=self.agg_frames,
                aggregate=None,
                metrics=None,
                estimate=None,
                elapsed_sec=float(time.perf_counter() - start),
                poll_count=polls,
                error=str(exc),
            )

    def decide(
        self,
        *,
        mode: AssistMode,
        cpu_metrics: DualRxPrimitiveMetrics | None,
        center_freq_hz: float,
        baseline_m: float,
        phase_calibration_deg: float,
    ) -> AssistDecision:
        if mode == "off":
            return AssistDecision(
                mode=mode,
                selected_source="cpu" if cpu_metrics is not None else "none",
                usable_for_assist=False,
                reason="feature_flag_off",
                gate_failures=(),
                cpu_metrics=cpu_metrics,
                fpga=None,
                quality_gate=self.quality_gate,
            )
        if mode not in ("shadow", "assist"):
            raise ValueError(f"unsupported assist mode: {mode}")

        fpga = self.read_fpga(
            center_freq_hz=center_freq_hz,
            baseline_m=baseline_m,
            phase_calibration_deg=phase_calibration_deg,
        )
        failures = self._gate_failures(fpga)
        usable = not failures
        if mode == "shadow":
            return AssistDecision(
                mode=mode,
                selected_source="cpu" if cpu_metrics is not None else "none",
                usable_for_assist=usable,
                reason="shadow_cpu_selected",
                gate_failures=tuple(failures),
                cpu_metrics=cpu_metrics,
                fpga=fpga,
                quality_gate=self.quality_gate,
            )
        if usable:
            return AssistDecision(
                mode=mode,
                selected_source="fpga",
                usable_for_assist=True,
                reason="assist_fpga_selected",
                gate_failures=(),
                cpu_metrics=cpu_metrics,
                fpga=fpga,
                quality_gate=self.quality_gate,
            )
        return AssistDecision(
            mode=mode,
            selected_source="cpu" if cpu_metrics is not None else "none",
            usable_for_assist=False,
            reason="assist_cpu_fallback",
            gate_failures=tuple(failures),
            cpu_metrics=cpu_metrics,
            fpga=fpga,
            quality_gate=self.quality_gate,
        )

    def _gate_failures(self, fpga: FpgaAssistRead) -> list[str]:
        if fpga.error is not None:
            return [f"fpga_read_error:{fpga.error}"]
        if fpga.aggregate is None or fpga.metrics is None or fpga.estimate is None:
            return ["fpga_missing_result"]

        aggregate = fpga.aggregate
        metrics = fpga.metrics
        failures: list[str] = []
        expected_samples = self.frame_len * self.agg_frames
        if not aggregate.done:
            failures.append("aggregate_not_done")
        if aggregate.overflow:
            failures.append("aggregate_overflow")
        if aggregate.target_frames != self.agg_frames:
            failures.append("target_frames_mismatch")
        if aggregate.frame_count != self.agg_frames:
            failures.append("frame_count_mismatch")
        if aggregate.sample_count != expected_samples:
            failures.append("sample_count_mismatch")
        if metrics.coherence is None or metrics.coherence < self.quality_gate.min_coherence:
            failures.append("coherence_below_gate")
        rssi_values = [value for value in (metrics.rx0_rssi_dbfs, metrics.rx1_rssi_dbfs) if value is not None]
        if not rssi_values or max(rssi_values) < self.quality_gate.min_rssi_dbfs:
            failures.append("rssi_below_gate")
        clip_total = int(metrics.rx0_clip_count or 0) + int(metrics.rx1_clip_count or 0)
        if clip_total > self.quality_gate.max_total_clip_count:
            failures.append("clip_count_above_gate")
        if fpga.estimate.clipped and not self.quality_gate.allow_aoa_phase_clipped:
            failures.append("aoa_phase_clipped")
        return failures
