#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"

required=(
  "AGENTS.md"
  "docs/reference/AMC_CORPUS_MANIFEST_V1.md"
  "docs/RF_PREPROCESS_V1_SELECTION_AUDIT_2026-09-05.json"
  "docs/validation/RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md"
  "docs/RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_AUDIT_2026-09-05.json"
  "docs/validation/RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md"
  "docs/evidence/RF_V1_PRECISION_SELECTION_AUDIT_2026-09-05.json"
  "docs/validation/RF_V1_PRECISION_SELECTION_VALIDATION_2026-09-05.md"
  "docs/SDR_AGENT_PROJECT_CHECKLIST.md"
  "deploy/agx/config/request.json"
  "deploy/agx/config/amc/rml2018a-d8-seed44.experimental.json"
  "deploy/agx/config/amc/rml2018a-d8-current.integration-profile.layout-v2.json"
  "deploy/agx/config/amc/legacy-adc-unit-rms-v0.json"
  "deploy/agx/config/amc/rf-preprocess-v1-selection-plan.json"
  "deploy/agx/config/amc/rf-preprocess-v1.json"
  "deploy/agx/config/amc/rf-v1-precision-selection-plan.json"
  "deploy/agx/config/amc/rml2018a-d8-rf-v1-ft-batched-seed44.candidate.json"
  "deploy/agx/config/amc/rml2018a-d8-rf-v1-fp16.candidate.json"
  "deploy/agx/config/amc/amc-corpus-manifest-v1.schema.json"
  "deploy/agx/config/runtime.env.example"
  "deploy/agx/scripts/amc-mamba-worker.py"
  "deploy/agx/scripts/audit-amc-split-isolation.py"
  "deploy/agx/scripts/select-rf-preprocess-validation.py"
  "deploy/agx/scripts/select-rf-v1-precision.py"
  "deploy/agx/scripts/validate-rf-aligned-checkpoint.py"
  "deploy/agx/scripts/validate-amc-corpus-manifest.py"
  "deploy/agx/tests/test_amc_corpus_manifest.py"
  "deploy/agx/tests/test_amc_split_isolation.py"
  "deploy/agx/tests/test_rf_preprocess_validation_selection.py"
  "deploy/agx/tests/test_rf_v1_precision_selection.py"
  "deploy/agx/tests/test_rf_aligned_checkpoint_validation.py"
  "deploy/agx/systemd/sdrharness-amc-mamba-experimental.service"
  "deploy/agx/systemd/sdrharness-planner.service"
  "deploy/agx/systemd/sdrharness-web.service"
  "deploy/agx/scripts/check-toolchain.sh"
  "src/agent/controller/Cargo.lock"
  "src/agent/controller/config/live-recognition.experimental.example.json"
  "src/agent/controller/tests/fixtures/rf-preprocess-v1-golden.json"
  "src/agent/planner-worker/package-lock.json"
  "src/agent/web-console/Cargo.lock"
  "src/sdrd/README.md"
)

for relative_path in "${required[@]}"; do
  if [[ ! -f "${repo_root}/${relative_path}" ]]; then
    echo "Missing required repository file: ${relative_path}" >&2
    exit 1
  fi
done

git -C "${repo_root}" diff --check
echo "checkout_ok root=${repo_root} target=/home/jetson/sdrharness"
