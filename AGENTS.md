# Project agent instructions

## Living project checklist

The authoritative implementation-status checklist is
[`docs/SDR_AGENT_PROJECT_CHECKLIST.md`](docs/SDR_AGENT_PROJECT_CHECKLIST.md).

All agents working in this repository must follow these rules:

1. Read the relevant checklist section before planning or changing a subsystem.
2. Update the checklist in the same change whenever a listed item is completed,
   invalidated, split into smaller work, or given a materially different scope.
3. Mark an item `- [x]` only after its stated completion condition has been
   implemented and verified. Code, design, mocks, or tests alone do not prove a
   live/deployed item unless the checklist wording explicitly says they do.
4. Keep an item `- [ ]` while any part of its wording remains incomplete. Split
   partially completed work into precise completed and incomplete child items
   instead of using an ambiguous partial-status symbol.
5. For hardware and deployment work, require live target validation before
   checking the item. Record the validation document, artifact hash, release,
   or test evidence when practical.
6. Do not mark future capability true in configuration merely to satisfy a
   checklist item. Runtime capability must come from the responsible Adapter or
   hardware probe and fail closed when unavailable.
7. Preserve completed historical items unless evidence shows a regression. If a
   regression occurs, uncheck the item and add a short note pointing to the
   failure evidence or follow-up task.
8. Before finishing a project change, review `git diff` and confirm the
   checklist accurately describes the resulting repository and deployed state.

## Retired FPGA scope

The user retired the FPGA acceleration route on 2026-09-02. This decision
overrides older FPGA plans, checklists, experiments, and standing approvals:

1. The production architecture is P201 Linux/IIO bounded RX acquisition and
   transport followed by AGX software aggregation, storage, and inference.
2. Do not build, enable, deploy, stage, or advertise an FPGA aggregation
   backend. Do not use `ENABLE_FPGA=1`, write FPGA registers, generate or copy a
   `BOOT.bin`, modify the boot chain, or resume FPGA/NX offload work.
3. Protocol-v1 FPGA fields may remain only as constant false/zero wire-compatibility
   fields for already deployed clients. They must not reach the Planner as a
   selectable capability.
4. The retired FPGA source tree, MMIO Adapter, Pi VkFFT experiment and obsolete
   research documents were removed from the working tree at the user's request
   on 2026-09-02. Git history before that cleanup is the audit archive; do not
   restore those files into current source merely for historical reference.
5. Reopening FPGA work requires a new explicit user decision that reverses this
   retirement; ordinary performance work or hardware access authorization is
   not sufficient.

## Development sweep authorization and data hygiene

The user authorizes the agent to approve receive-only, bounded sweep operations
during development without asking again, subject to all of these constraints:

1. The sweep must stay inside repository safety limits, use one RX path by
   default, have explicit frequency/sample-rate/bandwidth/dwell/point limits,
   and include a direct stop plus verified radio-state restoration.
2. This authorization does not cover transmission, arbitrary IIO writes,
   capture without a plan-derived finite byte count, persistent radio changes,
   FPGA/`BOOT.bin` work, or disabling a safety check. FPGA/`BOOT.bin` work is
   retired from project scope; the other actions require separate explicit
   authority.
3. Before a live sweep, print or record the validated plan, estimated duration,
   maximum bytes, free-space check, and the exact temporary data directory.
4. In the software path, the SDR is responsible only for bounded RX acquisition
   and transport. AGX owns raw-IQ storage, software aggregation, power/noise
   estimation, candidate merging, and model-facing summaries. Do not move
   software aggregation back onto the SDR merely to reduce transport unless the
   user explicitly changes this architecture. There is no active FPGA summary
   backend.
5. Put AGX development data only under
   `/var/tmp/sdrharness-dev/<feature-id>/`, legacy Pi development data only under
   `/var/tmp/sdr-agent-dev/<feature-id>/`, and SDR-local transient data only
   under `/tmp/sdr-agent-dev/<feature-id>/`. Use a unique feature ID. There is no
   project-wide fixed 64 MiB ceiling: derive and record a finite maximum byte
   count from the validated frequency/point/sample plan, verify AGX free space
   before capture, and fail closed if the exact bound or space check is absent.
   SDR-local data must be transient and removed after confirmed AGX receipt.
6. Keep raw IQ and intermediate sweep outputs out of Git. Retain the feature's
   source code, public and internal interfaces, tests, configuration examples,
   design documents, bounded summaries, hashes, metrics, and validation
   documentation.
7. User-visible acquisition results are not development temporary data. The AGX
   may persist processed sweep points, candidates, recognition output, or
   explicitly selected IQ in an application-owned result store outside Git.
   Such results must have a visible manual-delete path and must not be removed
   by development cleanup unless the user selected them for deletion.
8. At the end of each feature, stop all feature processes, verify the exact
   resolved feature-directory paths, delete those directories and workstation
   staging artifacts, and report what was removed. A feature is not complete
   and its checklist item must not be checked until cleanup is verified.
9. Treat each completed feature as its own delivery unit: after tests pass,
   temporary data cleanup is verified, and the checklist is updated, create a
   focused commit and push it to the configured Git remote promptly. Do not
   defer several completed features into one unrelated batch.

Nested `AGENTS.md` files may add subsystem-specific instructions. The nearest
file to the changed code takes precedence when instructions differ.
