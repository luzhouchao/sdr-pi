from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Protocol

from .sdr_kernel_contract import (
    MAX_V8_AGG_FRAMES,
    MAX_V5_CORRECTED_FRAME_LEN,
    SummaryVersion,
    SUM8_REGISTER_BY_NAME,
    V5_REGISTER_BY_NAME,
    signed48,
    signed64_from_words,
    signed96,
    unsigned48,
    unsigned96,
)


SUM8_ABI_VERSION = 0x00010002
SUM8_CAPABILITY = 0x000003FF
SUM8_BUILD_ID = 0x56380001
V8D0_BUILD_ID = 0x56384430
V8L1_BUILD_ID = 0x56384C31
V8L2_BUILD_ID = 0x56384C32
QUA8_VERSION = 0x51554138
QUA8_CAPABILITY = 0x0000000F
QUA8_BUILD_ID = 0x51380001
V8D0_QUA8_BUILD_ID = 0x51384430
V8L1_QUA8_BUILD_ID = 0x51384C31
V8L2_QUA8_BUILD_ID = 0x51384C32
AGG8_VERSION = 0x41474738
AGG8_CAPABILITY = 0x0000001F
V8L1_AGG8_CAPABILITY = 0x0000003F
AGG8_BUILD_ID = 0x41380001
V8D0_AGG8_BUILD_ID = 0x41384430
V8L1_AGG8_BUILD_ID = 0x41384C31
V8L2_AGG8_BUILD_ID = 0x41384C32


class RegisterTransport(Protocol):
    def read32(self, offset: int) -> int:
        ...

    def write32(self, offset: int, value: int) -> None:
        ...


@dataclass(frozen=True)
class Sum5Summary:
    frame_counter: int
    sample_count: int
    rx0_power_raw: int
    rx1_power_raw: int
    cross_re_raw: int
    cross_im_raw: int
    rx0_peak_power: int
    rx0_peak_index: int
    rx1_peak_power: int
    rx1_peak_index: int
    i0_sum: int
    q0_sum: int
    i1_sum: int
    q1_sum: int
    rx0_corr_power_num: int
    rx1_corr_power_num: int
    corr_cross_re_num: int
    corr_cross_im_num: int
    coherence: float
    phase_deg: float

    def to_dict(self) -> dict:
        return asdict(self)


class Sum5KernelClient:
    def __init__(self, transport: RegisterTransport) -> None:
        self.transport = transport

    def _read(self, name: str) -> int:
        return self.transport.read32(V5_REGISTER_BY_NAME[name].offset)

    def _write_offset(self, offset: int, value: int) -> None:
        self.transport.write32(offset, value)

    def version(self) -> int:
        return self._read("summary_version")

    def assert_sum5(self) -> None:
        version = self.version()
        if version != int(SummaryVersion.SUM5):
            raise RuntimeError(f"Expected SUM5 0x{int(SummaryVersion.SUM5):08X}, got 0x{version:08X}")
        snapshot_count = self._read("snapshot_count")
        if snapshot_count != 0:
            raise RuntimeError(f"Expected SUM5 production snapshot_count=0, got {snapshot_count}")

    def trigger_frame(self, frame_len: int) -> None:
        if frame_len < 1 or frame_len > MAX_V5_CORRECTED_FRAME_LEN:
            raise ValueError(f"SUM5 corrected-numerator validation frame_len must be 1..{MAX_V5_CORRECTED_FRAME_LEN}")
        self._write_offset(0x04, frame_len)
        self._write_offset(0x00, 0x00000002)
        self._write_offset(0x00, 0x00000001)

    def read_summary(self) -> Sum5Summary:
        sample_count = self._read("sample_count")
        rx0_power = unsigned48(self._read("rx0_power_lo"), self._read("rx0_power_hi"))
        rx1_power = unsigned48(self._read("rx1_power_lo"), self._read("rx1_power_hi"))
        cross_re = signed48(self._read("cross_re_lo"), self._read("cross_re_hi"))
        cross_im = signed48(self._read("cross_im_lo"), self._read("cross_im_hi"))
        i0_sum = signed48(self._read("i0_sum_lo"), self._read("i0_sum_hi"))
        q0_sum = signed48(self._read("q0_sum_lo"), self._read("q0_sum_hi"))
        i1_sum = signed48(self._read("i1_sum_lo"), self._read("i1_sum_hi"))
        q1_sum = signed48(self._read("q1_sum_lo"), self._read("q1_sum_hi"))
        rx0_corr = signed64_from_words(self._read("rx0_corr_power_num_lo"), self._read("rx0_corr_power_num_mid"), self._read("rx0_corr_power_num_hi"))
        rx1_corr = signed64_from_words(self._read("rx1_corr_power_num_lo"), self._read("rx1_corr_power_num_mid"), self._read("rx1_corr_power_num_hi"))
        corr_re = signed64_from_words(self._read("corr_cross_re_num_lo"), self._read("corr_cross_re_num_mid"), self._read("corr_cross_re_num_hi"))
        corr_im = signed64_from_words(self._read("corr_cross_im_num_lo"), self._read("corr_cross_im_num_mid"), self._read("corr_cross_im_num_hi"))
        denom = math.sqrt(max(0, rx0_corr) * max(0, rx1_corr))
        coherence = float(math.hypot(corr_re, corr_im) / denom) if denom > 0 else 0.0
        phase_deg = float(math.degrees(math.atan2(corr_im, corr_re)))
        return Sum5Summary(
            frame_counter=self._read("frame_counter"),
            sample_count=sample_count,
            rx0_power_raw=rx0_power,
            rx1_power_raw=rx1_power,
            cross_re_raw=cross_re,
            cross_im_raw=cross_im,
            rx0_peak_power=self._read("rx0_peak_power"),
            rx0_peak_index=self._read("rx0_peak_index"),
            rx1_peak_power=self._read("rx1_peak_power"),
            rx1_peak_index=self._read("rx1_peak_index"),
            i0_sum=i0_sum,
            q0_sum=q0_sum,
            i1_sum=i1_sum,
            q1_sum=q1_sum,
            rx0_corr_power_num=rx0_corr,
            rx1_corr_power_num=rx1_corr,
            corr_cross_re_num=corr_re,
            corr_cross_im_num=corr_im,
            coherence=coherence,
            phase_deg=phase_deg,
        )


@dataclass(frozen=True)
class Sum8Aggregate:
    frame_count: int
    sample_count: int
    target_frames: int
    control: int
    last_frame: int
    rx0_corr_power_num: int
    rx1_corr_power_num: int
    corr_cross_re_num: int
    corr_cross_im_num: int
    rx0_raw_power: int
    rx1_raw_power: int
    rx0_clip_count: int
    rx1_clip_count: int
    rx0_zero_cross_count: int
    rx1_zero_cross_count: int
    same_sign_count: int
    coherence: float | None
    phase_deg: float | None
    rx0_rssi_dbfs: float | None
    rx1_rssi_dbfs: float | None
    rx0_corr_mean_dbfs: float | None
    rx1_corr_mean_dbfs: float | None
    sequence: int | None = None

    @property
    def done(self) -> bool:
        return bool(self.control & (1 << 4))

    @property
    def auto_roll(self) -> bool:
        return bool(self.control & (1 << 2))

    @property
    def overflow(self) -> bool:
        return bool(self.control & (1 << 5))

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["done"] = self.done
        payload["auto_roll"] = self.auto_roll
        payload["overflow"] = self.overflow
        payload["control_hex"] = f"0x{self.control:08X}"
        return payload


class Sum8AggregateClient:
    def __init__(self, transport: RegisterTransport) -> None:
        self.transport = transport

    def _read(self, name: str) -> int:
        return self.transport.read32(SUM8_REGISTER_BY_NAME[name].offset)

    def _write_offset(self, offset: int, value: int) -> None:
        self.transport.write32(offset, value)

    def assert_sum8(self) -> None:
        expected = {
            "summary_version": int(SummaryVersion.SUM8),
            "abi_version": SUM8_ABI_VERSION,
            "capability_bitmap": SUM8_CAPABILITY,
            "build_id": (SUM8_BUILD_ID, V8D0_BUILD_ID, V8L1_BUILD_ID, V8L2_BUILD_ID),
            "quality_version": QUA8_VERSION,
            "quality_capability": QUA8_CAPABILITY,
            "quality_build_id": (QUA8_BUILD_ID, V8D0_QUA8_BUILD_ID, V8L1_QUA8_BUILD_ID, V8L2_QUA8_BUILD_ID),
            "agg_version": AGG8_VERSION,
            "agg_capability": (AGG8_CAPABILITY, V8L1_AGG8_CAPABILITY),
            "agg_build_id": (AGG8_BUILD_ID, V8D0_AGG8_BUILD_ID, V8L1_AGG8_BUILD_ID, V8L2_AGG8_BUILD_ID),
            "agg_limit": MAX_V8_AGG_FRAMES,
        }
        for name, value in expected.items():
            actual = self._read(name)
            allowed = value if isinstance(value, tuple) else (value,)
            if actual not in allowed:
                expected_text = ", ".join(f"0x{item:08X}" for item in allowed)
                raise RuntimeError(f"Expected {name} in {{{expected_text}}}, got 0x{actual:08X}")

    def assert_v8d0(self) -> None:
        expected = {
            "summary_version": int(SummaryVersion.SUM8),
            "abi_version": SUM8_ABI_VERSION,
            "capability_bitmap": SUM8_CAPABILITY,
            "build_id": V8D0_BUILD_ID,
            "quality_version": QUA8_VERSION,
            "quality_capability": QUA8_CAPABILITY,
            "quality_build_id": V8D0_QUA8_BUILD_ID,
            "agg_version": AGG8_VERSION,
            "agg_capability": V8L1_AGG8_CAPABILITY,
            "agg_build_id": V8D0_AGG8_BUILD_ID,
            "agg_limit": MAX_V8_AGG_FRAMES,
        }
        for name, value in expected.items():
            actual = self._read(name)
            if actual != value:
                raise RuntimeError(f"Expected V8D0 {name}=0x{value:08X}, got 0x{actual:08X}")

    def assert_v8l1(self) -> None:
        expected = {
            "summary_version": int(SummaryVersion.SUM8),
            "abi_version": SUM8_ABI_VERSION,
            "capability_bitmap": SUM8_CAPABILITY,
            "build_id": V8L1_BUILD_ID,
            "quality_version": QUA8_VERSION,
            "quality_capability": QUA8_CAPABILITY,
            "quality_build_id": V8L1_QUA8_BUILD_ID,
            "agg_version": AGG8_VERSION,
            "agg_capability": V8L1_AGG8_CAPABILITY,
            "agg_build_id": V8L1_AGG8_BUILD_ID,
            "agg_limit": MAX_V8_AGG_FRAMES,
        }
        for name, value in expected.items():
            actual = self._read(name)
            if actual != value:
                raise RuntimeError(f"Expected V8L1 {name}=0x{value:08X}, got 0x{actual:08X}")

    def assert_v8l2(self) -> None:
        expected = {
            "summary_version": int(SummaryVersion.SUM8),
            "abi_version": SUM8_ABI_VERSION,
            "capability_bitmap": SUM8_CAPABILITY,
            "build_id": V8L2_BUILD_ID,
            "quality_version": QUA8_VERSION,
            "quality_capability": QUA8_CAPABILITY,
            "quality_build_id": V8L2_QUA8_BUILD_ID,
            "agg_version": AGG8_VERSION,
            "agg_capability": V8L1_AGG8_CAPABILITY,
            "agg_build_id": V8L2_AGG8_BUILD_ID,
            "agg_limit": MAX_V8_AGG_FRAMES,
        }
        for name, value in expected.items():
            actual = self._read(name)
            if actual != value:
                raise RuntimeError(f"Expected V8L2 {name}=0x{value:08X}, got 0x{actual:08X}")

    def arm_aggregate(self, frame_len: int, agg_frames: int) -> None:
        if frame_len < 1 or frame_len > 65535:
            raise ValueError("SUM8 frame_len must be 1..65535")
        if agg_frames < 1 or agg_frames > MAX_V8_AGG_FRAMES:
            raise ValueError(f"SUM8 agg_frames must be 1..{MAX_V8_AGG_FRAMES}")
        self._write_offset(0x004, frame_len)
        self._write_offset(SUM8_REGISTER_BY_NAME["agg_target"].offset, agg_frames)
        self._write_offset(SUM8_REGISTER_BY_NAME["agg_control"].offset, 0x00000003)
        self._write_offset(SUM8_REGISTER_BY_NAME["agg_control"].offset, 0x00000001)
        self._write_offset(0x000, 0x00000002)
        self._write_offset(0x000, 0x00000001)

    def start_auto_roll(self, frame_len: int, agg_frames: int) -> None:
        if frame_len < 1 or frame_len > 65535:
            raise ValueError("V8D0/V8L1/V8L2 frame_len must be 1..65535")
        if agg_frames < 1 or agg_frames > MAX_V8_AGG_FRAMES:
            raise ValueError(f"V8D0/V8L1/V8L2 agg_frames must be 1..{MAX_V8_AGG_FRAMES}")
        self._write_offset(0x004, frame_len)
        self._write_offset(SUM8_REGISTER_BY_NAME["agg_target"].offset, agg_frames)
        self._write_offset(SUM8_REGISTER_BY_NAME["agg_control"].offset, 0x00000007)
        self._write_offset(SUM8_REGISTER_BY_NAME["agg_control"].offset, 0x00000005)
        self._write_offset(0x000, 0x00000002)
        self._write_offset(0x000, 0x00000001)

    def stop_auto_roll(self) -> None:
        self._write_offset(SUM8_REGISTER_BY_NAME["agg_control"].offset, 0x00000000)

    def aggregate_done(self) -> bool:
        return bool(self._read("agg_control") & (1 << 4))

    def read_aggregate(self) -> Sum8Aggregate:
        rx0_corr = signed96(
            self._read("agg_rx0_corr_power_num_lo"),
            self._read("agg_rx0_corr_power_num_mid"),
            self._read("agg_rx0_corr_power_num_hi"),
        )
        rx1_corr = signed96(
            self._read("agg_rx1_corr_power_num_lo"),
            self._read("agg_rx1_corr_power_num_mid"),
            self._read("agg_rx1_corr_power_num_hi"),
        )
        corr_re = signed96(
            self._read("agg_corr_cross_re_num_lo"),
            self._read("agg_corr_cross_re_num_mid"),
            self._read("agg_corr_cross_re_num_hi"),
        )
        corr_im = signed96(
            self._read("agg_corr_cross_im_num_lo"),
            self._read("agg_corr_cross_im_num_mid"),
            self._read("agg_corr_cross_im_num_hi"),
        )
        rx0_raw = unsigned96(
            self._read("agg_rx0_raw_power_lo"),
            self._read("agg_rx0_raw_power_mid"),
            self._read("agg_rx0_raw_power_hi"),
        )
        rx1_raw = unsigned96(
            self._read("agg_rx1_raw_power_lo"),
            self._read("agg_rx1_raw_power_mid"),
            self._read("agg_rx1_raw_power_hi"),
        )
        sample_count = self._read("agg_samples")
        phase_deg = float(math.degrees(math.atan2(corr_im, corr_re))) if (corr_re or corr_im) else None
        denom = math.sqrt(float(rx0_corr) * float(rx1_corr)) if rx0_corr > 0 and rx1_corr > 0 else 0.0
        coherence = float(math.hypot(corr_re, corr_im) / denom) if denom > 0.0 else None
        rx0_rssi = 10.0 * math.log10(float(rx0_corr) / float(sample_count) / float(32768 * 32768)) if rx0_corr > 0 and sample_count > 0 else None
        rx1_rssi = 10.0 * math.log10(float(rx1_corr) / float(sample_count) / float(32768 * 32768)) if rx1_corr > 0 and sample_count > 0 else None
        rx0_corr_mean = 10.0 * math.log10(float(rx0_corr) / float(sample_count * sample_count) / float(32768 * 32768)) if rx0_corr > 0 and sample_count > 0 else None
        rx1_corr_mean = 10.0 * math.log10(float(rx1_corr) / float(sample_count * sample_count) / float(32768 * 32768)) if rx1_corr > 0 and sample_count > 0 else None
        return Sum8Aggregate(
            frame_count=self._read("agg_frames"),
            sample_count=sample_count,
            target_frames=self._read("agg_target"),
            control=self._read("agg_control"),
            last_frame=self._read("agg_last_frame"),
            rx0_corr_power_num=rx0_corr,
            rx1_corr_power_num=rx1_corr,
            corr_cross_re_num=corr_re,
            corr_cross_im_num=corr_im,
            rx0_raw_power=rx0_raw,
            rx1_raw_power=rx1_raw,
            rx0_clip_count=self._read("agg_rx0_clip_count"),
            rx1_clip_count=self._read("agg_rx1_clip_count"),
            rx0_zero_cross_count=self._read("agg_rx0_zero_cross_count"),
            rx1_zero_cross_count=self._read("agg_rx1_zero_cross_count"),
            same_sign_count=self._read("agg_same_sign_count"),
            coherence=coherence,
            phase_deg=phase_deg,
            rx0_rssi_dbfs=rx0_rssi,
            rx1_rssi_dbfs=rx1_rssi,
            rx0_corr_mean_dbfs=rx0_corr_mean,
            rx1_corr_mean_dbfs=rx1_corr_mean,
            sequence=self._read("agg_sequence"),
        )
