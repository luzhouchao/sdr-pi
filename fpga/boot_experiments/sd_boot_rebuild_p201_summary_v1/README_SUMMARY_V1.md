# P201 Summary V1 First Frame Summary

Generated: 2026-06-07 17:50 Asia/Shanghai

## Purpose

V1 is the first versioned FPGA summary experiment. It proves the custom tap can expose a deterministic frame-level summary through AXI-Lite without changing NX runtime code or the `robot_control` launch chain.

Use V1 only as a minimal fallback baseline.

## FPGA Logic

V1 adds summary mirror registers for one RX channel:

```text
0x40 SUMMARY_VERSION  0x53554D31 ("SUM1")
0x44 SUMMARY_FLAGS
0x48 FRAME_COUNTER
0x4c SAMPLE_COUNT
0x50/0x54 SUM_POWER
0x58 PEAK_POWER
0x5c PEAK_INDEX
```

Snapshot and dual-RX registers are not available in V1.

## Vivado And Bootgen

```text
IP packaging: PASS
BD validation: PASS
write_bitstream Complete!
WNS: +0.015 ns
WHS: +0.059 ns
route fully routed
routing errors: 0
Bootgen: PASS
```

## Hashes

```text
5f550533c3441b309e62488bd5d3ffeaafec222825305a90bb9973fa4e614b6e  BOOT_p201_summary_v1.bin
f51c8d88cd59de7ab0ef48ab7e627ef52945989cfc919e4aa7cac4278ee01f6a  system_top_with_p201_summary_v1.bit
```

## Hardware Validation

V1 was hardware-validated after physical SDR power-cycle.

Report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v1_hardware_validation_20260607.md
```

Expected register:

```text
devmem 0x43C00040 32 -> 0x53554D31
```

## NX Script

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v1_frame.py
```

## Rollback Role

Use V1 only if later dual-RX versions need to be bypassed for basic tap-health debugging.
