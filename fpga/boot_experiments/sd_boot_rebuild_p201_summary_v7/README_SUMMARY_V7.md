# P201Pro Summary V7 Quality Page Candidate

Status: PC-built, timing-clean, Bootgen PASS, not hardware-tested yet.

Test order: use V5 first, then V6, then V7. If V7 fails, fall back to V6 or V5; use V4/V3 for snapshot-capable debug.

## Performance Decision

A short sub-agent review recommended a conservative SUM7A instead of a full quality-statistics build. The first V7 attempt added active abs-sum accumulators and produced a bitstream, but failed timing at `WNS -0.371 ns`; that build was not packaged as burnable.

The handed-off V7/SUM7A keeps the new 12-bit register decode and quality page ABI, but removes active abs-sum computation. Offsets `0x128..0x134` are reserved and read zero. This restored timing while still giving NX reusable low-cost signal-quality primitives.

## FPGA Logic Changes

V7 keeps the SUM6 production summary at `0x00..0xff` and adds a second page at `0x100..0x13c`.

```text
0x40 SUMMARY_VERSION    0x53554D37 ("SUM7")
0xec ABI_VERSION        0x00010001
0xf0 CAPABILITY_BITMAP  0x000001FF, SUM6 bits plus bit8 quality_page
0xfc BUILD_ID           0x56370001

0x100 QUALITY_VERSION   0x51554137 ("QUA7")
0x104 QUALITY_FLAGS
0x108 QUALITY_FRAME
0x10c QUALITY_SAMPLES
0x110 RX0_CLIP_COUNTS   upper16 Q, lower16 I
0x114 RX1_CLIP_COUNTS   upper16 Q, lower16 I
0x118 RX0_ZC_COUNTS     upper16 Q, lower16 I
0x11c RX1_ZC_COUNTS     upper16 Q, lower16 I
0x120 SIGN_SAME_COUNTS  upper16 Q0/Q1, lower16 I0/I1
0x124 QUAD_COUNTS       upper16 RX1 I/Q, lower16 RX0 I/Q
0x128..0x134            reserved abs-sum registers, read 0 in SUM7A
0x138 QUALITY_CAP       0x0000000F
0x13c QUALITY_BUILD_ID  0x51370001
```

Snapshot readback remains disabled:

```text
0x60 SNAPSHOT_COUNT -> 0
0x68 SNAPSHOT_DATA  -> 0
0x6c SNAPSHOT1_DATA -> 0
```

## Vivado Status

```text
IP packaging: PASS
BD validation: PASS
write_bitstream Complete!
WNS +0.015 ns
WHS +0.003 ns
route fully routed
routing errors 0
```

Resource snapshot:

```text
Slice LUTs       16007 / 53200  30.09%
Slice Registers  23668 / 106400 22.24%
DSPs                80 / 220    36.36%
Block RAM Tile       6 / 140     4.29%
```

## Bootgen

BIF:

```text
image : {
  [bootloader] fsbl_from_pzsdr_fw.elf
  system_top_with_p201_summary_v7.bit
  u-boot_from_pzsdr_fw.elf
}
```

Command:

```powershell
& 'E:\Xilinx\SDK\2019.1\bin\bootgen.bat' -arch zynq -image 'p201_summary_v7_sd.bif' -w -o 'BOOT_p201_summary_v7.bin'
```

Bootgen status: PASS.

## Hashes

```text
ca7af9cfa33ddb26a5817b9a0117e550e295f3b1a992cf5236d040dabfe405d1  BOOT_p201_summary_v7.bin
fc13a47c12fa90bc9a1c7617b632a00174ee642447e555cb6693da617a932464  system_top_with_p201_summary_v7.bit
5115c0e1872c61fe64b9b7ff1c0b448b5afaea2f3f538776368e815f0f393a24  fsbl_from_pzsdr_fw.elf
69b9b060dd7a3525806e98e6c93e77b2b47795993dc9069279b7beca1a4c943d  u-boot_from_pzsdr_fw.elf
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  sd_payload/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  sd_payload/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  sd_payload/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  sd_payload/uramdisk.image.gz
```

## Safe SD Copy

Ready-to-copy payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v7\sd_payload
```

Copy only these files to a copied/new SDR SD boot partition:

```text
BOOT.bin
devicetree.dtb
uEnv.txt
uImage
uramdisk.image.gz
```

Do not copy anything into:

```text
C:\Users\20642\Desktop\开发\SDR\2r2t
```

## NX Validation

NX validation must stay inside:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
```

Prepared local-only experiment script:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v7_quality_page.py
```

Minimum register reads after physical SDR power-cycle:

```bash
devmem 0x43C00040 32
devmem 0x43C000EC 32
devmem 0x43C000F0 32
devmem 0x43C000FC 32
devmem 0x43C00100 32
devmem 0x43C00138 32
devmem 0x43C0013C 32
```

Expected:

```text
0x43C00040 -> 0x53554D37
0x43C000EC -> 0x00010001
0x43C000F0 -> 0x000001FF
0x43C000FC -> 0x56370001
0x43C00100 -> 0x51554137
0x43C00138 -> 0x0000000F
0x43C0013C -> 0x51370001
```

## Known Risks

- Hardware validation has not been performed.
- V7 should not replace V5/V6 as the first burn target.
- `WHS +0.003 ns` is timing-clean but thin; keep V7 after V5/V6 in the test order.
- The reserved abs-sum registers intentionally read zero. Restore abs sums only after adding pipeline/shadow stages.
- Do not use V7 to replace active NX SDR compute until side-by-side validation passes.
