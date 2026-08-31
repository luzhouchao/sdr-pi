# `sdrd` shadow control plane

`sdrd` is the C control-plane process intended to run on the P201 Pro's ARMv7
Buildroot Linux. Version 1 is deliberately read-only:

- it reports `ad9361-phy` and `cf-ad9361-lpc` visibility;
- it reports FPGA identity only when an explicitly enabled UIO or guarded
  `/dev/mem` backend is available;
- it serves a small versioned protocol over a persistent TCP connection;
- it rejects retune, profile, session, and IQ-capture commands;
- it never writes FPGA registers or IIO attributes;
- it is not installed as a startup service by this repository.

The current SDR uses the original `BOOT.bin` with SHA-256
`02c7f8f84f003879fda27021bb243517ccf8e9b85e7404a37db2e4dda1d8b951`.
That image does not expose the later SUM8 page at `0x43c00000`, so
[`config/sdrd-shadow.conf`](config/sdrd-shadow.conf) keeps
`fpga_backend=disabled`.

## Protocol v1

One request is one bounded ASCII line:

```text
SDRD/1 HELLO <request_id>
SDRD/1 CAPABILITIES <request_id>
SDRD/1 HEALTH <request_id>
SDRD/1 QUIT <request_id>
```

Each response is one JSON line carrying the same request ID. Mutating commands
such as `APPLY_PROFILE`, `RETUNE`, `CAPTURE_IQ`, and `START_SESSION` return
`read_only_shadow`.

The protocol is intentionally small enough for the future Rust Pi Harness and
for a C implementation on the SDR. Raw IQ is not transported by this control
protocol; a later bounded data plane will be added only after session ownership
and FPGA identity are proven.

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
