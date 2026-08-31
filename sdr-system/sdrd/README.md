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
state machine, bounded-capture contract, and radio Adapter interface. These are
unit-tested with a fake Adapter but are not enabled on the SDR: the production
IIO Adapter does not exist yet, and capability reporting therefore fails closed.
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
SDRD/1 EXECUTION_STATUS <request_id> <generation>
SDRD/1 STOP_SESSION <request_id> <generation>
```

Each response is one JSON line carrying the same strictly increasing, nonzero
request ID. Generations reject stale session actions. `RETUNE` is deliberately
not allowlisted; `APPLY_PROFILE` is the atomic tuning operation.

`APPLY_PROFILE` accepts only the configured subset of the verified project
limits: 70 MHz..6 GHz center frequency, 2.083333..30.72 MS/s sample rate,
0.2..56 MHz RF bandwidth, RF bandwidth no greater than sample rate, allowlisted
gain modes, and RX0 only in this slice. `CAPTURE_IQ` requires a safe feature ID,
uses four bytes per complex int16 sample, and cannot exceed the configured hard
cap (64 MiB by default). Adapter results use paths relative to
`/tmp/sdr-agent-dev`; clients cannot submit an arbitrary output path.

The session snapshots radio state before ownership and arms restoration before
any mutation. Stop, quit, disconnect, apply failure, capture failure, or an
Adapter contract violation calls stop and restore. A failed restore faults the
session and prevents new ownership. The future real Adapter must snapshot and
restore LO, sample rate, bandwidth, gain mode, and enabled channels.

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

## Static ARMv7 cross-build

```bash
docker build -t p201-sdrd-cross -f sdr-system/sdrd/Dockerfile.cross \
  sdr-system/sdrd
docker run --rm -v "$PWD:/work" -w /work/sdr-system/sdrd p201-sdrd-cross \
  make clean all CC=arm-linux-gnueabihf-gcc \
  BUILD_DIR=build-armhf LDFLAGS=-static
file sdr-system/sdrd/build-armhf/sdrd
sha256sum sdr-system/sdrd/build-armhf/sdrd
```

Do not start `--serve` on the SDR until `--check-config` and `--probe` pass.
Version 1 should be run manually from a temporary directory; it must not replace
IIOD or be added to boot.

For a host-only socket smoke test, use
`config/sdrd-loopback-test.conf`; it binds only to `127.0.0.1` and must not be
deployed to the SDR.
