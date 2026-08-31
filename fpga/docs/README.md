# Documentation Index

Current docs live here. Superseded plans and long history live under
`docs/archive/`.

## Current Route And Plans

- `..\VERSION_ROUTE.md`: source of truth for versions, hashes, validation state, and test order.
- `..\HANDOFF.md`: short working handoff.
- `..\PROJECT_MAP.md`: project map and cleanup policy.
- `P201PRO_REUSABLE_SUBMODULE_MATRIX_20260610.md`: reusable submodule inventory.
- `P201PRO_PROJECT_LEVEL_BAND_SCAN_OPTIMIZATION_PLAN.md`: current unified project-level optimization plan; prioritizes seconds-level band-scan/session improvements over bottom-level FPGA/IIO micro-optimization.
- `P201PRO_PHASE1_FFT_PSD_SHADOW_PLAN.md`: flexible Phase 1 plan for FFT/PSD summary shadow, mmap/UIO transport, subagent lanes, and live-test gates.
- `..\experiments\phase1_fft_shadow_selftest\HANDOFF.md`: A-lane low-resolution FFT shadow working boundary and handoff.
- `P201PRO_V10S5_COMBINED_SELFTEST_PLAN.md`: combined V10S5 source/script candidate plan.
- `..\nx_experiments\sdr_fpga_offload_test\OFFLOAD_VALIDATION_PLAN.md`: current independent NX validation ladder.
- `..\reports\p201_phase1_p1_1_native_mmap_transport_20260609.md`: P1.1 native mmap/UIO transport fake-register software evidence.
- `..\reports\p201_phase1_p1_1_native_mmap_board_probe_20260609.md`: P1.1 SDR-local native mmap board probe evidence on current-loaded V10S0/V8D0 SUM8/AGG8 registers.
- `..\reports\p201_phase1_p1_2_fft_psd_reference_tolerances_20260609.md`: P1.2 offline FFT/PSD reference and tolerance gate for exact 96-bin coarse PSD.
- `..\reports\p201_phase1_p1_3_fft_shadow_selftest_20260609.md`: P1.3 PC-only isolated `fpga_fft_shadow` RTL self-test and OOC evidence.
- `..\reports\p201_phase1_p1_3b_fft_shadow_top4_reducer_20260609.md`: P1.3b PC-only signed top-4 PSD peak reducer primitive and timing evidence.
- `..\reports\p201_phase1_p1_3c_fft_shadow_coarse96_reducer_20260609.md`: P1.3c PC-only exact 2048-to-96 coarse PSD reducer primitive and timing evidence.
- `..\reports\p201_phase1_p1_3d_fft_shadow_fft4_smoke_core_20260609.md`: P1.3d PC-only FFT4 smoke core and timing evidence.
- `..\reports\p201_phase1_p1_4a_fft_shadow_integration_review_20260609.md`: P1.4a PC-only FFT shadow integration review and pre-board gate; no hardware version change.
- `..\reports\p201_phase1_p1_4b_fft_shadow_xfft2048_probe_20260609.md`: P1.4b PC-only Vivado/XFFT2048 IP OOC probe; no hardware version change.
- `..\reports\p201_current_sdr_function_timing_inventory_20260609.md`: current implemented SDR software-function timing inventory; uses existing logs, read-only active NX source inspection, and offline NX synthetic CPU timing.
- `..\reports\p201_phase1_fft_shadow_abi_draft_20260609.md`: `fpga_fft_shadow` software ABI draft with preferred 96 coarse PSD bins.

Deleted/retired:

- The old 20260610 day-plan document was deleted after second-day work began. Use `..\VERSION_ROUTE.md` and `..\HANDOFF.md`.

## Contracts

- `P201_SDR_FPGA_KERNEL_CONTRACT.md`: canonical FPGA/NX register and kernel contract.
- `FPGA_NX_KERNEL_API_ROADMAP.md`: staged NX API direction.

## Active Technical Plans

- `P201PRO_PROJECT_LEVEL_BAND_SCAN_OPTIMIZATION_PLAN.md`: current top-level optimization direction. Treat FPGA low-resolution shadow and high-resolution IIO/CPU/GPU as backend options under one band-scan session/service.
- `P201Pro_V8L2_AD9361_FAILURE_ROOT_CAUSE_AND_V8L3_PLAN.md`: AD9361/IIO failure isolation plan.
- `P201PRO_PHASE1_FFT_PSD_SHADOW_PLAN.md`: Phase 1 FFT/PSD shadow plan; now subordinate to the project-level band-scan/session optimization direction.
- `P201PRO_V10S1_QUALITY_STATS_MODULE_PLAN.md`: quality stats reusable module.
- `P201PRO_V10S2_FRAME_WINDOW_MODULE_PLAN.md`: frame/window reusable module.
- `P201PRO_V10S3_ENERGY_PEAK_MODULE_PLAN.md`: energy/peak reusable module.
- `P201PRO_V10S4_NONFFT_SELFTEST_PLAN.md`: combined non-FFT self-test image.
- `P201PRO_V10S5_COMBINED_SELFTEST_PLAN.md`: planned combined FFT-family/non-FFT self-test image.

## Archive

Use `docs/archive/README.md` before relying on archived files. Archived files
may mention obsolete paths or superseded version plans.
