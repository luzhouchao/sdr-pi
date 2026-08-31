# P201 Summary V4 Mean-Corrected Debug

Generated: 2026-06-07 23:30 Asia/Shanghai

## Purpose

V4 is a historical debug fallback for the V5 production-summary path. It keeps
same-frame raw snapshot readback and adds signed I/Q sums so NX can compare
mean-corrected AoA math while still seeing the exact raw samples used by FPGA.

Use V4 if V5 fails to boot, fails `SUM5` register validation, or needs snapshot-level debugging.

## FPGA Logic

V4 keeps V3 registers and changes version:

```text
0x40 SUMMARY_VERSION  0x53554D34 ("SUM4")
```

V4 keeps dual-RX snapshot/debug:

```text
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

V4 adds signed 48-bit I/Q sums:

```text
0x9c/0xa0 I0_SUM
0xa4/0xa8 Q0_SUM
0xac/0xb0 I1_SUM
0xb4/0xb8 Q1_SUM
```

Corrected numerator registers are not available in V4; NX computes them from raw summary and I/Q sums.

## Vivado And Bootgen

```text
IP packaging: PASS
BD validation: PASS
write_bitstream Complete!
WNS: +0.015 ns
WHS: +0.051 ns
route fully routed
routing errors: 0
Bootgen: PASS
```

## Hashes

```text
fd7c080532ee0668eb462db83208b220bbdbc3ace7a61b23e34f2b6a0699accd  BOOT_p201_summary_v4.bin
62f0b3866902ef31df44d8a838f9e8eb0be86ff139bec027afe17617b1930d66  system_top_with_p201_summary_v4.bit
```

## Hardware Validation

V4 is PC-built and timing-clean but not hardware-tested yet.

Expected register after physical SDR power-cycle:

```text
devmem 0x43C00040 32 -> 0x53554D34
```

## NX Script

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v4_mean_corrected.py
```

## SD Copy Rule

Copy only to a copied/new SDR SD card. Do not modify the original SD backup.

If manually copying, rename this file to `BOOT.bin` on the SD boot partition:

```text
BOOT_p201_summary_v4.bin
```

Keep companion boot files from the known-good SD-ready deliverable unless a later report says otherwise:

```text
devicetree.dtb
uEnv.txt
uImage
uramdisk.image.gz
```

## Rollback Role

Use V4 as the snapshot-capable fallback after V5. If V4 fails, fall back to hardware-validated V3.
