# P201Pro SDR FPGA Version Route

Last updated: 2026-06-09 19:20 Asia/Shanghai

This file is the fast locator for FPGA SDR offload versions. Update it whenever a version is built, packaged, rejected, or hardware-validated.

Worktree note: historical artifact paths are rooted at
`E:\vivado\fpga_p201pro_accel`. If using the active
`E:\vivado\fpga_p201pro_accel_mainline` worktree, keep commands local to that
git root and do not promote side-path V10S5 evidence into the mainline route
until the artifact gate is complete.

Project map and cleanup policy:

```text
E:\vivado\fpga_p201pro_accel\PROJECT_MAP.md
```

Retired plan note:

```text
The old 20260610 day-plan document was deleted after second-day work began.
Do not use or recreate it as a current route. Use this VERSION_ROUTE.md,
HANDOFF.md, and current reports instead.
```

Canonical FPGA/NX kernel contract:

```text
E:\vivado\fpga_p201pro_accel\docs\P201_SDR_FPGA_KERNEL_CONTRACT.md
E:\vivado\fpga_p201pro_accel\docs\FPGA_NX_KERNEL_API_ROADMAP.md
```

Current flexible Phase 1 compute-offload plan:

```text
E:\vivado\fpga_p201pro_accel\docs\P201PRO_PHASE1_FFT_PSD_SHADOW_PLAN.md
```

Current project-level optimization plan:

```text
E:\vivado\fpga_p201pro_accel\docs\P201PRO_PROJECT_LEVEL_BAND_SCAN_OPTIMIZATION_PLAN.md
```

Current Phase 1 A-lane handoff:

```text
E:\vivado\fpga_p201pro_accel\experiments\phase1_fft_shadow_selftest\HANDOFF.md
```

The project-level band-scan/session plan is now the top-level optimization
direction. The FFT/PSD shadow plan remains useful backend evidence, but it is no
longer the primary route by itself. Do not push FPGA or IIO micro-optimization
unless it improves seconds-level scan/session timing. This does not promote any
version, does not claim FFT/PSD runtime integration, and leaves Phase 2 AoA
phase/coherence as an aperture until the unified scan/session evidence is good.

Independent NX interface files:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\sdr_kernel_contract.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\sdr_kernel_client.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\fpga_assisted_metrics.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\feature_flag_assist.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\native_transport.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\fft_shadow_client.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\include\p201_sdr_kernel_contract.hpp
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\native\p201_native_mmio.c
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\native\p201_native_mmio.h
```

Current Phase 1 software progress:

```text
P1.1 native C mmap/UIO transport fake-register tests PASS on 2026-06-09.
SDR-local native mmap board probe PASS on the current-loaded V10S0/V8D0 image:
read-only SUM8/AGG8 identity passed, explicit arm/read 64x64 passed, repeat20
with poll-us=50 passed 20/20, and post-test AD9361/IIO health remained good.
This is transport evidence only: no FFT/PSD hardware exists, no active runtime
is integrated, and no FPGA version is promoted.
`fpga_fft_shadow` software ABI draft now reserves page 0x400..0x6fc for summary,
four top peaks, and 64..128 coarse PSD bins with 96 preferred. This also does
not promote any FPGA version.
P1.2 offline FFT/PSD reference and tolerance gate PASS on 2026-06-09. The
reference matches the current NX Hann/fftshift/coherent-gain PSD shape, keeps an
exact 96-bin coarse PSD ABI with `coarse_bin_step_q16=1398101` for 2048-point
FFT input, and records the current UI max-hold compressor difference
(`2048 -> 98` bins when max_bins is 96). No live 2048-point FPGA FFT/PSD
hardware exists yet.
P1.3 isolated `fpga_fft_shadow` RTL self-test PASS on 2026-06-09. A PC-only
AXI-Lite fixture now exposes the `0x400..0x6fc` ABI with summary, four top
peaks, 96 populated coarse PSD bins, and reserved bins 96..127 reading zero.
XSIM PASS and OOC synth PASS with WNS +6.476 ns, WHS +0.129 ns, 103 LUT,
30 FF, 0 BRAM, 0 DSP. This is deterministic register-shape evidence only:
no live AD9361 FFT/PSD hardware, no bitstream, no BOOT/SD payload, no board
staging, no hardware validation, and no FPGA version promotion exists.
P1.3b isolated top-4 PSD peak reducer PASS on PC on 2026-06-09. It adds a
timing-clean signed reducer primitive with guard-bin suppression for the
`fpga_fft_shadow` post-PSD summary path. XSIM PASS covers the reducer testbench;
OOC timing PASS at 8.138 ns with WNS +1.102 ns, WHS +0.129 ns, 340 LUT,
509 FF, 0 BRAM, 0 DSP. This is not FFT, not PSD generation, not live AD9361
integration, not a bitstream/BOOT/SD artifact, and not a version promotion.
P1.3c isolated coarse96 PSD reducer PASS on PC on 2026-06-09. It adds an exact
2048-to-96 signed PSD max-hold reducer matching the P1.2 grouping rule and
`coarse_bin_step_q16=1398101`. XSIM PASS and OOC timing PASS at 8.138 ns with
WNS +2.264 ns, WHS +0.185 ns, 2138 LUT, 3275 FF, 0 BRAM, 0 DSP. This is not
FFT, not PSD generation, not live AD9361 integration, not a bitstream/BOOT/SD
artifact, and not a version promotion. P1.4 must review whether 96 direct
AXI-Lite coarse bins should stay in the runtime register path.
P1.3d isolated FFT4 smoke core PASS on PC on 2026-06-09. It adds a 4-point
complex FFT butterfly datapath with per-bin power, total power, and peak
summary. XSIM PASS and OOC timing PASS at 8.138 ns with WNS +1.424 ns,
WHS +0.132 ns, 1299 LUT, 856 FF, 0 BRAM, 8 DSP. This is a minimal true-FFT
datapath smoke test only: not a 2048-point FFT/window/PSD generator, not live
AD9361 integration, not a bitstream/BOOT/SD artifact, and not a version
promotion.
P1.4a FFT shadow integration review COMPLETE on PC on 2026-06-09. It records
that P1.1 native transport, P1.2 reference/tolerance, P1.3 ABI fixture, P1.3b
top-4 reducer, P1.3c coarse96 reducer, and P1.3d FFT4 smoke core are usable
building blocks, but the 2048-point FFT/window/PSD generator and live AD9361
coupling are still missing. The recommended next step is an isolated Xilinx FFT
IP or equivalent OOC probe before any V8-derived live tap integration. This
does not add RTL, does not generate a bitstream/BOOT/SD payload, does not stage
or validate hardware, and does not promote any FPGA version.
P1.4b XFFT2048 probe PASS on PC on 2026-06-09. Vivado 2019.1 can create
`xilinx.com:ip:xfft:9.1` and run an isolated 2048-point fixed-point
pipelined-streaming IP OOC probe for `xc7z020clg400-2` at 122.88 MHz
(`8.138 ns`). OOC synthesis and timing PASS with WNS +5.029 ns, WHS +0.190 ns,
3153 LUT, 5063 FF, 7 RAMB18, and 15 DSP. This proves the reproducible XFFT IP
entry only: no Hann/window, no PSD scaling/log path, no top-4/coarse96
composition, no live AD9361 coupling, no bitstream/BOOT/SD payload, no board
staging, no hardware validation, and no version promotion. The next safe
A-route step is a PC-only composition probe that bridges XFFT-style streaming
output framing into PSD powers and the existing top-4/coarse96 reducers.
```

## Recommended Test Order

Recommended active hardware test order:

```text
1. V8L1 / SUM8 + QUA8 + AGG8 auto-aggregate candidate, current highest hardware-validated bypass offload
2. V8 / SUM8 + AGG8 multi-frame hardware aggregate candidate, first validated rollback
3. V7 / SUM7 quality page validated rollback
4. V6 / SUM6 block ABI validated production-summary fallback
5. V4 / SUM4 mean-corrected snapshot debug fallback only
```

V5 booted but failed production consistency and is not in the active test order.

Current highest hardware-validated candidate:

```text
V8L1 / SUM8 + QUA8 + AGG8 auto-aggregate candidate
```

Latest V9A hardware validation attempt:

```text
V9A / SUM9 + QUA9 + AGG9 + SPEC9 four-bin coarse spectral proxy
```

Current forward baseline:

```text
V8L1 / SUM8 + QUA8 + AGG8 auto-aggregate candidate, hardware-validated after physical SDR power-cycle
```

Latest V10S0 reusable submodule self-test artifact:

```text
V10S0 / V8D0 base + isolated AXI-Lite submodule self-test page at 0x43C10000
```

Status:

```text
XSIM PASS, OOC synth PASS, IP package PASS, BD integration PASS, full bitstream PASS,
Bootgen PASS, SD payload generated. SDR /sd staging PASS on 2026-06-09
10:48 Asia/Shanghai; all five remote hashes matched and sync was run.
Physical SDR power-cycle validation PASS on 2026-06-09 10:52 Asia/Shanghai:
/sd hashes PASS, AD9361/IIO health PASS, V8D0 base registers PASS,
V10S0 identity registers PASS, and V10S0 deterministic self-test registers
PASS. Hardware-validated as an isolated reusable submodule self-test only.
```

Artifact:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s0_submodule_selftest
```

Payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s0_submodule_selftest\sd_payload
```

BOOT hash:

```text
83ff655ff8cba879b2c37568cc99399ad3c3deecadaf56f5961c664aed61be1b
```

Expected V10S0 identity:

```text
devmem 0x43C10000 32 -> 0x53305430
devmem 0x43C10018 32 -> 0x0000000F
devmem 0x43C1001C 32 -> 0x56313053
devmem 0x43C10020 32 -> 0x000A2000
```

Use V10S0 only as an isolated reusable submodule hardware-test candidate. It
does not connect AD9361 sample/valid/clock/reset nets, and it is not live
FFT/PSD/runtime integration.

Staging evidence:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s0_submodule_selftest\stage_v10s0_submodule_selftest_to_sdr_sd_20260609.json
E:\vivado\fpga_p201pro_accel\reports\p201_v10s0_submodule_selftest_sd_staging_20260609.md
E:\vivado\fpga_p201pro_accel\reports\p201_v10s0_submodule_selftest_after_powercycle_20260609.json
E:\vivado\fpga_p201pro_accel\reports\p201_v10s0_submodule_selftest_hardware_validation_20260609.md
```

Mainline passive live shadow evidence on the V10S0 image's V8D0 base:

```text
2026-06-09 12:08 Asia/Shanghai:
SUM8/QUA8/AGG8 V8D0 live tap base at 0x43C00000 was used from the independent
NX experiment directory. Extended devmem-only passive read PASS, 20/20 captures
at frame_len=64 with agg_frames=16/64/256/1024. Extended raw-IIO vs FPGA AGG8
shadow compare PASS, 15/15 captures: 10/10 at agg_frames=64 and 5/5 at
agg_frames=256. CPU raw-IQ and FPGA AGG8 windows were adjacent/nearby, not
hardware-synchronized, so this is passive shadow workflow evidence only.

An auto-roll/latest-window probe on the same base did not pass the sequence
advance check: 1/8 reads passed, sequence_deltas were all 0 after the first
read, with control 0x00000015. Treat the current V10S0/V8D0 base as a stable
explicit arm/read passive aggregate backend, not an auto-roll runtime polling
backend. It is not active NX robot_control integration, not feature-flag assist,
not ROS, and not a new hardware-validation promotion.
```

Independent feature-flag assist prototype on the same base:

```text
2026-06-09 12:20 Asia/Shanghai:
An explicit arm/read feature-flag assist prototype was added under the
independent NX experiment directory. Shadow mode PASS, 5/5: CPU remained the
selected source while FPGA sidecar reads succeeded. Default assist mode PASS,
5/5: FPGA reads succeeded but all 5 decisions fell back to CPU because the AoA
phase was clipped by the conservative policy gate. Primitive-assist mode with
allow_aoa_phase_clipped PASS, 5/5: FPGA primitives were selected while the
clipped AoA flag remained visible to NX policy.

This is the next mainline shape: FPGA provides SUM8/AGG8 primitives through an
explicit arm/read feature flag; NX keeps fallback, calibration, clipping policy,
and publication. This is still independent-experiment evidence only, not active
robot_control integration.

2026-06-09 12:27 Asia/Shanghai:
Current-loaded FPGA identity was rechecked by read-only registers after the user
noted no new physical power-cycle had happened. The loaded image exposes V8D0
base IDs at 0x43C00000 and the V10S0 self-test page at 0x43C10000:
BASE_BUILD=0x56384430, BASE_QUALITY_BUILD=0x51384430,
BASE_AGG_BUILD=0x41384430, V10S0_MAGIC=0x53305430,
V10S0_DONE=0x0000000F, V10S0_BUILD=0x56313053. V10S4 and V10S5 pages were not
present. Therefore the feature-flag assist probes below are current-loaded-image
board tests only; they are not a new SD payload staging or post-power-cycle
hardware-validation event.

Stress probe results on the current-loaded V10S0/V8D0 image: default assist
stress20 PASS, FPGA read OK 20/20, selected FPGA 1/20, CPU fallback 19/20 due to
conservative aoa_phase_clipped gate. Primitive-assist with
allow_aoa_phase_clipped stress20 PASS, FPGA read OK 20/20, selected FPGA 20/20.

2026-06-09 12:34 Asia/Shanghai:
Stress100 current-loaded board test PASS. Default assist: FPGA read OK 100/100,
selected FPGA 4/100, CPU fallback 96/100; gate failures were
aoa_phase_clipped=94 and coherence_below_gate=7. Primitive-assist with
allow_aoa_phase_clipped: FPGA read OK 100/100, selected FPGA 97/100, CPU
fallback 3/100 due to coherence_below_gate=3. Post-stress read-only health
remained good: V8D0/V10S0 identity registers still matched, and IIO still found
ad9361-phy plus cf-ad9361-lpc.
```

Evidence:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\sum8_v8d0_passive_read_20260609_fast_mainline.json
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\sum8_v8d0_shadow_compare_20260609_fast_mainline.json
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\sum8_v8d0_passive_read_20260609_extended_mainline.json
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\sum8_v8d0_shadow_compare_20260609_extended64_mainline.json
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\sum8_v8d0_shadow_compare_20260609_extended256_mainline.json
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\v8d0_auto_roll_batch_ssh_20260609_mainline.json
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\feature_flag_assist_shadow_v8d0_20260609_mainline.json
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\feature_flag_assist_assist_v8d0_20260609_mainline.json
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\feature_flag_assist_primitive_allow_clip_v8d0_20260609_mainline.json
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\feature_flag_assist_assist_v8d0_20260609_stress20_mainline.json
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\feature_flag_assist_primitive_allow_clip_v8d0_20260609_stress20_mainline.json
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\feature_flag_assist_assist_v8d0_20260609_stress100_mainline.json
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\logs\feature_flag_assist_primitive_allow_clip_v8d0_20260609_stress100_mainline.json
```

Latest V10S4 non-FFT reusable submodule self-test artifact:

```text
V10S4 / V8D0 base + isolated non-FFT AXI-Lite self-test page at 0x43C20000
```

Status:

```text
V10S1/V10S2/V10S3 XSIM PASS, combined OOC PASS. V10S4 XSIM PASS,
OOC synth PASS, IP package PASS, BD integration PASS, full bitstream PASS,
Bootgen PASS, SD payload generated. SDR /sd staging PASS on 2026-06-09
10:36 Asia/Shanghai; all five remote hashes matched and sync was run. Physical
SDR power-cycle validation was attempted on 2026-06-09. /sd hashes, V8D0 base
registers, and V10S4 deterministic self-test registers PASS, but AD9361/IIO
health FAIL: `cf-ad9361-lpc` missing, `Tuning TX FAILED`, and `cf_axi_adc`
probe error `-5`. NOT HARDWARE VALIDATED.
```

Artifact:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s4_nonfft_selftest
```

Payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s4_nonfft_selftest\sd_payload
```

BOOT hash:

```text
df773e5b8b01f301634ff838f462464289213cfb4bba6c11855d022e08a377ce
```

Expected V10S4 identity:

```text
devmem 0x43C20000 32 -> 0x53345430
devmem 0x43C20018 32 -> 0x00000007
devmem 0x43C2001C 32 -> 0x56313034
devmem 0x43C20020 32 -> 0x000A4000
```

V10S4 is an isolated deterministic non-FFT submodule self-test candidate for
quality stats, frame/window, and energy/peak reducers. It does not connect
AD9361 sample/valid/clock/reset nets, and it is not FFT, not PSD, not live
AD9361 integration, and not active NX robot_control integration.

Staging evidence:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s4_nonfft_selftest\stage_v10s4_nonfft_selftest_to_sdr_sd_20260609.json
E:\vivado\fpga_p201pro_accel\reports\p201_v10s4_nonfft_selftest_sd_staging_20260609.md
E:\vivado\fpga_p201pro_accel\reports\p201_v10s4_nonfft_selftest_after_powercycle_20260609.json
E:\vivado\fpga_p201pro_accel\reports\p201_v10s4_nonfft_selftest_hardware_failure_20260609.md
```

V10S4 registers were read from hardware and passed, but the candidate failed
AD9361/IIO health. Do not call V10S4 hardware-validated. Roll back to V8L1
first, then V8 if needed.

Latest V10S5 combined reusable submodule self-test candidate:

```text
V10S5 / planned V8D0 base + isolated combined AXI-Lite self-test page at 0x43C30000
```

Status:

```text
Source-level RTL/test/scripts prepared for review. FFT-family sidecar and
non-FFT sidecar module checks were reported by subagents. Combined AXI wrapper
XSIM PASS and OOC synth PASS on 2026-06-09, timing-clean at WNS +4.021 ns and
WHS +0.129 ns. No IP package, BD integration, bitstream, Bootgen, SD payload,
SDR staging, or hardware validation exists yet.
```

Candidate files:

```text
E:\vivado\fpga_p201pro_accel\experiments\v10s5_combined_selftest
E:\vivado\fpga_p201pro_accel\docs\P201PRO_V10S5_COMBINED_SELFTEST_PLAN.md
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\validate_v10s5_combined_selftest_after_powercycle_via_nx.py
E:\vivado\fpga_p201pro_accel\scripts\xsim_v10s5_combined_selftest.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_ooc_v10s5_combined_selftest.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_package_v10s5_combined_selftest_ip.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_integrate_v10s5_combined_selftest_v8d0_base.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_impl_bitstream_v10s5_combined_selftest_v8d0_base.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_postroute_physopt_v10s5_combined_selftest_v8d0_base.tcl
```

Expected V10S5 identity, after a successful future build:

```text
devmem 0x43C30000 32 -> 0x53355430
devmem 0x43C30018 32 -> 0x0000003F
devmem 0x43C3001C 32 -> 0x56313035
devmem 0x43C30020 32 -> 0x000A5000
```

V10S5 is not live AD9361 integration, not a proven FFT/PSD runtime path, not an
active NX robot_control integration, not staged, and not hardware validated.
The current combined wrapper defaults to deterministic internal mirrors; it is
not yet the true external-sidecar-core integration unless that interface is
explicitly reviewed and enabled.

Latest V8L2 hardware validation attempt:

```text
V8L2 / SUM8 + QUA8 + AGG8 continuous auto-roll fix candidate, identity registers PASS but AD9361/IIO FAIL, NOT hardware-validated
```

Current root-cause plan:

```text
E:\vivado\fpga_p201pro_accel\docs\P201Pro_V8L2_AD9361_FAILURE_ROOT_CAUSE_AND_V8L3_PLAN.md
```

Current forward engineering direction:

```text
Do not use rollback as the main path. Continue from the V8L1 hardware-validated
baseline with offline V8-derived diagnostic builds. First isolate whether
fresh implementation/layout churn alone breaks AD9361/IIO, then attempt the
continuous auto-roll fix with incremental/checkpoint-preserving implementation.
```

Offline diagnostic candidates now prepared:

```text
V8D0 / layout probe, V8L1 logic with build-ID-only HDL change
V8D1 / V8L2 auto-roll fix with V8L1-referenced incremental implementation script
```

Latest V8D0 staging state:

```text
V8D0 / layout probe was staged to SDR /sd on 2026-06-09 10:27 Asia/Shanghai.
The staging script reported PASS, all five remote /sd hashes matched the local
payload hashes, and sync was run. This was the pre-validation staging step;
the post-power-cycle validation below later passed.
```

Latest V8D0 hardware validation:

```text
V8D0 / layout probe passed post-power-cycle validation on 2026-06-09
10:32 Asia/Shanghai. /sd hashes PASS, AD9361/IIO health PASS,
V8D0 identity registers PASS, SPEC page read-zero PASS, and AGG8 no-motion
captures passed 3 / 3. V8D0 is hardware-validated as a diagnostic layout probe
only. V8L1 remains the current forward hardware-validated baseline.
```

Artifact:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8d0_layout_probe
```

Payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8d0_layout_probe\sd_payload
```

BOOT hash:

```text
3e2c59a32a6ba8b6a80fc9cfe4c4a0ec94a43051cbb1d383f99cbd596417f883
```

Staging evidence:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8d0_layout_probe\stage_v8d0_layout_probe_to_sdr_sd_20260609.json
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8d0_layout_probe_sd_staging_20260609.md
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8d0_layout_probe_after_powercycle_20260609.json
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8d0_layout_probe_hardware_validation_20260609.md
```

Post-power-cycle validation script:

```text
E:\vivado\fpga_p201pro_accel\scripts\validate_v8d0_layout_probe_after_powercycle_via_nx.py
```

V8D0 expected build IDs:

```text
devmem 0x43C000FC 32 -> 0x56384430
devmem 0x43C0013C 32 -> 0x51384430
devmem 0x43C001F8 32 -> 0x41384430
```

V8D1 expected build IDs:

```text
devmem 0x43C000FC 32 -> 0x56384431
devmem 0x43C0013C 32 -> 0x51384431
devmem 0x43C001F8 32 -> 0x41384431
```

Candidate files:

```text
E:\vivado\fpga_p201pro_accel\experiments\v8d0_layout_probe
E:\vivado\fpga_p201pro_accel\experiments\v8d1_incremental_auto_roll_fix
E:\vivado\fpga_p201pro_accel\scripts\vivado_package_ad9361_power_tap_ip_v8d0_layout_probe.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_integrate_ad9361_power_tap_v8d0_layout_probe.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_impl_bitstream_integrated_ad9361_tap_project_v8d0_layout_probe.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_postroute_physopt_integrated_ad9361_tap_project_v8d0_layout_probe.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_package_ad9361_power_tap_ip_v8d1_incremental_auto_roll_fix.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_integrate_ad9361_power_tap_v8d1_incremental_auto_roll_fix.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_impl_bitstream_integrated_ad9361_tap_project_v8d1_incremental_auto_roll_fix.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_postroute_physopt_integrated_ad9361_tap_project_v8d1_incremental_auto_roll_fix.tcl
```

Current validated production-summary fallback:

```text
V6 / SUM6 block ABI and widened corrected-path metadata
```

V3/V2/V1 have already been hardware-tested or superseded and are not part of the normal active burn list. Keep them only as historical rollback/locator baselines:

```text
V3 / SUM3 hardware-validated dual-RX snapshot baseline
V2 / SUM2 intermediate snapshot/debug baseline
V1 / SUM1 first hardware-validated single-RX summary
```

Do not test any version by writing to the original SD backup. Use a copied SD card or new SD card only.

## V8L2 / SUM8 + QUA8 + AGG8 Continuous Auto-Roll Fix Candidate

Status: PC-built, timing-clean after post-route phys_opt, Bootgen PASS, SD
payload generated and staged to SDR `/sd`, then synced, physical SDR
power-cycle validation attempted. V8L2 identity registers PASS, but AD9361/IIO
health FAIL. NOT HARDWARE VALIDATED.

Do not continue V8L2 as an active hardware candidate unless explicitly
diagnosing AD9361 interface sensitivity. It fixes the V8L1 auto-roll continuity
stall in RTL, but the generated hardware image reproduced the TX tuning /
`cf-ad9361-lpc` failure pattern. V8L1 remains the current highest
hardware-validated version.

What it does:

- Keeps the V8L1 SUM8/QUA8/AGG8 register surface.
- Bumps build IDs to V8L2/Q8L2/A8L2.
- Preserves manual/classic aggregate stop-on-done behavior.
- Lets auto mode continue accepting samples across target windows.
- Does not add SPEC, FFT, BRAM, DMA, ROS, SDR streaming runtime, or active
  robot-control integration.

Artifact directory:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8l2_auto_roll_fix
```

BOOT and payload:

```text
BOOT hash: 1f7935fb9153966eb9eb9cec9f4f1fa2364ac54e45badced0848fac4b43e5248
Payload: E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8l2_auto_roll_fix\sd_payload
```

Current SDR `/sd` staging evidence:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8l2_auto_roll_fix\stage_v8l2_auto_roll_fix_to_sdr_sd_20260608.json
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8l2_auto_roll_fix_sd_staging_20260608.md
```

Hardware validation attempt after physical power-cycle:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8l2_auto_roll_fix_after_powercycle_20260608.json
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8l2_auto_roll_fix_hardware_failure_20260608.md
```

SDR `/sd` staging result:

```text
remote_before_hashes: V8L1 BOOT bdd7e27c4cd02259cb891e06bc25cdf70f0763de55dda77d2853da660a8f24aa
remote_after_hashes:  V8L2 BOOT 1f7935fb9153966eb9eb9cec9f4f1fa2364ac54e45badced0848fac4b43e5248
devicetree/uEnv/uImage/uramdisk hashes match the known-good companion files
sync was run on SDR after copying
```

PC artifact evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8l2_auto_roll_fix_pc_artifacts_20260608.md
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8l2_auto_roll_fix_pc_artifacts_20260608.json
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_ip_v8l2_auto_roll_fix
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_integration_v8l2_auto_roll_fix
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_integrated_synth_v8l2_auto_roll_fix
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream_physopt_v8l2_auto_roll_fix
```

Expected registers after SDR `/sd` staging and physical SDR power-cycle:

```text
devmem 0x43C00040 32 -> 0x53554D38
devmem 0x43C000EC 32 -> 0x00010002
devmem 0x43C000F0 32 -> 0x000003FF
devmem 0x43C000FC 32 -> 0x56384C32
devmem 0x43C00100 32 -> 0x51554138
devmem 0x43C00138 32 -> 0x0000000F
devmem 0x43C0013C 32 -> 0x51384C32
devmem 0x43C00180 32 -> 0x41474738
devmem 0x43C001F4 32 -> 0x0000003F
devmem 0x43C001F8 32 -> 0x41384C32
devmem 0x43C00200 32 -> 0x00000000
devmem 0x43C002F0 32 -> 0x00000000
devmem 0x43C002F4 32 -> 0x00000000
devmem 0x43C002F8 32 -> 0x00000000
devmem 0x43C002FC 32 -> 0x00000000
```

Hashes:

```text
1f7935fb9153966eb9eb9cec9f4f1fa2364ac54e45badced0848fac4b43e5248  BOOT_p201_summary_v8l2_auto_roll_fix.bin
87805373c852e0a2932045c6180d8bb3595d95970054a39395f79ca24a97027a  system_top_with_p201_v8l2_auto_roll_fix.bit
```

Timing:

```text
Post-route physopt WNS +0.015 ns
Post-route physopt WHS +0.053 ns
route fully routed
routing errors 0
```

Vivado/Bootgen status:

```text
IP packaging: PASS
BD validation: PASS
integrated synthesis: PASS
post-route phys_opt_design: PASS
route_design: PASS
write_bitstream: PASS
Bootgen: PASS
DRC: 0 errors; 0 critical warnings; known warning/advisory classes remain
```

NX validation script:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\benchmark_v8l1_auto_roll_batch_ssh.py
```

Post-power-cycle result:

```text
/sd BOOT hash PASS
V8L2 identity registers PASS
SPEC page disabled/read-zero PASS
AD9361/IIO health FAIL
cf-ad9361-lpc missing
dmesg: ad9361_dig_tune_delay: Tuning TX FAILED!
dmesg: cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
continuous AGG auto-roll benchmark was not run because IIO health failed first
```

V8L1 rollback staging after V8L2 failure:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8l1_auto_agg\stage_v8l1_rollback_after_v8l2_to_sdr_sd_20260608.json
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8l1_rollback_after_v8l2_sd_staging_20260608.md
remote_before_hashes: V8L2 BOOT 1f7935fb9153966eb9eb9cec9f4f1fa2364ac54e45badced0848fac4b43e5248
remote_after_hashes:  V8L1 BOOT bdd7e27c4cd02259cb891e06bc25cdf70f0763de55dda77d2853da660a8f24aa
sync was run on SDR after copying
physical SDR power-cycle is still required before rollback validation
```

Fallback:

```text
V8L1 first, then V8.
```

## V8L1 / SUM8 + QUA8 + AGG8 Auto-Aggregate Candidate

Status: hardware-validated after PC build, post-route phys_opt, Bootgen, SDR
`/sd` staging, physical SDR power-cycle, AD9361/IIO health, V8L1 identity
registers, and no-motion AGG auto-roll captures.

Intent:

```text
V8-derived low-NX-load AGG8 auto-roll candidate.
Keep the V8 AD9361/IIO-safe base and reduce NX register polling.
No SPEC, FFT, BRAM, DMA, ROS, streaming runtime, or robot-control integration.
```

Artifact directory:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8l1_auto_agg
```

BOOT and payload:

```text
BOOT hash: bdd7e27c4cd02259cb891e06bc25cdf70f0763de55dda77d2853da660a8f24aa
Payload: E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8l1_auto_agg\sd_payload
```

Evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_v8l1_auto_agg_bitstream_gate_20260608.md
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8l1_auto_agg_pc_artifacts_20260608.json
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8l1_auto_agg_sd_staging_20260608.md
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8l1_auto_agg_hardware_validation_20260608.md
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8l1_auto_agg_after_powercycle_20260608.json
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8l1_auto_agg\stage_v8l1_auto_agg_to_sdr_sd_20260608.json
E:\vivado\fpga_p201pro_accel\scripts\validate_v8l1_auto_agg_after_powercycle_via_nx.py
```

SDR `/sd` staging result:

```text
remote_before_hashes: V8 BOOT   6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
remote_after_hashes:  V8L1 BOOT bdd7e27c4cd02259cb891e06bc25cdf70f0763de55dda77d2853da660a8f24aa
devicetree/uEnv/uImage/uramdisk hashes match the known-good V8 companion files
sync was run on SDR after copying
```

Hardware validation after physical power-cycle:

```text
/sd BOOT hash == bdd7e27c4cd02259cb891e06bc25cdf70f0763de55dda77d2853da660a8f24aa
cf-ad9361-lpc registered
AD9361/IIO health PASS
devmem 0x43C00040 32 -> 0x53554D38
devmem 0x43C000FC 32 -> 0x56384C31
devmem 0x43C00100 32 -> 0x51554138
devmem 0x43C0013C 32 -> 0x51384C31
devmem 0x43C00180 32 -> 0x41474738
devmem 0x43C001F4 32 -> 0x0000003f
devmem 0x43C001F8 32 -> 0x41384C31
AGG auto-roll capture: 3 / 3 PASS
```

## V9B0 / S9B0 + Q9B0 + A9B0 Minimal Isolation Candidate

Status: PC-built, timing-clean after post-route phys_opt, Bootgen PASS, SD payload staged to SDR `/sd`, physical SDR power-cycle validation attempted. All V9B0 identity registers PASS, but AD9361/IIO health FAIL. NOT HARDWARE VALIDATED.

Use V9B0 as the next hardware-changing diagnostic after V9A/SPEC9 failed AD9361/IIO health. It keeps SUM/QUA/AGG style behavior close to V8/V9A but disables the SPEC page/readback behavior so the test isolates whether V9A's SPEC-sized footprint/routing/fanout contributed to TX tuning failure and `cf-ad9361-lpc` absence.

What it does:

- Uses a separate candidate HDL copy under the V9B0 artifact directory.
- Preserves the intended FPGA/NX split: FPGA exposes fixed-shape summary registers; NX owns divide/sqrt/atan2/calibration/fallback/logging.
- Exposes V9B0 identity registers on the SUM/QUA/AGG pages.
- Forces SPEC identity/capability/bin-count/readbacks to zero.
- Removes active SPEC bin accumulation from the ADC hot path.

What it is not:

- Not hardware-validated yet.
- Not FFT.
- Not PSD.
- Not calibrated spectrum.
- Not active NX robot_control integration.

Artifact directory:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9b0_minimal_isolation
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9b0_minimal_isolation\BOOT_p201_summary_v9b0_minimal_isolation.bin
```

Ready-to-copy SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9b0_minimal_isolation\sd_payload
```

PC artifact evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9b0_minimal_isolation_pc_artifacts_20260608.md
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9b0_minimal_isolation_pc_artifacts_20260608.json
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_ip_v9b0
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_integration_v9b0
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_integrated_synth_v9b0
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream_physopt_v9b0
```

Current SDR `/sd` staging evidence:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9b0_minimal_isolation\stage_v9b0_to_sdr_sd_20260608.json
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9b0_minimal_isolation_sd_staging_20260608.md
```

Hardware validation attempt after physical power-cycle:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9b0_minimal_isolation_after_powercycle_20260608.json
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9b0_minimal_isolation_hardware_failure_20260608.md
```

Result:

```text
remote_before_hashes: V8 BOOT 6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
remote_after_hashes:  V9B0 BOOT 0051864c24513248e78fde9bb6ced7d465b4a0c5df6cee804bbafb50d55d35e2
devicetree/uEnv/uImage/uramdisk hashes match the known-good companion files
sync was run on SDR after copying
```

Post-power-cycle result:

```text
/sd hashes: PASS
V9B0 identity registers: PASS
AD9361/IIO health: FAIL
cf-ad9361-lpc missing
dmesg: ad9361_dig_tune_delay: Tuning TX FAILED!
dmesg: cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
```

V8 rollback staging after V9B0 failure:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8\stage_v8_rollback_after_v9b0_to_sdr_sd_20260608.json
remote_before_hashes: V9B0 BOOT 0051864c24513248e78fde9bb6ced7d465b4a0c5df6cee804bbafb50d55d35e2
remote_after_hashes:  V8 BOOT   6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
sync was run on SDR after copying
```

Expected registers after SDR `/sd` staging and physical SDR power-cycle:

```text
devmem 0x43C00040 32 -> 0x53394230
devmem 0x43C000EC 32 -> 0x00010002
devmem 0x43C000F0 32 -> 0x000003ff
devmem 0x43C000FC 32 -> 0x56394230
devmem 0x43C00100 32 -> 0x51394230
devmem 0x43C00138 32 -> 0x0000000f
devmem 0x43C0013C 32 -> 0x51394230
devmem 0x43C00180 32 -> 0x41394230
devmem 0x43C001F4 32 -> 0x0000001f
devmem 0x43C001F8 32 -> 0x41394230
devmem 0x43C00200 32 -> 0x00000000
devmem 0x43C002F0 32 -> 0x00000000
devmem 0x43C002F4 32 -> 0x00000000
devmem 0x43C002F8 32 -> 0x00000000
devmem 0x43C002FC 32 -> 0x00000000
```

Hashes:

```text
0051864c24513248e78fde9bb6ced7d465b4a0c5df6cee804bbafb50d55d35e2  BOOT_p201_summary_v9b0_minimal_isolation.bin
9a3f0a3dcc5bd220e63a2b06cc6c31ca96d2c513cfc78386e921aa423817cec8  system_top_with_p201_summary_v9b0_minimal_isolation.bit
```

Timing:

```text
OOC/IP: WNS +1.292 ns, WHS +0.037 ns
Post-route physopt: WNS +0.015 ns, WHS +0.053 ns
route fully routed
routing errors 0
```

Vivado/Bootgen status:

```text
IP packaging: PASS
BD validation: PASS
integrated synthesis: PASS
post-route phys_opt_design: PASS
route_design: PASS
write_bitstream: PASS
Bootgen: PASS
DRC: 0 errors; known warning/advisory classes remain
```

After-powercycle validation script:

```text
E:\vivado\fpga_p201pro_accel\scripts\validate_v9b0_minimal_isolation_after_powercycle_via_nx.py
```

Next safe step:

```text
Stop V9B0. Continue lowering NX load from the pre-V9A SUM8 snapshot, not from the V9A/V9B0 source line. Do not keep re-staging V8 unless rollback safety or a new hardware test explicitly requires it.
```

Fallback:

```text
V8L1 is now the current highest hardware-validated candidate. V8 remains the first rollback target if later V8L1-derived work fails AD9361/IIO health or register validation.
```

## V9A / SUM9 + QUA9 + AGG9 + SPEC9 PC-Built Candidate

Status: PC-built, timing-clean after post-route phys_opt, Bootgen PASS, SD payload staged to SDR `/sd`, physical power-cycle validation attempted. SUM9/QUA9/AGG9/SPEC9 registers PASS and SPEC9 captures PASS, but AD9361/IIO health FAIL. NOT HARDWARE VALIDATED. After live diagnosis reproduced the failure, V8 rollback payload was staged back to SDR `/sd`, synced, power-cycled, and validated.

Use V9A only for continued bypass diagnosis. Do not restage V9A as-is. V8L1 is now the current highest hardware-validated candidate; V8 remains the first rollback target.

What it does:

- Preserves V8-style SUM/QUA/AGG summary behavior while updating identity metadata to SUM9/QUA9/AGG9.
- Adds a `SPEC9` summary page at `0x200..0x2fc`.
- Computes a four-bin fixed coarse spectral proxy for gating and quality classification.
- Exposes dominant coarse bin, total coarse spectral proxy power, noise-floor proxy, prominence proxy, flags, and four bin powers.
- Keeps NX responsible for register orchestration, divide/sqrt/atan2, calibration, fallback, logging, and algorithm composition.

What it is not:

- Not hardware-validated yet.
- Not FFT.
- Not PSD.
- Not calibrated spectrum.
- Not active NX robot_control integration.

Artifact directory:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9\BOOT_p201_summary_v9a_spec9.bin
```

Ready-to-copy SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9\sd_payload
```

Current SDR `/sd` staging evidence:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9\stage_v9a_to_sdr_sd_20260608.json
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9a_spec9_iio_diagnosis_and_v8_rollback_20260608.md
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9a_spec9_iio_diagnosis_and_v8_rollback_20260608.json
```

Result:

```text
remote_before_hashes: V8 BOOT 6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
remote_after_hashes:  V9A BOOT 58de598eea686e857a5cbb82135fea6fca2c0c79904b65af5f1b4b5f5f259447
devicetree/uEnv/uImage/uramdisk hashes match the known-good companion files
sync was run on SDR after copying
```

Later V8 rollback staging after V9A IIO failure diagnosis:

```text
remote_before_hashes: V9A BOOT 58de598eea686e857a5cbb82135fea6fca2c0c79904b65af5f1b4b5f5f259447
remote_after_hashes:  V8 BOOT 6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
devicetree/uEnv/uImage/uramdisk hashes remained the known-good companion hashes
sync was run on SDR after copying
physical SDR power-cycle completed; V8 rollback validation PASS
```

V8 rollback validation after physical power-cycle:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8_after_v9a_rollback_powercycle_20260608.md
E:\vivado\fpga_p201pro_accel\reports\summary_v8_after_v9a_rollback_powercycle_20260608.json
```

Hardware validation attempt after physical power-cycle:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9a_spec9_hardware_validation_20260608.md
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9a_spec9_hardware_validation_20260608.json
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9a_spec9_iio_failure_diagnostics_20260608.json
```

Offline V9A TX tune root-cause review:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_v9a_tx_tune_root_cause_review_20260608.md
E:\vivado\fpga_p201pro_accel\reports\p201_v9a_tx_tune_root_cause_review_20260608.json
E:\vivado\fpga_p201pro_accel\reports\v9a_ad9361_interface_diagnostics_20260608
```

Result:

```text
/sd hashes: PASS
physical power-cycle evidence: PASS, SDR uptime 464.15 seconds at validation
SUM9/QUA9/AGG9/SPEC9 identity registers: PASS
SPEC9 capture consistency: 6 / 6 PASS
AD9361/IIO health: FAIL
cf-ad9361-lpc missing
dmesg: ad9361_dig_tune_delay: Tuning TX FAILED!
dmesg: cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
overall V9A hardware validation: FAIL / incomplete
```

Root-cause review assessment:

```text
Most likely implementation-side AD9361 interface sensitivity from V9A tap footprint/routing/fanout growth, not companion boot files or explicit TX-path wiring.
Recommended next hardware-changing experiment: V9B0 V8-compatible minimal isolation candidate before reintroducing SPEC9-sized logic.
```

Read-only live diagnosis before V8 rollback staging reconfirmed:

```text
/sd/BOOT.bin was V9A
runtime DTB was the validated LVDS-bias DTB
SUM9/QUA9/AGG9/SPEC9 registers were still alive
cf-ad9361-lpc was still missing
dmesg still showed Tuning TX FAILED and cf_axi_adc probe error -5
```

Expected registers after user-approved staging and physical SDR power-cycle:

```text
devmem 0x43C00040 32 -> 0x53554D39
devmem 0x43C000EC 32 -> 0x00010003
devmem 0x43C000F0 32 -> 0x000007FF
devmem 0x43C000FC 32 -> 0x56390001
devmem 0x43C00100 32 -> 0x51554139
devmem 0x43C00180 32 -> 0x41474739
devmem 0x43C00200 32 -> 0x53504339
devmem 0x43C002F0 32 -> 0x00000004
devmem 0x43C002F8 32 -> 0x53390001
devmem 0x43C002FC 32 -> 0x00010003
```

Hash:

```text
58de598eea686e857a5cbb82135fea6fca2c0c79904b65af5f1b4b5f5f259447  BOOT_p201_summary_v9a_spec9.bin
1929b3d70ffacb40dd5c6489f1c5db83e6d0ef2e071a47d03eb9da7accc19542  system_top_with_p201_summary_v9a_spec9.bit
```

Timing:

```text
WNS +0.015 ns
WHS +0.061 ns
clk_fpga_0 WNS +0.488 ns
rx_clk WNS +0.170 ns
route fully routed
routing errors 0
```

Vivado/Bootgen status:

```text
IP packaging: PASS
BD validation: PASS
write_bitstream Complete!
phys_opt_design: PASS
route_design: PASS
Bootgen: PASS
DRC: 0 Errors, 0 Critical Warnings; 121 warnings/advisories remain
SPEC9 reference selftest: 6 / 6 PASS
```

README:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9\README_SUMMARY_V9A_SPEC9.md
```

NX validation scripts:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\read_spec9_once.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\compare_spec9_reference.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\compare_spec9_batch_ssh.py
```

Fallback:

```text
V8 rollback is active and validated after physical SDR power-cycle. If V8 regresses, use V7, then V6, then V4 snapshot debug only.
```

Known reasons to skip V9A:

- You need a hardware-validated version now; use V8.
- You need real FFT/PSD; V9A is only a four-bin coarse proxy.
- You need healthy AD9361/IIO RX context; this V9A validation attempt did not register `cf-ad9361-lpc`.
- You need a safe next burn path; build a V9B0 isolation candidate instead of restaging V9A as-is.
- You need active SDR/runtime integration; V9A remains bypass-only and is not active NX integration.

## Performance Route Decision

Pre-write performance review for the next possible FFT/PSD version concluded:

```text
Historical V6 FFT/window/PSD HDL add-on: NO-GO
```

Reason:

- V5 is already the right large-step burnable candidate.
- FFT/window/PSD is a separate kernel architecture requiring buffering, scaling, coefficient management, FFT IP or custom pipeline choice, DMA/register protocol, validation vectors, and timing closure.
- Adding that scope at the same time risked losing the burnable path while V5 still needed hardware validation.

Next-stage architecture after V5 hardware validation:

```text
FPGA: optional Python-callable kernels such as FFT/window/PSD/noise/peak blocks.
NX: version routing, register/DMA reads, divide/sqrt/atan2/calibration, aggregation, fallback, frontend/ROS publication.
```

V6 performance review concluded:

```text
V6 register-only Block Summary ABI / width release: GO as a PC-built candidate after V5.
V6 FFT/window/PSD/DMA: still NO-GO.
```

Reason:

- It keeps the intended FPGA/NX split: FPGA performs fixed-shape high-rate reductions and metadata, NX composes algorithms and publishes later.
- It does not add FFT buffering, scale/window management, vector readback, DMA, or new clocking paths.
- It has higher DSP/resource pressure than V5, so V5 remains the first hardware burn target.

V7 performance review concluded:

```text
Full V7 with active abs-sum accumulators: NO-GO, WNS -0.371 ns.
Conservative SUM7A quality page without active abs sums: GO, timing-clean.
```

Reason:

- Keep the intended reusable-kernel split: FPGA exposes low-cost quality primitives; NX composes algorithms.
- Preserve 12-bit AXI-Lite decode and the `0x100` quality page ABI.
- Do not add FFT, DMA, vector buffers, or active abs-sum accumulators until the timing path is pipelined.
- Abs-sum offsets remain reserved and read zero.

V8 performance review concluded:

```text
V8 hardware multi-frame aggregate page: GO as the next large-step bypass validation candidate.
V8 FFT/window/PSD/DMA: still NO-GO for this step.
```

Reason:

- V7 already validates the per-frame fixed-shape reduction primitives.
- V8 moves repeated multi-frame summary aggregation out of NX Python and into FPGA registers, reducing NX polling and CPU/GPU coordination overhead without touching the active NX SDR chain.
- FPGA adds no new FFT, DMA, vector buffers, or streaming runtime. NX still owns divide/sqrt/atan2/calibration/AoA/backend/frontend composition.
- The first full V8 implementation exposed a reset fanout timing violation; the final V8 build uses local AXI reset replication and is timing-clean.

## V8 / SUM8 + AGG8 Multi-Frame Aggregate Candidate

Status: hardware-validated after physical SDR power-cycle. V8 is now the first rollback behind the newer V8L1 auto-aggregate candidate.

Use V8 for the next bypass integration step. V8 preserves SUM7-compatible single-frame reductions and quality offsets while adding an aggregate page at `0x180..0x1fc`.

What it does:

- Keeps V7-style production no-snapshot per-frame reductions.
- Adds `AGG8` multi-frame hardware accumulation for corrected RX0/RX1 power numerators, corrected cross real/imag numerators, raw RX0/RX1 power, and quality counts.
- Lets NX set `AGG_TARGET`, arm/clear `AGG_CONTROL`, wait for `done`, then read one stable aggregate page.
- Keeps NX responsible for divide/sqrt/atan2, calibration, AoA composition, CPU/GPU coordination, and later publication.

Artifact directory:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8\BOOT_p201_summary_v8.bin
```

Ready-to-copy SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8\sd_payload
```

Expected registers:

```text
devmem 0x43C00040 32 -> 0x53554D38
devmem 0x43C000EC 32 -> 0x00010002
devmem 0x43C000F0 32 -> 0x000003FF
devmem 0x43C000FC 32 -> 0x56380001
devmem 0x43C00100 32 -> 0x51554138
devmem 0x43C00180 32 -> 0x41474738
devmem 0x43C001F4 32 -> 0x0000001F
devmem 0x43C001F8 32 -> 0x41380001
```

Hash:

```text
6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb  BOOT_p201_summary_v8.bin
```

Timing:

```text
WNS +0.011 ns
WHS +0.053 ns
route fully routed
routing errors 0
```

README:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8\README_SUMMARY_V8.md
```

NX validation script:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v8_aggregate.py
```

Reusable NX client/API:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\sdr_kernel_client.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\read_sum8_aggregate_client.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\read_sum8_aggregate_batch_ssh.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\compare_sum8_fpga_assisted_metrics.py
```

Fallback:

```text
V7 if V8 boot/register/aggregate validation fails. V6 if a simpler production-summary fallback is needed. V4 only for snapshot debug.
```

Hardware validation on 2026-06-08:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8_hardware_validation_20260608.md
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8_after_v9a_rollback_powercycle_20260608.md
```

Result:

- SDR `/sd/BOOT.bin` hash matched V8: `6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb`.
- `SUMMARY_VERSION = 0x53554D38`.
- `ABI_VERSION = 0x00010002`.
- `CAPABILITY = 0x000003FF`.
- `BUILD_ID = 0x56380001`.
- `QUALITY_VERSION = 0x51554138`.
- `AGG_VERSION = 0x41474738`.
- `AGG_CAP = 0x0000001F`.
- `AGG_BUILD_ID = 0x41380001`.
- Primary aggregate validation passed 5 / 5 captures at `frame_len=64`, `agg_frames=16`.
- Reusable SUM8 client validation passed 6 / 6 captures across `agg_frames=4,16,64`.
- FPGA-assisted shadow backend validation passed 5 / 5 captures with corrected mean dBFS and original-AoA-shaped output.
- Batch AGG8 read validation passed 9 / 9 captures across `agg_frames=16,64,256`, about 0.285 s per aggregate over one SSH exec.
- Rollback validation after V9A IIO failure passed after physical power-cycle: `/sd/BOOT.bin` matched V8, `cf-ad9361-lpc` registered, SUM8/QUA8/AGG8 identities matched, and AGG8 validation passed 5 / 5 captures.

Known reasons to skip V8:

- Timing is clean but thin (`WNS +0.011 ns`); keep V7 available as rollback.
- It is an aggregate summary primitive, not a replacement for the current NX SDR computation chain.

## V7 / SUM7 Quality Page Candidate

Status: hardware-validated after physical SDR power-cycle.

Use as the validated quality-page rollback behind V8. V7 preserves SUM6-compatible offsets and adds `QUA7` clip/zero-cross/sign quality counters.

What it does:

- Keeps SUM6 production no-snapshot dual-RX reductions and ABI metadata.
- Expands internal AXI-Lite decode to 12-bit while BD range remains 64K at `0x43C00000`.
- Adds quality page version/capability/build metadata.
- Adds RX0/RX1 clip counts, zero-cross counts, I/Q and channel same-sign counters.
- Keeps `0x128..0x134` as reserved abs-sum registers that read zero in SUM7A.

Artifact directory:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v7
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v7\BOOT_p201_summary_v7.bin
```

Ready-to-copy SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v7\sd_payload
```

Expected registers:

```text
devmem 0x43C00040 32 -> 0x53554D37
devmem 0x43C000EC 32 -> 0x00010001
devmem 0x43C000F0 32 -> 0x000001FF
devmem 0x43C000FC 32 -> 0x56370001
devmem 0x43C00100 32 -> 0x51554137
devmem 0x43C00138 32 -> 0x0000000F
devmem 0x43C0013C 32 -> 0x51370001
```

Hash:

```text
ca7af9cfa33ddb26a5817b9a0117e550e295f3b1a992cf5236d040dabfe405d1  BOOT_p201_summary_v7.bin
```

Timing:

```text
WNS +0.015 ns
WHS +0.003 ns
route fully routed
routing errors 0
```

README:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v7\README_SUMMARY_V7.md
```

NX validation script:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v7_quality_page.py
```

Fallback:

```text
V6 if V7 boot/register/quality-page validation fails. Use V4/V3 if snapshot debug is needed.
```

Hardware validation on 2026-06-08:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v7_hardware_validation_20260608.md
```

Result:

- SDR `/sd/BOOT.bin` hash matched V7: `ca7af9cfa33ddb26a5817b9a0117e550e295f3b1a992cf5236d040dabfe405d1`.
- `SUMMARY_VERSION = 0x53554D37`.
- `ABI_VERSION = 0x00010001`.
- `CAPABILITY = 0x000001FF`.
- `BUILD_ID = 0x56370001`.
- `QUALITY_VERSION = 0x51554137`.
- `QUALITY_CAP = 0x0000000F`.
- `QUALITY_BUILD_ID = 0x51370001`.
- Reserved abs-sum registers at `0x128..0x134` read zero in every capture.
- Quality page sweep passed 15 / 15 captures across 64, 128, and 256 samples.

Known reasons to skip V7:

- Hold margin is timing-clean but very thin (`WHS +0.003 ns`).
- You need abs-sum features; they are intentionally reserved/read-zero in SUM7A.

## V6 / SUM6 Block ABI Candidate

Status: hardware-validated after physical SDR power-cycle.

Use as the current validated production-summary fallback. V6 preserves all V5 production summary offsets and adds ABI/capability/limit/build metadata at `0xec..0xfc`.

What it does:

- Keeps V5 production no-snapshot dual-RX reductions and corrected numerator registers.
- Adds summary ABI version, capability bitmap, limit flags, max corrected frame length, and build ID.
- Adds `corrected_valid` and `arithmetic_overflow` flags so NX can reject unsupported frames.
- Keeps snapshot disabled for production-shape low-bandwidth behavior.

Artifact directory:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v6
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v6\BOOT_p201_summary_v6.bin
```

Ready-to-copy SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v6\sd_payload
```

Expected registers:

```text
devmem 0x43C00040 32 -> 0x53554D36
devmem 0x43C00060 32 -> 0x00000000
devmem 0x43C000EC 32 -> 0x00010000
devmem 0x43C000F0 32 -> 0x000000FF
devmem 0x43C000F8 32 -> 0x0000FFFF
devmem 0x43C000FC 32 -> 0x56360001
```

Hash:

```text
e47c012ad5f8f14bc769620f00add18ef75be74bd09dbaaddaa91aaf62ade60b  BOOT_p201_summary_v6.bin
```

Timing:

```text
WNS +0.015 ns
WHS +0.014 ns
route fully routed
routing errors 0
```

README:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v6\README_SUMMARY_V6.md
```

NX validation script:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v6_block_abi.py
```

Fallback:

```text
V4 if V6 boot/register/ABI validation fails. Keep V6 as fallback while testing V7.
```

Hardware validation on 2026-06-08:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v6_hardware_validation_20260608.md
```

Result:

- SDR `/sd/BOOT.bin` hash matched V6: `e47c012ad5f8f14bc769620f00add18ef75be74bd09dbaaddaa91aaf62ade60b`.
- `SUMMARY_VERSION = 0x53554D36`.
- `ABI_VERSION = 0x00010000`.
- `CAPABILITY = 0x000000FF`.
- `MAX_CORR_FRAME = 0x0000FFFF`.
- `BUILD_ID = 0x56360001`.
- `LIMIT_FLAGS = 0x0000000C`.
- Production sweep passed 15 / 15 captures across 64, 128, and 256 samples.

Known reasons to skip V6:

- V6 is already hardware-validated; skip only if testing the newer V7 quality page.
- The 8-bit register page is now full through `0xfc`; future FFT/PSD/DMA should use a new page/IP.

## V5 / SUM5 Production No-Snapshot

Status: hardware boot/register PASS after physical SDR power-cycle, production consistency FAIL.

Use only as a hardware-booted reference. Do not treat V5 as production-validated.

What it does:

- FPGA computes dual-RX power, peaks, cross real/imag, signed I/Q sums.
- FPGA also computes mean-corrected numerator registers for power and cross terms.
- NX reads summary registers and does divide/sqrt/atan2/calibration/aggregation.
- Snapshot readback is intentionally disabled for timing and production-shape behavior.

Artifact directory:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v5
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v5\BOOT_p201_summary_v5.bin
```

Ready-to-copy SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v5\sd_payload
```

Expected register:

```text
devmem 0x43C00040 32 -> 0x53554D35
devmem 0x43C00060 32 -> 0x00000000
```

Hash:

```text
a9849d26185671c9fb276cdab032913864b379b3c8fcca9286d472be964f0544  BOOT_p201_summary_v5.bin
```

Timing:

```text
WNS +0.015 ns
WHS +0.030 ns
route fully routed
routing errors 0
```

README:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v5\README_SUMMARY_V5.md
```

NX validation script:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v5_production.py
```

Preferred SDR-local performance helper:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v5_local.py
```

Use the Paramiko script for safe functional validation. Use the SDR-local helper after boot/version checks when timing matters, because SSH-per-`devmem` timing is dominated by transport overhead.

Fallback:

```text
V4 if V5 boot/register/internal-consistency validation fails.
```

Hardware validation on 2026-06-08:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v5_hardware_validation_20260608.md
```

Result:

- SDR `/sd/BOOT.bin` hash matched V5: `a9849d26185671c9fb276cdab032913864b379b3c8fcca9286d472be964f0544`.
- `SUMMARY_VERSION` was consistently `0x53554D35`.
- `SNAPSHOT_COUNT` was consistently `0`.
- Production sweep was not fully passing: 9 / 15 captures passed.
- Failures were tied to anomalous `Q1_SUM` values near `+/-2^47`, causing RX1 corrected-power and corrected-cross checks to fail.
- Continue with V6.

## V4 / SUM4 Mean-Corrected Debug

Status: hardware-validated after physical SDR power-cycle.

Use V4 only if same-frame snapshot debugging is needed. Keep it out of the normal active burn order because V7/V6 are better production-summary candidates and V8 is the next aggregate offload candidate.

What it does:

- Keeps V3 dual-RX snapshot and raw cross/power summary.
- Adds signed I/Q sums for NX-side mean-corrected AoA comparison.
- Does not include V5 corrected numerator registers.

Artifact directory:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v4
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v4\BOOT_p201_summary_v4.bin
```

Ready-to-copy SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v4\sd_payload
```

Expected register:

```text
devmem 0x43C00040 32 -> 0x53554D34
```

Hash:

```text
fd7c080532ee0668eb462db83208b220bbdbc3ace7a61b23e34f2b6a0699accd  BOOT_p201_summary_v4.bin
```

Timing:

```text
WNS +0.015 ns
WHS +0.051 ns
route fully routed
routing errors 0
```

README:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v4\README_SUMMARY_V4.md
```

NX validation script:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v4_mean_corrected.py
```

Fallback:

```text
V3 if V4 boot or register validation fails.
```

Hardware validation on 2026-06-08:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v4_hardware_validation_20260608.md
```

Result:

- SDR was physically power-cycled after staging V4.
- `SUMMARY_VERSION = 0x53554D34`.
- Same-frame snapshot count was 64.
- RX0/RX1 power, peaks, raw cross, signed I/Q sums, mean-corrected phase, and mean-corrected coherence all matched the snapshot reference.
- Local evidence: `E:\vivado\fpga_p201pro_accel\reports\summary_v4_mean_corrected_after_reboot_20260608.json`.

## V3 / SUM3 Dual-RX Snapshot Baseline

Status: hardware-validated after physical SDR power-cycle.

Use V3 as the known-good dual-RX snapshot fallback.

What it does:

- Adds versioned summary register `SUM3`.
- Captures 64-sample RX0/RX1 same-frame snapshot.
- Computes RX0/RX1 power, cross real/imag, RX1 peak.

Artifact directory:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v3
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v3\BOOT_p201_summary_v3.bin
```

Ready-to-copy SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v3\sd_payload
```

Expected register:

```text
devmem 0x43C00040 32 -> 0x53554D33
```

Hash:

```text
c6c727bc4ac16a6e21565d5074a18404b01a6c43a160809ab1178224d3bce7f1  BOOT_p201_summary_v3.bin
```

Hardware evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v3_hardware_validation_20260607.md
```

NX validation script:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v3_dual_snapshot.py
```

Fallback:

```text
V1 if dual-RX path needs to be bypassed for basic tap health.
```

## V2 / SUM2 Intermediate Debug

Status: hardware-tested during bring-up, superseded by V3.

Use V2 only for historical comparison if V3/V4 behavior is confusing.

Artifact directory:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v2
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v2\BOOT_p201_summary_v2.bin
```

Expected register:

```text
devmem 0x43C00040 32 -> 0x53554D32
```

Hash:

```text
0abd8a02e8798fb56c3ac6d38aa9b1e261e71e9e444a82ccd8d9b37615393a43  BOOT_p201_summary_v2.bin
```

Report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v2_hardware_validation_20260607.md
```

## V1 / SUM1 First Summary Baseline

Status: hardware-validated after physical SDR power-cycle.

Use V1 only as a minimal single-RX frame-summary baseline.

Artifact directory:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v1
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v1\BOOT_p201_summary_v1.bin
```

Expected register:

```text
devmem 0x43C00040 32 -> 0x53554D31
```

Hash:

```text
5f550533c3441b309e62488bd5d3ffeaafec222825305a90bb9973fa4e614b6e  BOOT_p201_summary_v1.bin
```

Report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v1_hardware_validation_20260607.md
```

## Companion Boot Files

Unless a version README says otherwise, keep companion boot files from the known-good SD-ready deliverable:

```text
E:\vivado\fpga_p201pro_accel\deliverables\p201pro_2t2r_sd_ready\boot\devicetree.dtb
E:\vivado\fpga_p201pro_accel\deliverables\p201pro_2t2r_sd_ready\boot\uEnv.txt
E:\vivado\fpga_p201pro_accel\deliverables\p201pro_2t2r_sd_ready\boot\uImage
E:\vivado\fpga_p201pro_accel\deliverables\p201pro_2t2r_sd_ready\boot\uramdisk.image.gz
```

Known-good DTB hash:

```text
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  devicetree.dtb
```
