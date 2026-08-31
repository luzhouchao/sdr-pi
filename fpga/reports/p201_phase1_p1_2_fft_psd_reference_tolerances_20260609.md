# P201Pro Phase 1.2 FFT/PSD Reference Tolerances

Date: 2026-06-09

## Result

P1.2 offline FFT/PSD reference and tolerance gate PASS on Windows and NX.

This is software/reference evidence only. It does not implement FPGA FFT/PSD
hardware, does not touch active `robot_control`, does not start ROS or SDR
runtime, and does not promote any FPGA version.

## What Changed

- Extended `sdr_fpga_offload_test/reference_compute.py` with:
  - `FftPsdReference`
  - `FftPsdTopPeak`
  - `FftPsdTolerance`
  - exact-count coarse PSD max-hold grouping
  - active-UI-compatible max-hold compression helper
  - top-N PSD peak extraction
  - candidate-vs-reference tolerance checks
- Added `scripts/test_fft_psd_reference.py`.
- Added NX-side evidence log:
  `nx_experiments/sdr_fpga_offload_test/logs/p1_2_fft_psd_reference_tolerances_20260609.json`.

## Current NX Reference Shape

Read-only inspection of the active NX code confirmed the current CPU FFT/PSD
math shape:

```text
I/Q extraction: arr[0::2], arr[1::2]
scale: 1 / 32768
window: np.hanning(nfft)
FFT: np.fft.fftshift(np.fft.fft(x))
PSD: 20 * log10(abs(spec) / coherent_gain + 1e-12)
peak: argmax(psd)
noise floor: median(psd)
prominence: peak - median
```

The active UI spectrum compression uses max-hold groups:

```text
group = int(len(psd) / spectrum_max_bins_per_channel)
compressed = np.maximum.reduceat(psd, starts)
```

With `SDR_NFFT=2048` and `SPECTRUM_MAX_BINS_PER_CHANNEL=96`, the active UI
compressor produces 98 bins because `2048 / 96` truncates to group size 21.

## Phase 1 ABI Reference Choice

For `fpga_fft_shadow`, the reference keeps an exact ABI count:

```text
coarse_bin_count = 96
coarse_bin_step_q16 = (2048 << 16) // 96 = 1398101
coarse_psd_dbfs = proportional exact-count max-hold over 96 bins
```

This keeps the FPGA register page stable at the preferred 96 bins while still
documenting the current NX UI max-hold behavior.

## Tolerances

Default software comparison tolerances:

```text
rssi_dbfs                 1.0 dB
peak_bin                  1 bin
peak_power_dbfs           1.5 dB
noise_floor_dbfs          2.0 dB
peak_prominence_db        2.5 dB
band_power_dbfs           1.5 dB
top_peak_bin              2 bins
top_peak_power_dbfs       2.0 dB
coarse_psd_max_abs_error  3.0 dB
coarse_psd_count          exact
```

These are initial Phase 1 software tolerances. They should be tightened or
split by capture type after real RTL/board shadow evidence exists.

## Test Vector

The test uses a deterministic synthetic multi-tone I/Q buffer:

```text
nfft = 2048
sample_count = 4096
tones = +123 bins, -317 bins, +511 bins, plus a weak +17-bin tone
```

Expected dominant peak:

```text
fftshift peak_index ~= 1024 + 123 = 1147
```

## Evidence

Command on NX:

```text
cd /home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
python3 scripts/test_fft_psd_reference.py --out-json logs/p1_2_fft_psd_reference_tolerances_20260609.json
```

Result:

```text
passed true
coarse_bin_count 96
coarse_bin_step_q16 1398101
peak_index 1147
peak_power_dbfs -7.535655
noise_floor_dbfs -130.127090
peak_prominence_db 122.591435
top_peaks 1147, 707, 1535, 1041
active_ui_2048_max96_group 21
active_ui_2048_max96_bins 98
coarse_96_group 1
coarse_96_bins 96
```

The test also constructs a deliberately bad candidate by moving `peak_bin` by
16 bins and verifies the tolerance gate fails.

## Safety Notes

- No SDR board command was needed for P1.2.
- No ROS, SDR streaming runtime, mapping, RTAB-Map, navigation,
  `robot_controller`, `cmd_vel`, or robot motion process was started.
- No active `robot_control` file was modified.
- No BOOT, SD payload, vendor package, or original SD backup was modified.

## Next Safe Step

Proceed to P1.3: isolated `fpga_fft_shadow` register/self-test implementation
using this reference and tolerance gate. Keep CPU publication and active runtime
untouched.
