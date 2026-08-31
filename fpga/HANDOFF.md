# P201Pro FPGA SDR Acceleration Handoff

Last updated: 2026-06-09 19:52 Asia/Shanghai

This is the short working handoff. Full history is in:

```text
E:\vivado\fpga_p201pro_accel\docs\archive\P201PRO_HANDOFF_HISTORY_20260608.md
```

Worktree note: use the current `git status --short --branch` and current git
top-level for commands. Mainline documentation must not absorb unvalidated V10S5
side-path work unless `VERSION_ROUTE.md` first records the completed artifact
gate.

## Current State

Highest hardware-validated version:

```text
V8L1 / SUM8 + QUA8 + AGG8 auto-aggregate
```

Current forward baseline:

```text
V8L1 remains the hardware-validated base. Continue V8-derived diagnostics and
reusable submodule work. Do not make rollback the main engineering path.
```

Failed or blocked candidates:

- `V8L2`: PC build, Bootgen, `/sd` staging, and identity registers passed, but AD9361/IIO failed after physical power-cycle. Not hardware validated.
- `V9A`: SPEC9 registers and captures passed, but AD9361/IIO failed with missing `cf-ad9361-lpc`, TX tuning failure, and `cf_axi_adc` error `-5`. Not hardware validated.
- `V9B0`: minimal-isolation registers passed, but the same AD9361/IIO failure repeated. Not hardware validated.
- `V10S0`: isolated submodule self-test image built and packaged; staged to SDR `/sd` by user request after V10S4 failure; post-power-cycle validation passed on 2026-06-09 10:52 Asia/Shanghai. `/sd` hashes, AD9361/IIO health, V8D0 base registers, and V10S0 deterministic self-test registers passed. Hardware-validated as isolated self-test only.
- `V10S4`: isolated non-FFT submodule self-test image built and packaged; staged to SDR `/sd`, then physical power-cycle validation was attempted. `/sd` hashes, V8D0 base registers, and V10S4 self-test registers passed, but AD9361/IIO failed with missing `cf-ad9361-lpc`, `Tuning TX FAILED`, and `cf_axi_adc` error `-5`. Not hardware validated.
- `V10S5`: combined FFT-family/non-FFT source and scripts prepared; combined wrapper XSIM/OOC passed on PC; IP/BD/bitstream/Bootgen/SD payload/staging/hardware validation have not happened.

Active staged diagnostic:

- `V8D0`: layout probe payload staged to SDR `/sd` on 2026-06-09 10:27 Asia/Shanghai and passed post-power-cycle validation on 2026-06-09 10:32 Asia/Shanghai. `/sd` hashes, AD9361/IIO health, V8D0 identity registers, SPEC read-zero, and AGG8 captures passed. V8D0 is hardware-validated as a diagnostic layout probe only; V8L1 remains the current forward baseline.
- `V10S4`: failed AD9361/IIO after power-cycle. Rollback to V8L1 remains the recommended recovery step.
- `V10S0`: currently staged to SDR `/sd` and validated as isolated self-test only. It is not live FFT/PSD/runtime integration.

Mainline passive shadow progress:

- On 2026-06-09 11:39 Asia/Shanghai, the current V10S0 image's V8D0 live tap base passed a devmem-only SUM8/AGG8 passive read: 2/2 captures passed at `frame_len=64`, `agg_frames=16`.
- The independent NX experiment then passed a short raw-IIO vs FPGA AGG8 shadow comparison: 2/2 captures passed. CPU raw-IQ and FPGA AGG8 windows are adjacent/nearby, not hardware-synchronized; treat this as passive shadow workflow evidence, not strict equivalence or runtime integration.
- Evidence is mirrored under `E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\sum8_v8d0_passive_read_20260609_fast_mainline.json` and `E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\sum8_v8d0_shadow_compare_20260609_fast_mainline.json`.
- On 2026-06-09 12:08 Asia/Shanghai, extended passive read passed 20/20 captures at `frame_len=64` with `agg_frames=16/64/256/1024`. Extended shadow compare passed 15/15 captures: 10/10 at `agg_frames=64` and 5/5 at `agg_frames=256`.
- The auto-roll/latest-window probe on the same base failed the sequence-advance check: 1/8 reads passed, with all post-first `sequence_delta` values equal to 0. The current base is suitable for explicit arm/read passive aggregate and shadow compare, not continuous auto-roll polling.
- New evidence is mirrored under `E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\sum8_v8d0_passive_read_20260609_extended_mainline.json`, `E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\sum8_v8d0_shadow_compare_20260609_extended64_mainline.json`, `E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\sum8_v8d0_shadow_compare_20260609_extended256_mainline.json`, and `E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\v8d0_auto_roll_batch_ssh_20260609_mainline.json`.
- On 2026-06-09 12:20 Asia/Shanghai, an independent feature-flag assist prototype was added and tested. Shadow mode passed 5/5 with CPU selected and FPGA sidecar reads OK. Default assist mode passed 5/5 with CPU fallback because all decisions hit the conservative `aoa_phase_clipped` gate. Primitive-assist mode with `allow_aoa_phase_clipped` passed 5/5 and selected FPGA primitives while preserving the clipped flag for NX policy.
- Feature-flag evidence is mirrored under `E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\feature_flag_assist_shadow_v8d0_20260609_mainline.json`, `E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\feature_flag_assist_assist_v8d0_20260609_mainline.json`, and `E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\feature_flag_assist_primitive_allow_clip_v8d0_20260609_mainline.json`.
- On 2026-06-09 12:27 Asia/Shanghai, current-loaded FPGA identity was rechecked read-only: V8D0 base IDs are present and V10S0 page is present; V10S4/V10S5 pages are absent. No new SD staging or physical power-cycle happened, so this is current-loaded-image board testing only.
- Stress20 feature-flag probes passed on the current-loaded image. Default assist: FPGA read OK 20/20, selected FPGA 1/20, CPU fallback 19/20 due to `aoa_phase_clipped`. Primitive-assist with `allow_aoa_phase_clipped`: FPGA read OK 20/20 and selected FPGA 20/20.
- Stress100 feature-flag probes passed on the current-loaded image. Default assist: FPGA read OK 100/100, selected FPGA 4/100, CPU fallback 96/100. Primitive-assist with `allow_aoa_phase_clipped`: FPGA read OK 100/100, selected FPGA 97/100, CPU fallback 3/100 due to `coherence_below_gate`.
- Post-stress read-only health stayed good: V8D0/V10S0 identity registers still matched, and IIO still found `ad9361-phy` plus `cf-ad9361-lpc`.
- P1.1 native C mmap/UIO transport was added under the independent NX experiment directory on 2026-06-09. Fake-register C tests, shared-library build, Python py_compile, and ctypes fake mmap smoke test passed. A standalone ARMHF SDR-local probe then passed current-loaded board readback on V10S0/V8D0: read-only identity PASS, explicit arm/read 64x64 PASS, repeat20 with poll-us=50 PASS 20/20, and post-test AD9361/IIO health PASS. This is not hardware validation and does not promote a version.
- `fpga_fft_shadow` software ABI draft was added on 2026-06-09. It reserves page `0x400..0x6fc` for identity/status, scalar summary, four top peaks, and 64..128 coarse PSD bins with 96 preferred. Later P1.3/P1.3d PC-only RTL evidence exists, but no board readback, live 2048-point FFT/PSD runtime integration, or version promotion exists for it yet.
- P1.2 offline FFT/PSD reference and tolerance gate passed on 2026-06-09. It matches the current NX Hann/fftshift/coherent-gain PSD math, keeps exact 96-bin coarse PSD for the FPGA ABI, and records that the current UI max-hold compressor maps 2048 bins to 98 bins when `max_bins=96`.
- P1.3 isolated `fpga_fft_shadow` self-test passed on PC on 2026-06-09. The new deterministic AXI-Lite fixture exposes the draft `0x400..0x6fc` ABI with summary, four top peaks, 96 populated coarse PSD bins, and reserved bins 96..127 reading zero. XSIM PASS; OOC synth PASS with WNS +6.476 ns, WHS +0.129 ns, 103 LUT, 30 FF, 0 BRAM, 0 DSP. This is not live AD9361 FFT/PSD hardware and does not promote a version.
- P1.3b isolated top-4 PSD peak reducer passed on PC on 2026-06-09. The signed reducer uses a timing-clean multi-cycle ready/valid state machine with guard-bin suppression. XSIM PASS; OOC timing PASS at 8.138 ns with WNS +1.102 ns, WHS +0.129 ns, 340 LUT, 509 FF, 0 BRAM, 0 DSP. This is a post-PSD helper only: not FFT, not PSD generation, not live AD9361 integration, and not a version promotion.
- P1.3c isolated coarse96 PSD reducer passed on PC on 2026-06-09. It implements exact 2048-to-96 signed PSD max-hold grouping matching P1.2, with `coarse_bin_step_q16=1398101`. XSIM PASS; OOC timing PASS at 8.138 ns with WNS +2.264 ns, WHS +0.185 ns, 2138 LUT, 3275 FF, 0 BRAM, 0 DSP. This is a coarse-bin helper only and not FFT/PSD generation. Review the 96-direct-register cost before P1.4 integration.
- P1.3d isolated FFT4 smoke core passed on PC on 2026-06-09. It implements a 4-point complex FFT butterfly datapath with per-bin power, total power, and peak summary. XSIM PASS; OOC timing PASS at 8.138 ns with WNS +1.424 ns, WHS +0.132 ns, 1299 LUT, 856 FF, 0 BRAM, 8 DSP. This is a minimal true-FFT datapath smoke test only, not a 2048-point FFT/window/PSD generator and not a version promotion.
- P1.4a FFT shadow integration review was recorded on PC on 2026-06-09. It keeps P1.1/P1.2/P1.3/P1.3b/P1.3c/P1.3d as usable blocks, but marks the 2048-point FFT/window/PSD generator and live AD9361 coupling as missing. The next recommended A-route step is an isolated Xilinx FFT IP or equivalent OOC probe composed with top-4 and coarse96 before any bitstream/BOOT/SD or board work. No hardware version changed.
- P1.4b XFFT2048 probe passed on PC on 2026-06-09. Vivado 2019.1 created `xfft` v9.1 Rev. 2 as a fixed 2048-point, 16-bit, scaled, pipelined-streaming IP and completed isolated OOC synthesis/timing at 122.88 MHz with WNS +5.029 ns, WHS +0.190 ns, 3153 LUT, 5063 FF, 7 RAMB18, and 15 DSP. This is an IP/OOC entry only: no Hann/window, PSD, top4/coarse96 composition, live AD9361 coupling, bitstream, BOOT/SD, board staging, or version promotion.
- On 2026-06-09, the optimization route was reframed around project-level band-scan/session speed. The current top-level plan is `docs\P201PRO_PROJECT_LEVEL_BAND_SCAN_OPTIMIZATION_PLAN.md`. A/B are no longer competing routes: high-resolution IIO/CPU/GPU and FPGA low-resolution shadow are backend options under one scan session. The goal is seconds-level scan improvement, such as moving a minute-scale scan toward about 10 seconds, not shaving a few milliseconds from isolated refill or FFT kernels.
- On 2026-06-09 19:52 Asia/Shanghai, a current implemented SDR software-function timing inventory was added. It uses existing independent logs, read-only active NX source inspection, and one offline NX synthetic CPU benchmark that imported active `robot_control` modules without IIO connect, SDR retune, ROS runtime, mapping, navigation, motion, BOOT/SD staging, or active file edits. Key findings: active CPU PSD/AoA math is sub-ms on synthetic NX data; existing live raw-IIO compare capture is about 29 ms median; current FPGA sidecar validation transport is about 0.8 s and not a fast runtime path; default heatmap/full-fingerprint scan profiles already contain seconds-scale repeated settle lower bounds. Evidence: `reports\p201_current_sdr_function_timing_inventory_20260609.md` and `.json`.

## Next Safe Work

Use this order unless `VERSION_ROUTE.md` is updated:

```text
1. Keep V8L1 as the hardware-validated baseline.
2. Use the V8D0 PASS result as evidence that V8L1-like fresh layout alone did not break AD9361/IIO.
3. Stop treating FPGA FFT or SDR-local refill as the primary optimization target.
4. Build the unified offline band-scan/session timing harness first: replay/synthetic payload timing, then a separately approved isolated non-ROS 1/6/11 live scan with per-function timing for connect, retune, settle, read_raw_i16, analyze_spectrum_batch, aggregation, occupancy scoring, spectrum compression, JSON payload, and optional AoA hook.
5. Use CPU/GPU high-resolution and FPGA low-resolution paths as interchangeable backends only when they improve session-level timing or payload size.
6. A live retune/session test requires separate approval, pre/post IIO health, state snapshot/restore, and no ROS/runtime/motion.
7. Do not enter bitstream/BOOT/SD work unless the session model shows FPGA removes a seconds-level cost block.
8. Do not call V10S0/V10S4/V10S5 FFT runtime, PSD runtime, active NX runtime integration, or hardware validated beyond their stated scope.
9. Do not start ROS, SDR streaming runtime, mapping, RTAB-Map, robot_controller, cmd_vel, navigation, or robot motion.
```

Important documents:

```text
E:\vivado\fpga_p201pro_accel\VERSION_ROUTE.md
E:\vivado\fpga_p201pro_accel\PROJECT_MAP.md
E:\vivado\fpga_p201pro_accel\docs\P201PRO_PROJECT_LEVEL_BAND_SCAN_OPTIMIZATION_PLAN.md
E:\vivado\fpga_p201pro_accel\docs\P201PRO_PHASE1_FFT_PSD_SHADOW_PLAN.md
E:\vivado\fpga_p201pro_accel\docs\P201PRO_V10S5_COMBINED_SELFTEST_PLAN.md
E:\vivado\fpga_p201pro_accel\docs\P201PRO_REUSABLE_SUBMODULE_MATRIX_20260610.md
E:\vivado\fpga_p201pro_accel\docs\P201Pro_V8L2_AD9361_FAILURE_ROOT_CAUSE_AND_V8L3_PLAN.md
E:\vivado\fpga_p201pro_accel\docs\archive\P201PRO_CLEANUP_LOG_20260609.md
```

Current top-level optimization plan:

```text
docs\P201PRO_PROJECT_LEVEL_BAND_SCAN_OPTIMIZATION_PLAN.md
```

Current Phase 1 FPGA backend plan:

```text
docs\P201PRO_PHASE1_FFT_PSD_SHADOW_PLAN.md
```

Current Phase 1 A-lane handoff:

```text
experiments\phase1_fft_shadow_selftest\HANDOFF.md
```

It keeps Phase 1 focused on local C mmap/UIO transport, FFT/PSD summary shadow,
top peaks, limited coarse PSD bins, independent NX shadow compare, and
active-package dry-run only. Phase 2 AoA phase/coherence work is intentionally
left as aperture only until Phase 1 evidence is complete.

The old 20260610 day-plan document was deleted. Do not use it as current route.
Current state is in `VERSION_ROUTE.md`, this handoff, and the reports/logs named
there.

Current NX experiment scope:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test
```

Use Git for meaningful state changes. `VERSION_ROUTE.md` remains the version
source of truth.
