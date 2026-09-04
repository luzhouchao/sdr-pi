#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"

required=(
  "AGENTS.md"
  "docs/AMC_CORPUS_MANIFEST_V1.md"
  "docs/AMC_SPLIT_ISOLATION_AUDIT_2026-09-05.json"
  "docs/AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md"
  "docs/SDR_AGENT_PROJECT_CHECKLIST.md"
  "jetson-agx/sdrharness/config/request.json"
  "jetson-agx/sdrharness/config/amc/rml2018a-d8-seed44.experimental.json"
  "jetson-agx/sdrharness/config/amc/rml2018a-d8-current.integration-profile.json"
  "jetson-agx/sdrharness/config/amc/legacy-adc-unit-rms-v0.json"
  "jetson-agx/sdrharness/config/amc/rf-preprocess-v1-selection-plan.json"
  "jetson-agx/sdrharness/config/amc/amc-corpus-manifest-v1.schema.json"
  "jetson-agx/sdrharness/config/runtime.env.example"
  "jetson-agx/sdrharness/scripts/amc-mamba-worker.py"
  "jetson-agx/sdrharness/scripts/audit-amc-split-isolation.py"
  "jetson-agx/sdrharness/scripts/validate-amc-corpus-manifest.py"
  "jetson-agx/sdrharness/tests/test_amc_corpus_manifest.py"
  "jetson-agx/sdrharness/tests/test_amc_split_isolation.py"
  "jetson-agx/sdrharness/systemd/sdrharness-amc-mamba-experimental.service"
  "jetson-agx/sdrharness/systemd/sdrharness-planner.service"
  "jetson-agx/sdrharness/systemd/sdrharness-web.service"
  "jetson-agx/sdrharness/scripts/check-toolchain.sh"
  "raspberry-pi/sdr-agent/controller/Cargo.lock"
  "raspberry-pi/sdr-agent/controller/config/live-recognition.experimental.example.json"
  "raspberry-pi/sdr-agent/planner-worker/package-lock.json"
  "raspberry-pi/sdr-agent/web-console/Cargo.lock"
  "sdr-system/sdrd/README.md"
)

for relative_path in "${required[@]}"; do
  if [[ ! -f "${repo_root}/${relative_path}" ]]; then
    echo "Missing required repository file: ${relative_path}" >&2
    exit 1
  fi
done

git -C "${repo_root}" diff --check
echo "checkout_ok root=${repo_root} target=/home/jetson/sdrharness"
