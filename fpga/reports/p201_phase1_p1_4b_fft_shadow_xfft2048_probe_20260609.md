# P201 Phase 1 P1.4b FFT Shadow XFFT2048 Probe

Generated: 2026-06-09 19:00 Asia/Shanghai

## Scope

P1.4b adds a PC-only Vivado 2019.1 probe for the missing 2048-point FFT
primitive in the low-resolution `fpga_fft_shadow` A lane.

The probe creates an isolated Xilinx Fast Fourier Transform IP instance and
runs the IP's own out-of-context synthesis/timing path on:

```text
Part: xc7z020clg400-2
IP: xilinx.com:ip:xfft:9.1 (Rev. 2), included license
Module: p201_phase1_xfft2048_probe
Transform length: 2048
Data format: fixed_point
Input width: 16
Phase factor width: 16
Scaling: scaled
Rounding: convergent_rounding
Implementation: pipelined_streaming_io
Runtime-configurable transform length: false
Clock: aclk 122.88 MHz / 8.138 ns
```

This is not a live AD9361 path, not a Hann/window implementation, not a PSD
generator, not top-4 or coarse96 composition, not a bitstream, not a
`BOOT.bin`, not an SD payload, not board-staged, not hardware validated, and
not a hardware version promotion.

## Added Entry Point

```text
scripts/vivado_ooc_phase1_fft_shadow_xfft2048_probe.tcl
```

Command:

```powershell
& E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source scripts\vivado_ooc_phase1_fft_shadow_xfft2048_probe.tcl
```

The Tcl regenerates the isolated project under ignored `vivado_out/` and writes
human-readable evidence under:

```text
reports/stage_phase1_fft_shadow_xfft2048_probe
```

## OOC Result

Final result:

```text
Project/IP create: PASS
IP configuration: PASS
Target generation / IP OOC run create: PASS
IP OOC synthesis: PASS
Timing parse: PASS
Run status: synth_design Complete!
Run progress: 100%
```

Timing at the final 122.88 MHz OOC constraint:

```text
Setup WNS: +5.029 ns
Hold WHS:  +0.190 ns
Failing setup endpoints: 0
Failing hold endpoints: 0
Timing summary: All user specified timing constraints are met.
```

Resource summary from OOC synthesis:

```text
Slice LUTs:       3153
Slice Registers:  5063
Block RAM Tile:   3.5
RAMB18:           7
DSPs:             15
```

Stage reports:

```text
reports/stage_phase1_fft_shadow_xfft2048_probe/ooc_report.md
reports/stage_phase1_fft_shadow_xfft2048_probe/ooc_timing_summary.txt
reports/stage_phase1_fft_shadow_xfft2048_probe/ooc_utilization.txt
reports/stage_phase1_fft_shadow_xfft2048_probe/ip_status.txt
reports/stage_phase1_fft_shadow_xfft2048_probe/xfft_config.txt
reports/stage_phase1_fft_shadow_xfft2048_probe/xfft_properties.txt
```

## Interpretation

P1.4b removes the first P1.4a blocker: Vivado 2019.1 can create and synthesize
a fixed 2048-point XFFT IP probe for the target Zynq-7020 part with positive
OOC timing at the same 8.138 ns target used by the previous Phase 1 OOC gates.

The probe still leaves these A-lane blockers:

- no Hann/window multiplier or coefficient policy in RTL
- no PSD square-sum, scale, or dB/log split
- no valid/ready wrapper from XFFT output into `p201_fft_shadow_top4_reducer`
- no valid/ready wrapper from XFFT/PSD output into
  `p201_fft_shadow_coarse96_reducer`
- no integrated XSIM vector comparing against the P1.2 2048-point reference
- no register-page integration
- no live AD9361 clock/valid/sample coupling
- no IP/BD integration, implementation, route, bitstream, Bootgen, SD payload,
  board staging, or physical-power-cycle validation

## Next Safe Step

Continue PC-only. The next A milestone should create a minimal composition
probe that explicitly bridges the XFFT-style streaming output shape into the
existing post-PSD helpers:

```text
XFFT2048 output framing -> PSD/power representation -> top4 reducer
XFFT2048 output framing -> PSD/power representation -> coarse96 reducer
```

If the XFFT generated simulation model is too heavy for a quick wrapper gate,
the fallback is a synthetic streaming FFT-output fixture that matches the XFFT
AXI-Stream data/tlast/config/status shape and drives the existing top4/coarse96
reducers with deterministic P1.2-style PSD powers. Do not enter bitstream,
BOOT/SD, board staging, or active runtime work from P1.4b alone.

## Checks

```text
Vivado 2019.1 XFFT2048 OOC probe -> PASS
```

No ROS, SDR streaming runtime, mapping, RTAB-Map, navigation,
`robot_controller`, `cmd_vel`, robot motion, bitstream generation, Bootgen, SD
copying, board access, or active `robot_control` modification was performed.
