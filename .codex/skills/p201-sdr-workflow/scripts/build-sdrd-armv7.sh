#!/usr/bin/env bash
set -euo pipefail

readonly script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly repo_root="$(cd "${script_dir}/../../../.." && pwd)"
readonly toolchain_root="/home/jetson/.local/lib/sdrharness/toolchains/gcc-arm-8.2-2018.08-x86_64-arm-linux-gnueabihf"
readonly builder_image="ubuntu:18.04"
readonly builder_image_id="sha256:152dc042452c496007f07ca9127571cb9c29697f42acbfad72324b2bb2e43c98"

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /var/tmp/sdrharness-dev/<feature-id>/<build-directory>" >&2
  exit 2
fi

output_dir="$(realpath -m -- "$1")"
case "${output_dir}" in
  /var/tmp/sdrharness-dev/*/*) ;;
  *)
    echo "output must be below /var/tmp/sdrharness-dev/<feature-id>/" >&2
    exit 2
    ;;
esac

for tool in arm-linux-gnueabihf-gcc arm-linux-gnueabihf-strip arm-linux-gnueabihf-readelf arm-linux-gnueabihf-nm; do
  if [[ ! -x "${toolchain_root}/bin/${tool}" ]]; then
    echo "missing persistent verified toolchain executable: ${toolchain_root}/bin/${tool}" >&2
    exit 1
  fi
done

actual_image_id="$(docker image inspect --format '{{.Id}}' "${builder_image}")"
if [[ "${actual_image_id}" != "${builder_image_id}" ]]; then
  echo "unexpected ${builder_image} image id: ${actual_image_id}" >&2
  exit 1
fi

mkdir -p -- "${output_dir}"
docker run --rm --platform linux/amd64 \
  --user "$(id -u):$(id -g)" \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --workdir /tmp \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  -v "${repo_root}:/src:ro" \
  -v "${toolchain_root}:/toolchain:ro" \
  -v "${output_dir}:/out" \
  "${builder_image}" \
  /toolchain/bin/arm-linux-gnueabihf-gcc \
    -I/src/sdr-system/sdrd/include \
    -std=c11 -O2 -Wall -Wextra -Wpedantic -Werror \
    -o /out/sdrd \
    /src/sdr-system/sdrd/src/main.c \
    /src/sdr-system/sdrd/src/sdrd.c \
    /src/sdr-system/sdrd/src/sdrd_iio.c \
    -ldl -pthread

nm_output="$(docker run --rm --platform linux/amd64 \
  --user "$(id -u):$(id -g)" \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --workdir /tmp \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  -v "${toolchain_root}:/toolchain:ro" \
  -v "${output_dir}:/out:ro" \
  "${builder_image}" \
  /toolchain/bin/arm-linux-gnueabihf-nm /out/sdrd)"
if printf '%s\n' "${nm_output}" | grep -Eiq 'fpga|mmio|uio'; then
  echo "retired FPGA/MMIO/UIO symbol gate failed" >&2
  exit 1
fi

docker run --rm --platform linux/amd64 \
  --user "$(id -u):$(id -g)" \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --workdir /tmp \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  -v "${toolchain_root}:/toolchain:ro" \
  -v "${output_dir}:/out" \
  "${builder_image}" \
  /toolchain/bin/arm-linux-gnueabihf-strip /out/sdrd

artifact="${output_dir}/sdrd"
file_output="$(file -- "${artifact}")"
echo "${file_output}"
if [[ "${file_output}" != *"ELF 32-bit"* || "${file_output}" != *"ARM"* || "${file_output}" != *"EABI5"* || "${file_output}" != *"dynamically linked"* ]]; then
  echo "ARM/EABI/dynamic-link gate failed" >&2
  exit 1
fi

readelf_output="$(docker run --rm --platform linux/amd64 \
  --user "$(id -u):$(id -g)" \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --workdir /tmp \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  -v "${toolchain_root}:/toolchain:ro" \
  -v "${output_dir}:/out:ro" \
  "${builder_image}" \
  /toolchain/bin/arm-linux-gnueabihf-readelf --version-info /out/sdrd)"
printf '%s\n' "${readelf_output}"

versions="$(printf '%s\n' "${readelf_output}" | sed -n 's/.*Name: \(GLIBC_[0-9.]*\).*/\1/p' | sort -Vu)"
if [[ -z "${versions}" ]]; then
  echo "no GLIBC requirements found" >&2
  exit 1
fi
while IFS= read -r version; do
  case "${version}" in
    GLIBC_2.4|GLIBC_2.7|GLIBC_2.17) ;;
    *)
      echo "unsupported GLIBC requirement: ${version}" >&2
      exit 1
      ;;
  esac
done <<< "${versions}"

sha256sum -- "${artifact}"
printf 'toolchain_root=%s\nbuilder_image_id=%s\nglibc_requirements=%s\n' \
  "${toolchain_root}" "${actual_image_id}" "$(printf '%s' "${versions}" | tr '\n' ',')"
