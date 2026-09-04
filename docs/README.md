# Documentation index

## Current sources of truth

- [`SDR_AGENT_PROJECT_CHECKLIST.md`](SDR_AGENT_PROJECT_CHECKLIST.md): exact
  implementation and validation status.
- [`CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md):
  current checkbox-based Chapter 1–6 receive-only implementation plan and the
  concise audit of what remains in Chapters 1–3.
- [`ROADMAP.md`](ROADMAP.md): ordered future work.
- [`SDR_AGENT_RUNTIME_DESIGN.md`](SDR_AGENT_RUNTIME_DESIGN.md): Agent,
  Controller and Planner boundaries.
- [`SDR_PREPROCESSING_SWEEP_ARCHITECTURE.md`](SDR_PREPROCESSING_SWEEP_ARCHITECTURE.md):
  current P201-to-AGX sweep and result path.
- [`LOCAL_RECOGNIZER_INTERFACE.md`](LOCAL_RECOGNIZER_INTERFACE.md): stable
  recognition interface and production-disabled experimental CUDA/Mamba
  Worker.
- [`AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md`](AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md):
  complete RML2018A/HisarMod2019 FP32 accuracy, 4090 logits parity and AGX
  latency/resource evidence; this does not enable the production Recognizer.
- [`AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md`](AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md):
  local BF16/Q8 Planner timing and smoke results, Mamba contention evidence,
  MTP/n-gram findings and the local-first/provider-interface decision.
- [`P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md`](P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md):
  Chapter 4 maximum-window load, pre-hardware overload rejection, bounded
  resources, timeout/disconnect restoration and exact cleanup evidence.
- [`AMC_CORPUS_MANIFEST_V1.md`](AMC_CORPUS_MANIFEST_V1.md): the normative
  Chapter 5 manifest/JSONL window contract for offline, P201 RX-only and golden
  data with explicit label provenance and split lineage.
- [`AMC_CORPUS_CONTRACT_VALIDATION_2026-09-05.md`](AMC_CORPUS_CONTRACT_VALIDATION_2026-09-05.md):
  strict-validator, negative-matrix and existing golden-fixture evidence.
- [`AGX_SDRHARNESS_MIGRATION.md`](AGX_SDRHARNESS_MIGRATION.md): AGX deployment
  layout and completed receive-ownership migration boundary.
- [`FPGA_RETIREMENT_DECISION_2026-09-02.md`](FPGA_RETIREMENT_DECISION_2026-09-02.md):
  permanent retired-scope boundary.

## Validation records

Files with dated `VALIDATION`, `DEPLOYMENT`, `RESULTS` or `BASELINE` names are
immutable evidence of what was actually tested. They may describe an older
release, but they are not current instructions. Follow the checklist and the
current design documents above when they differ.

The former
[`CHAPTER_4_6_INTEGRATION_PLAN.md`](CHAPTER_4_6_INTEGRATION_PLAN.md) is retained
only as superseded design rationale. It is no longer a current plan or status
source.

[`NX_B210_MAMBA_D8_ASSET_HANDOFF.md`](NX_B210_MAMBA_D8_ASSET_HANDOFF.md) is a
historical hardware/model handoff. Its B210 details remain useful port evidence,
but B210/USRP transmission is not part of the current Chapter 1–6 plan.

The large retired FPGA/Vivado tree, FPGA-only reports, Pi VkFFT experiment and
superseded research notes were removed from the working tree on 2026-09-02.
They remain available in Git history before the cleanup change if an audit ever
requires them.
