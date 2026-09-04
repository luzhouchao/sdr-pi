# Documentation index

## Current sources of truth

- [`SDR_AGENT_PROJECT_CHECKLIST.md`](SDR_AGENT_PROJECT_CHECKLIST.md): exact
  implementation and validation status.
- [`ROADMAP.md`](ROADMAP.md): ordered future work.
- [`SDR_AGENT_RUNTIME_DESIGN.md`](SDR_AGENT_RUNTIME_DESIGN.md): Agent,
  Controller and Planner boundaries.
- [`SDR_PREPROCESSING_SWEEP_ARCHITECTURE.md`](SDR_PREPROCESSING_SWEEP_ARCHITECTURE.md):
  current P201-to-AGX sweep and result path.
- [`LOCAL_RECOGNIZER_INTERFACE.md`](LOCAL_RECOGNIZER_INTERFACE.md): stable
  recognition interface and unfinished CUDA/Mamba backend.
- [`NX_B210_MAMBA_D8_ASSET_HANDOFF.md`](NX_B210_MAMBA_D8_ASSET_HANDOFF.md):
  verified NX/B210 inventory and externally staged AGX D8/RML2018A candidate
  checkpoint handoff.
- [`AGX_SDRHARNESS_MIGRATION.md`](AGX_SDRHARNESS_MIGRATION.md): AGX deployment
  layout and remaining acquisition cutover gate.
- [`FPGA_RETIREMENT_DECISION_2026-09-02.md`](FPGA_RETIREMENT_DECISION_2026-09-02.md):
  permanent retired-scope boundary.

## Validation records

Files with dated `VALIDATION`, `DEPLOYMENT`, `RESULTS` or `BASELINE` names are
immutable evidence of what was actually tested. They may describe an older
release, but they are not current instructions. Follow the checklist and the
current design documents above when they differ.

The large retired FPGA/Vivado tree, FPGA-only reports, Pi VkFFT experiment and
superseded research notes were removed from the working tree on 2026-09-02.
They remain available in Git history before the cleanup change if an audit ever
requires them.
