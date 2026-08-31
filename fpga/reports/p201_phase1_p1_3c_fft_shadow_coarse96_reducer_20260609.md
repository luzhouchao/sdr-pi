# P201 Phase 1 P1.3c FFT Shadow Coarse96 Reducer

Date: 2026-06-09

## Scope

This is a PC-only isolated RTL milestone for the Phase 1 `fpga_fft_shadow`
coarse PSD path.

It adds an exact 2048-to-96 signed PSD max-hold reducer under:

```text
experiments\phase1_fft_shadow_selftest\rtl\p201_fft_shadow_coarse96_reducer.v
experiments\phase1_fft_shadow_selftest\test\tb_p201_fft_shadow_coarse96_reducer.v
scripts\vivado_ooc_phase1_fft_shadow_coarse96_reducer.tcl
```

The reducer consumes signed PSD bin powers and packs them into 96 coarse bins
using the same exact-count max-hold grouping rule as the P1.2 software
reference:

```text
start = floor(coarse_index * 2048 / 96)
stop  = floor((coarse_index + 1) * 2048 / 96)
```

The RTL maps each incoming bin to that rule with:

```text
coarse_index = floor(((bin_index + 1) * 96 - 1) / 2048)
```

This fixed 2048/96 configuration avoids a general divider and keeps the first
coarse PSD primitive aligned with the preferred Phase 1 ABI.

## Evidence

XSIM:

```text
Command:
& E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source scripts\xsim_phase1_fft_shadow_selftest.tcl

Result:
PHASE1_FFT_SHADOW_XSIM_STATUS=PASS
TB_PASS p201_fft_shadow_selftest_axi_regs
TB_PASS p201_fft_shadow_top4_reducer
TB_PASS p201_fft_shadow_coarse96_reducer
```

OOC synthesis and timing:

```text
Command:
& E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source scripts\vivado_ooc_phase1_fft_shadow_coarse96_reducer.tcl

Result:
PHASE1_FFT_SHADOW_COARSE96_OOC_PROJECT_STATUS=PASS
PHASE1_FFT_SHADOW_COARSE96_OOC_SYNTH_STATUS=PASS
PHASE1_FFT_SHADOW_COARSE96_OOC_TIMING_STATUS=PASS
Clock target: 8.138 ns
Setup WNS: +2.264 ns
Hold WHS: +0.185 ns
```

Utilization:

```text
Slice LUTs:      2138
Slice registers: 3275
Block RAM:       0
DSP:             0
```

Generated stage evidence:

```text
reports\stage_phase1_fft_shadow_selftest\xsim_report.md
reports\stage_phase1_fft_shadow_coarse96_reducer\ooc_report.md
reports\stage_phase1_fft_shadow_coarse96_reducer\ooc_timing_summary.txt
reports\stage_phase1_fft_shadow_coarse96_reducer\ooc_utilization.txt
```

## Design Note

The full 96-entry coarse PSD readback array is timing-clean in isolation, but it
is much heavier than the P1.3/P1.3b scalar primitives. Before live integration,
review whether the runtime path should keep all 96 bins in direct AXI-Lite
registers, expose a smaller runtime subset, or move wider vector readback into
a debug/BRAM window.

## Important Non-Claims

This is not live AD9361 FFT/PSD hardware.

This is not a complete FFT, window, or PSD generator.

This does not generate an IP package, BD integration, bitstream, BOOT.bin, SD
payload, SDR staging, or hardware validation.

This does not modify active `robot_control`, start ROS, start SDR streaming, or
change any runtime publication path.

## Next Safe Step

Use the P1.3b top-4 reducer and P1.3c coarse96 reducer as PC-only evidence when
choosing the first true spectral-method or FFT-backed isolated self-test. Do not
stage to SDR until P1.4 integration, route, Bootgen, payload, and rollback
evidence all pass.
