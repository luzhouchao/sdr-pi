# P201Pro Phase 1 P1.3 FFT Shadow Self-Test Report

Date: 2026-06-09

## Scope

This milestone adds a PC-only isolated RTL self-test for the Phase 1
`fpga_fft_shadow` register ABI. It proves the planned `0x400..0x6fc` AXI-Lite
page shape before any live AD9361 integration.

This report is not a hardware-validation claim.

## Added Sources

```text
experiments/phase1_fft_shadow_selftest/README.md
experiments/phase1_fft_shadow_selftest/rtl/p201_fft_shadow_selftest_axi_regs.v
experiments/phase1_fft_shadow_selftest/test/tb_p201_fft_shadow_selftest_axi_regs.v
scripts/xsim_phase1_fft_shadow_selftest.tcl
scripts/vivado_ooc_phase1_fft_shadow_selftest.tcl
```

## Register Fixture

The fixture is derived from the P1.2 synthetic multi-tone reference and exposes:

```text
magic                0x46465431 ("FFT1")
build_id             0x46505331 ("FPS1")
abi_version          0x00020000
capability           0x00000fff
status               valid only
sample_count         4096
nfft                 2048
sample_rate_hz       2000000
window_id            1 (Hann)
coarse_bin_count     96
coarse_bin_step_q16  1398101
top peaks            1147, 707, 1535, 1041
coarse PSD bins      96 populated, bins 96..127 reserved/read-zero
```

The RTL is a deterministic ABI fixture. It does not compute a live FFT from
AD9361 samples.

## XSIM Gate

```text
Command:
E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source scripts\xsim_phase1_fft_shadow_selftest.tcl

Result:
PASS
```

Evidence:

```text
reports/stage_phase1_fft_shadow_selftest/xsim_report.md
```

The testbench checks identity/status, scalar summary, four top peaks, all 128
coarse PSD read offsets, and that bins above the 96-bin count read zero.

## OOC Gate

```text
Command:
E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source scripts\vivado_ooc_phase1_fft_shadow_selftest.tcl

Result:
Project setup PASS
Synthesis PASS
Run status synth_design Complete!
```

Timing summary:

```text
WNS +6.476 ns
WHS +0.129 ns
All user specified timing constraints are met.
```

Utilization:

```text
Slice LUTs       103
Slice registers   30
Block RAM          0
DSP                0
```

Evidence:

```text
reports/stage_phase1_fft_shadow_selftest/ooc_report.md
reports/stage_phase1_fft_shadow_selftest/ooc_utilization.txt
reports/stage_phase1_fft_shadow_selftest/ooc_timing_summary.txt
reports/stage_phase1_fft_shadow_selftest/ooc_clock.xdc
```

## Warnings

OOC synthesis has ordinary warnings because this self-test page is currently a
read-only fixture: write address/data/strobe ports are accepted for AXI-Lite
handshake but optimized away, and `irq` is tied low. There are no critical
warnings or errors.

## Safety Notes

No IP package, BD integration, bitstream, BOOT.bin, SD payload, SDR staging,
hardware validation, active `robot_control` modification, ROS launch, SDR
streaming runtime, mapping, navigation, `cmd_vel`, or motion-related step was
performed.

## Next Step

The next safe Phase 1 step is to replace the deterministic fixture with an
isolated spectral method or FFT-backed self-test while keeping the same ABI
checks. Board staging still waits for the later AD9361-safe artifact gate and
user power-cycle workflow.
