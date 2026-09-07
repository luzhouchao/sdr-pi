#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
artifact_root="${repo_root}/.artifacts/sdrharness"

if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "This native build entry must run on the Jetson AGX (aarch64)." >&2
  exit 2
fi

for command_name in cargo node npm c++ make install; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing required command: ${command_name}" >&2
    exit 2
  fi
done

mkdir -p "${artifact_root}/bin"

controller="${repo_root}/raspberry-pi/sdr-agent/controller"
(
  cd "${controller}"
  cargo fmt -- --check
  cargo test --all-targets
  cargo clippy --all-targets -- -D warnings
  cargo build --locked --release --bins
)
install -m 0755 "${controller}/target/release/sdr-agent" "${artifact_root}/bin/"
# This directory is generated build staging, not the installed runtime or a
# retained rollback release. Do not publish obsolete binaries from older builds.
rm -f -- "${artifact_root}/bin/sdr-agent-controller" "${artifact_root}/bin/sdr-agent-health"

web_console="${repo_root}/raspberry-pi/sdr-agent/web-console"
(
  cd "${web_console}"
  cargo fmt -- --check
  cargo test --all-targets
  cargo clippy --all-targets -- -D warnings
  cargo build --locked --release
)
install -m 0755 "${web_console}/target/release/sdr-agent-web-console" "${artifact_root}/bin/"

planner="${repo_root}/raspberry-pi/sdr-agent/planner-worker"
(
  cd "${planner}"
  npm ci
  npm test
)

recognizer_worker="${repo_root}/raspberry-pi/sdr-agent/recognizer-worker"
(
  cd "${recognizer_worker}"
  make test
)

sha256sum "${artifact_root}/bin/"* | tee "${artifact_root}/SHA256SUMS"
echo "AGX runtime artifacts: ${artifact_root}"
