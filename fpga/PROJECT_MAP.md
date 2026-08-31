# P201Pro Project Map

Last updated: 2026-06-09 19:20 Asia/Shanghai

This file is the quick locator for the workspace. It does not replace
`VERSION_ROUTE.md`, which remains the version source of truth.

## Start Here

Read in this order:

```text
AGENTS.md
VERSION_ROUTE.md
HANDOFF.md
README.md
PROJECT_MAP.md
```

For current testing:

```text
docs\P201PRO_PROJECT_LEVEL_BAND_SCAN_OPTIMIZATION_PLAN.md
docs\P201PRO_REUSABLE_SUBMODULE_MATRIX_20260610.md
docs\P201PRO_PHASE1_FFT_PSD_SHADOW_PLAN.md
docs\P201PRO_V10S5_COMBINED_SELFTEST_PLAN.md
docs\P201_SDR_FPGA_KERNEL_CONTRACT.md
docs\FPGA_NX_KERNEL_API_ROADMAP.md
```

For AD9361/IIO failure root-cause work:

```text
docs\P201Pro_V8L2_AD9361_FAILURE_ROOT_CAUSE_AND_V8L3_PLAN.md
reports\p201_summary_v8l2_auto_roll_fix_hardware_failure_20260608.md
reports\p201_summary_v9a_spec9_iio_failure_diagnostics_20260608.json
reports\p201_v9a_tx_tune_root_cause_review_20260608.md
```

## Current Version Facts

Current highest hardware-validated candidate:

```text
V8L1 / SUM8 + QUA8 + AGG8 auto-aggregate
```

Recommended active test order is in `VERSION_ROUTE.md`.

Current reusable submodule candidates:

- `V10S0`: isolated AXI-Lite reusable submodule self-test at `0x43C10000`; PC build/Bootgen/SD payload/staging/power-cycle validation passed. Hardware-validated only as an isolated self-test page on a V8D0 live tap base.
- `V10S4`: isolated AXI-Lite non-FFT self-test at `0x43C20000`; PC build/Bootgen/SD payload/staging and self-test registers passed, but AD9361/IIO failed after power-cycle; not hardware validated.
- `V10S5`: isolated combined self-test source/script candidate at `0x43C30000`; wrapper XSIM/OOC pass, artifact build not complete; not staged; not hardware validated.

Current mainline NX shadow state:

```text
The currently staged V10S0 image exposes a V8D0 SUM8/QUA8/AGG8 live tap base at
0x43C00000. On 2026-06-09, the independent NX experiment directory passed a
devmem-only passive aggregate read and a raw-IIO vs FPGA AGG8 shadow compare
against that base. Extended evidence now covers 20/20 passive reads and 15/15
shadow compares. Auto-roll latest-window sequence did not advance on this base,
so the next usable assist shape is explicit arm/read with CPU fallback in the
experiment directory. This does not modify robot_control and is not runtime
assist/integration.
An independent feature-flag assist prototype now exists in
nx_experiments/sdr_fpga_offload_test. It uses explicit arm/read AGG8 access with
CPU fallback. Primitive-assist mode can select FPGA primitives while leaving
AoA clipping policy visible to NX.
Current-loaded board identity was rechecked read-only before interpreting the
stress probes: V8D0 base and V10S0 page are loaded; V10S4/V10S5 pages are not.
No new power-cycle validation was performed for this step.
P1.1 native C mmap/UIO transport now exists in the independent experiment
directory and passes fake-register tests plus SDR-local board probes on the
current V10S0/V8D0 image. Read-only identity, explicit arm/read 64x64, and
repeat20 poll-us=50 all passed, with post-test IIO health still good.
`fpga_fft_shadow` software ABI draft now exists at page 0x400..0x6fc with
summary, four top peaks, and preferred 96 coarse PSD bins. It is not hardware.
P1.2 offline FFT/PSD reference/tolerance gate now exists and passes on Windows
and NX. It defines exact 96-bin coarse PSD comparison for the FPGA ABI and
records the current active UI max-hold compression difference.
P1.3 isolated `fpga_fft_shadow` RTL self-test now exists and passes XSIM/OOC on
PC. It is a deterministic ABI fixture only, not live AD9361 FFT/PSD hardware.
P1.3b isolated signed top-4 PSD peak reducer now exists and passes XSIM/OOC
timing on PC. It is a post-PSD helper primitive only, not FFT/PSD generation or
live AD9361 integration.
P1.3c isolated exact 2048-to-96 coarse PSD reducer now exists and passes
XSIM/OOC timing on PC. It is a coarse-bin helper primitive only; the full
96-direct-register resource cost needs P1.4 review before integration.
P1.3d isolated FFT4 smoke core now exists and passes XSIM/OOC timing on PC. It
is a minimal true FFT butterfly datapath gate only, not a 2048-point
FFT/window/PSD generator or live AD9361 integration.
P1.4a FFT shadow integration review is now recorded as a PC-only milestone. It
keeps P1.1/P1.2/P1.3/P1.3b/P1.3c/P1.3d as usable blocks, identifies the missing
2048-point FFT/window/PSD generator and live AD9361 coupling, and recommends an
isolated Xilinx FFT IP or equivalent OOC probe before any bitstream/BOOT/SD or
board work.
P1.4b XFFT2048 IP/OOC probe now passes on PC at 122.88 MHz. It proves the
reproducible Vivado 2019.1 XFFT2048 entry only. The project route has now been
reframed around seconds-level band-scan/session optimization, so FPGA FFT work
is backend evidence, not the top-level optimization direction by itself.
```

Current root-cause direction:

```text
Do not roll back as the main strategy. Use V8L1 as the validated base,
then diagnose AD9361/IIO sensitivity with V8-derived builds before adding
heavier FFT/SPEC-style logic to the live tap path.
```

Current project-level optimization plan:

```text
docs\P201PRO_PROJECT_LEVEL_BAND_SCAN_OPTIMIZATION_PLAN.md
```

Use it for the unified band-scan/session direction: channel plan, session
lifecycle, backend provider interface, result schema, and seconds-level timing
model. FPGA low-resolution shadow and high-resolution IIO/CPU/GPU are backend
options under this plan.

Current implemented SDR software-function timing inventory:

```text
reports\p201_current_sdr_function_timing_inventory_20260609.md
```

Use it as the baseline before choosing FPGA, CPU/GPU, or scan-policy work. It
does not start ROS/runtime/retune/motion and does not modify active
`robot_control`.

Current Phase 1 FPGA backend plan:

```text
docs\P201PRO_PHASE1_FFT_PSD_SHADOW_PLAN.md
```

Use it for the fast FFT/PSD summary shadow route: local C mmap/UIO transport,
summary plus top peaks plus limited coarse PSD bins, independent NX shadow
compare, and active-package dry-run only. Phase 2 AoA phase/coherence work is
left as aperture only until Phase 1 evidence is complete.

## Top-Level Folders

| Path | Role | Keep/clean policy |
| --- | --- | --- |
| `hdl/` | Current canonical reusable RTL and constraints. | Keep tracked sources. |
| `experiments/` | Versioned RTL experiments, V8 diagnostic sources, reusable submodules. | Keep tracked source/test files. |
| `scripts/` | Vivado, Bootgen, staging, validation, MATLAB helper scripts. | Keep tracked scripts; update when paths move. |
| `boot_experiments/` | Versioned BOOT/SD payload artifacts, hashes, BIFs, artifact READMEs, staging JSON. | Keep evidence and manifests; ignored binaries may remain local. |
| `reports/` | PC gate, staging, hardware validation, and failure evidence. | Keep text/JSON evidence. |
| `docs/` | Current contracts, plans, test matrix, and active design notes. | Keep current docs short and linked. |
| `docs/archive/` | Superseded plans, long handoff history, early NX handoff files. | Keep for history; do not use as current route. |
| `nx_experiments/` | Windows mirror of the safe NX experiment directory. | Keep independent validation code only. |
| `nx_experiments/sdr_fpga_offload_test/native/` | Phase 1.1 local C mmap/UIO backend and fake-register tests. | Keep source and Makefile; generated `build/` output is ignored. |
| `vivado/` | Local generated Vivado package/IP workspace. | Regenerable; safe to clean generated project/cache directories. |
| `vendor_experiments/` | Local copied vendor Vivado project workspace. | Ignored but useful for builds; do not edit original vendor package. |
| `deliverables/` | Old generated deliverable/reference bundle. | Ignored historical/reference output; do not treat as current route. |
| `tomorrow_validation_bundle_20260608/` | Historical validation bundle from 2026-06-08. | Ignored local bundle; do not treat as current route. |
| `vivado_out/`, `.Xil/`, root `*.log/*.jou/*.pb` | Vivado/simulation generated caches and logs. | Safe to delete when cleaning. |

## Current Source Modules

Main tap RTL:

```text
hdl\p201pro_ad9361_power_tap_axi_regs.v
hdl\p201pro_ad9361_power_tap_cdc.xdc
```

Reusable submodule source areas:

```text
experiments\v10s0_submodule_selftest
experiments\v10s1_quality_stats
experiments\v10s2_frame_window
experiments\v10s3_energy_peak
experiments\v10s4_nonfft_selftest
experiments\v10s5_combined_selftest
experiments\phase1_fft_shadow_selftest
```

The Phase 1 FFT shadow experiment includes the deterministic ABI fixture,
P1.3b top-4 reducer primitive, P1.3c coarse96 reducer primitive, and P1.3d
FFT4 smoke core. Its A-lane handoff is
`experiments\phase1_fft_shadow_selftest\HANDOFF.md`. Each current V10 source
directory has a local `README.md`.
Read those before running scripts or moving files.

V8-derived diagnostic source areas:

```text
experiments\v8d0_layout_probe
experiments\v8d1_incremental_auto_roll_fix
```

## Artifact Map

Current or recent artifact directories:

| Version | Directory | Status |
| --- | --- | --- |
| V8L1 | `boot_experiments\sd_boot_rebuild_p201_summary_v8l1_auto_agg` | Highest hardware-validated baseline. |
| V8 | `boot_experiments\sd_boot_rebuild_p201_summary_v8` | Validated rollback. |
| V8L2 | `boot_experiments\sd_boot_rebuild_p201_summary_v8l2_auto_roll_fix` | PC/staging/register pass; AD9361/IIO fail; not hardware validated. |
| V8D0 | `boot_experiments\sd_boot_rebuild_p201_summary_v8d0_layout_probe` | Diagnostic layout probe artifact. |
| V9A | `boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9` | SPEC9 checks pass; AD9361/IIO fail; not hardware validated. |
| V9B0 | `boot_experiments\sd_boot_rebuild_p201_summary_v9b0_minimal_isolation` | Identity pass; AD9361/IIO fail; not hardware validated. |
| V10S0 | `boot_experiments\sd_boot_rebuild_p201_v10s0_submodule_selftest` | PC build/Bootgen/payload/staging/power-cycle pass; hardware-validated only as isolated self-test. |
| V10S4 | `boot_experiments\sd_boot_rebuild_p201_v10s4_nonfft_selftest` | PC build/Bootgen/payload/staging/self-test pass; AD9361/IIO fail; not hardware validated. |
| V10S5 | no artifact directory yet | Source/script candidate only; XSIM/OOC pass, not IP/BD/bitstream/Bootgen-gated, not staged, not hardware validated. |

Older V1-V7 artifacts remain as historical rollback/evidence baselines.

## Report Map

Use `reports/README.md` for a more detailed index.

High-signal evidence:

```text
reports\p201_summary_v8l1_auto_agg_hardware_validation_20260608.md
reports\p201_summary_v8_hardware_validation_20260608.md
reports\p201_summary_v8l2_auto_roll_fix_hardware_failure_20260608.md
reports\p201_summary_v9a_spec9_hardware_validation_20260608.md
reports\p201_summary_v9a_spec9_iio_failure_diagnostics_20260608.json
reports\p201_summary_v9b0_minimal_isolation_hardware_failure_20260608.md
reports\stage_v10s0_submodule_selftest_bitstream\bitstream_report.md
reports\stage_v10s4_nonfft_selftest_bitstream\bitstream_report.md
```

Current cleanup/history note:

```text
docs\archive\P201PRO_CLEANUP_LOG_20260609.md
```

## Cleanup Policy

Safe to delete/regenerate:

```text
.Xil\
vivado_out\
vivado\ad9361_tap_ip_packager_project*
vivado\ip_packager_project\
root vivado*.log / vivado*.jou
root webtalk*.log / webtalk*.jou
root xsim*.log / xsim*.jou
root xelab.* / xvlog.*
```

Keep unless a newer route explicitly replaces them:

```text
boot_experiments\
reports\
experiments\
scripts\
hdl\
VERSION_ROUTE.md
HANDOFF.md
docs\*.md
nx_experiments\sdr_fpga_offload_test
vendor_experiments\
```

Do not modify:

```text
C:\Users\20642\Desktop\寮€鍙慭SDR\2r2t
G:\ROS寮€鍙慭SDR P201P
```

## Git Notes

Generated bitstreams, BOOT images, Vivado project output, and vendor copies are
ignored. Text manifests, artifact READMEs, hashes, reports, scripts, HDL, and
route documents should be tracked when they define project state.
