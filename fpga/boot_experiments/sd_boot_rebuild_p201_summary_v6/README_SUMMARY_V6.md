# P201Pro Summary V6 Block ABI Candidate

Status: PC-built, timing-clean, Bootgen PASS, not hardware-tested yet.

Test order: use V5 first. If V5 hardware validation passes and you want the wider ABI candidate, test V6 next. If V6 fails, fall back to V4 for snapshot-capable debug, then V3 for the known hardware-validated dual-RX baseline.

## Performance Decision

A short sub-agent performance review concluded that V6 is a reasonable large step only because it stays register-only. FPGA still computes fixed-shape SDR reductions and corrected numerator primitives; NX still performs division, sqrt, atan2, calibration, aggregation, CPU/GPU selection, and frontend/ROS publication after side-by-side validation.

FFT/window/PSD remains intentionally out of V6. That needs buffering, scale/window management, FFT IP or a custom pipeline, DMA or BRAM readout, and new validation vectors. V6 is therefore an ABI/width consolidation version, not an FFT version.

## FPGA Logic Changes

V6 keeps the V5 production no-snapshot summary and adds a tail metadata block:

```text
0x40 SUMMARY_VERSION     0x53554D36 ("SUM6")
0x44 SUMMARY_FLAGS       bit0 enable
                         bit1 result_valid/pending
                         bit2 busy/pending
                         bit3 frame_len_limited
                         bit4 arithmetic_overflow
                         bit5 corrected_valid
                         bit6 snapshot_disabled
0x48 RESULT_SEQUENCE     frame counter
0xec ABI_VERSION         0x00010000, major 1 minor 0
0xf0 CAPABILITY_BITMAP   bit0 dual_rx
                         bit1 raw_power
                         bit2 peaks
                         bit3 cross
                         bit4 iq_sums
                         bit5 corrected_numerators
                         bit6 snapshot_disabled
                         bit7 wide_corrected_path
0xf4 LIMIT_FLAGS         bit0 frame_len_limited, currently 0
                         bit1 arithmetic_overflow
                         bit2 corrected_valid
                         bit3 snapshot_disabled
0xf8 MAX_CORR_FRAME_LEN  65535
0xfc BUILD_ID            0x56360001
```

Snapshot readback remains disabled:

```text
0x60 SNAPSHOT_COUNT -> 0
0x68 SNAPSHOT_DATA  -> 0
0x6c SNAPSHOT1_DATA -> 0
```

Corrected numerator post-frame I/Q sum products are widened from the V5 narrow post path. V6 exposes `corrected_valid` and `arithmetic_overflow` so NX can reject a frame if the widened calculation was outside the supported bound.

## Vivado Status

```text
IP packaging: PASS
BD validation: PASS
write_bitstream Complete!
WNS +0.015 ns
WHS +0.014 ns
route fully routed
routing errors 0
```

Resource note:

```text
Slice LUTs       15759 / 53200  29.62%
Slice Registers  23087 / 106400 21.70%
Slice             6879 / 13300  51.72%
```

The widened corrected path increases DSP/resource pressure compared with V5. This is acceptable for a PC-built candidate, but V5 remains the first hardware test target.

## Bootgen

BIF:

```text
image : {
  [bootloader] fsbl_from_pzsdr_fw.elf
  system_top_with_p201_summary_v6.bit
  u-boot_from_pzsdr_fw.elf
}
```

Command:

```powershell
& 'E:\Xilinx\SDK\2019.1\bin\bootgen.bat' -arch zynq -image 'p201_summary_v6_sd.bif' -w -o 'BOOT_p201_summary_v6.bin'
```

Bootgen status: PASS.

## Hashes

```text
e47c012ad5f8f14bc769620f00add18ef75be74bd09dbaaddaa91aaf62ade60b  BOOT_p201_summary_v6.bin
b56295ea8ae80ea5b9eca8731b596171da48e31310fbb7f1d382e73d7f0e6fb6  system_top_with_p201_summary_v6.bit
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
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v6\sd_payload
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

Minimum register reads after physical SDR power-cycle:

```bash
devmem 0x43C00040 32
devmem 0x43C00044 32
devmem 0x43C00048 32
devmem 0x43C00060 32
devmem 0x43C000EC 32
devmem 0x43C000F0 32
devmem 0x43C000F4 32
devmem 0x43C000F8 32
devmem 0x43C000FC 32
```

Expected:

```text
0x43C00040 -> 0x53554D36
0x43C00060 -> 0x00000000
0x43C000EC -> 0x00010000
0x43C000F0 -> 0x000000FF
0x43C000F8 -> 0x0000FFFF
0x43C000FC -> 0x56360001
```

The existing V5 production validation script can be used as a base because all V5 offsets are preserved. It should additionally check ABI/capability/limit/build registers before treating V6 as passed.

## Known Risks

- Hardware validation has not been performed.
- V6 should not replace V5 as the first burn target.
- The widened corrected path has higher DSP/resource pressure than V5.
- `MAX_CORR_FRAME_LEN=65535` is a declared HDL capability, but real algorithm use should still start with small frame lengths such as 64, 128, and 256 until hardware-side numeric checks pass.
- The 8-bit AXI register page is now full through `0xfc`; FFT/PSD/DMA should use a new page/IP rather than extending this page further.
