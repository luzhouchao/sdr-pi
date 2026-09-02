# P201 Pro Rust/libiio reference benchmark

> Historical Pi-side benchmark. Production acquisition now runs through P201
> `sdrd`, with aggregation and persistence on AGX. Keep this tool for repeatable
> direct-IIOD measurements only; do not run it while another collector owns the
> RX path.

This is a minimal test client for the PUZHI PZSDR P201PRO connected through
IIOD at `ip:192.168.1.10`. It deliberately has three analysis modes:

- `probe`: read-only context, device, channel, and sample-format validation.
- `capture`: configure the existing safe profile and collect a short IQ stream.
- `capture --analysis aggregate`: reduce the stream to averaged spectrum
  snapshots and merged candidate bands.

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
./p201pro-test capture --seconds 3 --analysis aggregate --report-hz 10 \
  --fft-size 2048 --overlap-percent 50 --coarse-bins 96 --threshold-db 12
./p201pro-test sweep --start-freq 2448000000 --stop-freq 2450000000 \
  --step-freq 1000000 --sample-rate 2100000 --rf-bandwidth 2000000 \
  --buffer-samples 8192 --frames-per-point 4 --fft-size 2048
```

`sweep` is the benchmark's bounded Pi CPU sweep mode. It validates the complete
plan before the first LO write, limits continuous steps to 80% of RF bandwidth,
and retains its own historical 64 MiB command ceiling; this is not a project-wide
capture limit. It
reuses one context/buffer/FFT allocation across every point, emits one compact
JSON report and restores LO, sample rate, RF bandwidth and scan-channel enables.
It writes no raw IQ. An explicit center list can be supplied with
`--centers 2400000000,2450000000`.

`--analysis full` scans every IQ sample and reports signal statistics.
`--analysis none` performs a pure refill benchmark and derives the sample count
from the returned byte count, which isolates the libiio/TCP data path.

`--analysis aggregate` runs a streaming Hann-windowed RustFFT pipeline. It
averages linear power over enough overlapping frames to meet `--report-hz`,
estimates the median noise floor, detects bins above `--threshold-db`, bridges
up to `--merge-gap-bins`, and emits compact records prefixed by
`spectrum_json=`. Each record contains:

- sequence and input-sample position;
- tuning, sample rate, FFT and averaging metadata;
- median noise floor and total band power;
- `--coarse-bins` display/agent PSD values rather than the full FFT;
- merged candidate start/stop/peak frequencies and power;
- a `contains_dc` warning for candidates crossing the direct-conversion DC bin.

The averaging is performed in linear power, not by averaging dB values. FFT
power is normalized against the 12-bit ADC full-scale code and Hann window
energy. Values are therefore internally comparable, but they are not calibrated
dBm until an RF gain/path calibration is added.

This software path validated the original result contract, but it is no longer
the production data path. Current operation transports bounded IQ through
`sdrd` and performs aggregation on AGX.

For future modulation or emitter-specific recognition, treat candidates as
triggers for bounded IQ capture. Coarse PSD is useful for discovery, but it does
not preserve carrier offset, IQ imbalance, amplifier non-linearity, transients,
or other features needed for RF fingerprinting.

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
