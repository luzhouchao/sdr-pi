# Reports Index

This directory contains evidence, not the active route. Use `VERSION_ROUTE.md`
for the current version decision.

## Current Evidence

- `p201_summary_v8l1_auto_agg_hardware_validation_20260608.md`: current highest hardware-validated baseline.
- `p201_summary_v8_hardware_validation_20260608.md`: validated rollback.
- `p201_summary_v8d0_layout_probe_hardware_validation_20260609.md`: V8D0 diagnostic layout probe pass.
- `p201_summary_v8l2_auto_roll_fix_hardware_failure_20260608.md`: V8L2 AD9361/IIO failure.
- `p201_summary_v9a_spec9_hardware_validation_20260608.md`: V9A register/SPEC9 pass plus AD9361/IIO failure.
- `p201_summary_v9a_spec9_iio_failure_diagnostics_20260608.json`: V9A IIO failure diagnostics.
- `p201_summary_v9b0_minimal_isolation_hardware_failure_20260608.md`: V9B0 repeated AD9361/IIO failure.
- `p201_v10s0_submodule_selftest_hardware_validation_20260609.md`: V10S0 isolated self-test pass on V8D0 base.
- `p201_v10s4_nonfft_selftest_hardware_failure_20260609.md`: V10S4 self-test register pass plus AD9361/IIO failure.
- `p201_v10s0_v8d0_passive_shadow_extended_20260609.md`: current-loaded V10S0/V8D0 passive shadow, feature-flag, and stress100 evidence.
- `sum8_robot_control_shadow_only_dry_run_20260609.md`: active-package dry-run for a safer shadow-only SUM8 sidecar patch; no active `robot_control` modification.
- `load_reduction_live_board_test_20260609.md`: live-board load-reduction timing summary for V10S0/V8D0 SUM8/AGG8 with current SSH/devmem validation transport.
- `p201_phase1_p1_1_native_mmap_transport_20260609.md`: Phase 1.1 local C mmap/UIO transport initial software milestone; fake-register tests pass.
- `p201_phase1_p1_1_native_mmap_board_probe_20260609.md`: Phase 1.1 SDR-local native mmap board probe PASS on current-loaded V10S0/V8D0 SUM8/AGG8 safe registers.
- `p201_phase1_p1_2_fft_psd_reference_tolerances_20260609.md`: Phase 1.2 offline FFT/PSD reference and tolerance gate for exact 96-bin `fpga_fft_shadow` coarse PSD.
- `p201_phase1_p1_3_fft_shadow_selftest_20260609.md`: Phase 1.3 PC-only isolated `fpga_fft_shadow` RTL self-test, XSIM/OOC evidence, and resource/timing summary.
- `p201_phase1_p1_3b_fft_shadow_top4_reducer_20260609.md`: Phase 1.3b PC-only signed top-4 PSD peak reducer primitive with XSIM/OOC timing evidence.
- `p201_phase1_p1_3c_fft_shadow_coarse96_reducer_20260609.md`: Phase 1.3c PC-only exact 2048-to-96 coarse PSD max-hold reducer primitive with XSIM/OOC timing evidence.
- `p201_phase1_p1_3d_fft_shadow_fft4_smoke_core_20260609.md`: Phase 1.3d PC-only 4-point complex FFT smoke core with XSIM/OOC timing evidence.
- `p201_phase1_p1_4a_fft_shadow_integration_review_20260609.md`: Phase 1.4a PC-only FFT shadow integration review; no bitstream, BOOT, board staging, hardware validation, or version promotion.
- `p201_phase1_p1_4b_fft_shadow_xfft2048_probe_20260609.md`: Phase 1.4b PC-only Xilinx FFT IP 2048-point OOC probe; no bitstream, BOOT, board staging, hardware validation, or version promotion.
- `p201_phase1_fft_shadow_abi_draft_20260609.md`: software ABI draft for `fpga_fft_shadow` summary, top peaks, and preferred 96-bin coarse PSD page; no hardware yet.
- `p201_current_sdr_function_timing_inventory_20260609.md`: current implemented SDR software-function timing inventory from existing logs, read-only active NX source inspection, and an offline NX synthetic CPU benchmark; no ROS/runtime/retune/motion.

## Build Gate Evidence

- `stage4_ad9361_tap_*`: AD9361 tap package/integration/bitstream evidence.
- `stage_v10s0_submodule_selftest*`: V10S0 self-test XSIM/OOC/IP/integration/bitstream reports.
- `stage_v10s4_nonfft_selftest*`: V10S4 self-test XSIM/OOC/IP/integration/bitstream reports.
- `stage_v10s123_nonfft_ooc`: combined OOC evidence for V10S1/S2/S3.

- `stage_v10s5_combined_selftest`: V10S5 combined wrapper XSIM/OOC reports.
- `stage_phase1_fft_shadow_selftest`: P1.3 isolated `fpga_fft_shadow` ABI fixture XSIM/OOC reports.
- `stage_phase1_fft_shadow_top4_reducer`: P1.3b isolated top-4 PSD reducer OOC timing/utilization reports.
- `stage_phase1_fft_shadow_coarse96_reducer`: P1.3c isolated coarse96 PSD reducer OOC timing/utilization reports.
- `stage_phase1_fft_shadow_fft4_smoke_core`: P1.3d isolated FFT4 smoke core OOC timing/utilization reports.
- `stage_phase1_fft_shadow_xfft2048_probe`: P1.4b isolated XFFT2048 IP OOC timing/utilization/config reports.

V10S5 XSIM/OOC reports are PC-only evidence. V10S5 is still source/script
candidate only until IP/BD/bitstream/Bootgen/SD payload and post-power-cycle
hardware validation pass.

## NX Experiment Evidence

Detailed JSON logs are mirrored under:

```text
nx_experiments\sdr_fpga_offload_test\logs
```

High-signal latest logs:

```text
sum8_v8d0_passive_read_20260609_extended_mainline.json
sum8_v8d0_shadow_compare_20260609_extended64_mainline.json
sum8_v8d0_shadow_compare_20260609_extended256_mainline.json
v8d0_auto_roll_batch_ssh_20260609_mainline.json
feature_flag_assist_assist_v8d0_20260609_stress100_mainline.json
feature_flag_assist_primitive_allow_clip_v8d0_20260609_stress100_mainline.json
p1_1_native_probe_readonly_20260609.json
p1_1_native_probe_arm64_20260609.json
p1_1_native_probe_arm64_repeat20_poll50_20260609.json
p1_2_fft_psd_reference_tolerances_20260609.json
p201_current_sdr_function_timing_inventory_20260609.json
```

These are current-loaded-image board tests, not a new SD staging or
post-power-cycle validation event.

Current active-package staging evidence:

```text
sum8_robot_control_shadow_only_dry_run_20260609.md
load_reduction_live_board_test_20260609.md
```

## Historical Evidence

Reports for V1-V7, AD9361 tuning experiments, and early HDL feasibility are
kept for comparison and rollback context. Do not delete hardware validation or
failure reports unless `VERSION_ROUTE.md` no longer references them and the
user explicitly approves that cleanup.
