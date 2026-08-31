# P201Pro V10S3 Energy Peak Module Plan

Date: 2026-06-09

Scope: PC-only reusable RTL candidate under
`experiments/v10s3_energy_peak`. This is not integrated with AD9361, AXI-Lite,
BOOT, SD payload, ROS, SDR streaming, or active NX runtime.

## Purpose

V10S3 provides a bounded non-FFT reducer for already-computed unsigned energy
bins or scalar power windows. It is meant to sit after a future FFT bin-power
block, a Goertzel-like detector, a bandpower path, or a direct scalar power
window. It does not compute FFT, PSD, I/Q power, averages, division, or square
roots.

## RTL Candidate

Module:

```text
experiments/v10s3_energy_peak/rtl/p201_v10s3_energy_peak_reducer.v
```

The reducer accepts one unsigned value per valid/ready transfer and closes a
window on either `sample_last` or `MAX_SAMPLES`. On close, it atomically updates
registered summary outputs:

```text
summary_sample_count
summary_total_energy
summary_noise_floor
summary_peak_value
summary_peak_index
summary_second_peak_value
summary_second_peak_index
summary_prominence
summary_threshold_count
summary_frame_id
summary_flags
```

`summary_noise_floor` is a minimum-value proxy. `summary_prominence` is
`summary_peak_value - summary_noise_floor`. `summary_threshold_count` increments
for values greater than or equal to `threshold_value`.

## Stream ABI

Inputs:

```text
clk
rst_n
enable
clear_summary
sample_valid
sample_ready
sample_last
sample_value[VALUE_WIDTH-1:0]
sample_index[INDEX_WIDTH-1:0]
threshold_value[VALUE_WIDTH-1:0]
```

Outputs:

```text
summary_flags[31:0]
summary_frame_id[31:0]
summary_sample_count[COUNT_WIDTH-1:0]
summary_total_energy[ACC_WIDTH-1:0]
summary_noise_floor[VALUE_WIDTH-1:0]
summary_peak_value[VALUE_WIDTH-1:0]
summary_peak_index[INDEX_WIDTH-1:0]
summary_second_peak_value[VALUE_WIDTH-1:0]
summary_second_peak_index[INDEX_WIDTH-1:0]
summary_prominence[VALUE_WIDTH-1:0]
summary_threshold_count[COUNT_WIDTH-1:0]
```

`sample_ready` is asserted when `enable` is high and `clear_summary` is low.
There is no output backpressure. Summary outputs hold the most recent complete
window until reset or clear.

`summary_flags` bits:

```text
bit 0: summary_valid
bit 1: frame_active
bit 2: total_energy_overflow_seen
bit 3: auto_closed_on_MAX_SAMPLES_without_sample_last
bit 4: second_peak_valid
bit 8: threshold_counter_supported
```

Other bits are reserved and currently zero.

Tie handling:

```text
Higher value wins. For equal values, lower sample_index wins.
```

## Parameters

Default synthesis-oriented parameters:

```text
VALUE_WIDTH = 32
INDEX_WIDTH = 16
ACC_WIDTH   = 64
COUNT_WIDTH = 16
MAX_SAMPLES = 16
```

`ACC_WIDTH` must be greater than or equal to `VALUE_WIDTH`.
`MAX_SAMPLES` must fit inside `COUNT_WIDTH`.

## Deterministic Testbench

Testbench:

```text
experiments/v10s3_energy_peak/test/tb_p201_v10s3_energy_peak_reducer.v
```

Coverage:

```text
1. Eight-value indexed bin window:
   values = 5, 7, 50, 2, 100, 25, 90, 30
   threshold = 50
   expected total = 309
   expected noise floor = 2
   expected peak = value 100 at index 4
   expected second peak = value 90 at index 6
   expected prominence = 98
   expected threshold count = 3

2. Five-value scalar power window:
   values = 4, 12, 3, 5, 9
   threshold = 9
   expected total = 33
   expected noise floor = 3
   expected peak = value 12 at index 1
   expected second peak = value 9 at index 4
   expected prominence = 9
   expected threshold count = 2
```

## FPGA/NX Split Review

This is the intended split:

```text
FPGA: cheap streaming reductions, min/max/top2, threshold count, stable summary.
NX: threshold selection, normalization, calibration, division/mean, policy,
fallback, logging, and any interpretation of confidence.
```

The helper is reusable because it does not assume FFT length, bin meaning,
radio sample format, AD9361 timing, AXI-Lite addresses, BRAM, DMA, or NX
runtime behavior.

## Risks

This candidate has not been run through Vivado synthesis or timing. Wide
comparators and adders can become timing-sensitive if `VALUE_WIDTH`,
`ACC_WIDTH`, or `MAX_SAMPLES` are increased substantially.

The noise floor is a minimum proxy, not a median, percentile, mean, or calibrated
PSD estimate. The prominence value is therefore a simple proxy and should not be
presented as calibrated spectral prominence.

`threshold_value` is sampled per input value. A future AXI wrapper should latch
the threshold at frame start if software writes can occur while a window is
active.

This is not FFT, not PSD, not hardware-validated, not burnable, and not connected
to live SDR or robot runtime.
