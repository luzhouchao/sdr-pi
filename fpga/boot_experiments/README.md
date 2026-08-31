# Boot Experiment Artifacts

This directory holds versioned BOOT/SD payload artifacts, BIFs, hashes, artifact
READMEs, and staging JSON. `VERSION_ROUTE.md` is the source of truth for which
artifact is current, validated, rejected, or a rollback.

## Current High-Signal Artifacts

| Version | Directory | Status |
| --- | --- | --- |
| V8L1 | `sd_boot_rebuild_p201_summary_v8l1_auto_agg` | Highest hardware-validated baseline. |
| V8 | `sd_boot_rebuild_p201_summary_v8` | First validated rollback. |
| V8L2 | `sd_boot_rebuild_p201_summary_v8l2_auto_roll_fix` | Identity pass, AD9361/IIO fail, not hardware validated. |
| V8D0 | `sd_boot_rebuild_p201_summary_v8d0_layout_probe` | Diagnostic layout probe artifact. |
| V9A | `sd_boot_rebuild_p201_summary_v9a_spec9` | SPEC9 checks pass, AD9361/IIO fail, not hardware validated. |
| V9B0 | `sd_boot_rebuild_p201_summary_v9b0_minimal_isolation` | Minimal isolation pass, AD9361/IIO fail, not hardware validated. |
| V10S0 | `sd_boot_rebuild_p201_v10s0_submodule_selftest` | PC build/Bootgen/payload/staging/power-cycle pass; hardware-validated only as isolated self-test on V8D0 base. |
| V10S4 | `sd_boot_rebuild_p201_v10s4_nonfft_selftest` | PC build/Bootgen/payload/staging and self-test registers pass; AD9361/IIO fail, not hardware validated. |
| V10S5 | not created yet | Source/script candidate only; no BOOT, no SD payload, not hardware validated. |

Older V1-V7 directories are historical rollback/evidence baselines.

## Rules

- Do not overwrite original SD backups or original `BOOT.bin` files.
- Only copy a version's `sd_payload` after the local artifact gate in `AGENTS.md` passes.
- Hardware validation requires physical SDR power-cycle by the user and the matching post-boot validation checks.
- Ignored binaries may exist locally; tracked text manifests and READMEs are the portable evidence.
