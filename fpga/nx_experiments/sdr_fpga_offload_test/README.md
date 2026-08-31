# SDR FPGA Offload Test

Last updated: 2026-06-09 19:20 Asia/Shanghai

Independent NX-side experiment package for P201Pro SDR FPGA offload validation.

This directory is intentionally separate from the active `robot_control` ROS package.
It does not modify `setup.py`, launch files, mode manager code, robot control, or any
existing SDR runtime path.

## Scope

Goal: validate FPGA-side SDR primitive calculations before replacing or
influencing any active NX SDR processing.

Current safe phase:

- Use current-loaded V10S0/V8D0 board image for independent explicit arm/read
  SUM8/QUA8/AGG8 primitive probes.
- Run passive shadow, default assist fallback, and primitive-assist stress tests
  in this directory only.
- Keep CPU fallback, clipped-AoA policy, and logs visible.
- Keep all outputs in this experiment directory.

Forbidden in this experiment:

- Starting ROS launch files.
- Starting `sdr_mode_manager`, `sdr_channel_monitor`, `sdr_dual_aoa_localizer`,
  `robot_controller`, mapping, RTAB-Map, or any `/cmd_vel` path.
- Modifying the parent `robot_control` package.
- Replacing or influencing the active NX SDR compute chain before explicit user
  approval.

Current status:

```text
V8D0/V10S0 current-loaded identity verified read-only.
Passive shadow extended PASS.
Default assist stress100 PASS with CPU fallback under policy gates.
Primitive-assist stress100 PASS with FPGA selected 97 / 100.
Post-stress AD9361/IIO health remained good.
Active-package shadow-only dry-run PASS; no active robot_control file modified.
Load-reduction live board timing PASS; current SSH/devmem path reduces
primitive/data movement burden but not total wall time yet.
P1.1 native C mmap/UIO transport fake-register tests PASS; SDR-local native
board probe PASS on current V10S0/V8D0 SUM8/AGG8 safe registers.
`fpga_fft_shadow` software ABI draft PASS for summary, four top peaks, and
preferred 96-bin coarse PSD page. No live 2048-point FFT/PSD hardware
implementation exists yet.
P1.2 FFT/PSD reference/tolerance gate PASS on Windows and NX for exact 96-bin
coarse PSD, top peaks, and current NX PSD math.
P1.3 isolated `fpga_fft_shadow` RTL self-test PASS on PC with XSIM/OOC. This is
an ABI fixture only; no board, runtime, or active package change exists.
P1.3b isolated signed top-4 PSD peak reducer PASS on PC with XSIM/OOC timing.
This is a post-PSD helper primitive only; no board, runtime, or active package
change exists.
P1.3c isolated exact 2048-to-96 coarse PSD max-hold reducer PASS on PC with
XSIM/OOC timing. This is a coarse-bin helper primitive only; no board, runtime,
or active package change exists.
P1.3d isolated FFT4 smoke core PASS on PC with XSIM/OOC timing. This is a
minimal true FFT butterfly datapath gate only; no board, runtime, or active
package change exists.
P1.4a FFT shadow integration review recorded on PC. It confirms the usable
shadow blocks, identifies the missing 2048-point FFT/window/PSD generator and
live AD9361 coupling, and recommends an isolated Xilinx FFT IP or equivalent
OOC probe before any board/runtime work.
```

## Existing NX Compute Chain Summary

Read-only inspection found the active SDR compute path in:

- `robot_control/sdr_iio_driver.py`
- `robot_control/sdr_band_scanner.py`
- `robot_control/sdr_channel_monitor.py`
- `robot_control/sdr_dual_aoa_core.py`
- `robot_control/sdr_dual_aoa_localizer.py`
- `robot_control/sdr_cuda_fft_backend.py`
- `robot_control/sdr_cuda_fft.cu`

Main inputs:

- IIO URI: `ip:192.168.1.10`
- PHY: `ad9361-phy`
- RX device: auto-detected, normally `cf-ad9361-lpc`
- Raw samples: interleaved int16 I/Q lanes from IIO buffer
- Defaults: 2 MSPS, NFFT 2048, heatmap buffer 4096, AoA buffer 8192

Main outputs:

- Spectrum/RSSI summaries: RSSI, peak power, peak frequency, noise floor,
  peak prominence, compressed PSD bins.
- Dual-RX AoA summaries: RX0/RX1 RSSI, coherence, phase, AoA, peak frequency,
  ambiguity/clipping flags.
- ROS topics are produced by existing nodes, but this experiment does not start them.

Main NX load candidates:

- IIO buffer transfer to NX.
- int16 to float normalization.
- Hanning window generation/application.
- FFT/fftshift/PSD.
- RSSI reductions.
- Multi-channel scan repetition and averaging.
- Dual-RX AoA cross-correlation and two-lane FFT.

## Files

- `sdr_fpga_offload_test/fpga_regs.py`: FPGA register definitions and read helpers.
- `sdr_fpga_offload_test/sdr_kernel_contract.py`: current SUM5/SUM6/SUM7/SUM8
  kernel contract, future kernel route, magic values, offsets, signedness, and
  frame/aggregate limits.
- `sdr_fpga_offload_test/sdr_kernel_client.py`: typed Python client for the SUM5
  production summary kernel and SUM8 multi-frame aggregate kernel.
- `sdr_fpga_offload_test/native_transport.py`: ctypes adapter for the local C
  mmap/UIO backend.
- `sdr_fpga_offload_test/fft_shadow_client.py`: software client/dataclasses for
  the draft `fpga_fft_shadow` ABI page; fake-register tested only.
- `sdr_fpga_offload_test/feature_flag_assist.py`: off/shadow/assist decision
  helper for explicit arm/read SUM8/AGG8 primitive probes.
- `sdr_fpga_offload_test/reference_compute.py`: offline reference implementation
  matching the existing NX spectrum/AoA math.
- `sdr_fpga_offload_test/compare_summary.py`: comparison helpers.
- `include/p201_sdr_kernel_contract.hpp`: C++ constants and structs for future
  CPU/GPU/C++ orchestration.
- `scripts/read_fpga_diag_registers.py`: read current tap diagnostic registers.
- `scripts/dump_sdr_kernel_contract.py`: dump machine-readable JSON contract for
  humans, scripts, or future AI agents.
- `scripts/capture_summary_v6_block_abi.py`: read SUM6 register-only block ABI
  and compare corrected numerators without touching the active SDR runtime chain.
- `scripts/capture_summary_v8_aggregate.py`: validate SUM8/AGG8 metadata and
  aggregate registers without touching the active SDR runtime chain.
- `scripts/validate_v10s0_submodule_selftest_after_powercycle_via_nx.py`:
  post-power-cycle validator for the isolated V10S0 self-test candidate.
- `scripts/validate_v10s4_nonfft_selftest_after_powercycle_via_nx.py`:
  post-power-cycle validator for the isolated V10S4 self-test candidate.
- `scripts/validate_v10s5_combined_selftest_after_powercycle_via_nx.py`:
  planned post-power-cycle validator for V10S5; use only after a V10S5 BOOT
  hash and SD payload exist.
- `scripts/read_sum8_aggregate_client.py`: reusable SUM8/AGG8 client/API check
  for CPU/GPU coordination experiments.
- `scripts/read_sum8_aggregate_batch_ssh.py`: faster batched AGG8 read using one
  SSH exec per aggregate capture.
- `scripts/compare_sum8_fpga_assisted_metrics.py`: side-by-side CPU raw-IQ
  primitives and FPGA AGG8 shadow-backend metrics.
- `scripts/probe_feature_flag_assist.py`: independent feature-flag assist probe
  with CPU fallback and quality gates.
- `native/`: Phase 1.1 C mmap/UIO backend with fake-register tests.
- `scripts/probe_sum8_native_transport.py`: local SUM8/AGG8 native mmap/UIO
  probe; default mode is read-only and `--arm` performs explicit AGG8 arm/read.
- `scripts/test_fft_shadow_contract.py`: fake-register test for the draft
  `fpga_fft_shadow` client and 96-bin coarse PSD shape.
- `scripts/test_fft_psd_reference.py`: offline FFT/PSD reference and tolerance
  test using deterministic synthetic tones.
- `staged_robot_control_integration/robot_control_sum8_shadow_only.patch`:
  active-package dry-run patch for CPU-publication shadow sidecar logging only.
- `scripts/compare_offload_summary.py`: compare FPGA summary JSON with offline raw
  reference data.
- `scripts/profile_reference_compute.py`: offline timing of the NX reference math.
- `NX_SDR_READONLY_ANALYSIS.md`: detailed read-only analysis.
- `OFFLOAD_VALIDATION_PLAN.md`: current validation ladder for identity,
  passive aggregate, shadow compare, feature-flag probe, and dry-run integration.

Canonical interface docs:

- `..\..\docs\P201_SDR_FPGA_KERNEL_CONTRACT.md`
- `..\..\docs\FPGA_NX_KERNEL_API_ROADMAP.md`

## Safe Commands

Read current diagnostic registers from SDR through NX:

```bash
cd /home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
python3 scripts/read_fpga_diag_registers.py --out logs/fpga_diag_latest.json
```

After booting the Summary V1 FPGA experiment, read the new frame summary mirror:

```bash
python3 scripts/read_fpga_diag_registers.py \
  --include-summary \
  --out logs/fpga_summary_v1_latest.json
```

Capture repeated register-only Summary V1 frames:

```bash
python3 scripts/capture_summary_v1_series.py \
  --frames 20 \
  --frame-len 64 \
  --out logs/summary_v1_register_frame_series.json
```

This only writes the FPGA tap control/frame-length registers and reads summary
registers. It does not start ROS or any long-running SDR worker.

Capture one raw I16 reference buffer outside the existing ROS nodes:

```bash
python3 scripts/capture_raw_i16_once.py \
  --buffer-size 64 \
  --out-npz samples/raw_i16_once.npz \
  --out-json logs/raw_i16_once_reference.json
```

This performs a single IIO buffer refill and closes the buffer immediately. It is
not synchronized to the FPGA register frame, so use it as a scale/statistical
sanity check only.

Historical/offline Summary V1 comparison against a saved raw buffer:

```bash
python3 scripts/compare_offload_summary.py \
  --raw-npz samples/reference_raw_i16.npz \
  --fpga-json logs/fpga_summary.json \
  --out logs/offload_compare.json
```

This comparison is for Summary V1 time-domain power registers:

```text
sample_count
sum_power_raw
peak_power_raw
peak_index
rssi_dbfs derived from sum_power_raw / sample_count
```

It intentionally does not compare FPGA `PEAK_POWER` against the existing NX FFT
PSD peak; FFT/PSD offload is a later stage.

Read SUM8/AGG8 aggregate primitives through the reusable client:

```bash
python3 scripts/read_sum8_aggregate_client.py \
  --frame-len 64 \
  --agg-frames 4 16 64 \
  --repeat 2 \
  --out-json logs/sum8_aggregate_client_20260608.json
```

This writes only the FPGA tap control/frame-length/aggregate registers and reads
the aggregate page. It does not start ROS, SDR streaming runtime, existing
`robot_control`, mapping, RTAB-Map, or motion paths.

Read SUM8/AGG8 through the faster batched control path:

```bash
python3 scripts/read_sum8_aggregate_batch_ssh.py \
  --frame-len 64 \
  --agg-frames 16 64 256 \
  --repeat 3 \
  --out-json logs/sum8_aggregate_batch_ssh_20260608.json
```

Run the FPGA-assisted shadow metric comparison:

```bash
python3 scripts/compare_sum8_fpga_assisted_metrics.py \
  --frame-len 64 \
  --agg-frames 64 \
  --repeat 5 \
  --out-json logs/sum8_fpga_assisted_metrics_corrected_20260608.json
```

Use `rx*_corr_mean_dbfs` / `rx*_rssi_dbfs` from the normalized shadow metric
layer for AoA/RSSI-style consumers. The raw aggregate also keeps legacy
`rx*_legacy_numerator_dbfs` values for debugging old validation output.

Latest mainline passive shadow result:

```text
2026-06-09 12:08 Asia/Shanghai
Current V10S0 image / V8D0 live tap base:
- read_sum8_aggregate_batch_ssh.py PASS, 2 / 2 captures
- compare_sum8_fpga_assisted_metrics.py PASS, 2 / 2 captures
- extended read_sum8_aggregate_batch_ssh.py PASS, 20 / 20 captures at
  `agg_frames=16/64/256/1024`
- extended compare_sum8_fpga_assisted_metrics.py PASS, 15 / 15 captures at
  `agg_frames=64/256`
- benchmark_v8l1_auto_roll_batch_ssh.py on V8D0 did not pass continuous
  latest-window sequence advance: 1 / 8 reads passed, post-first
  `sequence_delta` values were 0
```

Mirrored evidence:

```text
logs/sum8_v8d0_passive_read_20260609_fast_mainline.json
logs/sum8_v8d0_shadow_compare_20260609_fast_mainline.json
logs/sum8_v8d0_passive_read_20260609_extended_mainline.json
logs/sum8_v8d0_shadow_compare_20260609_extended64_mainline.json
logs/sum8_v8d0_shadow_compare_20260609_extended256_mainline.json
logs/v8d0_auto_roll_batch_ssh_20260609_mainline.json
```

This is passive shadow evidence only. The CPU raw-IQ and FPGA AGG8 windows are
adjacent/nearby rather than hardware-synchronized, so strict equivalence is not
claimed. It does not start ROS, SDR streaming runtime, `robot_control`, mapping,
RTAB-Map, navigation, or motion paths.

For the current V10S0/V8D0 base, use explicit arm/read aggregate access for any
feature-flag assist prototype. Do not use it as a continuous auto-roll polling
backend unless a later candidate shows advancing `agg_sequence`.

Feature-flag assist prototype:

```bash
python3 scripts/probe_feature_flag_assist.py --mode shadow --frame-len 64 --agg-frames 64 --repeat 5
python3 scripts/probe_feature_flag_assist.py --mode assist --frame-len 64 --agg-frames 64 --repeat 5
python3 scripts/probe_feature_flag_assist.py --mode assist --allow-aoa-phase-clipped --frame-len 64 --agg-frames 64 --repeat 5
```

Latest probe result on V10S0/V8D0:

```text
feature_flag_assist_shadow_v8d0_20260609_mainline.json
  PASS, 5 / 5, CPU selected, FPGA sidecar read OK

feature_flag_assist_assist_v8d0_20260609_mainline.json
  PASS, 5 / 5, CPU fallback because conservative aoa_phase_clipped gate fired

feature_flag_assist_primitive_allow_clip_v8d0_20260609_mainline.json
  PASS, 5 / 5, FPGA primitive selected with clipped flag preserved

feature_flag_assist_assist_v8d0_20260609_stress20_mainline.json
  PASS, FPGA read OK 20 / 20, selected FPGA 1 / 20, CPU fallback 19 / 20

feature_flag_assist_primitive_allow_clip_v8d0_20260609_stress20_mainline.json
  PASS, FPGA read OK 20 / 20, selected FPGA 20 / 20

feature_flag_assist_assist_v8d0_20260609_stress100_mainline.json
  PASS, FPGA read OK 100 / 100, selected FPGA 4 / 100, CPU fallback 96 / 100

feature_flag_assist_primitive_allow_clip_v8d0_20260609_stress100_mainline.json
  PASS, FPGA read OK 100 / 100, selected FPGA 97 / 100, CPU fallback 3 / 100
```

Current-loaded board identity before interpreting stress20:

```text
BASE_BUILD=0x56384430
BASE_QUALITY_BUILD=0x51384430
BASE_AGG_BUILD=0x41384430
V10S0_MAGIC=0x53305430
V10S0_DONE=0x0000000F
V10S0_BUILD=0x56313053
V10S4_MAGIC absent
V10S5_MAGIC absent
```

No new SDR `/sd` staging or physical power-cycle was performed for these
feature-flag probes; they are current-loaded-image tests only.

Post-stress100 read-only health:

```text
V8D0/V10S0 identity still matched.
IIO devices included ad9361-phy and cf-ad9361-lpc.
```

Offline profile of reference math:

```bash
python3 scripts/profile_reference_compute.py \
  --raw-npz samples/reference_raw_i16.npz \
  --iterations 100 \
  --out logs/reference_profile.json
```

Build and fake-test the native mmap/UIO backend:

```bash
cd /home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/native
make clean test lib
```

Run a local native SUM8/AGG8 read-only probe on SDR Linux:

```bash
cd /home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
python3 scripts/probe_sum8_native_transport.py --mode devmem --device /dev/mem
```

Run explicit native AGG8 arm/read only after confirming the loaded image and
safety scope:

```bash
python3 scripts/probe_sum8_native_transport.py \
  --mode devmem \
  --device /dev/mem \
  --arm \
  --frame-len 64 \
  --agg-frames 64 \
  --out-json logs/sum8_native_transport_CURRENT.json
```

Latest P1.1 native board result:

```text
2026-06-09:
p1_1_native_probe_readonly_20260609.json
  PASS, identity_ok true, snapshot_elapsed_ns 10107

p1_1_native_probe_arm64_20260609.json
  PASS, aggregate_ok true, agg_samples 4096, status_flags 0x00000000

p1_1_native_probe_arm64_repeat20_poll50_20260609.json
  PASS 20 / 20, snapshot_elapsed_ns median 8560, poll_elapsed_ns median 141771

p1_1_native_phase0_after_probe_20260609.json
  PASS, V8D0/V10S0 identity and AD9361/IIO health still good
```

Run the P1.2 offline FFT/PSD reference gate:

```bash
python3 scripts/test_fft_psd_reference.py \
  --out-json logs/p1_2_fft_psd_reference_tolerances_20260609.json
```

Latest P1.2 result:

```text
p1_2_fft_psd_reference_tolerances_20260609.json
  PASS, peak_index 1147, coarse_bin_count 96, coarse_bin_step_q16 1398101
  active UI compression reference: 2048 bins -> 98 bins with max_bins=96
```

Latest P1.3 PC-only RTL self-test result:

```text
reports/p201_phase1_p1_3_fft_shadow_selftest_20260609.md
  PASS, XSIM and OOC synth
  0x400..0x6fc ABI fixture, four top peaks, 96 populated coarse PSD bins
  WNS +6.476 ns, WHS +0.129 ns, 103 LUT, 30 FF, 0 BRAM, 0 DSP
```

Latest P1.3b PC-only top-4 reducer result:

```text
reports/p201_phase1_p1_3b_fft_shadow_top4_reducer_20260609.md
  PASS, XSIM and OOC timing
  signed top-4 PSD peak reducer with guard-bin suppression
  WNS +1.102 ns, WHS +0.129 ns, 340 LUT, 509 FF, 0 BRAM, 0 DSP
```

Latest P1.3c PC-only coarse96 reducer result:

```text
reports/p201_phase1_p1_3c_fft_shadow_coarse96_reducer_20260609.md
  PASS, XSIM and OOC timing
  exact 2048-to-96 signed PSD max-hold grouping
  WNS +2.264 ns, WHS +0.185 ns, 2138 LUT, 3275 FF, 0 BRAM, 0 DSP
```

Latest P1.3d PC-only FFT4 smoke core result:

```text
reports/p201_phase1_p1_3d_fft_shadow_fft4_smoke_core_20260609.md
  PASS, XSIM and OOC timing
  4-point complex FFT butterfly with per-bin power, total power, and peak summary
  WNS +1.424 ns, WHS +0.132 ns, 1299 LUT, 856 FF, 0 BRAM, 8 DSP
```

Latest P1.4a PC-only integration review result:

```text
reports/p201_phase1_p1_4a_fft_shadow_integration_review_20260609.md
  COMPLETE, documentation/integration review only
  usable: native mmap/UIO, ABI/client, P1.2 reference, ABI fixture, top-4,
          coarse96, FFT4 smoke
  missing: 2048 FFT/window/PSD generator and live AD9361 coupling
  next: isolated Xilinx FFT IP or equivalent OOC probe before bitstream/BOOT/SD
```

## Current FPGA Register State

The currently validated FPGA tap exposes diagnostic registers only:

```text
0x43C00030 DEBUG_FLAGS
0x43C00034 DEBUG_CLK
0x43C00038 DEBUG_VALID
0x43C0003c DEBUG_ACCEPT
```

The Summary V1 FPGA experiment build adds:

```text
0x43C00040 SUMMARY_VERSION  0x53554d31 ("SUM1")
0x43C00044 SUMMARY_FLAGS
0x43C00048 FRAME_COUNTER
0x43C0004c SAMPLE_COUNT
0x43C00050 SUM_POWER_LO
0x43C00054 SUM_POWER_HI
0x43C00058 PEAK_POWER
0x43C0005c PEAK_INDEX
```

That build has been hardware validated after physical power-cycle. First check:

```text
0x43C00040 -> 0x53554D31
```

Summary V2 experiment adds a same-frame raw IQ snapshot:

```text
0x43C00040 SUMMARY_VERSION  0x53554d32 ("SUM2")
0x43C00060 SNAPSHOT_COUNT
0x43C00064 SNAPSHOT_INDEX   write/read 0..63
0x43C00068 SNAPSHOT_DATA    {Q[15:0], I[15:0]}
```

After booting V2, run:

```bash
python3 scripts/capture_summary_v2_snapshot.py \
  --frame-len 64 \
  --out-json logs/summary_v2_snapshot_compare.json \
  --out-npz samples/summary_v2_snapshot_raw_i16.npz
```
