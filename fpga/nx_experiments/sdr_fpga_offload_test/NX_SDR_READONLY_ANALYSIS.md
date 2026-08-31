# NX SDR Read-Only Analysis

Date: 2026-06-07

Repository inspected read-only:

```text
/home/wheeltec/ros2_ws/src/robot_control
```

No existing SDR runtime, ROS launch, mapping, robot controller, or motion path was
started during this analysis.

## Existing Data Path

### IIO Driver

File: `robot_control/sdr_iio_driver.py`

The driver creates an IIO context from `SDR_URI`, finds `ad9361-phy`, locates the
RX device, configures LO/sample-rate/bandwidth, enables RX voltage channels, and
creates an IIO buffer.

Input:

- `iio.Context("ip:192.168.1.10")`
- RX device, normally `cf-ad9361-lpc`
- enabled voltage input channels
- int16 IIO buffer

Output:

- `read_raw_i16()`: raw int16 interleaved sample vector
- `read_spectrum_snapshot()`: RSSI, PSD, peak power/frequency
- `analyze_spectrum_batch()`: batch spectrum summaries

Key math:

- IQ extraction: `arr[0::2]`, `arr[1::2]`
- scale: `1 / 32768`
- RSSI: `10 * log10(mean(I^2 + Q^2) + 1e-12)`
- window: `np.hanning(nfft)`
- FFT: `np.fft.fftshift(np.fft.fft(x))`
- PSD: `20 * log10(abs(spec) / coherent_gain + 1e-12)`
- peak: `argmax(psd)`

CUDA path:

- `robot_control/sdr_cuda_fft_backend.py`
- `robot_control/sdr_cuda_fft.cu`

The CUDA backend offloads windowing, cuFFT, shifted PSD, and optionally RSSI, but
the raw samples still move to NX.

### Channel Scan

File: `robot_control/sdr_band_scanner.py`

The scanner tunes to each scan point, sleeps for settle time, captures multiple
raw buffers, runs spectrum analysis, and aggregates:

- mean RSSI
- RSSI standard deviation
- peak RSSI
- mean PSD
- PSD median noise floor
- PSD max peak
- peak prominence

### Channel Monitor

File: `robot_control/sdr_channel_monitor.py`

This ROS node wraps the scanner and publishes JSON payloads on SDR topics. It also
compresses PSD bins for UI payloads.

This experiment does not start this node.

### Dual-RX AoA

Files:

- `robot_control/sdr_dual_aoa_core.py`
- `robot_control/sdr_aoa_backend.py`
- `robot_control/sdr_dual_aoa_localizer.py`

Input:

- Four interleaved lanes mapped as `[I0, Q0, I1, Q1]`
- sample rate
- center frequency
- antenna baseline
- phase calibration

Key math:

- normalize lanes to complex RX0/RX1
- subtract per-channel mean
- power per RX
- cross product and coherence
- Hanning-windowed FFT of RX0/RX1
- peak on RX0 power
- summed cross spectrum around peak bins
- corrected phase to AoA using wavelength and baseline

Outputs:

- RSSI0/RSSI1
- coherence
- phase
- AoA
- peak frequency/power
- ambiguity/clipping flags

## Bottleneck Candidates

Highest-value FPGA offload candidates:

1. RSSI/power reduction per frame.
2. peak power and peak index/frequency.
3. optional noise-floor/peak-prominence approximations.
4. dual-RX cross-power and relative phase summaries.
5. sample-valid/count diagnostics for each frame.

The current FPGA tap already proves clock/valid/accept visibility. The next
hardware step should expose frame-level summary registers so NX can avoid pulling
full raw buffers for every scan result.

## Do-Not-Replace Gate

Before any existing NX path changes, side-by-side validation should pass on the
same capture window:

- FPGA `sample_count` matches expected frame size.
- FPGA RSSI/power agrees with NX reference within fixed-point tolerance.
- FPGA peak index agrees exactly or within one bin.
- FPGA peak power agrees within tolerance after matching normalization.
- For AoA, FPGA cross phase/coherence agrees within tolerance.
