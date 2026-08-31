# `sdrd` control plane

`sdrd` is the C control-plane process intended to run on the P201 Pro's ARMv7
Buildroot Linux. The deployed configuration remains deliberately read-only:

- it reports `ad9361-phy` and `cf-ad9361-lpc` visibility;
- it reports FPGA identity only when an explicitly enabled UIO or guarded
  `/dev/mem` backend is available;
- it serves a small versioned protocol over a persistent TCP connection;
- it rejects profile, session, and IQ-capture commands in `mode=shadow`;
- it never writes FPGA registers or IIO attributes;
- it is not installed as a startup service by this repository.

The current SDR uses the original `BOOT.bin` with SHA-256
`02c7f8f84f003879fda27021bb243517ccf8e9b85e7404a37db2e4dda1d8b951`.
That image does not expose the later SUM8 page at `0x43c00000`, so
[`config/sdrd-shadow.conf`](config/sdrd-shadow.conf) keeps
`fpga_backend=disabled`.

The library now also contains the controlled-mode command parser, ownership
state machine, bounded-capture contract, and a local libiio 0.21 Adapter. The
Adapter keeps one process-local IIO context, snapshots all controlled state,
uses one session buffer, writes bounded complex-int16 files, and restores state
on stop or failure. It is development-validated but is not installed as an SDR
service; the deployed SDR remains in shadow mode.
[`config/sdrd-controlled-interface.conf`](config/sdrd-controlled-interface.conf)
documents the accepted limits but is explicitly not a deployment configuration.

## Protocol v1

One request is one bounded ASCII line:

```text
SDRD/1 HELLO <request_id>
SDRD/1 CAPABILITIES <request_id>
SDRD/1 HEALTH <request_id>
SDRD/1 QUIT <request_id>
```

Controlled mode adds only these allowlisted messages:

```text
SDRD/1 START_SESSION <request_id> <generation>
SDRD/1 APPLY_PROFILE <request_id> <generation> <center_hz> <sample_rate_hz> <rf_bandwidth_hz> <gain_mode> <enabled_channels>
SDRD/1 CAPTURE_IQ <request_id> <generation> <sample_count> <max_bytes> <feature_id>
SDRD/1 CAPTURE_SUMMARY <request_id> <generation> <frame_samples> <aggregate_frames> <timeout_ms>
SDRD/1 EXECUTION_STATUS <request_id> <generation>
SDRD/1 STOP_SESSION <request_id> <generation>
SDRD/1 CANCEL_SESSION <request_id> <generation>
```

Each response is one JSON line carrying the same strictly increasing, nonzero
request ID. Generations reject stale session actions. `RETUNE` is deliberately
not allowlisted; `APPLY_PROFILE` is the atomic tuning operation.

One normal connection exclusively owns execution. `CANCEL_SESSION` is the only
command accepted on a second connection while that owner is active. It must
name the active generation; an early or stale generation fails closed. The
acknowledgement means that cancellation was requested. The owner connection's
`capture_failed_restored` response proves that capture stopped, the partial file
was removed, and restoration ran.

`CAPTURE_SUMMARY` is capability-gated by the validated SUM8/AGG8 identity and a
writable UIO or guarded `/dev/mem` Adapter. It arms one bounded aggregate,
polls with timeout and cancellation checks, and returns fixed-size power,
quality, sequence and timing metadata. The current original FPGA image reports
`fpga_aggregate=false`, so this command cannot run until a compatible image and
register resource are installed and verified.

`APPLY_PROFILE` accepts only the configured subset of the verified project
limits: 70 MHz..6 GHz center frequency, 2.083333..30.72 MS/s sample rate,
0.2..56 MHz RF bandwidth, RF bandwidth no greater than sample rate, allowlisted
gain modes, and RX0 only in this slice. `CAPTURE_IQ` requires a safe feature ID,
uses four bytes per complex int16 sample, and cannot exceed the configured hard
cap (64 MiB by default). Adapter results use paths relative to
`/tmp/sdr-agent-dev`; clients cannot submit an arbitrary output path.

The session snapshots radio state before ownership, resets its cancellation
latch, and arms restoration before any mutation. Stop, quit, disconnect, apply
failure, capture failure, or an Adapter contract violation calls stop and
restore. A failed restore faults the session and prevents new ownership.
Cancellation interrupts an active libiio buffer refill, or remains latched
until capture begins, then follows the same capture-failure restoration path.
The Adapter snapshots and restores LO, sample rate, bandwidth, gain mode, and
enabled channels.

Raw IQ is not transported inside the JSON control response. The Adapter returns
only bounded metadata and a safe path relative to the configured development
data root.

## Native build and tests

From WSL/Linux at the repository root:

```bash
make -C sdr-system/sdrd test
make -C sdr-system/sdrd all
sdr-system/sdrd/build/sdrd \
  --config sdr-system/sdrd/config/sdrd-shadow.conf --check-config
```

## ARMv7 builds

The static Docker build remains valid for shadow-only probes. Do not use that
artifact for controlled mode: a static glibc 2.36 executable cannot safely
`dlopen` the SDR's glibc 2.28 libiio and fails before opening an IIO context.

```bash
docker build -t p201-sdrd-cross -f sdr-system/sdrd/Dockerfile.cross \
  sdr-system/sdrd
docker run --rm -v "$PWD:/work" -w /work/sdr-system/sdrd p201-sdrd-cross \
  make clean all CC=arm-linux-gnueabihf-gcc \
  BUILD_DIR=build-armhf LDFLAGS=-static
file sdr-system/sdrd/build-armhf/sdrd
sha256sum sdr-system/sdrd/build-armhf/sdrd
```

Controlled mode uses the Xilinx 2019.1 hard-float toolchain, whose dynamic
artifact requires only GLIBC 2.17 while the SDR provides GLIBC 2.28:

```powershell
powershell -ExecutionPolicy Bypass -File `
  sdr-system/sdrd/scripts/build-armhf-xilinx.ps1
```

Always inspect the emitted GLIBC requirements and artifact hash before staging.

Do not start controlled `--serve` until `--check-config`, `--probe`, and the
read-only `--probe-radio` pass. Run it manually from a unique directory below
`/tmp/sdr-agent-dev`; it must not replace IIOD or be added to boot.

For a host-only socket smoke test, use
`config/sdrd-loopback-test.conf`; it binds only to `127.0.0.1` and must not be
deployed to the SDR.
