# P201Pro V10S2 Frame Window Module Plan

Status: PC-only reusable submodule candidate. Not integrated with AD9361, AXI-Lite,
Vivado packaging, BOOT, SD payload, NX runtime, ROS, mapping, RTAB-Map,
robot_controller, cmd_vel, or robot motion.

## Scope

V10S2 adds an isolated non-FFT SDR frame/window preparation primitive under:

```text
experiments/v10s2_frame_window
```

The candidate prepares an already-clocked sample stream for later SDR kernels by
combining:

- configurable decimation-by-N sample gating,
- rectangular or fixed 8-point Hann-like window selection,
- signed I/Q coefficient multiply,
- frame sample index,
- frame counter,
- valid/ready style output,
- last_out marking,
- raw, accepted, dropped, and overflow counters.

This is intentionally generic and independent from live AD9361 integration. It
does not define a memory map, DMA path, FFT path, PSD path, or runtime ABI.

## RTL Files

```text
experiments/v10s2_frame_window/rtl/p201_v10s2_frame_window.v
experiments/v10s2_frame_window/rtl/p201_v10s2_hann8_coeff.v
```

## Test Files

```text
experiments/v10s2_frame_window/test/tb_p201_v10s2_frame_window.v
```

The testbench is deterministic and checks:

- decimation-by-2 rectangular output for one 8-sample frame,
- decimation-by-1 Hann-like output for one 8-sample frame,
- last_out behavior on frame boundaries,
- frame_id increment after completed frames,
- raw_sample_count, accepted_count, dropped_count, and overflow_count,
- output backpressure drop/overflow accounting.

## Signal Contract

Clock and control:

```text
clk
rst_n
enable
clear
```

Configuration:

```text
decim_factor  : decimation interval; 0 is treated as 1
window_mode   : 0 rectangular pass-through, 1 fixed Hann-like coefficients
```

Input stream:

```text
sample_valid
sample_ready
sample_i
sample_q
```

Output stream:

```text
out_valid
out_ready
last_out
out_i
out_q
frame_index
frame_id
```

Counters and status:

```text
raw_sample_count
accepted_count
dropped_count
overflow_count
status_flags
```

`sample_ready` deasserts when the output register is occupied and downstream is
not ready. A sample presented while `sample_ready` is low increments
`dropped_count` and `overflow_count`. This candidate does not include an input
FIFO.

## Window Format

The Hann-like ROM is fixed for `FRAME_LEN=8` and uses unsigned Q1.15
coefficients:

```text
0, 6170, 20057, 31229, 31229, 20057, 6170, 0
```

The multiply truncates the Q1.15 product back to signed 16-bit sample width.
This is suitable as a small bounded module candidate, not as a final flexible
window-coefficient IP.

## Performance Review

FPGA/NX split: GO for a reusable primitive. FPGA handles cheap sample gating,
fixed coefficient multiply, frame control, and counters. NX or a future control
page should own policy, dynamic window selection, calibration, and runtime
fallback.

Hot-path cost: bounded. The block contains one output register, simple
decimation control, and two signed sample multiplies when Hann mode is enabled.
There is no FFT, BRAM vector readback, DMA, AXI-Lite page, or AD9361 fanout.

Debug isolation: the candidate lives only under `experiments/v10s2_frame_window`
and has no active hardware route.

## Known Risks

- `FRAME_LEN` is intended to remain 8 for this candidate. The coefficient ROM
  and frame index width are not a general Hann generator.
- There is no input FIFO. Backpressure drops samples by design and records the
  loss in counters.
- Coefficient multiply is truncating, not rounded or saturated.
- No Vivado synthesis, implementation, timing, packaging, Bootgen, SD staging,
  or hardware validation was requested or performed.
