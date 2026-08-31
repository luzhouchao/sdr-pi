# P201 Summary V3 Dual-RX Snapshot Baseline

Generated: 2026-06-07 22:30 Asia/Shanghai

## Purpose

V3 is the latest hardware-validated dual-RX debug baseline. It proves same-frame RX0/RX1 snapshot readback and FPGA dual-channel summary math after physical SDR power-cycle.

Historical note: V3 was the known-good fallback behind the later V4/V5 tests.
Use the current rollback order in `VERSION_ROUTE.md` for present work.

## FPGA Logic

V3 keeps V2 RX0 snapshot and adds RX1 snapshot plus dual-RX raw summary:

```text
0x40 SUMMARY_VERSION  0x53554D33 ("SUM3")
0x60 SNAPSHOT_COUNT
0x64 SNAPSHOT_INDEX
0x68 SNAPSHOT_DATA    RX0 {Q[15:0], I[15:0]}
0x6c SNAPSHOT1_DATA   RX1 {Q1[15:0], I1[15:0]}
0x70 DUAL_SAMPLES
0x74/0x78 RX0_POWER
0x7c/0x80 RX1_POWER
0x84/0x88 CROSS_RE
0x8c/0x90 CROSS_IM
0x94 RX1_PEAK_POWER
0x98 RX1_PEAK_INDEX
```

I/Q sums and corrected numerator registers are not available in V3.

## Vivado And Bootgen

```text
IP packaging: PASS
BD validation: PASS
write_bitstream Complete!
WNS: +0.015 ns
WHS: +0.053 ns
route fully routed
routing errors: 0
Bootgen: PASS
```

## Hashes

```text
c6c727bc4ac16a6e21565d5074a18404b01a6c43a160809ab1178224d3bce7f1  BOOT_p201_summary_v3.bin
2e6484ca8f0132b283beeb831f54d78b8d4be50a1c420c5759f1173e207c5c62  system_top_with_p201_summary_v3.bit
```

## Hardware Validation

V3 passed hardware validation after physical SDR power-cycle.

Report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v3_hardware_validation_20260607.md
```

Expected register:

```text
devmem 0x43C00040 32 -> 0x53554D33
```

Validated result:

```text
same-frame dual-RX snapshot comparison: passed
repeat runs: 5/5 passed
```

## NX Script

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v3_dual_snapshot.py
```

## Rollback Role

Use V3 when production-summary versions fail and same-frame raw sample proof is needed.
