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

## Repository cleanup

- At the user's request, the complete `fpga/` tree, FPGA-only reports, MMIO
  Adapter and its tests were removed from the current working tree.
- The obsolete Pi VkFFT route, Pi-sized model research, superseded performance
  plans and duplicate P201 connection skill were also removed.
- Protocol-v1 capability and health responses retain constant false/zero FPGA
  fields so already deployed clients keep parsing. The Planner strips the old
  `fpga_available=false` field and rejects any legacy true claim.
- `CAPTURE_SUMMARY` remains recognizable only to return `retired_command`; no
  implementation or configuration path exists.
- The pre-cleanup tree remains recoverable from Git history at `59cbb17` if a
  future audit needs the old evidence. It is not an active project archive.
- Reopening the route requires a new explicit user decision reversing this
  retirement. Performance pressure alone is not authorization.

## State verified at retirement

- The deployed Web PlanningContext reported `fpga_available=false` while the
  SDR remained online with bounded retune and IQ-capture capability.
- The production terminal constructs `SdrdSoftwareSweepAdapter`; it does not
  construct `SdrdFpgaSweepAdapter`.
- Current SDRD configuration contains no FPGA backend or MMIO settings.
- The deployed AGX scan path was already live-validated as P201 inline IQ to
  AGX software aggregation, SQLite/Web persistence, optional SigMF storage,
  cancellation and radio restoration.

The active unfinished performance work is therefore sustained 5/10 MS/s
software-path measurement, dropped-sample/latency/thermal accounting, fault
recovery and long-duration soak testing. The next functional milestone remains
the AGX CUDA modulation recognizer, not FPGA offload.
