# P201 Pro Rust test results

Test date: 2026-08-31

## Environment

- Build host: local WSL/Docker, Rust 1.98.0
- Target: Raspberry Pi 4B, aarch64, DietPi/Debian
- Rust wrapper: `industrial-io` 0.6.1
- Raspberry Pi client library: libiio 0.26
- P201 Pro IIOD: libiio 0.21 at `192.168.1.10:30431`
- RX format: little-endian signed 12-bit samples in 16-bit I/Q containers

The client was cross-compiled locally. Rust/Cargo were not installed on the
Raspberry Pi. The Pi only received the `libiio0` runtime package and the test
binary.

## Build verification

- `cargo fmt -- --check`: passed
- `cargo test --all-targets`: 10 passed, 0 failed
- `cargo clippy --all-targets -- -D warnings`: passed
- Artifact: ARM64 GNU/Linux PIE, dynamically linked, stripped
- Artifact SHA-256:
  `71cfcc98c892171b07093521b2ce514058bd8fafc398b354cf2c3262649ad381`

## Device probe

The Rust client identified:

- `PUZHI PZSDR P201PRO`
- `ad9361-phy`
- `cf-ad9361-dds-core-lpc`
- `cf-ad9361-lpc`
- RX I/Q channels `voltage0` and `voltage1`

Client libiio 0.26 successfully interoperated with the SDR's IIOD 0.21.

## Capture results

| Requested rate | Analysis | Measured rate | Payload throughput | Max refill | User CPU | System CPU |
|---:|---|---:|---:|---:|---:|---:|
| 2.1 MS/s | full | 2.096 MS/s | 7.995 MiB/s | 34.821 ms | not recorded | not recorded |
| 2.1 MS/s | aggregate | 2.090 MS/s | 7.973 MiB/s | 35.350 ms | not recorded | not recorded |
| 5 MS/s | full | 4.991 MS/s | 19.040 MiB/s | 17.035 ms | 0.592 s | 0.134 s |
| 10 MS/s | full | 9.601 MS/s | 36.624 MiB/s | 10.148 ms | 1.137 s | 0.268 s |
| 10 MS/s | none/refill only | 9.988 MS/s | 38.102 MiB/s | 10.201 ms | 0.034 s | 0.299 s |

Each performance row used a three-second capture. The 10 MS/s readback from
both AD9361 PHY channels was exactly 10,000,000 S/s. The difference between the
two 10 MS/s rows shows that scalar per-sample signal analysis in the acquisition
thread, not libiio/TCP, caused the approximately 4% shortfall in the full mode.

The aggregate row used FFT 2048, 50% overlap, five reports per second, 24
coarse PSD bins and a 12 dB-above-median-noise candidate threshold. It consumed
6,291,456 complex samples in 3.010 seconds and emitted 14 completed snapshots.
Each completed snapshot averaged 411 FFT frames. The first snapshot reported a
median noise floor of -53.21 dBFS/bin and no candidate above the configured
threshold. The aggregate test finished successfully, and the temporary binary
and output log were removed from the Pi afterward.

This historical test validates Pi-side streaming aggregation and downstream
result reduction. The current production architecture instead transports
bounded RX data through `sdrd` and aggregates it on AGX.

The Pi stayed near 36-37 C and reported `throttled=0x0` after the higher-rate
tests. No timeout, short read, or connection error occurred.

## Final device state

After testing, a successful one-second capture restored and read back:

- sample rate: 2,100,000 S/s
- RF bandwidth: 2,000,000 Hz
- center frequency: 2,452,000,000 Hz

No service or startup entry was created.
