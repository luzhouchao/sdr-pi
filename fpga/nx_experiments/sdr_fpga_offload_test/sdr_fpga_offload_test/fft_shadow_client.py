from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from .sdr_kernel_contract import (
    FFT_SHADOW_ABI_VERSION,
    FFT_SHADOW_CAPABILITY,
    FFT_SHADOW_COARSE_BIN_MAX,
    FFT_SHADOW_COARSE_BIN_MIN,
    FFT_SHADOW_COARSE_BIN_PREFERRED,
    FFT_SHADOW_MAGIC,
    FFT_SHADOW_REGISTER_BY_NAME,
    FFT_SHADOW_STATUS_BUSY,
    FFT_SHADOW_STATUS_LOW_CONFIDENCE,
    FFT_SHADOW_STATUS_OVERFLOW,
    FFT_SHADOW_STATUS_PROXY_NOT_FFT,
    FFT_SHADOW_STATUS_SAMPLE_MISMATCH,
    FFT_SHADOW_STATUS_STALE,
    FFT_SHADOW_STATUS_VALID,
    FFT_SHADOW_TOP_PEAK_COUNT,
)


class RegisterTransport(Protocol):
    def read32(self, offset: int) -> int:
        ...

    def write32(self, offset: int, value: int) -> None:
        ...


def signed32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & (1 << 31) else value


@dataclass(frozen=True)
class FftShadowPeak:
    bin_index: int
    power_dbfs_x100: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class FftShadowSnapshot:
    magic: int
    build_id: int
    abi_version: int
    capability: int
    sequence: int
    status: int
    sample_count: int
    nfft: int
    sample_rate_hz: int
    window_id: int
    scale_exponent: int
    coarse_bin_count: int
    coarse_bin_step_q16: int
    rx_mask: int
    source_frame: int
    rssi_dbfs_x100: int
    peak_bin: int
    peak_offset_hz: int
    peak_power_dbfs_x100: int
    noise_floor_dbfs_x100: int
    peak_prominence_db_x100: int
    band_power_dbfs_x100: int
    summary_flags: int
    top_peaks: tuple[FftShadowPeak, ...]
    coarse_psd_dbfs_x100: tuple[int, ...]

    @property
    def valid(self) -> bool:
        return bool(self.status & FFT_SHADOW_STATUS_VALID)

    @property
    def busy(self) -> bool:
        return bool(self.status & FFT_SHADOW_STATUS_BUSY)

    @property
    def stale(self) -> bool:
        return bool(self.status & FFT_SHADOW_STATUS_STALE)

    @property
    def overflow(self) -> bool:
        return bool(self.status & FFT_SHADOW_STATUS_OVERFLOW)

    @property
    def low_confidence(self) -> bool:
        return bool(self.status & FFT_SHADOW_STATUS_LOW_CONFIDENCE)

    @property
    def sample_mismatch(self) -> bool:
        return bool(self.status & FFT_SHADOW_STATUS_SAMPLE_MISMATCH)

    @property
    def proxy_not_fft(self) -> bool:
        return bool(self.status & FFT_SHADOW_STATUS_PROXY_NOT_FFT)

    @property
    def passed_shadow_gate(self) -> bool:
        blocked = (
            self.busy
            or self.stale
            or self.overflow
            or self.low_confidence
            or self.sample_mismatch
            or self.proxy_not_fft
        )
        return self.valid and not blocked

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload.update(
            {
                "magic_hex": f"0x{self.magic:08X}",
                "build_id_hex": f"0x{self.build_id:08X}",
                "abi_version_hex": f"0x{self.abi_version:08X}",
                "capability_hex": f"0x{self.capability:08X}",
                "status_hex": f"0x{self.status:08X}",
                "valid": self.valid,
                "busy": self.busy,
                "stale": self.stale,
                "overflow": self.overflow,
                "low_confidence": self.low_confidence,
                "sample_mismatch": self.sample_mismatch,
                "proxy_not_fft": self.proxy_not_fft,
                "passed_shadow_gate": self.passed_shadow_gate,
            }
        )
        return payload


class FftShadowClient:
    def __init__(self, transport: RegisterTransport) -> None:
        self.transport = transport

    def _read(self, name: str) -> int:
        return self.transport.read32(FFT_SHADOW_REGISTER_BY_NAME[name].offset)

    def read_snapshot(self) -> FftShadowSnapshot:
        top_peak_count = min(self._read("fft_shadow_top_peak_count"), FFT_SHADOW_TOP_PEAK_COUNT)
        coarse_bin_count = self._read("fft_shadow_coarse_bin_count")
        read_bin_count = min(coarse_bin_count, FFT_SHADOW_COARSE_BIN_MAX)
        peaks = []
        for index in range(FFT_SHADOW_TOP_PEAK_COUNT):
            peaks.append(
                FftShadowPeak(
                    bin_index=self._read(f"fft_shadow_top{index}_bin"),
                    power_dbfs_x100=signed32(self._read(f"fft_shadow_top{index}_power_dbfs_x100")),
                )
            )
        coarse = tuple(
            signed32(self._read(f"fft_shadow_coarse_psd_{index:03d}_dbfs_x100"))
            for index in range(read_bin_count)
        )
        return FftShadowSnapshot(
            magic=self._read("fft_shadow_magic"),
            build_id=self._read("fft_shadow_build_id"),
            abi_version=self._read("fft_shadow_abi_version"),
            capability=self._read("fft_shadow_capability"),
            sequence=self._read("fft_shadow_sequence"),
            status=self._read("fft_shadow_status"),
            sample_count=self._read("fft_shadow_sample_count"),
            nfft=self._read("fft_shadow_nfft"),
            sample_rate_hz=self._read("fft_shadow_sample_rate_hz"),
            window_id=self._read("fft_shadow_window_id"),
            scale_exponent=signed32(self._read("fft_shadow_scale_exponent")),
            coarse_bin_count=coarse_bin_count,
            coarse_bin_step_q16=self._read("fft_shadow_coarse_bin_step_q16"),
            rx_mask=self._read("fft_shadow_rx_mask"),
            source_frame=self._read("fft_shadow_source_frame"),
            rssi_dbfs_x100=signed32(self._read("fft_shadow_rssi_dbfs_x100")),
            peak_bin=self._read("fft_shadow_peak_bin"),
            peak_offset_hz=signed32(self._read("fft_shadow_peak_offset_hz")),
            peak_power_dbfs_x100=signed32(self._read("fft_shadow_peak_power_dbfs_x100")),
            noise_floor_dbfs_x100=signed32(self._read("fft_shadow_noise_floor_dbfs_x100")),
            peak_prominence_db_x100=signed32(self._read("fft_shadow_peak_prominence_db_x100")),
            band_power_dbfs_x100=signed32(self._read("fft_shadow_band_power_dbfs_x100")),
            summary_flags=self._read("fft_shadow_summary_flags"),
            top_peaks=tuple(peaks[:top_peak_count]),
            coarse_psd_dbfs_x100=coarse,
        )

    def assert_fft_shadow(self, snapshot: FftShadowSnapshot | None = None) -> FftShadowSnapshot:
        snap = snapshot if snapshot is not None else self.read_snapshot()
        expected = {
            "magic": FFT_SHADOW_MAGIC,
            "abi_version": FFT_SHADOW_ABI_VERSION,
            "capability": FFT_SHADOW_CAPABILITY,
        }
        actual = {
            "magic": snap.magic,
            "abi_version": snap.abi_version,
            "capability": snap.capability,
        }
        for name, value in expected.items():
            if actual[name] != value:
                raise RuntimeError(f"Expected FFT shadow {name}=0x{value:08X}, got 0x{actual[name]:08X}")
        if snap.coarse_bin_count < FFT_SHADOW_COARSE_BIN_MIN or snap.coarse_bin_count > FFT_SHADOW_COARSE_BIN_MAX:
            raise RuntimeError(
                "Expected FFT shadow coarse_bin_count "
                f"{FFT_SHADOW_COARSE_BIN_MIN}..{FFT_SHADOW_COARSE_BIN_MAX}, got {snap.coarse_bin_count}"
            )
        return snap


def preferred_fft_shadow_shape() -> dict:
    return {
        "magic": f"0x{FFT_SHADOW_MAGIC:08X}",
        "abi_version": f"0x{FFT_SHADOW_ABI_VERSION:08X}",
        "capability": f"0x{FFT_SHADOW_CAPABILITY:08X}",
        "top_peak_count": FFT_SHADOW_TOP_PEAK_COUNT,
        "coarse_bin_min": FFT_SHADOW_COARSE_BIN_MIN,
        "coarse_bin_preferred": FFT_SHADOW_COARSE_BIN_PREFERRED,
        "coarse_bin_max": FFT_SHADOW_COARSE_BIN_MAX,
    }
