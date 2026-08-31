# P201 Summary V6 PC Artifacts Report

Generated: 2026-06-08 02:25 Asia/Shanghai

Status: PC-built, timing-clean, Bootgen PASS, not hardware-tested.

## Scope

V6 is a register-only Block Summary ABI and width consolidation candidate. It is not an FFT, PSD, or DMA build.

V6 should be tested after V5. V5 remains the first recommended hardware burn target.

## Artifact Directory

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v6
```

Ready-to-copy SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v6\sd_payload
```

## Vivado Results

```text
IP packaging: PASS
BD validation: PASS
Implementation: write_bitstream Complete!
WNS +0.015 ns
WHS +0.014 ns
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
Slice LUTs       15759 / 53200  29.62%
Slice Registers  23087 / 106400 21.70%
Slice             6879 / 13300  51.72%
```

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
```

SD payload hashes:

```text
e47c012ad5f8f14bc769620f00add18ef75be74bd09dbaaddaa91aaf62ade60b  sd_payload/BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  sd_payload/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  sd_payload/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  sd_payload/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  sd_payload/uramdisk.image.gz
```

## Expected Registers

```text
0x43C00040 SUMMARY_VERSION  0x53554D36
0x43C00060 SNAPSHOT_COUNT   0x00000000
0x43C000EC ABI_VERSION      0x00010000
0x43C000F0 CAPABILITY       0x000000FF
0x43C000F8 MAX_CORR_FRAME   0x0000FFFF
0x43C000FC BUILD_ID         0x56360001
```

## NX Validation

Prepared local-only experiment script:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v6_block_abi.py
```

Run only inside the independent NX experiment directory after copying it there:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
```

Do not modify or start active `robot_control` runtime.

## Risks

- Not hardware-tested.
- Higher DSP/resource pressure than V5.
- The 8-bit AXI register page is full through `0xfc`; future FFT/PSD/DMA should use a separate page/IP.
- Start validation with small frame lengths such as 64, 128, and 256 even though V6 declares `MAX_CORR_FRAME_LEN=65535`.
