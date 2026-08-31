# SUM8 FPGA-Assisted Shadow Backend Progress

Date: 2026-06-08

## Result

PASS as a bypass shadow backend step. SUM8/AGG8 can now produce original-AoA-shaped
primitive estimates from FPGA aggregate registers without modifying the active
`robot_control` chain.

This does not yet replace the live CPU/GPU path. It prepares the replaceable
boundary: AGG8 provides multi-frame power/cross/quality primitives, while NX
keeps CPU/GPU composition, calibration, AoA policy, publication, and fallback.

## New Code

Local and NX-synced files:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\fpga_assisted_metrics.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\compare_sum8_fpga_assisted_metrics.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\read_sum8_aggregate_batch_ssh.py
```

Existing client update:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\sdr_kernel_client.py
```

The client now exposes both:

```text
rx*_legacy_numerator_dbfs  = old numerator / N dB value, kept for compatibility
rx*_corr_mean_dbfs         = corrected numerator / N^2 dBFS, use this for AoA/RSSI style metrics
```

## Performance Review

Decision: GO for bypass shadow-backend integration, NO-GO for direct live
`robot_control` replacement in this step.

Reason:

- AGG8 is a reusable FPGA primitive, not a one-off hard-coded full algorithm.
- Corrected power/cross/quality aggregation is a good FPGA/NX split and can reduce
  NX raw-buffer and repeated Python aggregation load.
- NX still needs flexible CPU/GPU logic for FFT/PSD, calibration, `atan2`, AoA
  policy, publication, and fallback.
- The current network/devmem control path must be batched before any live
  integration, otherwise SSH overhead hides FPGA value.

## Validation Evidence

Shadow backend side-by-side log:

```text
E:\vivado\fpga_p201pro_accel\reports\sum8_fpga_assisted_metrics_corrected_20260608.json
```

Hash:

```text
0883e3c10dfc9c0d7d0c6061145d6190854717d2ba0fc535b4b7cb76b3722268
```

Result:

```text
captures = 5
pass_count = 5
passed = true
modified_robot_control = false
started_ros = false
started_streaming_runtime = false
```

This run emits:

- CPU raw-IQ primitive metrics.
- FPGA SUM8 primitive metrics using corrected mean dBFS.
- `fpga_aoa_estimate_shape` matching the original AoA result shape enough for a
  future backend selector.
- Explicit note that raw-IQ and AGG8 windows are not hardware-synchronized yet.

Batch AGG8 read log:

```text
E:\vivado\fpga_p201pro_accel\reports\sum8_aggregate_batch_ssh_20260608.json
```

Hash:

```text
5b797e2ed38c9543dd3df19b9b0eceddea97ae052674905d1ddcf61bc979d1a0
```

Result:

```text
agg_frames = 16, 64, 256
repeat = 3
captures = 9
pass_count = 9
passed = true
single_ssh_exec_total ~= 0.285 s per aggregate capture
```

The batched read path replaces many per-register SSH/devmem calls with one SSH
exec per aggregate capture. This is the current preferred control path until a
lower-overhead transport is added.

## Interpretation

The FPGA side is ready to act as a shadow primitive provider for the original
algorithm:

```text
FPGA: corrected power/cross/quality multi-frame primitives
NX: backend selection, calibration, AoA policy, FFT/PSD, publication, fallback
```

The remaining gap before live replacement is not V8 hardware validity. It is
runtime integration policy:

- Need feature flag / backend selector.
- Need fallback to current CPU/GPU result when AGG8 is absent, stale, clipped,
  low coherence, or transport fails.
- Need same-window or repeated-environment acceptance criteria before trusting
  FPGA phase/RSSI as the published result.

## Next Step

Create a staged `robot_control` integration patch that is off by default:

```text
parameter: sdr_fpga_backend = off | shadow | assist
off:    current CPU/GPU behavior only
shadow: publish/log CPU/GPU result, compute FPGA result beside it
assist: use FPGA primitive metrics for power/cross/quality when checks pass,
        fall back to CPU/GPU otherwise
```

Do not enable `assist` as default until shadow logs pass the chosen acceptance
criteria.
