# Phase 1 FFT Shadow Lane Handoff

Last updated: 2026-06-09 18:24 Asia/Shanghai

This is the A-lane handoff for the low-resolution `fpga_fft_shadow` mainline.
Use this file with `README.md`, the global `VERSION_ROUTE.md`, and the current
P1.4a report.

## Scope

Lane root:

```text
experiments/phase1_fft_shadow_selftest
```

A-lane target path:

```text
AD9361 -> FPGA summary/top/coarse -> C mmap/UIO -> NX
```

This lane owns the PC-only low-resolution FFT/PSD shadow building blocks:

- `fpga_fft_shadow` ABI fixture
- signed top-4 PSD reducer
- exact 2048-to-96 coarse PSD reducer
- FFT4 smoke core
- future isolated 2048 FFT/window/PSD OOC probe

NX-side A-lane work is limited to the independent experiment directory and only
to low-resolution FFT shadow, contract, validation, and low-resolution evidence
files:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
```

Allowed NX-side A-lane examples:

```text
sdr_fpga_offload_test/fft_shadow_client.py
SDR_KERNEL_CONTRACT.json
scripts/test_fft_shadow_contract.py
scripts/test_fft_psd_reference.py
low-resolution fft_shadow logs and reports
```

This handoff is not a B-lane high-resolution IIO helper handoff.

WSL may be used only for A-lane offline scripts, software gates, and lightweight
checks. It must not start ROS, SDR streaming runtime, mapping, active
`robot_control`, hardware access flows, or any B-lane high-resolution helper
work.

Stage evidence stays under:

```text
reports/stage_phase1_fft_shadow_*
```

Milestone reports stay under:

```text
reports/p201_phase1_p1_4a_fft_shadow_integration_review_20260609.md
```

## Latest Evidence

Current completed A-lane evidence:

- P1.1 native C mmap/UIO transport PASS on fake registers and SDR-local
  current-loaded V10S0/V8D0 SUM8/AGG8 safe registers.
- P1.2 FFT/PSD reference and tolerance gate PASS for the current NX
  Hann/fftshift/coherent-gain PSD math and exact 96-bin coarse PSD ABI.
- P1.3 ABI fixture XSIM/OOC PASS for the `0x400..0x6fc` shadow page.
- P1.3b top-4 PSD reducer XSIM/OOC PASS.
- P1.3c exact 2048-to-96 coarse PSD reducer XSIM/OOC PASS.
- P1.3d FFT4 smoke core XSIM/OOC PASS.
- P1.4a integration review COMPLETE as a PC-only documentation/design gate.
- P1.4b XFFT2048 IP/OOC probe PASS at 122.88 MHz.

Important report:

```text
reports/p201_phase1_p1_4a_fft_shadow_integration_review_20260609.md
reports/p201_phase1_p1_4b_fft_shadow_xfft2048_probe_20260609.md
```

## Not Hardware/BOOT/SD

This lane is currently not:

- hardware validated
- live AD9361 FFT/PSD integration
- a bitstream
- a `BOOT.bin`
- an SD payload
- board staged
- active `robot_control` integration
- safe for runtime publication or motion influence

Do not present `p201_fft_shadow_fft4_smoke_core` as a 2048-point FFT. It is only
a minimal true-FFT datapath smoke test.

## Current Blockers

Board staging is blocked until this lane has:

- a completed XFFT2048/window/PSD/top4/coarse96 composition gate, or a clearly
  renamed smaller spectral-method probe
- integrated valid/ready framing from FFT/window/PSD into top-4 and coarse96
- a documented fixed-point scaling and dB/log split between FPGA and NX
- live AD9361 sample/valid/clock/reset coupling reviewed against V8L1/V8D0
  safety constraints
- IP/BD, implementation, route, timing, Bootgen, payload, hashes, and artifact
  README evidence, if a board candidate is made

## Next Safe Step

P1.4b should be PC-only:

```text
P1.4b XFFT2048 IP/OOC probe is complete. Continue with a PC-only composition
probe that bridges XFFT-style streaming output framing into PSD powers and the
existing top-4/coarse96 reducers before any V8-derived live tap integration.
```

Keep 96 coarse bins only if timing and register decode remain clean after
integration. If they do not, document a 64-bin runtime fallback or a debug-only
vector path before testing.

## Files Changed

P1.4a evidence and global route commit:

```text
HANDOFF.md
PROJECT_MAP.md
README.md
VERSION_ROUTE.md
docs/FPGA_NX_KERNEL_API_ROADMAP.md
docs/P201PRO_PHASE1_FFT_PSD_SHADOW_PLAN.md
docs/P201_SDR_FPGA_KERNEL_CONTRACT.md
docs/README.md
nx_experiments/sdr_fpga_offload_test/OFFLOAD_VALIDATION_PLAN.md
nx_experiments/sdr_fpga_offload_test/README.md
reports/README.md
reports/p201_phase1_p1_4a_fft_shadow_integration_review_20260609.md
```

This lane-boundary handoff update:

```text
HANDOFF.md
PROJECT_MAP.md
README.md
VERSION_ROUTE.md
docs/README.md
experiments/phase1_fft_shadow_selftest/HANDOFF.md
experiments/phase1_fft_shadow_selftest/README.md
```

Global index/handoff files may point to this lane handoff. Do not include B
lane files such as:

```text
docs/P201PRO_HIGHRES_IIO_HELPER_PHASE1_PLAN.md
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/
nx_experiments/sdr_fpga_offload_test/logs/highres_iio_*.json
```

## Checks

Latest P1.4a lightweight checks:

```text
python scripts/test_fft_shadow_contract.py -> PASS
python scripts/test_fft_psd_reference.py -> PASS
git diff --check -> PASS
git diff --cached --name-only -> A-lane/global index files only
```

No ROS, SDR streaming runtime, mapping, RTAB-Map, navigation,
`robot_controller`, `cmd_vel`, robot motion, bitstream generation, Bootgen, SD
copying, board access, or WSL-launched hardware/runtime flow is part of this
lane handoff update.
