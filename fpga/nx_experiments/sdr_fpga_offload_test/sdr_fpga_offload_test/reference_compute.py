from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping

import numpy as np


@dataclass(frozen=True)
class PowerFrameReference:
    rssi_dbfs: float
    sum_power_raw: int
    peak_power_raw: int
    peak_index: int
    sample_count: int
    elapsed_sec: float


@dataclass(frozen=True)
class SpectrumReference:
    rssi_dbfs: float
    peak_power_dbfs: float
    peak_index: int
    peak_offset_hz: float
    peak_freq_hz: float
    freq_start_hz: float
    freq_step_hz: float
    noise_floor_dbfs: float
    peak_prominence_db: float
    sample_count: int
    nfft: int
    elapsed_sec: float


@dataclass(frozen=True)
class FftPsdTopPeak:
    bin_index: int
    power_dbfs: float
    offset_hz: float


@dataclass(frozen=True)
class FftPsdReference:
    rssi_dbfs: float
    peak_power_dbfs: float
    peak_index: int
    peak_offset_hz: float
    peak_freq_hz: float
    noise_floor_dbfs: float
    peak_prominence_db: float
    band_power_dbfs: float
    sample_count: int
    nfft: int
    sample_rate_hz: float
    center_freq_hz: float
    window_id: int
    coarse_bin_count: int
    coarse_bin_step_q16: int
    coarse_psd_dbfs: tuple[float, ...]
    top_peaks: tuple[FftPsdTopPeak, ...]
    elapsed_sec: float

    def to_candidate_dict(self) -> dict[str, Any]:
        return {
            "rssi_dbfs_x100": round_dbfs_x100(self.rssi_dbfs),
            "peak_bin": int(self.peak_index),
            "peak_power_dbfs_x100": round_dbfs_x100(self.peak_power_dbfs),
            "noise_floor_dbfs_x100": round_dbfs_x100(self.noise_floor_dbfs),
            "peak_prominence_db_x100": round_dbfs_x100(self.peak_prominence_db),
            "band_power_dbfs_x100": round_dbfs_x100(self.band_power_dbfs),
            "coarse_bin_count": int(self.coarse_bin_count),
            "coarse_bin_step_q16": int(self.coarse_bin_step_q16),
            "coarse_psd_dbfs_x100": tuple(round_dbfs_x100(v) for v in self.coarse_psd_dbfs),
            "top_peaks": tuple(
                {
                    "bin_index": int(peak.bin_index),
                    "power_dbfs_x100": round_dbfs_x100(peak.power_dbfs),
                }
                for peak in self.top_peaks
            ),
        }


@dataclass(frozen=True)
class FftPsdTolerance:
    rssi_db: float = 1.0
    peak_bin: int = 1
    peak_power_db: float = 1.5
    noise_floor_db: float = 2.0
    prominence_db: float = 2.5
    band_power_db: float = 1.5
    top_peak_bin: int = 2
    top_peak_power_db: float = 2.0
    coarse_psd_db: float = 3.0


@dataclass(frozen=True)
class FftPsdToleranceCheck:
    name: str
    reference: float
    candidate: float
    tolerance: float
    units: str
    passed: bool


@dataclass(frozen=True)
class AoaReference:
    rssi0_dbfs: float
    rssi1_dbfs: float
    coherence: float
    phase_cross_deg: float
    phase_used_deg: float
    phase_corrected_deg: float
    aoa_deg: float
    peak_index: int
    peak_freq_hz: float
    peak_power_dbfs: float
    sample_count: int
    nfft: int
    elapsed_sec: float


def load_raw_i16_npz(path: str) -> np.ndarray:
    data = np.load(path)
    if "raw_i16" in data:
        raw = data["raw_i16"]
    elif "raw" in data:
        raw = data["raw"]
    else:
        keys = ", ".join(data.files)
        raise RuntimeError(f"Expected raw_i16 or raw in {path}; found: {keys}")
    return np.ascontiguousarray(raw.reshape(-1), dtype=np.int16)


def spectrum_reference(
    raw_i16: np.ndarray,
    *,
    use_iq: bool = True,
    nfft: int = 2048,
    center_freq_hz: float = 2_452_000_000.0,
    sample_rate_hz: float = 2_000_000.0,
) -> SpectrumReference:
    start = time.perf_counter()
    raw = np.ascontiguousarray(raw_i16.reshape(-1), dtype=np.int16)
    if use_iq:
        i_sig = raw[0::2]
        q_sig = raw[1::2]
        if q_sig.size == 0:
            q_sig = np.zeros_like(i_sig)
    else:
        i_sig = raw
        q_sig = np.zeros_like(i_sig)

    sample_count = int(min(i_sig.size, q_sig.size))
    if sample_count <= 0:
        raise RuntimeError("Empty SDR buffer")
    nfft_eff = int(max(64, min(int(nfft), sample_count)))

    scale = np.float32(1.0 / 32768.0)
    i_norm = i_sig[:sample_count].astype(np.float32, copy=False) * scale
    q_norm = q_sig[:sample_count].astype(np.float32, copy=False) * scale
    power_linear = float(np.mean(i_norm * i_norm + q_norm * q_norm))
    rssi_dbfs = float(10.0 * np.log10(power_linear + 1e-12))

    iq_norm = (i_norm + 1j * q_norm).astype(np.complex64, copy=False)
    window = np.hanning(nfft_eff).astype(np.float32)
    coherent_gain = float(np.sum(window))
    spec = np.fft.fftshift(np.fft.fft(iq_norm[:nfft_eff] * window))
    psd = 20.0 * np.log10((np.abs(spec) / max(coherent_gain, 1e-12)) + 1e-12)
    psd = np.asarray(psd, dtype=np.float32)

    idx = int(np.argmax(psd))
    freq_step_hz = float(sample_rate_hz / nfft_eff)
    peak_offset_hz = float((idx - (nfft_eff / 2.0)) * freq_step_hz)
    noise_floor_dbfs = float(np.median(psd))
    peak_power_dbfs = float(psd[idx])
    return SpectrumReference(
        rssi_dbfs=rssi_dbfs,
        peak_power_dbfs=peak_power_dbfs,
        peak_index=idx,
        peak_offset_hz=peak_offset_hz,
        peak_freq_hz=float(center_freq_hz + peak_offset_hz),
        freq_start_hz=float(center_freq_hz - sample_rate_hz / 2.0),
        freq_step_hz=freq_step_hz,
        noise_floor_dbfs=noise_floor_dbfs,
        peak_prominence_db=float(peak_power_dbfs - noise_floor_dbfs),
        sample_count=sample_count,
        nfft=nfft_eff,
        elapsed_sec=float(time.perf_counter() - start),
    )


def round_dbfs_x100(value: float) -> int:
    return int(round(float(value) * 100.0))


def _candidate_db(candidate: Mapping[str, Any], x100_name: str, float_name: str) -> float:
    if x100_name in candidate:
        return float(candidate[x100_name]) / 100.0
    if float_name in candidate:
        return float(candidate[float_name])
    raise KeyError(x100_name)


def _candidate_coarse_dbfs(candidate: Mapping[str, Any]) -> tuple[float, ...]:
    if "coarse_psd_dbfs_x100" in candidate:
        return tuple(float(v) / 100.0 for v in candidate["coarse_psd_dbfs_x100"])
    if "coarse_psd_dbfs" in candidate:
        return tuple(float(v) for v in candidate["coarse_psd_dbfs"])
    raise KeyError("coarse_psd_dbfs_x100")


def _candidate_peak_power_db(peak: Mapping[str, Any]) -> float:
    if "power_dbfs_x100" in peak:
        return float(peak["power_dbfs_x100"]) / 100.0
    return float(peak["power_dbfs"])


def _candidate_peak_bin(peak: Mapping[str, Any]) -> int:
    if "bin_index" in peak:
        return int(peak["bin_index"])
    return int(peak["bin"])


def coarse_bin_step_q16(nfft: int, coarse_bin_count: int) -> int:
    if nfft <= 0 or coarse_bin_count <= 0:
        raise ValueError("nfft and coarse_bin_count must be positive")
    return int((int(nfft) << 16) // int(coarse_bin_count))


def coarse_psd_max_hold(psd_dbfs: np.ndarray, coarse_bin_count: int) -> tuple[float, ...]:
    arr = np.asarray(psd_dbfs, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        raise RuntimeError("Empty PSD")
    if coarse_bin_count <= 0 or coarse_bin_count > arr.size:
        raise ValueError("coarse_bin_count must be in 1..len(psd)")

    out: list[float] = []
    for index in range(int(coarse_bin_count)):
        start = int((index * arr.size) // coarse_bin_count)
        stop = int(((index + 1) * arr.size) // coarse_bin_count)
        if stop <= start:
            stop = start + 1
        out.append(float(np.max(arr[start:stop])))
    return tuple(out)


def ui_compress_psd_max_hold(psd_dbfs: np.ndarray, max_bins: int = 96) -> tuple[tuple[float, ...], int]:
    arr = np.asarray(psd_dbfs, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return (), 1
    if arr.size <= max_bins:
        return tuple(float(v) for v in arr), 1
    group = max(1, int(arr.size / int(max_bins)))
    starts = np.arange(0, arr.size, group, dtype=np.int64)
    compressed = np.maximum.reduceat(arr, starts)
    return tuple(float(v) for v in compressed), group


def top_psd_peaks(
    psd_dbfs: np.ndarray,
    *,
    count: int = 4,
    guard_bins: int = 3,
    sample_rate_hz: float = 2_000_000.0,
) -> tuple[FftPsdTopPeak, ...]:
    arr = np.asarray(psd_dbfs, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return ()
    blocked = np.zeros(arr.size, dtype=bool)
    order = np.argsort(arr)[::-1]
    peaks: list[FftPsdTopPeak] = []
    freq_step_hz = float(sample_rate_hz) / float(arr.size)
    for raw_idx in order:
        idx = int(raw_idx)
        if blocked[idx]:
            continue
        offset_hz = float((idx - (arr.size / 2.0)) * freq_step_hz)
        peaks.append(FftPsdTopPeak(bin_index=idx, power_dbfs=float(arr[idx]), offset_hz=offset_hz))
        lo = max(0, idx - int(guard_bins))
        hi = min(arr.size, idx + int(guard_bins) + 1)
        blocked[lo:hi] = True
        if len(peaks) >= count:
            break
    return tuple(peaks)


def fft_psd_shadow_reference(
    raw_i16: np.ndarray,
    *,
    use_iq: bool = True,
    nfft: int = 2048,
    center_freq_hz: float = 2_452_000_000.0,
    sample_rate_hz: float = 2_000_000.0,
    coarse_bin_count: int = 96,
    top_peak_count: int = 4,
    peak_guard_bins: int = 3,
) -> FftPsdReference:
    start = time.perf_counter()
    raw = np.ascontiguousarray(raw_i16.reshape(-1), dtype=np.int16)
    if use_iq:
        i_sig = raw[0::2]
        q_sig = raw[1::2]
        if q_sig.size == 0:
            q_sig = np.zeros_like(i_sig)
    else:
        i_sig = raw
        q_sig = np.zeros_like(i_sig)

    sample_count = int(min(i_sig.size, q_sig.size))
    if sample_count <= 0:
        raise RuntimeError("Empty SDR buffer")
    nfft_eff = int(max(64, min(int(nfft), sample_count)))
    if coarse_bin_count < 1 or coarse_bin_count > nfft_eff:
        raise ValueError("coarse_bin_count must be in 1..nfft")

    scale = np.float32(1.0 / 32768.0)
    i_norm = i_sig[:sample_count].astype(np.float32, copy=False) * scale
    q_norm = q_sig[:sample_count].astype(np.float32, copy=False) * scale
    power_linear = float(np.mean(i_norm * i_norm + q_norm * q_norm))
    rssi_dbfs = float(10.0 * np.log10(power_linear + 1e-12))

    iq_norm = (i_norm + 1j * q_norm).astype(np.complex64, copy=False)
    window = np.hanning(nfft_eff).astype(np.float32)
    coherent_gain = float(np.sum(window))
    spec = np.fft.fftshift(np.fft.fft(iq_norm[:nfft_eff] * window))
    psd = 20.0 * np.log10((np.abs(spec) / max(coherent_gain, 1e-12)) + 1e-12)
    psd = np.asarray(psd, dtype=np.float32)

    idx = int(np.argmax(psd))
    freq_step_hz = float(sample_rate_hz / nfft_eff)
    peak_offset_hz = float((idx - (nfft_eff / 2.0)) * freq_step_hz)
    noise_floor_dbfs = float(np.median(psd))
    peak_power_dbfs = float(psd[idx])
    linear_power = np.power(10.0, psd.astype(np.float64) / 10.0)
    band_power_dbfs = float(10.0 * np.log10(float(np.mean(linear_power)) + 1e-24))

    return FftPsdReference(
        rssi_dbfs=rssi_dbfs,
        peak_power_dbfs=peak_power_dbfs,
        peak_index=idx,
        peak_offset_hz=peak_offset_hz,
        peak_freq_hz=float(center_freq_hz + peak_offset_hz),
        noise_floor_dbfs=noise_floor_dbfs,
        peak_prominence_db=float(peak_power_dbfs - noise_floor_dbfs),
        band_power_dbfs=band_power_dbfs,
        sample_count=sample_count,
        nfft=nfft_eff,
        sample_rate_hz=float(sample_rate_hz),
        center_freq_hz=float(center_freq_hz),
        window_id=1,
        coarse_bin_count=int(coarse_bin_count),
        coarse_bin_step_q16=coarse_bin_step_q16(nfft_eff, coarse_bin_count),
        coarse_psd_dbfs=coarse_psd_max_hold(psd, coarse_bin_count),
        top_peaks=top_psd_peaks(
            psd,
            count=int(top_peak_count),
            guard_bins=int(peak_guard_bins),
            sample_rate_hz=sample_rate_hz,
        ),
        elapsed_sec=float(time.perf_counter() - start),
    )


def compare_fft_psd_candidate(
    reference: FftPsdReference,
    candidate: Mapping[str, Any],
    tolerance: FftPsdTolerance | None = None,
) -> list[FftPsdToleranceCheck]:
    tol = tolerance or FftPsdTolerance()
    checks: list[FftPsdToleranceCheck] = []

    def add(name: str, ref_value: float, cand_value: float, allowed: float, units: str) -> None:
        checks.append(
            FftPsdToleranceCheck(
                name=name,
                reference=float(ref_value),
                candidate=float(cand_value),
                tolerance=float(allowed),
                units=units,
                passed=abs(float(ref_value) - float(cand_value)) <= float(allowed),
            )
        )

    add("rssi_dbfs", reference.rssi_dbfs, _candidate_db(candidate, "rssi_dbfs_x100", "rssi_dbfs"), tol.rssi_db, "dB")
    add("peak_bin", reference.peak_index, int(candidate["peak_bin"]), float(tol.peak_bin), "bins")
    add(
        "peak_power_dbfs",
        reference.peak_power_dbfs,
        _candidate_db(candidate, "peak_power_dbfs_x100", "peak_power_dbfs"),
        tol.peak_power_db,
        "dB",
    )
    add(
        "noise_floor_dbfs",
        reference.noise_floor_dbfs,
        _candidate_db(candidate, "noise_floor_dbfs_x100", "noise_floor_dbfs"),
        tol.noise_floor_db,
        "dB",
    )
    add(
        "peak_prominence_db",
        reference.peak_prominence_db,
        _candidate_db(candidate, "peak_prominence_db_x100", "peak_prominence_db"),
        tol.prominence_db,
        "dB",
    )
    add(
        "band_power_dbfs",
        reference.band_power_dbfs,
        _candidate_db(candidate, "band_power_dbfs_x100", "band_power_dbfs"),
        tol.band_power_db,
        "dB",
    )

    candidate_peaks = tuple(candidate.get("top_peaks", ()))
    for index, ref_peak in enumerate(reference.top_peaks[: len(candidate_peaks)]):
        cand_peak = candidate_peaks[index]
        add(
            f"top{index}_bin",
            ref_peak.bin_index,
            _candidate_peak_bin(cand_peak),
            float(tol.top_peak_bin),
            "bins",
        )
        add(
            f"top{index}_power_dbfs",
            ref_peak.power_dbfs,
            _candidate_peak_power_db(cand_peak),
            tol.top_peak_power_db,
            "dB",
        )

    candidate_coarse = _candidate_coarse_dbfs(candidate)
    compare_count = min(len(reference.coarse_psd_dbfs), len(candidate_coarse))
    if compare_count == 0:
        add("coarse_psd_count", len(reference.coarse_psd_dbfs), 0, 0, "bins")
    else:
        errors = [
            abs(float(reference.coarse_psd_dbfs[index]) - float(candidate_coarse[index]))
            for index in range(compare_count)
        ]
        add("coarse_psd_count", len(reference.coarse_psd_dbfs), len(candidate_coarse), 0, "bins")
        add("coarse_psd_max_abs_error", 0.0, max(errors), tol.coarse_psd_db, "dB")
    return checks


def power_frame_reference(raw_i16: np.ndarray, *, use_iq: bool = True) -> PowerFrameReference:
    start = time.perf_counter()
    raw = np.ascontiguousarray(raw_i16.reshape(-1), dtype=np.int16)
    if use_iq:
        i_sig = raw[0::2]
        q_sig = raw[1::2]
        if q_sig.size == 0:
            q_sig = np.zeros_like(i_sig)
    else:
        i_sig = raw
        q_sig = np.zeros_like(i_sig)

    sample_count = int(min(i_sig.size, q_sig.size))
    if sample_count <= 0:
        raise RuntimeError("Empty SDR buffer")
    i32 = i_sig[:sample_count].astype(np.int64, copy=False)
    q32 = q_sig[:sample_count].astype(np.int64, copy=False)
    power = (i32 * i32) + (q32 * q32)
    sum_power = int(np.sum(power, dtype=np.int64))
    peak_index = int(np.argmax(power))
    peak_power = int(power[peak_index])
    mean_power_norm = float(sum_power) / float(sample_count) / float(32768.0 * 32768.0)
    return PowerFrameReference(
        rssi_dbfs=float(10.0 * np.log10(mean_power_norm + 1e-12)),
        sum_power_raw=sum_power,
        peak_power_raw=peak_power,
        peak_index=peak_index,
        sample_count=sample_count,
        elapsed_sec=float(time.perf_counter() - start),
    )


def to_complex_lanes(raw_i16: np.ndarray, lane_count: int, lane_map: list[int]) -> tuple[np.ndarray, np.ndarray]:
    raw = np.ascontiguousarray(raw_i16.reshape(-1), dtype=np.int16)
    usable = int(raw.size - (raw.size % lane_count))
    if usable <= 0:
        raise RuntimeError("Empty SDR buffer")
    lanes = raw[:usable].reshape(-1, lane_count).astype(np.float32) / 32768.0
    i0, q0, i1, q1 = lane_map
    return (
        (lanes[:, i0] + 1j * lanes[:, q0]).astype(np.complex64, copy=False),
        (lanes[:, i1] + 1j * lanes[:, q1]).astype(np.complex64, copy=False),
    )


def wrap_to_pi(rad: float) -> float:
    return float((rad + math.pi) % (2.0 * math.pi) - math.pi)


def aoa_reference(
    raw_i16: np.ndarray,
    *,
    lane_count: int = 4,
    lane_map: list[int] | None = None,
    sample_rate_hz: float = 2_000_000.0,
    center_freq_hz: float = 2_452_000_000.0,
    baseline_m: float = 0.02,
    phase_calibration_deg: float = 0.0,
    nfft: int = 2048,
) -> AoaReference:
    start = time.perf_counter()
    if lane_map is None:
        lane_map = [0, 1, 2, 3]
    rx0, rx1 = to_complex_lanes(raw_i16, lane_count, lane_map)
    n = int(min(rx0.size, rx1.size))
    if n < 64:
        raise RuntimeError(f"Too few samples for AoA: {n}")

    rx0 = rx0[:n] - np.mean(rx0[:n])
    rx1 = rx1[:n] - np.mean(rx1[:n])
    p0 = float(np.vdot(rx0, rx0).real / n)
    p1 = float(np.vdot(rx1, rx1).real / n)
    cross = np.vdot(rx1, rx0) / n
    coherence = float(np.abs(cross) / max(1e-12, math.sqrt(max(1e-12, p0 * p1))))
    phase_cross = float(np.angle(cross))

    nfft_eff = int(max(64, min(int(nfft), n)))
    window = np.hanning(nfft_eff).astype(np.float32)
    fft_input = np.empty((2, nfft_eff), dtype=np.complex64)
    fft_input[0, :] = rx0[:nfft_eff] * window
    fft_input[1, :] = rx1[:nfft_eff] * window
    spectra = np.fft.fftshift(np.fft.fft(fft_input, axis=1), axes=1)
    x0 = spectra[0]
    x1 = spectra[1]
    power0 = (x0.real * x0.real) + (x0.imag * x0.imag)
    idx = int(np.argmax(power0))
    lo = max(0, idx - 2)
    hi = min(nfft_eff, idx + 3)
    cross_spec = np.sum(x0[lo:hi] * np.conjugate(x1[lo:hi]))
    phase_used = float(np.angle(cross_spec)) if np.abs(cross_spec) > 1e-12 else phase_cross
    corrected_phase = wrap_to_pi(phase_used - math.radians(phase_calibration_deg))

    freq_step_hz = float(sample_rate_hz / nfft_eff)
    peak_offset_hz = float((idx - (nfft_eff / 2.0)) * freq_step_hz)
    peak_freq_hz = float(center_freq_hz + peak_offset_hz)
    wavelength = 299_792_458.0 / max(1.0, peak_freq_hz)
    sin_arg = corrected_phase * wavelength / (2.0 * math.pi * baseline_m)
    aoa_deg = float(math.degrees(math.asin(float(np.clip(sin_arg, -1.0, 1.0)))))

    return AoaReference(
        rssi0_dbfs=float(10.0 * math.log10(max(1e-12, p0))),
        rssi1_dbfs=float(10.0 * math.log10(max(1e-12, p1))),
        coherence=coherence,
        phase_cross_deg=float(math.degrees(phase_cross)),
        phase_used_deg=float(math.degrees(phase_used)),
        phase_corrected_deg=float(math.degrees(corrected_phase)),
        aoa_deg=aoa_deg,
        peak_index=idx,
        peak_freq_hz=peak_freq_hz,
        peak_power_dbfs=float(10.0 * np.log10(float(power0[idx]) + 1e-24)),
        sample_count=n,
        nfft=nfft_eff,
        elapsed_sec=float(time.perf_counter() - start),
    )


def dataclass_to_dict(value) -> dict:
    return asdict(value)
