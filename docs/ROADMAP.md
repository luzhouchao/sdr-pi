# SDR Agent roadmap

Last reviewed: 2026-09-05

The authoritative item-level status is
[`SDR_AGENT_PROJECT_CHECKLIST.md`](SDR_AGENT_PROJECT_CHECKLIST.md).

## Current Chapter 1–6 plan

The former separate Stage 1/2 and Chapter 4–6 lists are replaced by one
checkbox-based receive-only plan:
[`CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md).
Do not maintain a second copy of its completion state here.

The fixed P201 RX1/A_BALANCED identity and the independent Chapter 4 bounded
acquisition/overload gates are complete. The next dependency chain is: define
the Chapter 5 corpus contract and freeze its preprocessing from train/validation
evidence; let the user train the RF-aligned Chapter 6 model and admit it on AGX;
then connect recognition to the Chapter 1/2 Runner, Agent and Web loop. The
detailed checklist records which parts of each dependency are already complete.

## After Chapter 1–6 — production operations

- Add protocol fuzzing and repeatable fault injection.
- Add log rotation, health monitoring, alerts, update and rollback procedures.
- Complete a documented 24-hour automatic-cruise soak.
- Keep bounded session resume and the single-active-control gate covered by
  regression tests; multi-user control is outside the selected operator model.

## Later research — emitter identification

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
