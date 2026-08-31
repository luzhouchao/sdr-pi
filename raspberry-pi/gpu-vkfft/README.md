# Raspberry Pi 4 VkFFT benchmark

This directory records the reproducible cross-build and target-side benchmark
for the Raspberry Pi 4 V3D/V3DV Vulkan path. It does not vendor VkFFT or commit
generated binaries.

## Pinned upstream

- VkFFT release: `v1.3.4`
- Commit: `066a17c17068c0f11c9298d848c2976c71fad1c1`
- Backend: Vulkan (`VKFFT_BACKEND=0`)

Clone the exact source outside this repository:

```bash
git clone --depth 1 --branch v1.3.4 https://github.com/DTolm/VkFFT.git /tmp/VkFFT-v1.3.4
test "$(git -C /tmp/VkFFT-v1.3.4 rev-parse HEAD)" = \
  066a17c17068c0f11c9298d848c2976c71fad1c1
```

## ARM64 cross-build

From this directory in WSL:

```bash
docker build -t p201-vkfft-cross:trixie -f Dockerfile.cross .
mkdir -p build
docker run --rm \
  -v /tmp/VkFFT-v1.3.4:/src \
  -v "$PWD:/work" \
  -v "$PWD/build:/build" \
  -w /build \
  p201-vkfft-cross:trixie \
  cmake -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE=/work/toolchain-aarch64.cmake \
    -DCMAKE_BUILD_TYPE=Release \
    -DVKFFT_BACKEND=0 \
    /src
docker run --rm \
  -v "$PWD/build:/build" \
  -w /build \
  p201-vkfft-cross:trixie \
  cmake --build . --parallel
```

Verify the produced target before deployment:

```bash
file build/VkFFT_TestSuite
aarch64-linux-gnu-readelf -l build/VkFFT_TestSuite | grep interpreter
aarch64-linux-gnu-readelf -d build/VkFFT_TestSuite | grep NEEDED
sha256sum build/VkFFT_TestSuite
```

Building does not authorize upload or execution. Target deployment and GPU
boot configuration require separate approval and a recorded rollback.

## Kernel-only test matrix

Force the real V3D device rather than llvmpipe by selecting device `0` only
after `-devices` confirms its name:

```bash
./VkFFT_TestSuite -devices
timeout 30s ./VkFFT_TestSuite -d 0 -benchmark_vkfft -X 2048 -Y 1 -Z 1 -P 0 -B 1 -N 50
timeout 30s ./VkFFT_TestSuite -d 0 -benchmark_vkfft -X 2048 -Y 1 -Z 1 -P 0 -B 8 -N 50
timeout 30s ./VkFFT_TestSuite -d 0 -benchmark_vkfft -X 2048 -Y 1 -Z 1 -P 0 -B 16 -N 50
timeout 30s ./VkFFT_TestSuite -d 0 -benchmark_vkfft -X 2048 -Y 1 -Z 1 -P 0 -B 32 -N 50
```

This upstream benchmark measures steady-state FFT/iFFT work. It does not
include SDR IQ handoff, i16 conversion, Hann, PSD, reduction, or result
readback, so it cannot by itself promote the GPU backend. The production gate
requires a later fused end-to-end benchmark against the RustFFT reference.

`N` records that many forward/inverse pairs into one Vulkan command buffer; it
is not an outer host-side repeat count. Keep it small and use an external
timeout. The first live test showed that `8192 x batch32 x N500` can make the Pi
unresponsive to SSH even while ICMP remains alive. That combination is a known
NO-GO and must not be repeated without an independent hardware watchdog.
