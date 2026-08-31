# Raspberry Pi 4B FFT compute baseline

Test date: 2026-08-31

## Purpose

Measure the CPU cost that a future Rust SDR pipeline will pay after receiving IQ data. This is not an FFT-only synthetic claim: the full timing includes conversion of interleaved signed `i16` IQ to `Complex32`, a Hann window, an in-place complex FFT, and a power-sum/peak reduction.

## Environment

- Raspberry Pi 4B, four Cortex-A72 cores, maximum 1.5 GHz
- 64-bit Raspberry Pi OS/Debian kernel `6.18.39+rpt-rpi-v8`
- CPU governor: `schedutil`
- RustFFT `6.4.1`, default AArch64 NEON path enabled
- Build host: WSL Ubuntu 24.04, Rust `1.98.0`
- Target: `aarch64-unknown-linux-musl`, statically linked and stripped
- Binary SHA-256: `8ed7d584df139026faaf4ee0e74d44d8bde499e8bc2ef203facc663074a4f012`
- Temperature: 37.4 °C before and 39.9 °C after
- Throttle flags: `0x0` before and after

The benchmark allocates the planner, FFT buffers, scratch space, Hann coefficients, and timing vectors before the measured loop. It runs a warm-up before each FFT size.

## Measured result

| NFFT | Iterations | Prepare p50 | FFT p50 | Reduce p50 | Full p50 | Full p99 | One-core capacity, no overlap | One-core capacity, 50% overlap | One-core capacity, 75% overlap |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1024 | 16384 | 2.926 µs | 15.444 µs | 2.982 µs | 24.074 µs | 32.778 µs | 42.536 MS/s | 21.268 MS/s | 10.634 MS/s |
| 2048 | 8192 | 5.370 µs | 32.889 µs | 5.315 µs | 46.352 µs | 51.408 µs | 44.184 MS/s | 22.092 MS/s | 11.046 MS/s |
| 4096 | 4096 | 10.222 µs | 82.518 µs | 9.852 µs | 105.389 µs | 110.648 µs | 38.866 MS/s | 19.433 MS/s | 9.716 MS/s |
| 8192 | 2048 | 18.315 µs | 173.630 µs | 18.352 µs | 213.204 µs | 221.166 µs | 38.423 MS/s | 19.212 MS/s | 9.606 MS/s |
| 16384 | 1024 | 36.426 µs | 389.278 µs | 37.445 µs | 466.074 µs | 482.834 µs | 35.153 MS/s | 17.577 MS/s | 8.788 MS/s |
| 32768 | 512 | 77.815 µs | 887.166 µs | 79.592 µs | 1048.259 µs | 1081.630 µs | 31.259 MS/s | 15.630 MS/s | 7.815 MS/s |

The complete run used 3.301 seconds of user CPU and 0.117 seconds of system CPU over 3.418 seconds wall time. The benchmark is single-threaded.

## 2048-point production budget

Required transforms per second are:

```text
FFTs/s = sample_rate / (NFFT * (1 - overlap))
```

Using the measured 2048-point full-pipeline p50/p99 times:

| Sample rate | Overlap | FFTs/s | CPU cores at p50 | CPU cores at p99 | Decision for one RX |
| ---: | ---: | ---: | ---: | ---: | --- |
| 10 MS/s | 0% | 4,883 | 0.226 | 0.251 | Fits one DSP core comfortably. |
| 20 MS/s | 0% | 9,766 | 0.453 | 0.502 | Fits one DSP core. |
| 25 MS/s | 0% | 12,207 | 0.566 | 0.628 | Fits one DSP core, but leaves less headroom. |
| 10 MS/s | 50% | 9,766 | 0.453 | 0.502 | Fits one DSP core. |
| 20 MS/s | 50% | 19,531 | 0.905 | 1.004 | Too close to one-core saturation; use two workers. |
| 25 MS/s | 50% | 24,414 | 1.132 | 1.255 | Requires at least two workers. |
| 10 MS/s | 75% | 19,531 | 0.905 | 1.004 | Use two workers for production headroom. |
| 20 MS/s | 75% | 39,063 | 1.811 | 2.008 | Consumes about two full cores before later classification. |
| 25 MS/s | 75% | 48,828 | 2.263 | 2.510 | Does not fit the proposed two-core DSP budget. |

Dual-RX processing doubles these CPU-core figures if each receiver requires an independent FFT. Additional operations such as `fftshift`, logarithmic PSD conversion, median/noise-floor estimation, top-k selection, feature extraction, recording, or modulation classification are not included and need further budget.

## Architecture consequence

Reserve CPU0 for Ethernet IRQ/softirq, CPU1 for libiio acquisition and bounded dispatch, and CPU2–CPU3 for two independent single-thread FFT workers. Each worker should own a planned FFT, scratch buffer, Hann coefficients, and reusable frame buffers. Small 2048-point transforms should be parallelized across frames; creating multiple threads inside each individual FFT is likely to add more scheduling overhead than useful work and must be justified by measurement.

Set a production admission limit of at most 70% sustained utilization on the two DSP cores. With that safety margin, one RX at 10 MS/s with 50% overlap is comfortable; 20–25 MS/s with 50% overlap needs two workers; dual RX or 75% overlap at high sample rates becomes a candidate for reduced overlap, decimation/channelization, or FPGA FFT/summary offload.

## Reproduction

Build on WSL, not on the Raspberry Pi:

```bash
export RUSTUP_HOME=/home/dev/.local/cpr-rust-toolchain/rustup
export CARGO_HOME=/home/dev/.local/cpr-rust-toolchain/cargo
export PATH=/home/dev/.local/cpr-rust-toolchain/cargo/bin:/usr/local/bin:/usr/bin:/bin
export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER=/home/dev/.local/cpr-rust-toolchain/rustup/toolchains/stable-x86_64-unknown-linux-gnu/lib/rustlib/x86_64-unknown-linux-gnu/bin/rust-lld
cargo test --bin p201pro-fft-bench
cargo build --locked --release --target aarch64-unknown-linux-musl --bin p201pro-fft-bench
```

Run the resulting binary directly; it does not connect to or modify the SDR.
