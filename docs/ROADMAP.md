# SDR Agent roadmap

Last reviewed: 2026-09-04

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

- Preserve the completed seed44/seed43 D8 source/checkpoint inventory, full
  FP32 corpus metrics, 4090 same-IQ numerical reference and the completed
  experimental P201-to-CUDA/Mamba wiring test.
- Treat the deployed local Spark-X2.5-4B as the Chapter 1–2 Planner: it consumes
  bounded receive observations and proposes the next RX-only action. Mamba is
  the Chapter 6 signal classifier; neither model receives hardware authority.
- Keep BF16 Spark as the local default. Retain the existing operator-selected
  OpenAI-compatible provider interface without automatic failover; keep the
  community Q8 build experimental until a larger fixed Planner regression
  reverses its current 3/5 versus BF16 4/5 smoke result.
- Jointly version the Chapter 4 acquisition-to-model handoff before further
  model promotion: candidate eligibility, fixed initial sample-rate domain,
  gain/SNR semantics, window alignment, preprocessing and exact byte limits.
- Freeze the labeled offline splits and build a versioned bounded P201
  receive-only corpus with explicit label provenance, session/day isolation and
  exact profile hashes. Unlabeled field windows may validate domain shift,
  quality and rejection, but must not be counted as classification accuracy.
- Resolve the disputed RML names while retaining numeric labels as the trusted
  interim identity.
- Treat seed44 as a historical baseline, freeze `rf_preprocess_v1` using only
  train/validation evidence, then retrain or fine-tune an RF-aligned D8 model on
  4090 instead of promoting the current unit-RMS bridge.
- Compare FP16/BF16/FP32 on the RF-aligned model and validate closed-set,
  noise/unknown rejection, per-class/SNR accuracy, latency, memory, queue drops,
  cancellation, concurrency and thermals.
- Keep local Spark and Mamba resident, follow the natural data order `Spark ->
  Mamba -> Spark`, and extend the inference lease to make that serial order
  fail-closed under cancellation, late-result and concurrent-input races.
  Complete sustained deadlines, queue and thermal validation before enabling
  recognition.
- Add runtime Worker/profile health probing, then connect the existing
  `run_local_recognition` action to Runner/Web. Feed its compact stateful result
  back to Spark for a newly validated receive-only next step, and enable the
  capability only after every admission gate passes.

The field-level ownership, chapter structure and delivery gates are defined in
[`CHAPTER_4_6_INTEGRATION_PLAN.md`](CHAPTER_4_6_INTEGRATION_PLAN.md).

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
