# P201 Phase 1 P1.3b FFT Shadow Top-4 Reducer

Date: 2026-06-09

## Scope

This is a PC-only isolated RTL milestone for the Phase 1 `fpga_fft_shadow`
post-PSD summary path.

It adds a signed top-4 PSD peak reducer with guard-bin suppression under:

```text
experiments\phase1_fft_shadow_selftest\rtl\p201_fft_shadow_top4_reducer.v
experiments\phase1_fft_shadow_selftest\test\tb_p201_fft_shadow_top4_reducer.v
scripts\vivado_ooc_phase1_fft_shadow_top4_reducer.tcl
```

The reducer consumes signed PSD bin powers and returns sorted top-4
bin/power pairs. Candidates within `GUARD_BINS` of an existing selected peak
are suppressed unless the new candidate is stronger, in which case it replaces
the older guarded entry and the list is re-sorted.

The timing-clean implementation is a small ready/valid multi-cycle state
machine. This is intentional for the first isolated primitive: it avoids a deep
one-cycle guard/replace/sort path and keeps the primitive easy to time-review.

## Evidence

XSIM:

```text
Command:
& E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source scripts\xsim_phase1_fft_shadow_selftest.tcl

Result:
PHASE1_FFT_SHADOW_XSIM_STATUS=PASS
TB_PASS p201_fft_shadow_selftest_axi_regs
TB_PASS p201_fft_shadow_top4_reducer
```

OOC synthesis and timing:

```text
Command:
& E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source scripts\vivado_ooc_phase1_fft_shadow_top4_reducer.tcl

Result:
PHASE1_FFT_SHADOW_TOP4_OOC_PROJECT_STATUS=PASS
PHASE1_FFT_SHADOW_TOP4_OOC_SYNTH_STATUS=PASS
PHASE1_FFT_SHADOW_TOP4_OOC_TIMING_STATUS=PASS
Clock target: 8.138 ns
Setup WNS: +1.102 ns
Hold WHS: +0.129 ns
```

Utilization:

```text
Slice LUTs:      340
Slice registers: 509
Block RAM:       0
DSP:             0
```

Generated stage evidence:

```text
reports\stage_phase1_fft_shadow_selftest\xsim_report.md
reports\stage_phase1_fft_shadow_top4_reducer\ooc_report.md
reports\stage_phase1_fft_shadow_top4_reducer\ooc_timing_summary.txt
reports\stage_phase1_fft_shadow_top4_reducer\ooc_utilization.txt
```

## Important Non-Claims

This is not live AD9361 FFT/PSD hardware.

This is not a complete FFT, window, PSD, or coarse PSD generator.

This does not generate an IP package, BD integration, bitstream, BOOT.bin, SD
payload, SDR staging, or hardware validation.

This does not modify active `robot_control`, start ROS, start SDR streaming, or
change any runtime publication path.

## Next Safe Step

Keep the P1.3 ABI fixture and top-4 reducer as PC-only gates. The next isolated
RTL step can add a coarse PSD reducer/packer or a true spectral-method fixture
that feeds the same `0x400..0x6fc` ABI without touching live AD9361 integration.
