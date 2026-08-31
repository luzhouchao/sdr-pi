# P201 Summary V4 PC Artifact Report

Generated: 2026-06-07 23:35 Asia/Shanghai

## Scope

Summary V4 is prepared on the Windows PC only. NX and SDR are powered off, so no
remote staging, SDR `/sd` write, ROS runtime, SDR streaming runtime, mapping,
RTAB-Map, robot controller, `/cmd_vel`, or robot motion path was touched.

This is an experiment-only bypass validation artifact. It is not promoted to the
final SD-ready deliverable until hardware validation passes after a physical
power-cycle.

## V4 RTL Change

HDL:

```text
E:\vivado\fpga_p201pro_accel\hdl\p201pro_ad9361_power_tap_axi_regs.v
```

Summary V4 keeps the V3 dual-RX snapshot and raw summary registers and adds
signed 48-bit I/Q sums for mean-corrected AoA-side comparison:

```text
0x43C00040 SUMMARY_VERSION  0x53554d34 ("SUM4")
0x43C0009c I0_SUM_LO
0x43C000a0 I0_SUM_HI
0x43C000a4 Q0_SUM_LO
0x43C000a8 Q0_SUM_HI
0x43C000ac I1_SUM_LO
0x43C000b0 I1_SUM_HI
0x43C000b4 Q1_SUM_LO
0x43C000b8 Q1_SUM_HI
```

Timing fix applied after the first V4 attempt failed with reset fanout to the
snapshot arrays:

- Kept normal reset for scalar control, status, and summary registers.
- Removed reset clearing of the 64-deep RX0/RX1 snapshot arrays.
- Snapshot entries remain software-valid only after `SNAPSHOT_COUNT > 0`; valid
  entries are overwritten by each captured frame.

## Vivado Results

Commands run locally:

```powershell
& 'E:\Xilinx\Vivado\2019.1\bin\vivado.bat' -mode batch -source 'E:\vivado\fpga_p201pro_accel\scripts\vivado_package_ad9361_power_tap_ip.tcl'
& 'E:\Xilinx\Vivado\2019.1\bin\vivado.bat' -mode batch -source 'E:\vivado\fpga_p201pro_accel\scripts\vivado_integrate_ad9361_power_tap.tcl'
& 'E:\Xilinx\Vivado\2019.1\bin\vivado.bat' -mode batch -source 'E:\vivado\fpga_p201pro_accel\scripts\vivado_impl_bitstream_integrated_ad9361_tap_project.tcl'
```

Results:

```text
IP integrity: PASS
OOC synthesis: synth_design Complete!
BD validation: PASS
Implementation: write_bitstream Complete!
WNS: +0.015 ns
WHS: +0.051 ns
Timing constraints: met
Route status: fully routed
Routing errors: 0
```

V4 bitstream:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v4\system_top_with_p201_summary_v4.bit
```

SHA256:

```text
62f0b3866902ef31df44d8a838f9e8eb0be86ff139bec027afe17617b1930d66  system_top_with_p201_summary_v4.bit
```

## Bootgen Results

Experiment folder:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v4
```

BIF:

```text
image : {
  [bootloader] fsbl_from_pzsdr_fw.elf
  system_top_with_p201_summary_v4.bit
  u-boot_from_pzsdr_fw.elf
}
```

Bootgen command:

```powershell
& 'E:\Xilinx\SDK\2019.1\bin\bootgen.bat' -arch zynq -image p201_summary_v4_sd.bif -w -o BOOT_p201_summary_v4.bin
```

Output:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v4\BOOT_p201_summary_v4.bin
```

SHA256:

```text
fd7c080532ee0668eb462db83208b220bbdbc3ace7a61b23e34f2b6a0699accd  BOOT_p201_summary_v4.bin
```

All local boot experiment hashes:

```text
fd7c080532ee0668eb462db83208b220bbdbc3ace7a61b23e34f2b6a0699accd  BOOT_p201_summary_v4.bin
5115c0e1872c61fe64b9b7ff1c0b448b5afaea2f3f538776368e815f0f393a24  fsbl_from_pzsdr_fw.elf
b684a1fc76d28fbbafa1496dd2800c4384f97d06525b2a7b4c785d55a94278ca  p201_summary_v4_sd.bif
62f0b3866902ef31df44d8a838f9e8eb0be86ff139bec027afe17617b1930d66  system_top_with_p201_summary_v4.bit
69b9b060dd7a3525806e98e6c93e77b2b47795993dc9069279b7beca1a4c943d  u-boot_from_pzsdr_fw.elf
```

## NX Experiment Tool Prepared

Local copy:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v4_mean_corrected.py
```

Script SHA256:

```text
2841d53916f3f9fc933a6a0c9545770571b54a01a37f7ce16bd6d4f0a6bcbd3e  capture_summary_v4_mean_corrected.py
```

Offline check:

```text
python -m py_compile capture_summary_v4_mean_corrected.py: PASS
```

The script reads V4 registers, captures the 64-sample dual-RX snapshot, and checks:

```text
SUM4 version
sample_count / dual_samples
RX0/RX1 raw power
raw cross real/imag
RX0/RX1 peak power/index
I0/Q0/I1/Q1 signed sums
mean-corrected phase
mean-corrected coherence
```

## Tomorrow Minimum Action

When NX and SDR are powered again, copy only the experiment BOOT to the SDR boot
partition as `/sd/BOOT.bin`, sync, then physically power-cycle the SDR.

Do not overwrite:

```text
C:\Users\20642\Desktop\开发\SDR\2r2t
```

Do not start the robot runtime chain during validation.
