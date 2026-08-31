#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdr_fpga_offload_test.fft_shadow_client import FftShadowClient  # noqa: E402
from sdr_fpga_offload_test.sdr_kernel_contract import (  # noqa: E402
    FFT_SHADOW_ABI_VERSION,
    FFT_SHADOW_BUILD_ID,
    FFT_SHADOW_CAPABILITY,
    FFT_SHADOW_COARSE_BIN_PREFERRED,
    FFT_SHADOW_MAGIC,
    FFT_SHADOW_REGISTER_BY_NAME,
    FFT_SHADOW_STATUS_VALID,
)


class FakeTransport:
    def __init__(self) -> None:
        self.regs: dict[int, int] = {}

    def read32(self, offset: int) -> int:
        return self.regs.get(offset, 0)

    def write32(self, offset: int, value: int) -> None:
        self.regs[offset] = value & 0xFFFFFFFF


def put(fake: FakeTransport, name: str, value: int) -> None:
    fake.write32(FFT_SHADOW_REGISTER_BY_NAME[name].offset, value)


def main() -> None:
    fake = FakeTransport()
    put(fake, "fft_shadow_magic", FFT_SHADOW_MAGIC)
    put(fake, "fft_shadow_build_id", FFT_SHADOW_BUILD_ID)
    put(fake, "fft_shadow_abi_version", FFT_SHADOW_ABI_VERSION)
    put(fake, "fft_shadow_capability", FFT_SHADOW_CAPABILITY)
    put(fake, "fft_shadow_sequence", 12)
    put(fake, "fft_shadow_status", FFT_SHADOW_STATUS_VALID)
    put(fake, "fft_shadow_sample_count", 2048)
    put(fake, "fft_shadow_nfft", 2048)
    put(fake, "fft_shadow_sample_rate_hz", 2_000_000)
    put(fake, "fft_shadow_window_id", 1)
    put(fake, "fft_shadow_scale_exponent", (-3) & 0xFFFFFFFF)
    put(fake, "fft_shadow_coarse_bin_count", FFT_SHADOW_COARSE_BIN_PREFERRED)
    put(fake, "fft_shadow_coarse_bin_step_q16", (2048 << 16) // FFT_SHADOW_COARSE_BIN_PREFERRED)
    put(fake, "fft_shadow_rx_mask", 1)
    put(fake, "fft_shadow_source_frame", 77)
    put(fake, "fft_shadow_rssi_dbfs_x100", (-4512) & 0xFFFFFFFF)
    put(fake, "fft_shadow_peak_bin", 1001)
    put(fake, "fft_shadow_peak_offset_hz", (-22000) & 0xFFFFFFFF)
    put(fake, "fft_shadow_peak_power_dbfs_x100", (-3010) & 0xFFFFFFFF)
    put(fake, "fft_shadow_noise_floor_dbfs_x100", (-7200) & 0xFFFFFFFF)
    put(fake, "fft_shadow_peak_prominence_db_x100", 1100)
    put(fake, "fft_shadow_band_power_dbfs_x100", (-2810) & 0xFFFFFFFF)
    put(fake, "fft_shadow_top_peak_count", 4)
    put(fake, "fft_shadow_top_peak_valid_mask", 0xF)
    for index in range(4):
        put(fake, f"fft_shadow_top{index}_bin", 1000 + index)
        put(fake, f"fft_shadow_top{index}_power_dbfs_x100", (-3000 - index * 100) & 0xFFFFFFFF)
    for index in range(FFT_SHADOW_COARSE_BIN_PREFERRED):
        put(fake, f"fft_shadow_coarse_psd_{index:03d}_dbfs_x100", (-8000 + index) & 0xFFFFFFFF)

    client = FftShadowClient(fake)
    snapshot = client.assert_fft_shadow()
    assert snapshot.valid
    assert snapshot.passed_shadow_gate
    assert snapshot.coarse_bin_count == FFT_SHADOW_COARSE_BIN_PREFERRED
    assert len(snapshot.coarse_psd_dbfs_x100) == FFT_SHADOW_COARSE_BIN_PREFERRED
    assert len(snapshot.top_peaks) == 4
    assert snapshot.scale_exponent == -3
    assert snapshot.rssi_dbfs_x100 == -4512
    assert snapshot.top_peaks[3].power_dbfs_x100 == -3300
    print("fft_shadow_contract fake-register test PASS")


if __name__ == "__main__":
    main()
