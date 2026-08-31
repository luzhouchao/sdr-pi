# SDR FPGA Offload Test Handoff

Last updated: 2026-06-09 19:20 Asia/Shanghai

This is the NX-side independent experiment handoff. It does not replace the
root `VERSION_ROUTE.md`, which remains the version source of truth.

## Scope

NX experiment directory:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
```

Windows mirror:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test
```

Safety:

```text
No ROS.
No SDR streaming runtime.
No active robot_control modification.
No mapping, RTAB-Map, navigation, cmd_vel, or robot motion.
No original SD backup writes.
```

## Current Board State

The current-loaded FPGA image was checked read-only before interpreting the
latest feature-flag stress tests:

```text
V8D0 base:
BASE_SUMMARY=0x53554D38
BASE_BUILD=0x56384430
BASE_QUALITY=0x51554138
BASE_QUALITY_BUILD=0x51384430
BASE_AGG=0x41474738
BASE_AGG_BUILD=0x41384430

V10S0 page:
V10S0_MAGIC=0x53305430
V10S0_DONE=0x0000000F
V10S0_BUILD=0x56313053

V10S4/V10S5 pages:
absent in the current-loaded image
```

No new `/sd` staging or physical power-cycle happened for the latest
feature-flag stress probes. Treat them as current-loaded-image board tests, not
as a new SD payload validation event.

## Latest Results

Passive V8D0 aggregate/shadow evidence on current V10S0 image:

```text
sum8_v8d0_passive_read_20260609_extended_mainline.json
  PASS 20 / 20
  frame_len=64
  agg_frames=16/64/256/1024

sum8_v8d0_shadow_compare_20260609_extended64_mainline.json
  PASS 10 / 10

sum8_v8d0_shadow_compare_20260609_extended256_mainline.json
  PASS 5 / 5

v8d0_auto_roll_batch_ssh_20260609_mainline.json
  FAIL for continuous latest-window semantics
  sequence did not advance after first read
```

Feature-flag assist prototype:

```text
feature_flag_assist_shadow_v8d0_20260609_mainline.json
  PASS 5 / 5
  CPU selected, FPGA sidecar read OK

feature_flag_assist_assist_v8d0_20260609_mainline.json
  PASS 5 / 5
  CPU fallback because conservative aoa_phase_clipped gate fired

feature_flag_assist_primitive_allow_clip_v8d0_20260609_mainline.json
  PASS 5 / 5
  FPGA primitive selected with clipped flag preserved

feature_flag_assist_assist_v8d0_20260609_stress100_mainline.json
  PASS 100 / 100
  FPGA read OK 100 / 100
  selected FPGA 4 / 100
  CPU fallback 96 / 100

feature_flag_assist_primitive_allow_clip_v8d0_20260609_stress100_mainline.json
  PASS 100 / 100
  FPGA read OK 100 / 100
  selected FPGA 97 / 100
  CPU fallback 3 / 100
```

Post-stress health:

```text
V8D0/V10S0 identity still matched.
IIO still exposed ad9361-phy and cf-ad9361-lpc.
```

Active-package dry-run:

```text
2026-06-09:
Shadow-only robot_control candidate patch prepared and dry-run checked against
the active NX package. Dry-run PASS:
checking file robot_control/sdr_aoa_backend.py
checking file robot_control/sdr_dual_aoa_localizer.py

Local and NX py_compile checks passed for the staged shadow-only backend
candidate and the staged localizer candidate. No active robot_control file was
modified, no patch was applied, and no runtime was started.
```

Evidence:

```text
reports/sum8_robot_control_shadow_only_dry_run_20260609.md
staged_robot_control_integration/robot_control_sum8_shadow_only.patch
staged_robot_control_integration/robot_control_shadow_only_candidate/sdr_aoa_backend.py
```

Load-reduction live board timing:

```text
2026-06-09:
Safe independent NX tests PASS. Current V8D0/V10S0 identity and IIO health
passed. Passive AGG8 reads passed 12/12. Shadow compares passed 5/5 at
agg_frames=64 and 3/3 at agg_frames=256. Primitive assist with clipped-AoA
allowed selected FPGA 10/10 with no fallback.

Burden reduction is strong at the primitive/data-movement level: for
frame_len=64 and agg_frames=64, raw dual-RX payload collapses from 32768 bytes
to about 156 bytes of AGG8 MMIO summary, about 210x / 99.52%. The per-frame
register-command model drops from 2432 commands to 46 commands, about 52.9x /
98.11%.

Total time is not reduced with the current Python + SSH + devmem validation
transport. The measured shadow path is about 0.884 s median for agg_frames=64,
versus about 0.030 s median for raw-IIO capture plus CPU primitive compute.
Treat this as computation offload evidence, not runtime-latency improvement.
```

Evidence:

```text
reports/load_reduction_live_board_test_20260609.md
logs/load_reduction_phase0_identity_iio_20260609.json
logs/load_reduction_sum8_passive_20260609.json
logs/load_reduction_shadow64_20260609.json
logs/load_reduction_shadow256_20260609.json
logs/load_reduction_feature_assist_primitive_20260609.json
```

P1.1 native mmap/UIO transport:

```text
2026-06-09:
Independent C backend and ctypes adapter were added under this experiment
directory. Fake-register tests PASS with strict C warnings enabled, the shared
library builds on WSL/Linux, and Python py_compile plus a ctypes fake mmap smoke
test passed. A standalone ARMHF probe was then copied to SDR `/tmp` because the
SDR image lacks gcc/python/tar/SFTP. SDR-local native board probe PASS on the
current-loaded V10S0/V8D0 image:
read-only identity PASS, explicit arm/read 64x64 PASS, repeat20 poll-us=50 PASS
20/20, and post-test V8D0/V10S0 identity plus AD9361/IIO health PASS.

Latest native timing evidence:
snapshot_elapsed_ns median 8560, poll_elapsed_ns median 141771 for repeat20
with poll-us=50. NX-triggered SSH exec wall median was still about 15.1 ms, so
that wrapper remains validation scaffolding and is not the runtime hot path.
```

Evidence:

```text
native/p201_native_mmio.c
native/p201_native_mmio.h
native/test_p201_native_mmio.c
native/Makefile
sdr_fpga_offload_test/native_transport.py
scripts/probe_sum8_native_transport.py
..\..\reports\p201_phase1_p1_1_native_mmap_transport_20260609.md
```

`fpga_fft_shadow` ABI draft:

```text
2026-06-09:
Software contract and client were added for a new `0x400..0x6fc` FFT shadow
page. The shape is scalar summary plus four top peaks plus 64..128 coarse PSD
bins, with 96 bins preferred. Fake-register tests PASS. Later P1.3/P1.3d
PC-only RTL evidence exists, but this is not board validation, not live
2048-point FFT/PSD runtime integration, and not a promotion of SPEC9.

P1.2 offline reference/tolerance gate PASS on Windows and NX. It matches the
current NX Hann/fftshift/coherent-gain PSD math, defines exact 96-bin coarse PSD
max-hold grouping for the FPGA ABI, and records that the active UI max-hold
compressor maps 2048 PSD bins to 98 bins when `max_bins=96`.

P1.3 isolated RTL self-test PASS on PC. The
experiments/phase1_fft_shadow_selftest fixture reads back the draft
`0x400..0x6fc` ABI with summary, four top peaks, 96 populated coarse PSD bins,
and reserved bins 96..127 reading zero. XSIM and OOC synth passed. This is not
live AD9361 FFT/PSD hardware and not active runtime integration.

P1.3b isolated signed top-4 PSD peak reducer PASS on PC. The reducer uses
guard-bin suppression and a timing-clean multi-cycle ready/valid state machine.
XSIM PASS and OOC timing PASS at 8.138 ns with WNS +1.102 ns, WHS +0.129 ns,
340 LUT, 509 FF, 0 BRAM, 0 DSP. This is a post-PSD helper only, not FFT/PSD
generation, not live AD9361 integration, and not active runtime integration.

P1.3c isolated exact 2048-to-96 coarse PSD reducer PASS on PC. The reducer
matches the P1.2 exact-count grouping rule and keeps
`coarse_bin_step_q16=1398101`. XSIM PASS and OOC timing PASS at 8.138 ns with
WNS +2.264 ns, WHS +0.185 ns, 2138 LUT, 3275 FF, 0 BRAM, 0 DSP. This is a
coarse-bin helper only, not FFT/PSD generation, not live AD9361 integration,
and not active runtime integration. Review the 96-direct-register cost before
P1.4 integration.

P1.3d isolated FFT4 smoke core PASS on PC. The core implements a 4-point
complex FFT butterfly datapath with per-bin power, total power, and peak
summary. XSIM PASS and OOC timing PASS at 8.138 ns with WNS +1.424 ns,
WHS +0.132 ns, 1299 LUT, 856 FF, 0 BRAM, 8 DSP. This is a minimal true-FFT
datapath smoke test only, not a 2048-point FFT/window/PSD generator, not live
AD9361 integration, and not active runtime integration.
```

Evidence:

```text
sdr_fpga_offload_test/sdr_kernel_contract.py
sdr_fpga_offload_test/fft_shadow_client.py
scripts/test_fft_shadow_contract.py
scripts/test_fft_psd_reference.py
SDR_KERNEL_CONTRACT.json
..\..\reports\p201_phase1_fft_shadow_abi_draft_20260609.md
..\..\reports\p201_phase1_p1_2_fft_psd_reference_tolerances_20260609.md
..\..\reports\p201_phase1_p1_3_fft_shadow_selftest_20260609.md
..\..\reports\p201_phase1_p1_3b_fft_shadow_top4_reducer_20260609.md
..\..\reports\p201_phase1_p1_3c_fft_shadow_coarse96_reducer_20260609.md
..\..\reports\p201_phase1_p1_3d_fft_shadow_fft4_smoke_core_20260609.md
```

## What Is Actually Downsampled/Offloaded

FPGA currently provides reusable SUM8/QUA8/AGG8 primitives:

```text
RX0/RX1 corrected power numerators
cross real/imag aggregate terms
coherence/phase input primitives
clip, zero-cross, and same-sign quality counters
multi-frame aggregate registers
```

NX still owns:

```text
register transport
division/sqrt/log/atan2
AoA calibration and clipping policy
feature gate and fallback
logging and result selection
publication/runtime integration
```

## Current Mainline Shape

Use explicit arm/read AGG8 access. Do not rely on auto-roll/latest-window
polling on V8D0/V10S0 because `agg_sequence` did not advance.

Supported modes in `sdr_fpga_offload_test/feature_flag_assist.py`:

```text
off     no FPGA read
shadow  read FPGA sidecar but select CPU
assist  select FPGA only when quality gates pass, otherwise CPU fallback
```

`--allow-aoa-phase-clipped` is a primitive-assist experiment knob. It allows the
FPGA primitive to be selected while preserving the clipped AoA flag for NX
policy. It is not approval to publish clipped AoA blindly.

## Next Safe Step

P1.1 native transport board gate, P1.2 FFT/PSD reference tolerance gate, P1.3
isolated `fpga_fft_shadow` ABI self-test, P1.3b top-4 reducer primitive, and
P1.3c coarse96 reducer primitive, and P1.3d FFT4 smoke core have passed. The
next safe mainline step is P1.4 integration review: decide how the
FFT/window/PSD generator, top-4 reducer, and coarse96 reducer should compose
into a timing-clean isolated candidate before any bitstream/BOOT/SD work.
Active-package dry-run has also passed, but applying it still requires explicit
user approval before touching active `robot_control` files:

```text
apply the shadow-only patch
py_compile the two touched active files
stop before any ROS launch or SDR runtime start
```

Only after explicit user approval should any active `robot_control` file be
modified, and the first active mode must remain off/shadow with CPU publication.

The current Phase 1 planning document is:

```text
E:\vivado\fpga_p201pro_accel\docs\P201PRO_PHASE1_FFT_PSD_SHADOW_PLAN.md
```

For NX experiment work, follow that plan's Phase 1 scope: prove local C
mmap/UIO transport first, then prepare FFT/PSD summary shadow with top peaks and
limited coarse PSD bins. Keep Phase 2 AoA phase/coherence as aperture only until
Phase 1 evidence is complete.
