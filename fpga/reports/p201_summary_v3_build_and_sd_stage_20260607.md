# P201Pro Summary V3 Build And SD Stage

Generated: 2026-06-07 22:30 Asia/Shanghai

## Scope

Summary V3 is an experiment-only FPGA BOOT payload for bypass validation of the
next offload primitive. It does not modify the existing NX SDR runtime code and
does not modify the existing `robot_control` launch/runtime chain.

## V2 Baseline

Summary V2 was hardware validated after physical power-cycle. Same-frame
snapshot math matched FPGA summary registers exactly for:

```text
sample_count
sum_power_raw
peak_power_raw
peak_index
```

Detailed report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v2_hardware_validation_20260607.md
```

## Summary V3 Additions

V3 keeps V2 snapshot compatibility:

```text
0x43C00060 SNAPSHOT_COUNT
0x43C00064 SNAPSHOT_INDEX
0x43C00068 SNAPSHOT_DATA     RX0 {Q[15:0], I[15:0]}
```

V3 changes the version:

```text
0x43C00040 SUMMARY_VERSION   0x53554d33 ("SUM3")
```

V3 adds dual-RX same-frame registers:

```text
0x43C0006c SNAPSHOT1_DATA    RX1 {Q1[15:0], I1[15:0]}
0x43C00070 DUAL_SAMPLES
0x43C00074 RX0_POWER_LO
0x43C00078 RX0_POWER_HI
0x43C0007c RX1_POWER_LO
0x43C00080 RX1_POWER_HI
0x43C00084 CROSS_RE_LO       sum(I0*I1 + Q0*Q1)
0x43C00088 CROSS_RE_HI
0x43C0008c CROSS_IM_LO       sum(Q0*I1 - I0*Q1)
0x43C00090 CROSS_IM_HI
0x43C00094 RX1_PEAK_POWER
0x43C00098 RX1_PEAK_INDEX
```

## BD Integration

AD9361 BD pin probe confirmed RX1 pins exist:

```text
/axi_ad9361/adc_data_i1
/axi_ad9361/adc_data_q1
/axi_ad9361/adc_valid_i1
```

V3 tap connections:

```text
adc_i      <- /axi_ad9361/adc_data_i0
adc_q      <- /axi_ad9361/adc_data_q0
adc_i1     <- /axi_ad9361/adc_data_i1
adc_q1     <- /axi_ad9361/adc_data_q1
adc_valid  <- /axi_ad9361/adc_valid_i0
adc_valid1 <- /axi_ad9361/adc_valid_i1
```

BD validation:

```text
validate_bd_design: PASS
AXI-Lite address: 0x43C00000
range: 64K
```

## Vivado Result

Command:

```text
E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source E:\vivado\fpga_p201pro_accel\scripts\vivado_impl_bitstream_integrated_ad9361_tap_project.tcl
```

Result:

```text
validate_bd_design: PASS
synth_design: Complete
write_bitstream: Complete
Timing: all user specified timing constraints are met
WNS: +0.015 ns
WHS: +0.053 ns
Route: fully routed
Routing errors: 0
```

Bitstream:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v3\system_top_with_p201_summary_v3.bit
```

Bitstream SHA256:

```text
2e6484ca8f0132b283beeb831f54d78b8d4be50a1c420c5759f1173e207c5c62
```

## Bootgen Result

Experiment folder:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v3
```

BIF:

```text
image : {
  [bootloader] fsbl_from_pzsdr_fw.elf
  system_top_with_p201_summary_v3.bit
  u-boot_from_pzsdr_fw.elf
}
```

Command:

```text
E:\Xilinx\SDK\2019.1\bin\bootgen.bat -arch zynq -image p201_summary_v3_sd.bif -w -o BOOT_p201_summary_v3.bin
```

Hashes:

```text
5115c0e1872c61fe64b9b7ff1c0b448b5afaea2f3f538776368e815f0f393a24  fsbl_from_pzsdr_fw.elf
2e6484ca8f0132b283beeb831f54d78b8d4be50a1c420c5759f1173e207c5c62  system_top_with_p201_summary_v3.bit
69b9b060dd7a3525806e98e6c93e77b2b47795993dc9069279b7beca1a4c943d  u-boot_from_pzsdr_fw.elf
c6c727bc4ac16a6e21565d5074a18404b01a6c43a160809ab1178224d3bce7f1  BOOT_p201_summary_v3.bin
```

## NX Experiment Directory

Updated independent files:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/boot_payload/BOOT_p201_summary_v3.bin
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/scripts/capture_summary_v3_dual_snapshot.py
```

The V3 script compiles on NX.

## SDR SD Stage

The V3 BOOT was copied to SDR `/sd/BOOT.bin` through NX with Paramiko SSH
tunneling and `cat > /sd/BOOT.bin && sync`.

SDR `/sd` hashes after write:

```text
c6c727bc4ac16a6e21565d5074a18404b01a6c43a160809ab1178224d3bce7f1  /sd/BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  /sd/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  /sd/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  /sd/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  /sd/uramdisk.image.gz
```

## Current Stop Point

Physical SDR power-cycle is required before V3 can be validated. Do not use Linux
`reboot` as final boot-health proof on this board.

After power-cycle, verify:

```text
sha256sum /sd/BOOT.bin
devmem 0x43C00040 32
python3 /home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/scripts/capture_summary_v3_dual_snapshot.py
```

Expected:

```text
/sd/BOOT.bin SHA256 = c6c727bc4ac16a6e21565d5074a18404b01a6c43a160809ab1178224d3bce7f1
SUMMARY_VERSION = 0x53554D33
dual-RX snapshot arithmetic comparison = PASS
```
