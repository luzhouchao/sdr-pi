from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


TAP_BASE = 0x43C00000
MAX_V5_CORRECTED_FRAME_LEN = 256
MAX_V6_CORRECTED_FRAME_LEN = 65535
MAX_V7_CORRECTED_FRAME_LEN = 65535
MAX_V8_AGG_FRAMES = 65535
MAX_V8L1_AGG_FRAMES = 65535
FFT_SHADOW_BASE_OFFSET = 0x400
FFT_SHADOW_MAGIC = 0x46465431
FFT_SHADOW_ABI_VERSION = 0x00020000
FFT_SHADOW_BUILD_ID = 0x46505331
FFT_SHADOW_COARSE_BIN_MIN = 64
FFT_SHADOW_COARSE_BIN_PREFERRED = 96
FFT_SHADOW_COARSE_BIN_MAX = 128
FFT_SHADOW_TOP_PEAK_COUNT = 4
FFT_SHADOW_CAPABILITY = 0x00000FFF

FFT_SHADOW_CAP_REAL_FFT = 1 << 0
FFT_SHADOW_CAP_PSD_DBFS_X100 = 1 << 1
FFT_SHADOW_CAP_TOP_PEAKS = 1 << 2
FFT_SHADOW_CAP_COARSE_PSD = 1 << 3
FFT_SHADOW_CAP_NOISE_FLOOR = 1 << 4
FFT_SHADOW_CAP_PROMINENCE = 1 << 5
FFT_SHADOW_CAP_BAND_POWER = 1 << 6
FFT_SHADOW_CAP_RX0 = 1 << 7
FFT_SHADOW_CAP_STALE_FLAG = 1 << 8
FFT_SHADOW_CAP_OVERFLOW_FLAG = 1 << 9
FFT_SHADOW_CAP_LOW_CONFIDENCE_FLAG = 1 << 10
FFT_SHADOW_CAP_SAMPLE_MISMATCH_FLAG = 1 << 11

FFT_SHADOW_STATUS_VALID = 1 << 0
FFT_SHADOW_STATUS_BUSY = 1 << 1
FFT_SHADOW_STATUS_STALE = 1 << 2
FFT_SHADOW_STATUS_OVERFLOW = 1 << 3
FFT_SHADOW_STATUS_LOW_CONFIDENCE = 1 << 4
FFT_SHADOW_STATUS_SAMPLE_MISMATCH = 1 << 5
FFT_SHADOW_STATUS_PROXY_NOT_FFT = 1 << 6


class SummaryVersion(IntEnum):
    SUM1 = 0x53554D31
    SUM2 = 0x53554D32
    SUM3 = 0x53554D33
    SUM4 = 0x53554D34
    SUM5 = 0x53554D35
    SUM6 = 0x53554D36
    SUM7 = 0x53554D37
    SUM8 = 0x53554D38


@dataclass(frozen=True)
class Register:
    name: str
    offset: int
    width_bits: int = 32
    signed: bool = False
    description: str = ""

    @property
    def address(self) -> int:
        return TAP_BASE + self.offset


V5_REGISTERS: tuple[Register, ...] = (
    Register("summary_version", 0x40, description="0x53554D35 for SUM5"),
    Register("summary_flags", 0x44),
    Register("frame_counter", 0x48),
    Register("sample_count", 0x4C),
    Register("summary_sum_power_lo", 0x50),
    Register("summary_sum_power_hi", 0x54),
    Register("rx0_peak_power", 0x58),
    Register("rx0_peak_index", 0x5C),
    Register("snapshot_count", 0x60, description="0 in SUM5 production"),
    Register("dual_samples", 0x70),
    Register("rx0_power_lo", 0x74),
    Register("rx0_power_hi", 0x78),
    Register("rx1_power_lo", 0x7C),
    Register("rx1_power_hi", 0x80),
    Register("cross_re_lo", 0x84, signed=True),
    Register("cross_re_hi", 0x88, signed=True),
    Register("cross_im_lo", 0x8C, signed=True),
    Register("cross_im_hi", 0x90, signed=True),
    Register("rx1_peak_power", 0x94),
    Register("rx1_peak_index", 0x98),
    Register("i0_sum_lo", 0x9C, signed=True),
    Register("i0_sum_hi", 0xA0, signed=True),
    Register("q0_sum_lo", 0xA4, signed=True),
    Register("q0_sum_hi", 0xA8, signed=True),
    Register("i1_sum_lo", 0xAC, signed=True),
    Register("i1_sum_hi", 0xB0, signed=True),
    Register("q1_sum_lo", 0xB4, signed=True),
    Register("q1_sum_hi", 0xB8, signed=True),
    Register("rx0_corr_power_num_lo", 0xBC, signed=True),
    Register("rx0_corr_power_num_mid", 0xC0, signed=True),
    Register("rx0_corr_power_num_hi", 0xC4, signed=True, description="sign extension of bit 63"),
    Register("rx1_corr_power_num_lo", 0xC8, signed=True),
    Register("rx1_corr_power_num_mid", 0xCC, signed=True),
    Register("rx1_corr_power_num_hi", 0xD0, signed=True, description="sign extension of bit 63"),
    Register("corr_cross_re_num_lo", 0xD4, signed=True),
    Register("corr_cross_re_num_mid", 0xD8, signed=True),
    Register("corr_cross_re_num_hi", 0xDC, signed=True, description="sign extension of bit 63"),
    Register("corr_cross_im_num_lo", 0xE0, signed=True),
    Register("corr_cross_im_num_mid", 0xE4, signed=True),
    Register("corr_cross_im_num_hi", 0xE8, signed=True, description="sign extension of bit 63"),
)


V5_REGISTER_BY_NAME = {reg.name: reg for reg in V5_REGISTERS}


SUM6_REGISTERS: tuple[Register, ...] = (
    Register("summary_version", 0x40, description="0x53554D36 for SUM6"),
) + V5_REGISTERS[1:] + (
    Register("abi_version", 0xEC, description="0x00010000, major 1 minor 0"),
    Register("capability_bitmap", 0xF0, description="bits: dual_rx raw_power peaks cross iq_sums corrected_numerators snapshot_disabled wide_corrected_path"),
    Register("limit_flags", 0xF4, description="bit0 frame_len_limited, bit1 arithmetic_overflow, bit2 corrected_valid, bit3 snapshot_disabled"),
    Register("max_corr_frame_len", 0xF8, description="65535 for SUM6"),
    Register("build_id", 0xFC, description="0x56360001"),
)


SUM6_REGISTER_BY_NAME = {reg.name: reg for reg in SUM6_REGISTERS}


SUM7_REGISTERS: tuple[Register, ...] = (
    Register("summary_version", 0x40, description="0x53554D37 for SUM7"),
) + V5_REGISTERS[1:] + (
    Register("abi_version", 0xEC, description="0x00010001, major 1 minor 1"),
    Register("capability_bitmap", 0xF0, description="SUM6 bits plus bit8 quality_page"),
    Register("limit_flags", 0xF4, description="bit0 frame_len_limited, bit1 arithmetic_overflow, bit2 corrected_valid, bit3 snapshot_disabled"),
    Register("max_corr_frame_len", 0xF8, description="65535 for SUM7"),
    Register("build_id", 0xFC, description="0x56370001"),
    Register("quality_version", 0x100, description="0x51554137 for QUA7"),
    Register("quality_flags", 0x104, description="reserved/status flags"),
    Register("quality_frame", 0x108, description="latched frame counter"),
    Register("quality_samples", 0x10C, description="latched sample count"),
    Register("rx0_clip_counts", 0x110, description="upper16 Q clip count, lower16 I clip count"),
    Register("rx1_clip_counts", 0x114, description="upper16 Q clip count, lower16 I clip count"),
    Register("rx0_zero_cross_counts", 0x118, description="upper16 Q zero-cross count, lower16 I zero-cross count"),
    Register("rx1_zero_cross_counts", 0x11C, description="upper16 Q zero-cross count, lower16 I zero-cross count"),
    Register("sign_same_counts", 0x120, description="upper16 Q0/Q1 same-sign count, lower16 I0/I1 same-sign count"),
    Register("quadrature_same_sign_counts", 0x124, description="upper16 RX1 I/Q same-sign count, lower16 RX0 I/Q same-sign count"),
    Register("reserved_rx0_abs_i_sum", 0x128, description="reserved, reads 0 in timing-clean SUM7A"),
    Register("reserved_rx0_abs_q_sum", 0x12C, description="reserved, reads 0 in timing-clean SUM7A"),
    Register("reserved_rx1_abs_i_sum", 0x130, description="reserved, reads 0 in timing-clean SUM7A"),
    Register("reserved_rx1_abs_q_sum", 0x134, description="reserved, reads 0 in timing-clean SUM7A"),
    Register("quality_capability", 0x138, description="0x0000000F: clip, zero-cross, sign-same, abs-reserved-zero"),
    Register("quality_build_id", 0x13C, description="0x51370001"),
)


SUM7_REGISTER_BY_NAME = {reg.name: reg for reg in SUM7_REGISTERS}


SUM8_REGISTERS: tuple[Register, ...] = (
    Register("summary_version", 0x40, description="0x53554D38 for SUM8"),
) + V5_REGISTERS[1:] + (
    Register("abi_version", 0xEC, description="0x00010002, major 1 minor 2"),
    Register("capability_bitmap", 0xF0, description="SUM7 bits plus bit9 aggregate_page"),
    Register("limit_flags", 0xF4, description="bit0 frame_len_limited, bit1 arithmetic_overflow, bit2 corrected_valid, bit3 snapshot_disabled"),
    Register("max_corr_frame_len", 0xF8, description="65535 for SUM8"),
    Register("build_id", 0xFC, description="0x56380001"),
    Register("quality_version", 0x100, description="0x51554138 for QUA8"),
    Register("quality_flags", 0x104, description="reserved/status flags"),
    Register("quality_frame", 0x108, description="latched frame counter"),
    Register("quality_samples", 0x10C, description="latched sample count"),
    Register("rx0_clip_counts", 0x110, description="upper16 Q clip count, lower16 I clip count"),
    Register("rx1_clip_counts", 0x114, description="upper16 Q clip count, lower16 I clip count"),
    Register("rx0_zero_cross_counts", 0x118, description="upper16 Q zero-cross count, lower16 I zero-cross count"),
    Register("rx1_zero_cross_counts", 0x11C, description="upper16 Q zero-cross count, lower16 I zero-cross count"),
    Register("sign_same_counts", 0x120, description="upper16 Q0/Q1 same-sign count, lower16 I0/I1 same-sign count"),
    Register("quadrature_same_sign_counts", 0x124, description="upper16 RX1 I/Q same-sign count, lower16 RX0 I/Q same-sign count"),
    Register("reserved_rx0_abs_i_sum", 0x128, description="reserved, reads 0 in timing-clean SUM8"),
    Register("reserved_rx0_abs_q_sum", 0x12C, description="reserved, reads 0 in timing-clean SUM8"),
    Register("reserved_rx1_abs_i_sum", 0x130, description="reserved, reads 0 in timing-clean SUM8"),
    Register("reserved_rx1_abs_q_sum", 0x134, description="reserved, reads 0 in timing-clean SUM8"),
    Register("quality_capability", 0x138, description="0x0000000F: clip, zero-cross, sign-same, abs-reserved-zero"),
    Register("quality_build_id", 0x13C, description="0x51380001"),
    Register("agg_sequence", 0x17C, description="V8L1 auto-roll sequence; 0 in classic V8 until auto-roll build"),
    Register("agg_version", 0x180, description="0x41474738 for AGG8"),
    Register("agg_control", 0x184, description="bit0 enable, bit1 clear/arm write, bit2 auto-roll in V8L1, bit4 done, bit5 overflow"),
    Register("agg_target", 0x188, description="target aggregate frame count, 1..65535"),
    Register("agg_frames", 0x18C, description="latched aggregate frame count"),
    Register("agg_samples", 0x190, description="latched aggregate sample count"),
    Register("agg_rx0_corr_power_num_lo", 0x194, signed=True),
    Register("agg_rx0_corr_power_num_mid", 0x198, signed=True),
    Register("agg_rx0_corr_power_num_hi", 0x19C, signed=True),
    Register("agg_rx1_corr_power_num_lo", 0x1A0, signed=True),
    Register("agg_rx1_corr_power_num_mid", 0x1A4, signed=True),
    Register("agg_rx1_corr_power_num_hi", 0x1A8, signed=True),
    Register("agg_corr_cross_re_num_lo", 0x1AC, signed=True),
    Register("agg_corr_cross_re_num_mid", 0x1B0, signed=True),
    Register("agg_corr_cross_re_num_hi", 0x1B4, signed=True),
    Register("agg_corr_cross_im_num_lo", 0x1B8, signed=True),
    Register("agg_corr_cross_im_num_mid", 0x1BC, signed=True),
    Register("agg_corr_cross_im_num_hi", 0x1C0, signed=True),
    Register("agg_rx0_raw_power_lo", 0x1C4),
    Register("agg_rx0_raw_power_mid", 0x1C8),
    Register("agg_rx0_raw_power_hi", 0x1CC),
    Register("agg_rx1_raw_power_lo", 0x1D0),
    Register("agg_rx1_raw_power_mid", 0x1D4),
    Register("agg_rx1_raw_power_hi", 0x1D8),
    Register("agg_rx0_clip_count", 0x1DC),
    Register("agg_rx1_clip_count", 0x1E0),
    Register("agg_rx0_zero_cross_count", 0x1E4),
    Register("agg_rx1_zero_cross_count", 0x1E8),
    Register("agg_same_sign_count", 0x1EC),
    Register("agg_last_frame", 0x1F0),
    Register("agg_capability", 0x1F4, description="0x0000001F"),
    Register("agg_build_id", 0x1F8, description="0x41380001"),
    Register("agg_limit", 0x1FC, description="65535"),
)


SUM8_REGISTER_BY_NAME = {reg.name: reg for reg in SUM8_REGISTERS}


FFT_SHADOW_HEADER_REGISTERS: tuple[Register, ...] = (
    Register("fft_shadow_magic", 0x400, description="0x46465431 for FFT1"),
    Register("fft_shadow_build_id", 0x404, description="0x46505331 draft build ID for FPS1"),
    Register("fft_shadow_abi_version", 0x408, description="0x00020000 for fpga_fft_shadow v1"),
    Register("fft_shadow_capability", 0x40C, description="FFT/PSD shadow capability bitmap"),
    Register("fft_shadow_sequence", 0x410, description="monotonic result sequence"),
    Register("fft_shadow_status", 0x414, description="valid/busy/stale/overflow/low-confidence/sample-mismatch flags"),
    Register("fft_shadow_sample_count", 0x418, description="sample count used for this spectral result"),
    Register("fft_shadow_nfft", 0x41C, description="FFT length, fixed first but register-visible"),
    Register("fft_shadow_sample_rate_hz", 0x420, description="sample rate used by the kernel"),
    Register("fft_shadow_window_id", 0x424, description="0 rectangular, 1 Hann, others reserved"),
    Register("fft_shadow_scale_exponent", 0x428, signed=True, description="kernel scale exponent"),
    Register("fft_shadow_coarse_bin_count", 0x42C, description="64..128, preferred 96"),
    Register("fft_shadow_coarse_bin_step_q16", 0x430, description="FFT bins per coarse bin in Q16.16"),
    Register("fft_shadow_rx_mask", 0x434, description="bit0 RX0, bit1 RX1 reserved for later"),
    Register("fft_shadow_source_frame", 0x438, description="source frame counter or aggregate frame ID"),
    Register("fft_shadow_reserved_43c", 0x43C, description="reserved, read zero until assigned"),
    Register("fft_shadow_rssi_dbfs_x100", 0x440, signed=True),
    Register("fft_shadow_peak_bin", 0x444),
    Register("fft_shadow_peak_offset_hz", 0x448, signed=True),
    Register("fft_shadow_peak_power_dbfs_x100", 0x44C, signed=True),
    Register("fft_shadow_noise_floor_dbfs_x100", 0x450, signed=True),
    Register("fft_shadow_peak_prominence_db_x100", 0x454, signed=True),
    Register("fft_shadow_band_power_dbfs_x100", 0x458, signed=True),
    Register("fft_shadow_summary_flags", 0x45C, description="summary-specific flags, reserved initially"),
    Register("fft_shadow_top_peak_count", 0x460, description="0..4"),
    Register("fft_shadow_top_peak_valid_mask", 0x464, description="bit per top peak entry"),
    Register("fft_shadow_top0_bin", 0x468),
    Register("fft_shadow_top0_power_dbfs_x100", 0x46C, signed=True),
    Register("fft_shadow_top1_bin", 0x470),
    Register("fft_shadow_top1_power_dbfs_x100", 0x474, signed=True),
    Register("fft_shadow_top2_bin", 0x478),
    Register("fft_shadow_top2_power_dbfs_x100", 0x47C, signed=True),
    Register("fft_shadow_top3_bin", 0x480),
    Register("fft_shadow_top3_power_dbfs_x100", 0x484, signed=True),
)


FFT_SHADOW_COARSE_PSD_REGISTERS: tuple[Register, ...] = tuple(
    Register(
        f"fft_shadow_coarse_psd_{index:03d}_dbfs_x100",
        0x500 + index * 4,
        signed=True,
        description="coarse PSD bin in dBFS x100; bins above coarse_bin_count are reserved",
    )
    for index in range(FFT_SHADOW_COARSE_BIN_MAX)
)


FFT_SHADOW_REGISTERS: tuple[Register, ...] = FFT_SHADOW_HEADER_REGISTERS + FFT_SHADOW_COARSE_PSD_REGISTERS
FFT_SHADOW_REGISTER_BY_NAME = {reg.name: reg for reg in FFT_SHADOW_REGISTERS}


FUTURE_KERNEL_ROUTE = {
    "SUM5": {
        "version": int(SummaryVersion.SUM5),
        "status": "pc-built-burnable-pending-hardware-validation",
        "transport": "axi-lite-register-summary",
        "payload_shape": "constant register set",
        "fpga_role": "dual-rx reductions and corrected numerators",
        "nx_role": "math composition, calibration, aggregation, frontend publication",
    },
    "SUM6": {
        "version": int(SummaryVersion.SUM6),
        "status": "pc-built-burnable-pending-hardware-validation-after-sum5",
        "transport": "axi-lite-register-summary",
        "payload_shape": "sum5-compatible registers plus abi capability limit build metadata",
        "fpga_role": "dual-rx reductions, widened corrected numerator path, ABI/status metadata",
        "nx_role": "versioned Python/C++ API, CPU/GPU backend selection, validation and aggregation",
    },
    "SUM7": {
        "version": int(SummaryVersion.SUM7),
        "status": "hardware-validated-quality-page-rollback",
        "transport": "axi-lite-register-summary",
        "payload_shape": "sum6-compatible registers plus 0x100 quality diagnostics page",
        "fpga_role": "dual-rx reductions, ABI metadata, light clip/zero-cross/sign quality counters",
        "nx_role": "read quality primitives, compare against existing SDR math, compose higher-level algorithms",
    },
    "SUM8": {
        "version": int(SummaryVersion.SUM8),
        "status": "hardware-validated-first-rollback-behind-v8l1",
        "transport": "axi-lite-register-summary",
        "payload_shape": "sum7-compatible registers plus 0x180 aggregate page",
        "fpga_role": "multi-frame aggregation for corrected power, corrected cross, raw power, and quality counts",
        "nx_role": "arm aggregate window, read one stable page, compute divide/sqrt/atan2/calibration/AoA/publication later",
    },
    "SUM8_V8D0": {
        "version": int(SummaryVersion.SUM8),
        "status": "hardware-validated-diagnostic-layout-probe-and-current-v10s0-live-tap-base",
        "transport": "axi-lite-register-summary",
        "payload_shape": "V8L1-like SUM8/QUA8/AGG8 pages with V8D0 build IDs",
        "fpga_role": "validated live AD9361 passive tap base for isolated V10 self-test images and NX shadow comparison",
        "nx_role": "read passive aggregate pages, run independent shadow comparisons, and avoid active robot_control replacement",
    },
    "SUM8_V8L1": {
        "version": int(SummaryVersion.SUM8),
        "status": "hardware-validated-auto-aggregate-current-baseline",
        "transport": "axi-lite-register-summary",
        "payload_shape": "sum8 aggregate page plus 0x17c sequence and agg_control bit2 auto-roll",
        "fpga_role": "auto-roll multi-frame aggregate windows for lower NX polling and fewer re-arm writes",
        "nx_role": "configure once, poll sequence or read latest aggregate page, compute divide/sqrt/atan2/calibration/publication later",
    },
    "SUM8_V8L2": {
        "version": int(SummaryVersion.SUM8),
        "status": "planned-v8l1-auto-roll-continuity-fix-not-hardware-validated",
        "transport": "axi-lite-register-summary",
        "payload_shape": "V8L1-compatible summary registers with V8L2 build IDs and continuous auto-roll sequence",
        "fpga_role": "keep auto-roll running after each aggregate target window instead of stalling after the first latched page",
        "nx_role": "configure once, monitor AGG_SEQUENCE, read latest aggregate page, and fall back to V8L1/V8 if validation fails",
    },
    "FFT_PSD_PLANNED": {
        "status": "phase1-fpga-fft-shadow-abi-draft-no-hardware-yet",
        "transport": "axi-lite summary page with local mmap/uio transport first",
        "payload_shape": "summary plus four top peaks plus 64..128 coarse PSD bins, preferred 96",
        "fpga_role": "fixed-shape FFT/window/PSD/noise/peak/coarse-bin kernel",
        "nx_role": "configure kernel, read summary/coarse bins, compute absolute frequency, policy, fallback, logging",
    },
}


def unsigned48(lo: int, hi: int) -> int:
    return ((hi & 0xFFFF) << 32) | (lo & 0xFFFFFFFF)


def signed48(lo: int, hi: int) -> int:
    value = unsigned48(lo, hi)
    return value - (1 << 48) if value & (1 << 47) else value


def signed64_from_words(lo: int, mid: int, hi: int = 0) -> int:
    value = (lo & 0xFFFFFFFF) | ((mid & 0xFFFFFFFF) << 32)
    return value - (1 << 64) if value & (1 << 63) else value


def unsigned96(lo: int, mid: int, hi: int) -> int:
    return ((hi & 0xFFFFFFFF) << 64) | ((mid & 0xFFFFFFFF) << 32) | (lo & 0xFFFFFFFF)


def signed96(lo: int, mid: int, hi: int) -> int:
    value = unsigned96(lo, mid, hi)
    return value - (1 << 96) if value & (1 << 95) else value


def as_register_dict() -> dict[str, dict]:
    return {
        reg.name: {
            "offset": reg.offset,
            "address": reg.address,
            "width_bits": reg.width_bits,
            "signed": reg.signed,
            "description": reg.description,
        }
        for reg in V5_REGISTERS
    }


def as_sum6_register_dict() -> dict[str, dict]:
    return {
        reg.name: {
            "offset": reg.offset,
            "address": reg.address,
            "width_bits": reg.width_bits,
            "signed": reg.signed,
            "description": reg.description,
        }
        for reg in SUM6_REGISTERS
    }


def as_sum7_register_dict() -> dict[str, dict]:
    return {
        reg.name: {
            "offset": reg.offset,
            "address": reg.address,
            "width_bits": reg.width_bits,
            "signed": reg.signed,
            "description": reg.description,
        }
        for reg in SUM7_REGISTERS
    }


def as_sum8_register_dict() -> dict[str, dict]:
    return {
        reg.name: {
            "offset": reg.offset,
            "address": reg.address,
            "width_bits": reg.width_bits,
            "signed": reg.signed,
            "description": reg.description,
        }
        for reg in SUM8_REGISTERS
    }


def as_fft_shadow_register_dict() -> dict[str, dict]:
    return {
        reg.name: {
            "offset": reg.offset,
            "address": reg.address,
            "width_bits": reg.width_bits,
            "signed": reg.signed,
            "description": reg.description,
        }
        for reg in FFT_SHADOW_REGISTERS
    }
