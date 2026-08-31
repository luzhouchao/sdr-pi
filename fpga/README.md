# P201Pro FPGA SDR Offload Workspace

Last updated: 2026-06-09 19:52 Asia/Shanghai

This repository coordinates the P201Pro 2T2R Zynq-7020 SDR FPGA offload work.
It is isolated from the active NX robot runtime.

`VERSION_ROUTE.md` is the version source of truth.

Worktree note: canonical project paths in historical artifacts still use
`E:\vivado\fpga_p201pro_accel`. If this repo is opened from
`E:\vivado\fpga_p201pro_accel_mainline`, run commands from the current git root
and keep V10S5 side-path changes separate from mainline state.

## Read First

- `AGENTS.md`: safety rules, artifact gates, SDR `/sd` staging rules.
- `VERSION_ROUTE.md`: current validated version, test order, hashes, rollback.
- `HANDOFF.md`: short working handoff.
- `PROJECT_MAP.md`: directory map and cleanup policy.
- `docs/P201PRO_PROJECT_LEVEL_BAND_SCAN_OPTIMIZATION_PLAN.md`: current top-level optimization plan for seconds-level SDR band-scan/session improvements.
- `reports/p201_current_sdr_function_timing_inventory_20260609.md`: current implemented SDR software-function timing inventory.
- `experiments/phase1_fft_shadow_selftest/HANDOFF.md`: A-lane low-resolution FFT shadow working boundary.
- `docs/P201PRO_REUSABLE_SUBMODULE_MATRIX_20260610.md`: reusable module inventory.
- `docs/P201PRO_V10S5_COMBINED_SELFTEST_PLAN.md`: current combined self-test candidate plan.

The old 20260610 day-plan document was deleted. Do not use it for current
routing. Use `VERSION_ROUTE.md`, `HANDOFF.md`, and the latest reports/logs.

## Current State

Highest hardware-validated version:

```text
V8L1 / SUM8 + QUA8 + AGG8 auto-aggregate
```

Current forward direction:

```text
Continue from the V8L1 hardware-validated baseline, but optimize at the
project scan/session level first. Treat high-resolution IIO/CPU/GPU and FPGA
low-resolution shadow as backend options under one band-scan session. Keep
active NX robot/SDR runtime untouched until shadow/assist validation is
explicitly approved.
```

Important current candidates:

- `V8L1`: hardware validated, current forward baseline.
- `V8`: first validated rollback.
- `V8L2`: PC build and `/sd` staging passed, identity registers passed, but AD9361/IIO failed after power-cycle; not hardware validated.
- `V9A` and `V9B0`: PC/staging/register checks passed, but AD9361/IIO failed; not hardware validated.
- `V10S0`: isolated AXI-Lite reusable submodule self-test at `0x43C10000`; PC build, Bootgen, SD payload, SDR `/sd` staging, and post-power-cycle validation passed. Hardware-validated only as an isolated self-test page on a V8D0 live tap base.
- `V10S4`: isolated AXI-Lite non-FFT submodule self-test at `0x43C20000`; PC build, Bootgen, SD payload, `/sd` staging, and self-test registers passed, but AD9361/IIO failed after power-cycle; not hardware validated.
- `V10S5`: isolated combined AXI-Lite self-test source candidate at `0x43C30000`; combined wrapper XSIM/OOC passed on PC, but IP/BD/bitstream/Bootgen/SD payload/staging/hardware validation have not happened.

V10S0, V10S4, and V10S5 self-test pages are not live AD9361 integration,
not active NX runtime integration, and not FFT/PSD runtime paths. The V10S0
image does include the V8D0 live SUM8/QUA8/AGG8 tap base at `0x43C00000`,
which is usable for independent passive shadow experiments.

Latest mainline NX experiment:

```text
2026-06-09 12:08 Asia/Shanghai: current V10S0/V8D0 base passed extended
devmem-only SUM8/AGG8 passive read, 20/20 captures, and extended raw-IIO vs
FPGA AGG8 shadow compare, 15/15 captures. Auto-roll latest-window sequence did
not advance, so the usable mainline shape is explicit arm/read passive assist
inside the independent NX experiment directory, not runtime integration.
2026-06-09 12:20 Asia/Shanghai: an independent feature-flag assist prototype
using explicit arm/read passed shadow and fallback checks. Primitive-assist mode
selected FPGA primitives 5/5 when AoA phase clipping was allowed to remain a
NX policy flag. This still does not touch active `robot_control`.
2026-06-09 12:27 Asia/Shanghai: current-loaded identity was rechecked read-only:
V8D0 base + V10S0 page are present, V10S4/V10S5 pages are absent. Stress20
feature-flag probes passed on the current-loaded image; no new `/sd` staging or
post-power-cycle validation occurred.
2026-06-09 12:34 Asia/Shanghai: stress100 current-loaded board test passed.
Default assist read FPGA 100/100 with CPU fallback under policy gates;
primitive-assist selected FPGA 97/100. Post-stress identity and IIO health were
still good.
2026-06-09: P1.1 native C mmap/UIO transport fake-register tests passed in the
independent NX experiment directory. SDR-local native board probe also passed on
the current V10S0/V8D0 image: read-only identity, explicit arm/read 64x64, and
repeat20 poll-us=50 all passed, with post-test IIO health still good.
2026-06-09: `fpga_fft_shadow` software ABI draft added at register page
0x400..0x6fc with summary, four top peaks, and preferred 96 coarse PSD bins.
No live 2048-point FFT/PSD hardware implementation exists yet.
2026-06-09: P1.2 offline FFT/PSD reference/tolerance gate passed on Windows and
NX. It fixes exact 96-bin coarse PSD for the FPGA ABI and documents the current
UI max-hold compressor difference where 2048 bins compress to 98 bins when
`max_bins=96`.
2026-06-09: P1.3 isolated `fpga_fft_shadow` RTL self-test passed on PC. The
fixture reads back the draft `0x400..0x6fc` ABI with summary, four top peaks,
96 populated coarse PSD bins, and reserved bins 96..127 as zero. XSIM and OOC
synthesis passed; no bitstream, BOOT/SD payload, board staging, or hardware
validation was produced.
2026-06-09: P1.3b isolated signed top-4 PSD peak reducer passed on PC. XSIM
PASS; OOC timing PASS at 8.138 ns with WNS +1.102 ns, WHS +0.129 ns,
340 LUT, 509 FF, 0 BRAM, 0 DSP. This is a post-PSD helper primitive, not FFT,
not PSD generation, not live AD9361 integration, and not a version promotion.
2026-06-09: P1.3c isolated exact 2048-to-96 coarse PSD max-hold reducer passed
on PC. XSIM PASS; OOC timing PASS at 8.138 ns with WNS +2.264 ns,
WHS +0.185 ns, 2138 LUT, 3275 FF, 0 BRAM, 0 DSP. This is a coarse-bin helper
primitive only and the direct 96-bin register cost must be reviewed before
P1.4 integration.
2026-06-09: P1.3d isolated FFT4 smoke core passed on PC. XSIM PASS; OOC timing
PASS at 8.138 ns with WNS +1.424 ns, WHS +0.132 ns, 1299 LUT, 856 FF,
0 BRAM, 8 DSP. This is the first minimal true FFT butterfly datapath gate, but
not a 2048-point FFT/window/PSD generator, not live AD9361 integration, and not
a version promotion.
2026-06-09: P1.4a FFT shadow integration review was recorded on PC. It confirms
the usable low-resolution shadow blocks and the missing 2048-point
FFT/window/PSD generator, warns not to present FFT4 as the 2048 FFT path, and
recommends an isolated Xilinx FFT IP or equivalent OOC probe before any
bitstream, BOOT/SD payload, board staging, or version promotion.
2026-06-09: P1.4b XFFT2048 probe passed on PC. Vivado 2019.1 created a fixed
2048-point, 16-bit, scaled, pipelined-streaming Xilinx FFT IP and completed
isolated OOC synthesis/timing at 122.88 MHz with WNS +5.029 ns, WHS +0.190 ns,
3153 LUT, 5063 FF, 7 RAMB18, and 15 DSP. This is an IP/OOC entry only; no
Hann/window, PSD, top4/coarse96 composition, live AD9361 coupling, bitstream,
BOOT/SD payload, board staging, hardware validation, or version promotion
exists for it yet.
2026-06-09: a current SDR software-function timing inventory was added from
existing independent logs, read-only active NX source inspection, and an
offline NX synthetic CPU benchmark. It measures current implemented function
costs, not FPGA primitives in isolation. Active CPU PSD/AoA math is sub-ms on
synthetic NX data; live raw-IIO compare capture is about 29 ms median; current
FPGA sidecar validation transport is about 0.8 s and not a runtime fast path.
```

## Safety Boundaries

Do not modify:

```text
C:\Users\20642\Desktop\寮€鍙慭SDR\2r2t
G:\ROS寮€鍙慭SDR P201P
```

Do not overwrite any original `BOOT.bin`.

Do not start or trigger:

```text
ROS
SDR streaming runtime
mapping
RTAB-Map
navigation
robot_controller
cmd_vel
robot motion
```

NX experiment scope only:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test
```

## Directory Map

Fast map:

- `hdl/`: current reusable RTL sources.
- `experiments/`: versioned RTL experiments and submodule self-tests.
- `scripts/`: Vivado, Bootgen, staging, and validation helpers.
- `boot_experiments/`: versioned burnable or diagnostic SD/BOOT artifacts.
- `reports/`: text/JSON evidence from PC gates, staging, and hardware tests.
- `docs/`: current plans, contracts, and module matrices.
- `docs/archive/`: superseded plans, long historical logs, and cleanup logs.
- `nx_experiments/`: safe NX-side validation mirror.
- `vivado/`: generated local Vivado IP/package workspace; scripts regenerate contents.

See `PROJECT_MAP.md` for the detailed map and cleanup policy.

## Tools

```text
Vivado:  E:\Xilinx\Vivado\2019.1\bin\vivado.bat
Bootgen: E:\Xilinx\SDK\2019.1\bin\bootgen.bat
```

NX SSH:

```text
ssh -i %USERPROFILE%\.ssh\codex_nx_ed25519 -p 22 wheeltec@192.168.2.193
```

SDR SSH from NX:

```text
ssh root@192.168.1.10
password: managed locally; never commit credentials
```

Hardware validation still requires physical SDR power removal and reapply by
the user, followed by the version-specific validation script and register checks.
