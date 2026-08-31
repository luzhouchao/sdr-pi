# P201 Pro Rust/libiio test client

This is a minimal test client for the PUZHI PZSDR P201PRO connected through
IIOD at `ip:192.168.1.10`. It deliberately has two modes:

- `probe`: read-only context, device, channel, and sample-format validation.
- `capture`: configure the existing safe profile and collect a short IQ stream.

The default capture profile matches the staged Raspberry Pi configuration:

- center frequency: 2.452 GHz
- complex sample rate: 2.1 MS/s
- RF bandwidth: 2.0 MHz
- buffer: 65,536 complex samples
- duration: 3 seconds

Examples:

```bash
./p201pro-test probe
./p201pro-test capture
./p201pro-test capture --seconds 5 --sample-rate 5000000 --rf-bandwidth 4000000
./p201pro-test capture --seconds 3 --sample-rate 10000000 --rf-bandwidth 8000000 --analysis none
```

`--analysis full` scans every IQ sample and reports signal statistics.
`--analysis none` performs a pure refill benchmark and derives the sample count
from the returned byte count, which isolates the libiio/TCP data path.

The program expects the system libiio v0.x shared library. It does not install a
service, write files, or persist SDR settings.

## Reproducible ARM64 cross-build

The included `Dockerfile.cross` provides Rust 1.98, the ARM64 GNU linker, and
both native and ARM64 libiio development libraries. From WSL:

```bash
docker build -t p201pro-rust-cross -f Dockerfile.cross .
docker run --rm -v "$PWD:/work" -w /work p201pro-rust-cross \
  bash -c 'cargo test --locked --all-targets && \
    CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc \
    cargo build --locked --release --target aarch64-unknown-linux-gnu --bins'
```

## Raspberry Pi FFT benchmark

`p201pro-fft-bench` measures a future DSP hot path without connecting to the
SDR. Each measured frame includes interleaved `i16` IQ conversion, Hann window,
complex FFT, power sum, and peak reduction. It preallocates the planner,
scratch, input, output, and window data.

For a standalone static ARM64 artifact, use the verified WSL Rust toolchain:

```bash
export RUSTUP_HOME=/home/dev/.local/cpr-rust-toolchain/rustup
export CARGO_HOME=/home/dev/.local/cpr-rust-toolchain/cargo
export PATH=/home/dev/.local/cpr-rust-toolchain/cargo/bin:/usr/local/bin:/usr/bin:/bin
export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER=/home/dev/.local/cpr-rust-toolchain/rustup/toolchains/stable-x86_64-unknown-linux-gnu/lib/rustlib/x86_64-unknown-linux-gnu/bin/rust-lld

cargo test --locked --bin p201pro-fft-bench
cargo build --locked --release --target aarch64-unknown-linux-musl --bin p201pro-fft-bench
file target/aarch64-unknown-linux-musl/release/p201pro-fft-bench
sha256sum target/aarch64-unknown-linux-musl/release/p201pro-fft-bench
```

See [`FFT_BENCH_RESULTS.md`](FFT_BENCH_RESULTS.md) for the measured Pi 4B
capacity and the overlap/sample-rate CPU budget.
