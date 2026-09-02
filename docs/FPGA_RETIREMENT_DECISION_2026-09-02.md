# FPGA retirement decision — 2026-09-02

## Decision

The user explicitly abandoned FPGA acceleration for the SDR Agent project on
2026-09-02. This cancels the former FPGA image, HDL kernel, FFT/PSD, DMA/ring,
shadow comparison, stability, and deployment milestones. FPGA is not a deferred
optimization and must not be presented as a future production backend.

The production architecture is:

```text
P201 AD9361 + Linux/IIO
  -> bounded receive-only IQ acquisition and transport
  -> AGX software aggregation, storage, candidate detection and inference
```

No `BOOT.bin`, FPGA register, MMIO, UIO, Vivado, Bootgen, or hardware state was
changed to enact this decision.

## Repository treatment

- Completed FPGA design, probe, protocol and fail-closed tests remain in Git as
  historical evidence. They are not proof of a production capability.
- The legacy protocol fields and Adapter source may remain where needed for
  compatibility with already deployed SDRD/1 schemas and old validation
  artifacts. Production must report the capability false and must never select
  that Adapter.
- `fpga/` and FPGA-specific reports are archived evidence. Their embedded older
  plans and standing approvals are superseded by the retirement notice in the
  root and nested `AGENTS.md` files.
- `ENABLE_FPGA=1` is prohibited for project builds and releases. Existing
  source-level support is not an authorized deployment path.
- Default native builds, unit tests, and ARMv7 cross-builds link only the
  fail-closed compatibility stub; they do not compile the historical MMIO
  implementation.
- Reopening the route requires a new explicit user decision reversing this
  retirement. Performance pressure alone is not authorization.

## State verified at retirement

- Every checked-in SDRD configuration sets `fpga_backend=disabled`.
- The deployed Web PlanningContext reported `fpga_available=false` while the
  SDR remained online with bounded retune and IQ-capture capability.
- The production terminal constructs `SdrdSoftwareSweepAdapter`; it does not
  construct `SdrdFpgaSweepAdapter`.
- The Linux/IIO-only daemon and unit-test build passed, the resulting daemon had
  no `p201_native_mmio` symbols, and an `ENABLE_FPGA=1` build was rejected by
  the retirement guard.
- The deployed AGX scan path was already live-validated as P201 inline IQ to
  AGX software aggregation, SQLite/Web persistence, optional SigMF storage,
  cancellation and radio restoration.

The active unfinished performance work is therefore sustained 5/10 MS/s
software-path measurement, dropped-sample/latency/thermal accounting, fault
recovery and long-duration soak testing. The next functional milestone remains
the AGX CUDA modulation recognizer, not FPGA offload.
