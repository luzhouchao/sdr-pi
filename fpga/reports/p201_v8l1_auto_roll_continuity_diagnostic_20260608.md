# P201Pro V8L1 Auto-Roll Continuity Diagnostic

Date: 2026-06-08

## Summary

Status: V8L1 remains hardware-validated for AD9361/IIO health, identity
registers, and single auto aggregate capture. A new latest-window benchmark
found that V8L1 does not continuously advance `AGG_SEQUENCE` after the first
auto-roll window.

This is not a V8L1 rollback trigger. It means V8L1 lowers some setup/validation
overhead but does not yet provide the intended continuous "configure once, read
latest aggregate" behavior.

No ROS, SDR streaming runtime, robot_control, cmd_vel, mapping, RTAB-Map, or
robot motion path was started.

## Live Benchmark

Script:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\benchmark_v8l1_auto_roll_batch_ssh.py
```

Result JSON:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\v8l1_auto_roll_batch_ssh_20260608.json
```

Command path:

```text
Windows -> NX SSH -> SDR SSH direct-tcpip -> devmem only
```

Observed result:

```text
V8L1 identity checks: PASS
auto_roll_enabled: PASS
agg_target / agg_frames / agg_samples: PASS
no_overflow: PASS
AGG_SEQUENCE first read: 1
AGG_SEQUENCE later reads: 1
AGG_CONTROL: 0x00000015
pass_count: 1 / 8
```

Interpretation:

```text
0x15 = enable bit0 + auto bit2 + done bit4
```

The hardware latches the first aggregate window, but then remains parked with
`done` visible and `AGG_SEQUENCE` unchanged.

## RTL Root Cause

File:

```text
E:\vivado\fpga_p201pro_accel\experiments\v8_derived_low_nx_load\hdl\p201pro_ad9361_power_tap_axi_regs.v
```

The V8L1 RTL resets accumulators in auto mode after `agg_target_done_next`, but
the frame pipeline still sets `pending_adc` whenever the target window completes:

```verilog
if (!agg_enable_sync_adc || agg_done_adc || agg_target_done_next || agg_bad_frame_adc) begin
    pending_adc <= 1'b1;
end
```

Because sample acceptance requires `!pending_adc`, the next aggregate window
does not start. This matches the board result: `AGG_SEQUENCE` increments once
and then stays at `1`.

## V8L2 Fix Prepared

Prepared RTL candidate:

```text
E:\vivado\fpga_p201pro_accel\experiments\v8_derived_low_nx_load\hdl\p201pro_ad9361_power_tap_axi_regs.v
```

V8L2 changes:

```text
SUMMARY_BUILD_ID = 0x56384C32
QUALITY_BUILD_ID = 0x51384C32
AGG_BUILD_ID     = 0x41384C32
```

Control fix:

```verilog
if (!agg_enable_sync_adc || (!agg_auto_sync_adc && (agg_done_adc || agg_target_done_next || agg_bad_frame_adc))) begin
    pending_adc <= 1'b1;
end
```

Expected behavior:

- Classic/manual V8-style aggregate remains stop-on-done.
- Auto mode continues accepting samples after each target window.
- Bad/overflow pages are latched for visibility, but auto mode continues to the
  next window.
- NX can monitor `AGG_SEQUENCE` and read latest aggregate summaries without
  re-arming every window.

## Next Safe Step

Build V8L2 as a unique artifact. Do not overwrite V8L1 artifacts. Required gate:

```text
IP packaging PASS
BD integration PASS
implementation/bitstream PASS
WNS >= 0
WHS >= 0
route fully routed
routing errors 0
Bootgen PASS
artifact README current
VERSION_ROUTE.md current
```

Only after the artifact gate passes should V8L2 be staged to SDR `/sd`, synced,
and then tested after a physical SDR power-cycle.

Rollback remains:

```text
V8L1 first, V8 second
```
