# Phase 1 FFT Shadow Self-Test

Last updated: 2026-06-09 18:24 Asia/Shanghai

This experiment is the A-lane root for the low-resolution Phase 1
`fpga_fft_shadow` mainline. Start with the lane handoff:

```text
experiments/phase1_fft_shadow_selftest/HANDOFF.md
```

The current work is a PC-only isolated RTL gate for the Phase 1
`fpga_fft_shadow` register ABI. It exposes the draft page at offsets
`0x400..0x6fc` with:

- identity, status, and frame metadata
- FFT/PSD summary fields
- four top peaks
- exactly 96 populated coarse PSD bins
- reserved coarse entries 96..127 reading zero

The values are a deterministic fixture derived from the P1.2 synthetic
multi-tone reference. This proves register layout and readback shape only.

P1.3b also adds `p201_fft_shadow_top4_reducer`, a timing-clean signed PSD
top-4 reducer primitive with guard-bin suppression. It is a post-PSD helper
for the same shadow ABI path, not a complete FFT, PSD, or coarse-bin generator.

P1.3c adds `p201_fft_shadow_coarse96_reducer`, an exact 2048-to-96 signed PSD
max-hold reducer using the same fixed grouping rule as the P1.2 reference. It
is a coarse-bin helper only, not a complete FFT/window/PSD generator.

P1.3d adds `p201_fft_shadow_fft4_smoke_core`, a 4-point complex FFT smoke core
with per-bin power, total power, and peak summary. It proves a minimal true FFT
butterfly datapath under XSIM/OOC, but it is not a 2048-point FFT, Hann/window,
PSD generator, live AD9361 path, or hardware version.

P1.4a is a PC-only integration review for:

```text
AD9361 -> FPGA summary/top/coarse -> C mmap/UIO -> NX
```

It confirms the usable blocks above, marks the 2048-point FFT/window/PSD
generator and live AD9361 coupling as current blockers, and recommends an
isolated Xilinx FFT IP or equivalent OOC probe before any bitstream, BOOT/SD
payload, board staging, or version promotion.

P1.4b adds `scripts/vivado_ooc_phase1_fft_shadow_xfft2048_probe.tcl`, a
PC-only Vivado 2019.1 Xilinx FFT IP probe for a fixed 2048-point,
16-bit, scaled, pipelined-streaming core. OOC synthesis/timing passes at
122.88 MHz, but this is only the FFT IP entry. It is not Hann/window, PSD,
top4/coarse96 composition, live AD9361 coupling, or a hardware version.

NX-side A-lane work must stay in the independent experiment directory and only
use low-resolution FFT shadow/contract/validation files such as
`sdr_fpga_offload_test/fft_shadow_client.py`, `SDR_KERNEL_CONTRACT.json`,
`scripts/test_fft_shadow_contract.py`, and `scripts/test_fft_psd_reference.py`.
Do not create or modify `highres_iio_helper/` or `logs/highres_iio_*.json` from
this lane.

## Safety Scope

This experiment is:

- not burnable
- not hardware validated
- not live AD9361 integration
- not active `robot_control` integration
- not a replacement for CPU FFT/PSD

It does not generate a bitstream, BOOT.bin, SD payload, or board staging files.
It must not be described as a live FFT/PSD runtime path.

## Register Fixture

The fixture matches the software ABI constants:

```text
0x400 magic            0x46465431 ("FFT1")
0x404 build_id         0x46505331 ("FPS1")
0x408 abi_version      0x00020000
0x40c capability       0x00000fff
0x414 status           valid only
0x418 sample_count     4096
0x41c nfft             2048
0x420 sample_rate_hz   2000000
0x424 window_id        1 (Hann)
0x42c coarse_count     96
0x430 coarse_step_q16  1398101
```

Summary and top-peak fields come from:

```text
nx_experiments/sdr_fpga_offload_test/scripts/test_fft_psd_reference.py
```

## PC Gates

Run XSIM:

```powershell
& E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source scripts\xsim_phase1_fft_shadow_selftest.tcl
```

Run OOC synthesis:

```powershell
& E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source scripts\vivado_ooc_phase1_fft_shadow_selftest.tcl
```

Run the top-4 reducer OOC timing gate:

```powershell
& E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source scripts\vivado_ooc_phase1_fft_shadow_top4_reducer.tcl
```

Run the coarse96 reducer OOC timing gate:

```powershell
& E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source scripts\vivado_ooc_phase1_fft_shadow_coarse96_reducer.tcl
```

Run the FFT4 smoke core OOC timing gate:

```powershell
& E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source scripts\vivado_ooc_phase1_fft_shadow_fft4_smoke_core.tcl
```

Run the XFFT2048 IP OOC probe:

```powershell
& E:\Xilinx\Vivado\2019.1\bin\vivado.bat -mode batch -source scripts\vivado_ooc_phase1_fft_shadow_xfft2048_probe.tcl
```

Reports are written under:

```text
reports/stage_phase1_fft_shadow_selftest
reports/stage_phase1_fft_shadow_top4_reducer
reports/stage_phase1_fft_shadow_coarse96_reducer
reports/stage_phase1_fft_shadow_fft4_smoke_core
reports/stage_phase1_fft_shadow_xfft2048_probe
```
