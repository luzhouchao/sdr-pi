from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


UINT32_MAX = 0xFFFFFFFF


@dataclass(frozen=True)
class Spec9Reference:
    flags: int
    samples: int
    peak_bin: int
    peak_power: int
    total_power: int
    noise_floor: int
    prominence: int
    bins: tuple[int, int, int, int]
    limit_flags: int

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["flags_hex"] = f"0x{self.flags:08X}"
        payload["limit_flags_hex"] = f"0x{self.limit_flags:08X}"
        return payload


def _sat32(value: int) -> tuple[int, bool]:
    if value < 0:
        return 0, True
    if value > UINT32_MAX:
        return UINT32_MAX, True
    return int(value), False


def _proxy_bins(iq_samples: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int], int]:
    b0_re = b0_im = 0
    b1_re = b1_im = 0
    b2_re = b2_im = 0
    b3_re = b3_im = 0
    count = 0
    for count, (i_raw, q_raw) in enumerate(iq_samples, start=1):
        i_val = int(i_raw)
        q_val = int(q_raw)
        idx = (count - 1) & 3

        b0_re += i_val
        b0_im += q_val

        if idx == 0:
            b1_re += i_val
            b1_im += q_val
            b3_re += i_val
            b3_im += q_val
        elif idx == 1:
            b1_re += q_val
            b1_im -= i_val
            b3_re -= q_val
            b3_im += i_val
        elif idx == 2:
            b1_re -= i_val
            b1_im -= q_val
            b3_re -= i_val
            b3_im -= q_val
        else:
            b1_re -= q_val
            b1_im += i_val
            b3_re += q_val
            b3_im -= i_val

        if idx & 1:
            b2_re -= i_val
            b2_im -= q_val
        else:
            b2_re += i_val
            b2_im += q_val

    return (b0_re, b0_im), (b1_re, b1_im), (b2_re, b2_im), (b3_re, b3_im), count


def spec9_reference(iq_samples: Iterable[tuple[int, int]]) -> Spec9Reference:
    raw_bins = _proxy_bins(iq_samples)
    count = raw_bins[4]
    mags_raw = [abs(re) + abs(im) for re, im in raw_bins[:4]]
    bins: list[int] = []
    limit_flags = 0
    for index, value in enumerate(mags_raw):
        sat_value, saturated = _sat32(value)
        bins.append(sat_value)
        if saturated:
            limit_flags |= 1 << index

    total_power, total_sat = _sat32(sum(mags_raw))
    if total_sat:
        limit_flags |= 1 << 4

    peak_power = bins[0]
    peak_bin = 0
    for index, value in enumerate(bins[1:], start=1):
        if value > peak_power:
            peak_power = value
            peak_bin = index

    others = [value for index, value in enumerate(bins) if index != peak_bin]
    max_other = max(others) if others else 0
    noise_floor = min(others) if others else 0
    prominence_raw = max(0, peak_power - max_other)
    prominence, prom_sat = _sat32(prominence_raw)
    if prom_sat:
        limit_flags |= 1 << 5

    sample_count_mismatch = (count & 3) != 0
    low_quality = total_power == 0
    broadband_like = prominence <= (peak_power >> 2)
    dominant_tone_like = prominence > (peak_power >> 1)
    flags = (
        1
        | (0 << 1)
        | ((1 if limit_flags else 0) << 2)
        | ((1 if sample_count_mismatch else 0) << 3)
        | ((1 if low_quality else 0) << 4)
        | ((1 if broadband_like else 0) << 5)
        | ((1 if dominant_tone_like else 0) << 6)
        | (0 << 7)
    )
    return Spec9Reference(
        flags=flags,
        samples=count,
        peak_bin=peak_bin,
        peak_power=peak_power,
        total_power=total_power,
        noise_floor=noise_floor,
        prominence=prominence,
        bins=(bins[0], bins[1], bins[2], bins[3]),
        limit_flags=limit_flags,
    )


def named_test_vectors() -> dict[str, list[tuple[int, int]]]:
    return {
        "all_zero": [(0, 0)] * 64,
        "constant_dc": [(1000, -500)] * 64,
        "alternating_fs2": [(1200 if (idx & 1) == 0 else -1200, 0) for idx in range(64)],
        "fs4_rotation_like": [(1000, 0), (0, -1000), (-1000, 0), (0, 1000)] * 16,
        "single_clip": [(32767, -32768)] + [(0, 0)] * 63,
        "random_noise_fixed_seed": _lcg_noise(64),
    }


def _lcg_noise(count: int) -> list[tuple[int, int]]:
    state = 0x12345678
    values: list[tuple[int, int]] = []
    for _ in range(count):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        i_val = (state % 4096) - 2048
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        q_val = (state % 4096) - 2048
        values.append((i_val, q_val))
    return values
