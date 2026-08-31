# SDR Agent FPGA sweep gate validation

Date: 2026-09-01

## Outcome

The Harness software path now reaches the FPGA image gate. The Rust
`SweepEngine.run(plan)` interface hides bounded plan expansion, one-session
multi-point execution, summary validation, noise estimation, candidate merging
and Agent-observation conversion. It has replay and SDRD production Adapters.

SDRD/1 now defines `CAPTURE_SUMMARY` for one generation-correlated aggregate
point. The C FPGA Adapter keeps one MMIO mapping, verifies the existing
SUM8/AGG8 identity before writable open, arms a bounded frame/aggregate count,
checks cancellation every millisecond, enforces a timeout, reads fixed-shape
quality and power metadata, and restores the radio on failure.

## Verification

- C build and strict-warning tests: pass.
- Rust formatting, 25 tests and Clippy with warnings denied: pass.
- ARMv7 `sdrd` final cross-build: GLIBC 2.17/2.4/2.7,
  SHA-256 `ffa78ef33c2222adec81eed4c08caf03888a1bc458328bcc681590aba2e3eac9`.
- Static AArch64 Controller:
  `3dea37a922dfc048873b5e8b27d9a47c0dbe7159434971dc531909ec1ee4a49f`.
- Static AArch64 terminal:
  `b6ab13970f06026c8b3327c0fe2f98b3c1a336f141f5963474984b528fc2e27b`.

The live gate plan contained three centers at 2.440, 2.442 and 2.444 GHz,
3 MS/s sample rate, 2.5 MHz bandwidth, 5 ms settle, and 2048 by 16 aggregate
samples per point. Its estimated upper duration was 1515 ms, summary output was
bounded below 16 KiB, and raw-IQ allowance was zero.

On the real SDR, the original FPGA image reported:

```text
fpga_backend=disabled
fpga_identity_valid=false
fpga_summary_version=0
fpga_aggregate=false
```

The production Controller returned `fpga_aggregate_unavailable` before
`START_SESSION`. Radio readback remained at the original 2452 MHz LO, 2.1 MS/s
sample rate, 2 MHz bandwidth, `slow_attack`, and scan mask zero. No IQ or sweep
data directory was created. No MMIO write, FPGA register access, `BOOT.bin`
change, transmission, reboot, or persistent SDR service change occurred.

## Deployment and cleanup

The fail-closed Harness binaries are deployed as:

```text
/opt/sdr-agent/current -> /opt/sdr-agent/releases/20260901-fpga-sweep-gate-v1
```

The previous `20260901-cancel-v1` release remains available for rollback and
the Planner service stayed active. Controlled SDRD was temporary and stopped.
The exact staging paths below were removed and verified absent:

```text
SDR: /tmp/sdr-agent-dev/fpga-sweep-gate-v1/
Pi:  /var/tmp/sdr-agent-dev/fpga-sweep-gate-v1/
Pi:  /var/tmp/sdr-agent-dev/fpga-sweep-deploy-v1/
```

## Required FPGA handoff

Do not enable `fpga_backend` yet. Resumption requires a board-matched image with
the documented identity/ABI/build ID, bounded aggregate arm/done behavior,
power and quality counters, monotonic sequence, overflow/stale flags, a UIO or
verified iomem resource, timing closure evidence, image hash, source commit and
golden rollback image. That is the first remaining step that changes the FPGA
image, so Harness sweep work stops here as requested.
