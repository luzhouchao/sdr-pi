# P201 Phase 1 P1.3d FFT Shadow FFT4 Smoke Core

Generated: 2026-06-09 17:36 Asia/Shanghai

## Scope

P1.3d adds a PC-only 4-point complex FFT smoke core under
`experiments/phase1_fft_shadow_selftest`.

The purpose is narrow:

- prove a real fixed butterfly FFT datapath on deterministic IQ samples
- compute per-bin power, total power, and the peak bin
- keep the same local XSIM/OOC gate style used by P1.3/P1.3b/P1.3c
- expose timing/resource pressure before any live AD9361 or 2048-point work

This is not a 2048-point FFT, not a Hann/window/PSD implementation, not a live
AD9361 path, not a bitstream, not a BOOT.bin/SD payload, not board-staged, and
not hardware validated.

## Added Files

```text
experiments/phase1_fft_shadow_selftest/rtl/p201_fft_shadow_fft4_smoke_core.v
experiments/phase1_fft_shadow_selftest/test/tb_p201_fft_shadow_fft4_smoke_core.v
scripts/vivado_ooc_phase1_fft_shadow_fft4_smoke_core.tcl
```

The existing XSIM gate was extended:

```text
scripts/xsim_phase1_fft_shadow_selftest.tcl
```

## Functional Gate

Command:

```powershell
& E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source scripts\xsim_phase1_fft_shadow_selftest.tcl
```

Result:

```text
PASS
```

The FFT4 smoke test drives a bin-1 complex tone:

```text
[1000 + j0, 0 + j1000, -1000 + j0, 0 - j1000]
```

Expected result:

```text
peak_bin    = 1
peak_power  = 16000000
total_power = 16000000
bin0/bin2/bin3 power = 0
```

The XSIM report is:

```text
reports/stage_phase1_fft_shadow_selftest/xsim_report.md
reports/stage_phase1_fft_shadow_selftest/xsim_fft4_smoke.log
```

## OOC Timing Gate

Command:

```powershell
& E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source scripts\vivado_ooc_phase1_fft_shadow_fft4_smoke_core.tcl
```

Final result:

```text
PASS
Clock target: 8.138 ns
Setup WNS: +1.424 ns
Hold WHS:  +0.132 ns
```

OOC reports:

```text
reports/stage_phase1_fft_shadow_fft4_smoke_core/ooc_report.md
reports/stage_phase1_fft_shadow_fft4_smoke_core/ooc_timing_summary.txt
reports/stage_phase1_fft_shadow_fft4_smoke_core/ooc_utilization.txt
```

## Resource Summary

Synthesized OOC on `xc7z020clg400-2`:

```text
Slice LUTs:      1299
Slice Registers: 856
Block RAM Tile:  0
DSPs:            8
```

The 8 DSP48E1 instances come from four bins of I/Q squaring. This is acceptable
for the smoke core evidence, but it is not a 2048-point resource forecast.

## Timing Note

The first one-stage power implementation functionally passed XSIM but failed OOC
setup timing:

```text
Setup WNS: -2.993 ns
Hold WHS:  +0.132 ns
```

The committed RTL splits power calculation into multiplier, square-sum, and
peak-summary stages. This preserves the external smoke-core interface while
making the OOC timing gate pass.

## Route Impact

P1.3d is evidence that the Phase 1 FFT shadow path has crossed from register
fixtures and post-PSD reducers into a minimal true FFT datapath smoke test.

It still does not justify board staging. The next safe step is P1.4 integration
review: decide how the FFT/window/PSD generator, top-4 reducer, and coarse96
reducer should be composed into a timing-clean isolated candidate before any
IP/BD/bitstream/Bootgen/SD work.
