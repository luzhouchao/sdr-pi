#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "wrong_arch expected=aarch64 actual=$(uname -m)" >&2
  exit 2
fi

required=(git rustc cargo node npm cc c++ make pkg-config curl)
for command_name in "${required[@]}"; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "missing=${command_name}" >&2
    exit 2
  fi
done

rustc --version
cargo --version
node --version
npm --version
cc --version | sed -n '1p'
c++ --version | sed -n '1p'
make --version | sed -n '1p'
pkg-config --version
curl --version | sed -n '1p'

if ! cargo fmt --version >/dev/null 2>&1; then
  echo "missing=rustfmt" >&2
  exit 2
fi
if ! cargo clippy --version >/dev/null 2>&1; then
  echo "missing=clippy" >&2
  exit 2
fi

echo "toolchain_ok architecture=aarch64"
