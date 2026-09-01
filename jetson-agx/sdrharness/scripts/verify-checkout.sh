#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"

required=(
  "AGENTS.md"
  "docs/SDR_AGENT_PROJECT_CHECKLIST.md"
  "jetson-agx/sdrharness/config/request.json"
  "jetson-agx/sdrharness/config/runtime.env.example"
  "jetson-agx/sdrharness/systemd/sdrharness-planner.service"
  "jetson-agx/sdrharness/systemd/sdrharness-web.service"
  "jetson-agx/sdrharness/scripts/check-toolchain.sh"
  "raspberry-pi/sdr-agent/controller/Cargo.lock"
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
