# P201 Summary V7 PC Artifacts Report

Generated: 2026-06-08 Asia/Shanghai

Status: PC-built, timing-clean, Bootgen PASS, not hardware-tested.

## Scope

V7/SUM7A is a SUM6-compatible register summary with a lightweight quality diagnostics page. It is not an FFT, PSD, DMA, CUDA, or ROS integration build.

V7 should be tested after V5 and V6.

## Artifact Directory

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v7
```

Ready-to-copy SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v7\sd_payload
```

## Vivado Results

```text
IP packaging: PASS
BD validation: PASS
Implementation: write_bitstream Complete!
WNS +0.015 ns
WHS +0.003 ns
route fully routed
routing errors 0
```

Implementation source report:

```text
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream\bitstream_report.md
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream\timing_summary_impl.txt
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream\route_status_impl.txt
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream\utilization_impl.txt
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
```

SD payload hashes:

```text
ca7af9cfa33ddb26a5817b9a0117e550e295f3b1a992cf5236d040dabfe405d1  sd_payload/BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  sd_payload/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  sd_payload/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  sd_payload/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  sd_payload/uramdisk.image.gz
```

## Expected Registers

```text
0x43C00040 SUMMARY_VERSION  0x53554D37
0x43C000EC ABI_VERSION      0x00010001
0x43C000F0 CAPABILITY       0x000001FF
0x43C000FC BUILD_ID         0x56370001
0x43C00100 QUALITY_VERSION  0x51554137
0x43C00138 QUALITY_CAP      0x0000000F
0x43C0013C QUALITY_BUILD_ID 0x51370001
```

## NX Validation

Prepared local-only experiment script:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v7_quality_page.py
```

Run only inside the independent NX experiment directory after copying it there:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
```

Do not modify or start active `robot_control` runtime.

## Risks

- Not hardware-tested.
- Timing is clean but hold margin is thin (`WHS +0.003 ns`).
- Use V5 and V6 before V7 unless explicitly testing the quality page.
- Abs-sum offsets are reserved and read zero in SUM7A.
