# `sdrd` control plane

当前部署状态见[项目入口](../../docs/README.md)；[早期系统验证](../../docs/validation/README.md#组件目录中的历史实验)仅按需读取。

`sdrd` is the C control-plane process intended to run on the P201 Pro's ARMv7
Buildroot Linux. It supports shadow observation and controlled receive-only acquisition:

- it reports `ad9361-phy` and `cf-ad9361-lpc` visibility;
- controlled mode admits one selected RX1 or RX2 path, with the corresponding
  AD9361 PHY channel, I/Q scan pair and `A_BALANCED` readback;
- it retains constant false/zero FPGA response fields only for SDRD/1 client
  compatibility; no FPGA configuration or implementation remains;
- it serves a small versioned protocol over a persistent TCP connection;
- it rejects profile, session, and IQ-capture commands in `mode=shadow`;
- shadow mode never writes IIO attributes;
- the personal installed service and release state are recorded in the project checklist.

The library now also contains the controlled-mode command parser, ownership
state machine, bounded-capture contract, and a local libiio 0.21 Adapter. The
Adapter keeps one process-local IIO context, snapshots all controlled state,
uses one session buffer, writes bounded complex-int16 files, and restores state
on stop or failure. A personal receive-only configuration and BusyBox init
script are provided in [`config/sdrd-personal.conf`](config/sdrd-personal.conf)
and [`deploy/S60sdrd`](deploy/S60sdrd). The live deployment is retained on
`/sd`, but the SDR's RAM root means the `/etc/init.d` copy is current-boot only;
see the deployment evidence before changing the boot chain.
[`config/sdrd-controlled-interface.conf`](config/sdrd-controlled-interface.conf)
documents the accepted limits but is explicitly not a deployment configuration.

## Receive-port selection

Set `rx_input=RX1` (default) or `rx_input=RX2` in the daemon configuration before
starting it. Selection is fixed for that daemon instance; finish its session and
stop it before restarting with another configuration. Editing a config file does
not switch an active capture. Do not start a second daemon/collector to change ports.

| Config / panel port | Logical RX | PHY | Scan I / Q | RF input |
| --- | --- | --- | --- | --- |
| RX1 | RX0 | voltage0 | voltage0 / voltage1 | A_BALANCED |
| RX2 | RX1 | voltage1 | voltage2 / voltage3 | A_BALANCED |

Both cases transport one interleaved `ci16_le` stream (4 bytes/complex sample).
Profile writes and gain snapshot/restoration use the selected PHY; the other
channel's gain is untouched, and the original scan mask is restored. RF-port
attributes are read, not written. TRX1/TRX2 are rejected: the supplied vendor
firmware fixes their external switch controls rather than exposing a selector.
This service neither changes that firmware nor transmits.

The frozen production RF-v1 and existing AGX Controller admit only RX1. RX2
requires a diagnostic client that validates its actual identity; it must not be
relabeled as RX1 or passed through the old profile. `CAPTURE_POWER` and its
`software_summary` capability are unavailable for RX2 because those legacy
fields explicitly represent RX0. AGX raw-IQ processing remains the primary path.

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
SDRD/1 APPLY_PROFILE <request_id> <generation> <center_hz> <sample_rate_hz> <rf_bandwidth_hz> <gain_mode> [hardware_gain_db] <enabled_channels>
SDRD/1 CAPTURE_IQ <request_id> <generation> <sample_count> <max_bytes> <feature_id> [timeout_ms]
SDRD/1 CAPTURE_IQ_INLINE <request_id> <generation> <sample_count> <exact_bytes> <feature_id> [timeout_ms]
SDRD/1 CAPTURE_POWER <request_id> <generation> <frame_samples> <aggregate_frames> <timeout_ms>
SDRD/1 EXECUTION_STATUS <request_id> <generation>
SDRD/1 STOP_SESSION <request_id> <generation>
SDRD/1 CANCEL_SESSION <request_id> <generation>
```

Each response is one JSON line carrying the same strictly increasing, nonzero
request ID. Generations reject stale session actions. `RETUNE` is deliberately
not allowlisted; `APPLY_PROFILE` is the atomic tuning operation.

Every successful capture/summary result carries the correlated `request_id`
and `session_generation`, the Adapter capture `sequence`, reported
`dropped_samples`/`overflow`, and two nested metadata objects:

```json
{"timeout":{"limit_ms":2000,"elapsed_us":731,"timed_out":false},"health":{"healthy":true,"flags":0,"source":"iio_adapter"}}
```

The timeout limit is the active IIO or request deadline and `elapsed_us` is
measured with `CLOCK_MONOTONIC`.  Drop accounting is derived from the actual
refill shape; `overflow` is asserted only for an Adapter overflow/EPIPE result.
Health flags describe short refill, overflow, timeout, cancellation, I/O,
sample-shape, or post-capture radio-state failures.  Healthy is true only when
the Adapter returned no such flag.  Timeout/capture failures return the same
metadata together with the restoration-specific error code, and the Rust
client preserves that object in its error/audit path.

`CAPABILITIES`, `HEALTH`, session start, profile, capture/summary, and stop
responses carry a versioned `rx_input` object. The default RX1 identity is:

```json
{"identity_version":1,"verified":true,"front_panel_port":"RX1","logical_channel":"RX0","phy_channel":"voltage0","scan_i_channel":"voltage0","scan_q_channel":"voltage1","rf_port_select":"A_BALANCED","source":"iio_channel_attr"}
```

The Adapter reads `rf_port_select`; it never writes it and the protocol exposes
no port selector. Missing, unreadable, mismatched, or changed identity disables
controlled capabilities and fails closed. The identity is checked when the
Adapter opens, before ownership, around profile and capture work, and after
stop/restoration on every session exit path.

One normal connection exclusively owns execution. `CANCEL_SESSION` is the only
command accepted on a second connection while that owner is active. It must
name the active generation; an early or stale generation fails closed. The
acknowledgement means that cancellation was requested. The owner connection's
`capture_failed_restored` response proves that capture stopped, the partial file
was removed, and restoration ran.

`CAPTURE_IQ_INLINE` is the AGX software-aggregation transport. It captures at
most 256 KiB of complex-int16 IQ, returns it as base64 in the correlated JSON
response, and removes the SDR-local transient file before acknowledging
success. The client must aggregate or store the decoded IQ on AGX.

`CAPTURE_POWER` is retained only as a legacy compatibility command and is not
the production AGX software-sweep backend. It uses the controlled IIO RX buffer to return a bounded scalar
power/clip summary without writing raw IQ to disk. It accepts at most 1,048,576
complex samples, enforces the request timeout, remains cancelable, and stays
inside the same session ownership and restoration path as `CAPTURE_IQ`.

The retired `CAPTURE_SUMMARY` spelling returns `retired_command`; it has no
implementation or configuration path.

`APPLY_PROFILE` accepts only the configured subset of the verified project
limits: 70 MHz..6 GHz center frequency, 2.083333..30.72 MS/s sample rate,
0.2..56 MHz RF bandwidth, RF bandwidth no greater than sample rate, allowlisted
gain modes, and one configured RX1 or RX2 input.
`CAPTURE_IQ` requires a safe feature ID,
uses four bytes per complex int16 sample, and cannot exceed the configured hard
cap (64 MiB by default). Adapter results use paths relative to
`/tmp/sdr-agent-dev`; clients cannot submit an arbitrary output path.

Non-manual gain modes keep the original `APPLY_PROFILE` command shape. Manual
mode requires an integer `hardware_gain_db` from 0 through 60. The Adapter sets
manual mode before hardware gain and rejects the profile unless numeric IIO
readback matches within 0.05 dB; the successful response includes
`hardware_gain_db`.

The session snapshots radio state before ownership, resets its cancellation
latch, and arms restoration before any mutation. Stop, quit, disconnect, apply
failure, capture failure, or an Adapter contract violation calls stop and
restore. A failed restore faults the session and prevents new ownership.
Cancellation interrupts an active libiio buffer refill, or remains latched
until capture begins, then follows the same capture-failure restoration path.
The Adapter snapshots and restores LO, sample rate, bandwidth, gain mode, and
enabled channels, while proving that the non-writable-by-this-service RX input
identity stayed unchanged.

`CAPTURE_IQ` returns bounded metadata and a safe path relative to the configured
development-data root. `CAPTURE_IQ_INLINE` is the deliberately bounded exception
that transports base64 IQ to AGX and immediately removes the P201 temporary file.
The AGX sweep path propagates the P201 request/generation, sequence,
drop/overflow, timeout, health and RX-input identity metadata into each
`SweepPoint`; it does not synthesize zero status or elapsed time after transport.

## Native build and tests

From WSL/Linux at the repository root:

```bash
make -C sdr-system/sdrd test
make -C sdr-system/sdrd all
sdr-system/sdrd/build/sdrd \
  --config sdr-system/sdrd/config/sdrd-shadow.conf --check-config
```

`make live-timeout-test` only builds the explicit-maintenance real-IIO checker;
it never runs as part of a host test or daemon startup. On P201 it must run only
after the normal single-instance stop gate proves no `sdrd` PID and no 43110
listener. The checker uses the production Adapter and SDRD/1 session state
machine to establish a temporary manual-gain baseline, trigger a bounded IQ
timeout, verify exact manual-gain restoration, and finally restore the original
radio state. It is a transient validation artifact, not a second service.

## ARMv7 builds

The production build contains only the Linux/IIO capture path. The retired
FPGA/MMIO source and compatibility stub were removed; the Makefile and
cross-build script still reject the old `ENABLE_FPGA=1` request explicitly.
See
[`../../docs/FPGA_RETIREMENT_DECISION_2026-09-02.md`](../../docs/reference/FPGA_RETIREMENT_DECISION_2026-09-02.md).

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
read-only `--probe-radio` pass. Ensure port 43110 has no listener before starting
the retained `/sd` release. The hardened `deploy/S60sdrd` also rejects an
existing PID/listener and verifies exact single-instance readiness. The AGX
recovery service reinstalls this persistent entry after a P201 reboot. The
verified vendor `mtd2` JFFS2 store restores the pinned ECDSA host key before
Dropbear starts, so strict unattended recovery no longer needs a manual repin.
Any host-key mismatch still fails closed and must never be automatically
accepted.

For a host-only socket smoke test, use
`config/sdrd-loopback-test.conf`; it binds only to `127.0.0.1` and must not be
deployed to the SDR.
