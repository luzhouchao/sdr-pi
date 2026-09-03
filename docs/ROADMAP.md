# SDR Agent roadmap

Last reviewed: 2026-09-03

The authoritative item-level status is
[`SDR_AGENT_PROJECT_CHECKLIST.md`](SDR_AGENT_PROJECT_CHECKLIST.md).

## Stage 1 — AGX software-path hardening

- Prove AGX is the sole receive-path owner.
- Add complete sequence, overflow, dropped-sample, timeout and health metadata.
- Validate IIO-timeout restoration and full-loop stale/cancel/reconnect recovery.
- Complete bounded AGX software-acquisition overload testing. The separate
  sustained 5/10-MS/s aggregate acceptance gate was removed by explicit
  operator decision on 2026-09-03; this does not add a throughput claim beyond
  the existing measured P201/AGX profile.

## Stage 2 — local modulation recognition

- Identify and version the trained Mamba checkpoint, labels, preprocessing,
  sample-rate policy, precision and acceptance thresholds.
- Implement a backend-neutral CUDA Recognizer Worker on AGX.
- Compare FP16/BF16/FP32 against the training reference and measure end-to-end
  latency, memory, drops and thermals.
- Validate accuracy/per-class recall, then enable the capability and feed only
  selected bounded IQ windows into it.

## Stage 3 — production operations

- Add protocol fuzzing and repeatable fault injection.
- Add log rotation, health monitoring, alerts, update and rollback procedures.
- Complete a documented 24-hour automatic-cruise soak.
- Keep bounded session resume and the single-active-control gate covered by
  regression tests; multi-user control is outside the selected operator model.

## Stage 4 — emitter identification

Start only after modulation recognition and bounded acquisition are stable.
First define whether the target is protocol family, transmitter model or an
individual physical emitter, then establish lawful data collection, open-set
handling and cross-day/channel validation.

## Non-goals

FPGA acceleration, MMIO/UIO, Vivado, `BOOT.bin` changes, transmit support and
multi-user concurrent control are not part of this project. The retired FPGA
implementation was removed from the working tree on 2026-09-02 and remains
recoverable from Git history only. The Web's two bounded conversations are
histories for one trusted human operator, not separate user identities.
