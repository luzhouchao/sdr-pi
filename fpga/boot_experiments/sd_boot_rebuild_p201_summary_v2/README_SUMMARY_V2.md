# P201 Summary V2 Snapshot Debug

Generated: 2026-06-07 21:50 Asia/Shanghai

## Purpose

V2 adds same-frame raw RX0 snapshot readback so NX can recompute FPGA summary fields from identical samples. It is a debug version and is superseded by V3.

## FPGA Logic

V2 keeps V1 summary registers and changes the version:

```text
0x40 SUMMARY_VERSION  0x53554D32 ("SUM2")
```

V2 adds RX0 snapshot readback:

```text
0x60 SNAPSHOT_COUNT
0x64 SNAPSHOT_INDEX
0x68 SNAPSHOT_DATA  {Q[15:0], I[15:0]}
```

Dual-RX and corrected numerator registers are not available in V2.

## Vivado And Bootgen

```text
IP packaging: PASS
BD validation: PASS
write_bitstream Complete!
WNS: +0.015 ns
WHS: +0.054 ns
route fully routed
routing errors: 0
Bootgen: PASS
```

## Hashes

```text
0abd8a02e8798fb56c3ac6d38aa9b1e261e71e9e444a82ccd8d9b37615393a43  BOOT_p201_summary_v2.bin
926399c34edd0e9a43517be16b361beab3c357d2bf17b427752f273d0511bf5d  system_top_with_p201_summary_v2.bit
```

## Hardware Validation

V2 was used during bring-up and was superseded by V3.

Report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v2_hardware_validation_20260607.md
```

Expected register:

```text
devmem 0x43C00040 32 -> 0x53554D32
```

## NX Script

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v2_snapshot.py
```

## Rollback Role

Use V2 only for historical RX0 snapshot comparison. Prefer V3 for dual-RX snapshot fallback.
