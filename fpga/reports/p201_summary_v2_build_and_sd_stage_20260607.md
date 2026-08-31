# P201Pro Summary V2 Build And SD Stage

Generated: 2026-06-07 21:50 Asia/Shanghai

## Scope

This is an experiment-only FPGA BOOT stage for the SDR FPGA offload bypass
validation path. It does not modify the existing NX SDR runtime code and does
not modify the existing `robot_control` launch/runtime chain.

## Summary V2 Register Additions

Tap base remains:

```text
0x43C00000
```

V2 keeps the Summary V1 frame summary registers and changes the version:

```text
0x43C00040 SUMMARY_VERSION  0x53554d32 ("SUM2")
```

V2 adds a same-frame raw IQ snapshot:

```text
0x43C00060 SNAPSHOT_COUNT
0x43C00064 SNAPSHOT_INDEX   write/read 0..63
0x43C00068 SNAPSHOT_DATA    {Q[15:0], I[15:0]}
```

The NX validation script recomputes `sample_count`, `sum_power_raw`,
`peak_power_raw`, `peak_index`, and `rssi_dbfs` from this snapshot and compares
the integer summary fields against FPGA registers from the same frame.

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
WHS: +0.054 ns
Route: fully routed
Routing errors: 0
```

Bitstream:

```text
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream\system_top_with_p201_tap.bit
```

Bitstream SHA256:

```text
926399c34edd0e9a43517be16b361beab3c357d2bf17b427752f273d0511bf5d  system_top_with_p201_tap.bit
```

## Bootgen Result

Experiment folder:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v2
```

BIF:

```text
image : {
  [bootloader] fsbl_from_pzsdr_fw.elf
  system_top_with_p201_summary_v2.bit
  u-boot_from_pzsdr_fw.elf
}
```

Command:

```text
E:\Xilinx\SDK\2019.1\bin\bootgen.bat -arch zynq -image p201_summary_v2_sd.bif -w -o BOOT_p201_summary_v2.bin
```

Result:

```text
bootgen exit code: 0
BOOT_p201_summary_v2.bin size: 4,565,732 bytes
```

Hashes:

```text
5115c0e1872c61fe64b9b7ff1c0b448b5afaea2f3f538776368e815f0f393a24  fsbl_from_pzsdr_fw.elf
926399c34edd0e9a43517be16b361beab3c357d2bf17b427752f273d0511bf5d  system_top_with_p201_summary_v2.bit
69b9b060dd7a3525806e98e6c93e77b2b47795993dc9069279b7beca1a4c943d  u-boot_from_pzsdr_fw.elf
0abd8a02e8798fb56c3ac6d38aa9b1e261e71e9e444a82ccd8d9b37615393a43  BOOT_p201_summary_v2.bin
```

## NX Experiment Directory

Independent NX directory:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
```

Updated files:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/boot_payload/BOOT_p201_summary_v2.bin
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/scripts/capture_summary_v2_snapshot.py
```

The V2 script was placed under `scripts/`. A previous root-level accidental copy
can be ignored; it is outside the active script path.

## SDR SD Stage

The V2 BOOT was copied to SDR `/sd/BOOT.bin` through NX with Paramiko SSH
tunneling and `cat > /sd/BOOT.bin && sync`.

SDR `/sd` hashes after write:

```text
0abd8a02e8798fb56c3ac6d38aa9b1e261e71e9e444a82ccd8d9b37615393a43  /sd/BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  /sd/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  /sd/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  /sd/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  /sd/uramdisk.image.gz
```

## Current Stop Point

Physical SDR power-cycle is required before V2 can be validated. The previous
board investigation showed Linux `reboot` is not equivalent to full power
removal for AD9361/PL boot-health validation.

After power-cycle, verify:

```text
sha256sum /sd/BOOT.bin
devmem 0x43C00040 32
python3 /home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/scripts/capture_summary_v2_snapshot.py
```

Expected:

```text
/sd/BOOT.bin SHA256 = 0abd8a02e8798fb56c3ac6d38aa9b1e261e71e9e444a82ccd8d9b37615393a43
SUMMARY_VERSION = 0x53554D32
snapshot arithmetic comparison = PASS
```
