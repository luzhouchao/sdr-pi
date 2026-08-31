# SUM8 Load Reduction Live Board Test

Date: 2026-06-09

## Scope

This was a safe live-board test from the independent NX experiment directory
only. It did not modify active `robot_control`, did not apply any patch, and did
not start ROS, SDR streaming runtime, mapping, navigation, `cmd_vel`, or robot
motion.

## Board Identity And Health

Phase0 PASS:

```text
BASE_SUMMARY       0x53554D38
BASE_BUILD         0x56384430
BASE_QUALITY       0x51554138
BASE_QUALITY_BUILD 0x51384430
BASE_AGG           0x41474738
BASE_AGG_BUILD     0x41384430
V10S0_MAGIC        0x53305430
V10S0_DONE         0x0000000F
V10S0_BUILD        0x56313053
IIO health         ad9361-phy and cf-ad9361-lpc present
```

Evidence:

```text
nx_experiments/sdr_fpga_offload_test/logs/load_reduction_phase0_identity_iio_20260609.json
```

## Live Timing Results

All live board probes PASS.

```text
Passive AGG8 read:
  captures: 12 / 12 PASS
  agg_frames: 16, 64, 256, 1024
  median single SSH exec total: 0.286550 s

Shadow compare, agg_frames=64:
  captures: 5 / 5 PASS
  median raw IIO capture:       0.029269 s
  median CPU primitive compute: 0.000950 s
  median FPGA aggregate read:   0.853403 s
  median iteration total:       0.884077 s

Shadow compare, agg_frames=256:
  captures: 3 / 3 PASS
  median raw IIO capture:       0.030619 s
  median CPU primitive compute: 0.001982 s
  median FPGA aggregate read:   0.845762 s
  median iteration total:       0.877964 s

Primitive-assist probe, allow clipped AoA:
  captures: 10 / 10 PASS
  FPGA read OK: 10 / 10
  selected FPGA: 10 / 10
  fallback: 0 / 10
  median FPGA read elapsed: 0.806739 s
  median iteration total:   0.835987 s
```

Evidence:

```text
nx_experiments/sdr_fpga_offload_test/logs/load_reduction_sum8_passive_20260609.json
nx_experiments/sdr_fpga_offload_test/logs/load_reduction_shadow64_20260609.json
nx_experiments/sdr_fpga_offload_test/logs/load_reduction_shadow256_20260609.json
nx_experiments/sdr_fpga_offload_test/logs/load_reduction_feature_assist_primitive_20260609.json
```

## Burden Reduction

For `frame_len=64`, `agg_frames=64`, one AGG8 result covers 4096 dual-RX
samples.

```text
Raw-IQ payload model:
  CPU raw dual-RX payload: 32768 bytes
  AGG8 MMIO summary words: 156 bytes
  reduction: 210.05x, 99.52%

Per-frame register-command model:
  per-frame summary commands: 2432 devmem commands
  one AGG8 window:            46 devmem commands
  reduction: 52.87x, 98.11%

Per-frame SSH exec model:
  one batched exec per frame: 64 execs
  one AGG8 window:            1 exec
  reduction: 64x, 98.44%
```

For `agg_frames=256`, the model improves to:

```text
payload reduction:        840.20x, 99.88%
devmem command reduction: 211.48x, 99.53%
batched exec reduction:   256x, 99.61%
```

## Total-Time Result

The current validation transport is still Python + SSH + devmem. With that
transport, total wall time is not reduced yet:

```text
agg_frames=64:
  CPU raw-IIO + CPU primitive median: 0.030219 s
  current FPGA shadow iteration:      0.884077 s
  result: no total-time reduction; about 29.3x slower in this validation path

agg_frames=256:
  CPU raw-IIO + CPU primitive median: 0.032601 s
  current FPGA shadow iteration:      0.877964 s
  result: no total-time reduction; about 26.9x slower in this validation path
```

This does not invalidate the offload. It means the computation/data movement
burden has been moved to FPGA, but the remaining register transport is not yet a
runtime transport.

The existing transport optimization evidence still shows batched SSH read is
better than per-devmem Paramiko reads:

```text
old per-devmem median:     0.837222 s
batched SSH median:        0.286887 s
transport reduction:       65.73%
transport speedup:         2.92x
```

## Conclusion

Current state:

```text
primitive calculation burden reduction: strong
raw payload / polling burden reduction: strong
current total-time reduction: none, because SSH/devmem dominates
runtime-load reduction: not claimed yet
```

The next performance step is not more algorithm scope. It is replacing the
validation transport with a local non-blocking register path, such as mmap/UIO,
inside a shadow-only active package test. Until then, the FPGA path is evidence
of computation offload, not evidence of lower end-to-end runtime latency.
