# Experiments Index

This directory holds source-level experiments. Burnable or SD-ready artifacts
belong under `boot_experiments/`; reports belong under `reports/`.

## Current V8-Derived Work

- `v8_derived_low_nx_load`: V8-derived low-NX-load source branch.
- `v8d0_layout_probe`: V8L1 logic with build-ID-only change for layout sensitivity isolation.
- `v8d1_incremental_auto_roll_fix`: V8L2-style auto-roll fix using incremental/checkpoint-preserving flow.

## Reusable SDR Submodules

- `v10s0_submodule_selftest`: isolated AXI-Lite self-test page with FFT-family summary helpers and correlation/bandpower reducers.
- `v10s1_quality_stats`: reusable quality/validity statistics module.
- `v10s2_frame_window`: reusable frame/window module and Hann coefficient helper.
- `v10s3_energy_peak`: reusable energy and peak reducer.
- `v10s123_nonfft_ooc`: combined OOC wrapper for V10S1/S2/S3.
- `v10s4_nonfft_selftest`: isolated AXI-Lite self-test page for non-FFT helpers.
- `v10s5_combined_selftest`: current combined FFT-family/non-FFT source/script candidate at `0x43C30000`.

V10S0 is hardware-validated only as an isolated deterministic self-test page on
a V8D0 live tap base. Its V8D0 base is currently useful for independent
explicit arm/read passive shadow and feature-flag primitive-assist experiments.

V10S4 passed its isolated self-test registers but failed AD9361/IIO after
power-cycle, so it is not hardware validated. V10S5 is not yet a burnable
artifact and remains a side-path/source candidate unless `VERSION_ROUTE.md`
says otherwise.

## Historical AD9361 Experiments

The `ad9361_*_20260607` directories are early tuning experiments. Keep them for
failure comparison, but do not use them as the current route.
