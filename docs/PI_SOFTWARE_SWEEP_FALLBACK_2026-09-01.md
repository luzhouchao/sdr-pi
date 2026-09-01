# Pi software sweep fallback validation

Date: 2026-09-01

## Outcome

`p201pro-test sweep` now provides a bounded Pi CPU fallback while the original
FPGA image reports no aggregation capability. One process owns and reuses the
remote IIOD context, RX buffer, RustFFT plan, Hann window, scratch arrays and
sample blocks for the complete sweep. It changes only the RX profile, produces
compact JSON and restores the initial radio profile on success or ordinary
error. It never writes raw IQ to a file.

The interface accepts an explicit comma-separated center list or a continuous
start/stop/step range. Validation enforces board frequency/rate/bandwidth
limits, a maximum point count, 80% bandwidth coverage for continuous ranges,
an estimated 60-second duration cap and a 64 MiB maximum network-IQ budget.
Each point reuses the FFT implementation through
`SpectrumAggregator.reset_for_center()` instead of rebuilding a plan.

## Build and tests

The Docker-backed native suite passed 11 Rust tests and Clippy with warnings
denied. The ARM64 GNU artifact is dynamically linked against the Pi's existing
`libiio.so.0`:

```text
interpreter=/lib/ld-linux-aarch64.so.1
needed=libiio.so.0,libgcc_s.so.1,libm.so.6,libc.so.6
sha256=8c42bdf9028d9c797b856efa733135770c211b414e161ef7fef88479ef7a9f0a
```

## Live bounded sweep

The development plan was:

```text
range=2448000000..2450000000 Hz
step=1000000 Hz
points=3
sample_rate=2100000 samples/s
rf_bandwidth=2000000 Hz
buffer_samples=8192
FFT=2048
overlap=50%
frames_per_point=4
settle=5 ms
maximum_network_bytes=98304
estimated_duration=27 ms
```

The run completed in 449 ms, returned all three points and three merged compact
candidates, and reported `restored=true`. The first AD9361 readback was
2,447,999,998 Hz for a requested 2,448,000,000 Hz; the existing 10 Hz
quantization tolerance accepted it.

Before and after the sweep, the SDR read back 2452 MHz, 2.1 MS/s, 2 MHz RF
bandwidth, `slow_attack` and scan mask zero. Controlled `sdrd` remained healthy
and continued to advertise bounded retune/capture while FPGA capability stayed
false. No transmission, FPGA, `BOOT.bin` or persistent radio setting changed.

## Deployment and cleanup

The Pi release is:

```text
/opt/sdr-agent/current -> /opt/sdr-agent/releases/20260901-software-sweep-v1
```

`20260901-runner-v1` remains the immediate rollback. The exact temporary Pi
directory `/var/tmp/sdr-agent-dev/software-sweep-v1/`, its 6.3 KiB JSON output
and workstation parsing copy were removed and verified absent. No SDR or Pi raw
IQ file was created.

The current fallback is an operator-invoked utility. Agent `survey_band`
execution and a shared Pi hardware lease remain separate work; until those are
implemented, do not run the utility concurrently with an Agent hardware action.
