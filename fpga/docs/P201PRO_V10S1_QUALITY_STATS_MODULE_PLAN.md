# P201Pro V10S1 Quality Stats Module Plan

Status: PC-only reusable submodule candidate. Not integrated with AD9361, AXI-Lite,
BOOT, SD payload, ROS, SDR streaming, or active NX runtime.

## Purpose

V10S1 adds a bounded non-FFT SDR quality/statistics RTL candidate for later
composition behind a summary register page. The FPGA side computes fixed-shape
per-frame integer reductions. NX remains responsible for division, square root,
atan2, calibration, policy, fallback, logging, and publication.

## Files

```text
experiments/v10s1_quality_stats/rtl/p201_sdr_quality_stats.v
experiments/v10s1_quality_stats/test/tb_p201_sdr_quality_stats.v
```

## Module ABI

Module:

```text
p201_sdr_quality_stats
```

Parameters:

```text
SAMPLE_WIDTH = 16
COUNT_WIDTH  = 32
SUM_WIDTH    = 48
POWER_WIDTH  = 64
MAX_SAMPLES  = 65535
```

Clock/reset/control:

```text
clk             input   single synchronous clock
rst_n           input   active-low reset
enable          input   module enable; low clears active state and counters
clear           input   synchronous clear
frame_start     input   starts a new statistics frame; may coincide with first sample_valid
frame_end       input   closes the current frame and latches stats_valid
```

Stream inputs:

```text
sample_valid    input   one I/Q sample valid for this clock
sample_drop     input   one upstream/drop event to count
sample_i        input   signed SAMPLE_WIDTH I sample
sample_q        input   signed SAMPLE_WIDTH Q sample
```

Status outputs:

```text
frame_active    output  module is inside a frame
frame_done      output  one-cycle pulse when a valid frame ends
stats_valid     output  held high after a completed frame until clear/start
overflow        output  sample_valid exceeded MAX_SAMPLES while active
protocol_error  output  sample outside frame, end outside frame, or nested start
```

Statistic outputs:

```text
sample_count    accepted in-frame samples
sum_i           signed sum of I
sum_q           signed sum of Q
sum_i2          sum of I*I
sum_q2          sum of Q*Q
sum_iq          signed sum of I*Q
abs_peak        maximum max(abs(I), abs(Q))
clip_i_count    I samples equal positive or negative full scale
clip_q_count    Q samples equal positive or negative full scale
sat_i_count     I samples at or beyond the internal saturation threshold
sat_q_count     Q samples at or beyond the internal saturation threshold
valid_count     sample_valid cycles in the frame
drop_count      sample_drop events in the frame
```

## Bounded Performance Review

Decision: GO as an isolated PC-only reusable kernel.

Reasoning:

- The module is a reusable fixed-shape integer reducer, not a rigid SDR
  algorithm.
- There is no FFT, DMA, vector BRAM window, AD9361 live connection, AXI-Lite
  page, BOOT image, or SD payload.
- The hot path is one signed multiply set plus accumulator updates per accepted
  sample. A later integrated candidate should register outputs at the page
  boundary and review DSP/resource use in the target top-level context.
- NX keeps all divide/sqrt/atan2/calibration and confidence policy.
- The deterministic testbench covers normal frame closure, signed sums, power,
  cross product, absolute peak, clipping/saturation counts, drop count, and
  clear/reuse behavior.

## Test

No Vivado run is required by this plan. The intended local simulation command is:

```powershell
& 'E:\Xilinx\Vivado\2019.1\bin\xvlog.bat' experiments/v10s1_quality_stats/rtl/p201_sdr_quality_stats.v experiments/v10s1_quality_stats/test/tb_p201_sdr_quality_stats.v
& 'E:\Xilinx\Vivado\2019.1\bin\xelab.bat' tb_p201_sdr_quality_stats -s tb_p201_sdr_quality_stats
& 'E:\Xilinx\Vivado\2019.1\bin\xsim.bat' tb_p201_sdr_quality_stats -runall
```

Expected terminal marker:

```text
PASS tb_p201_sdr_quality_stats
```

## Risks And Next Step

- `POWER_WIDTH` and `SUM_WIDTH` assume the chosen `MAX_SAMPLES` remains bounded.
  Wider future frames need a width review.
- Saturation threshold is intentionally simple and internal. If NX needs a
  calibrated ADC threshold, expose a register-configured threshold in a later
  wrapper.
- Timing/resource behavior is not claimed until the module is synthesized in the
  real P201Pro top-level context.
- Next safe step is an isolated XSIM/OOC synthesis check. Do not integrate with
  AD9361 or active NX runtime until this kernel has a documented wrapper ABI and
  timing evidence.
