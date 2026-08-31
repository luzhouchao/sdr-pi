#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import argparse
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdr_fpga_offload_test.reference_compute import (  # noqa: E402
    compare_fft_psd_candidate,
    fft_psd_shadow_reference,
    ui_compress_psd_max_hold,
)
from sdr_fpga_offload_test.sdr_kernel_contract import (  # noqa: E402
    FFT_SHADOW_COARSE_BIN_PREFERRED,
)


def synthetic_multitone_iq(*, sample_count: int = 4096, nfft: int = 2048) -> np.ndarray:
    index = np.arange(sample_count, dtype=np.float64)
    tones = (
        (123, 0.42, 0.0),
        (-317, 0.18, 0.35),
        (511, 0.10, -1.10),
    )
    iq = np.zeros(sample_count, dtype=np.complex128)
    for bin_offset, amplitude, phase in tones:
        iq += amplitude * np.exp(2j * math.pi * (float(bin_offset) / float(nfft)) * index + 1j * phase)
    iq += 0.015 * np.exp(2j * math.pi * (17.0 / float(nfft)) * index)
    i_part = np.clip(np.real(iq), -0.95, 0.95)
    q_part = np.clip(np.imag(iq), -0.95, 0.95)
    interleaved = np.empty(sample_count * 2, dtype=np.int16)
    interleaved[0::2] = np.clip(i_part * 32767.0, -32768, 32767).astype(np.int16)
    interleaved[1::2] = np.clip(q_part * 32767.0, -32768, 32767).astype(np.int16)
    return interleaved


def checks_pass(checks) -> bool:
    return all(item.passed for item in checks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline FFT/PSD reference and tolerance gate.")
    parser.add_argument("--out-json", default="")
    args = parser.parse_args()

    raw = synthetic_multitone_iq()
    ref = fft_psd_shadow_reference(raw, nfft=2048, coarse_bin_count=FFT_SHADOW_COARSE_BIN_PREFERRED)
    candidate = ref.to_candidate_dict()
    checks = compare_fft_psd_candidate(ref, candidate)

    assert ref.nfft == 2048
    assert ref.coarse_bin_count == 96
    assert len(ref.coarse_psd_dbfs) == 96
    assert ref.coarse_bin_step_q16 == (2048 << 16) // 96
    assert abs(ref.peak_index - (1024 + 123)) <= 1
    assert ref.peak_prominence_db > 20.0
    assert len(ref.top_peaks) == 4
    assert any(abs(peak.bin_index - (1024 - 317)) <= 2 for peak in ref.top_peaks)
    assert checks_pass(checks)

    ui_bins, ui_group = ui_compress_psd_max_hold(np.asarray(ref.coarse_psd_dbfs, dtype=np.float32), max_bins=96)
    assert ui_group == 1
    assert len(ui_bins) == 96

    full_ref = fft_psd_shadow_reference(raw, nfft=2048, coarse_bin_count=128)
    full_ui_bins, full_ui_group = ui_compress_psd_max_hold(
        np.linspace(-90.0, -30.0, full_ref.nfft, dtype=np.float32),
        max_bins=96,
    )
    assert full_ui_group == 21
    assert len(full_ui_bins) == 98

    bad_candidate = dict(candidate)
    bad_candidate["peak_bin"] = int(candidate["peak_bin"]) + 16
    bad_checks = compare_fft_psd_candidate(ref, bad_candidate)
    assert not checks_pass(bad_checks)
    assert any(item.name == "peak_bin" and not item.passed for item in bad_checks)

    payload = {
        "operation": "test_fft_psd_reference",
        "passed": True,
        "reference": {
            "peak_index": ref.peak_index,
            "peak_power_dbfs": ref.peak_power_dbfs,
            "noise_floor_dbfs": ref.noise_floor_dbfs,
            "peak_prominence_db": ref.peak_prominence_db,
            "coarse_bin_count": ref.coarse_bin_count,
            "coarse_bin_step_q16": ref.coarse_bin_step_q16,
            "top_peaks": [asdict(item) for item in ref.top_peaks],
        },
        "checks": [asdict(item) for item in checks],
        "ui_compression": {
            "coarse_96_group": ui_group,
            "coarse_96_bins": len(ui_bins),
            "active_ui_2048_max96_group": full_ui_group,
            "active_ui_2048_max96_bins": len(full_ui_bins),
        },
    }
    if args.out_json:
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
