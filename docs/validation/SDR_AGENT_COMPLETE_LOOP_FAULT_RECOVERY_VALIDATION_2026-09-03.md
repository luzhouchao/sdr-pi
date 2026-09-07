# Complete-loop fault and recovery validation — 2026-09-03

## Scope and safety boundary

This validation completed the remaining planning-loop recovery item with the
deployed AGX Controller, the real local Spark-X2.5-4B Planner and the real P201
Linux/IIO receive path.  Every hardware action was receive-only and finite.
No FPGA, MMIO, UIO, boot-image, transmit or arbitrary-IIO operation was used.
The legacy Spectrum Web, predictor and resume units remained disabled, so the
AGX Harness remained the sole enabled receive control path.

The AGX development roots were:

```text
/var/tmp/sdrharness-dev/fault-loop-20260903/
/var/tmp/sdrharness-dev/fl-0903/       # short TMPDIR for Unix-socket tests
```

The P201 deployment staging root was
`/tmp/sdr-agent-dev/fault-loop-20260903/`.  Each inline-IQ point used the
server-validated transient identifier `agx-sweep-<generation>-<point>` and was
removed by `sdrd` after use.  The direct cancellation path was the independent
SDRD/1 `CANCEL_SESSION` command exposed by Controller `--mode cancel`.

## Complete-loop fault matrix

### Planner timeout before execution

Request/session generation 2500 used the live read-only SDR observation and
real local Spark Planner, with the Planner socket deadline reduced to 100 ms.
It returned no hardware action.  The mode-0600 JSONL audit contained exactly:

```text
input_observation
planning_failed: read planner response: Resource temporarily unavailable
```

This proved that Planner timeout fails before validation, authorization or SDR
execution.

### IIO point timeout and failure metadata

Request/session generation 2501 selected the current measured candidate
`request-2402-1` at 90 MHz with 3 MS/s, 2.5 MHz RF bandwidth, fixed 20 dB,
20-ms settle, 4,096 complex samples and an exact 16,384-byte maximum.  AGX free
space was checked before the action.  The point deadline was deliberately one
millisecond.  The real P201 Adapter returned:

```text
error=capture_failed_restored
request_id=5 session_generation=2501 sequence=26
dropped_samples=0 overflow=false
timeout.limit_ms=1 timeout.elapsed_us=3184 timeout.timed_out=true
health.healthy=false health.flags=4 health.source=iio_adapter
```

The Runner preserved this object under `execution_failed`; it did not replace
the measured metadata with configured healthy values.  The session, RX buffer
and scan elements were clear after restoration.

### Direct SDR cancellation during a partial action

Request/session generation 2502 was a 201-point receive-only survey from
70–90 MHz in 100-kHz steps at 10 MS/s / 10-MHz RF bandwidth, fixed 20 dB,
10-ms settle and 4,096 complex samples per point.  Its exact finite maximum was
3,293,184 bytes.  After the real Spark proposal passed Rust validation and the
Runner wrote `authorized`, an independent Controller connection issued the
direct cancel:

```json
{"session_generation":2502,"cancel_requested":true}
```

The active owner stopped after a partial sweep (capture response request 331,
Adapter sequence 190) and returned `capture_failed_restored` with cancellation
health flag 16, zero dropped samples, no overflow and `timed_out=false`.  The
Runner wrote `execution_failed` and emitted no successful aggregate or fresh
candidate observation.  The original radio state and zero buffer/scan mask
were restored.

### SDRD disconnect and reconnect

The AGX recovery timer was paused, the idle P201 `/etc/init.d/S60sdrd` service
was stopped normally, and zero `sdrd` PID plus zero 43110 listener was proved.
Request/session generation 2503 then failed its initial live observation with
`Connection refused`; its audit contained only `observation_failed`, so the
Planner and hardware were not called.

Starting `sdrharness-p201-sdrd-recovery.service` recovered exactly one daemon
and one private-link listener from `/sd/sdr-agent/current`, with the same
deployed hash and restored radio state.  The periodic timer was re-enabled.

### Model cancellation and old-generation invalidation

With the Web temporarily stopped, the deployed terminal was run directly with
`--session-state off`.  A prompt and `/stop` were supplied while the local
Spark response was active.  The terminal acknowledged both the upstream abort
and session stop, invalidated the old plan, and emitted no late old-generation
result during a five-second observation window.  `/status` then reported the
upstream idle, queue length zero, next request 3 and generation 3.  The normal
Web service was restored and returned HTTP 200.

Deterministic full-Runner tests additionally inject a stale Planner generation
and a stale SDR sweep-point generation.  Both are rejected before execution or
new observation and audited respectively as `validation_failed` and
`execution_failed`.  Terminal tests cover stale asynchronous model frames and
generation invalidation after stop/failure.

### SDRD transport timeout and daemon survival

Request/session generation 2504 used the same one-point candidate inspection
with a 100-ms client socket timeout.  The client correctly returned
`read_response: Resource temporarily unavailable`, but the deployed daemon
exited after attempting to send its late response.  Investigation identified
an unhandled `SIGPIPE` in `send_all()`.

The daemon was corrected to use `MSG_NOSIGNAL` when available and rebuilt only
through the project `p201-sdr-workflow` skill.  Request/session generation 2505
then repeated the real Spark and P201 path with this pre-recorded bound:

```text
center=90 MHz, sample rate=3 MS/s, RF bandwidth=2.5 MHz
points=1, samples/point=4096, maximum bytes=16384
estimated hardware duration <=100 ms, client socket timeout=100 ms
AGX available bytes=840206962688
AGX root=/var/tmp/sdrharness-dev/fault-loop-20260903/
P201 transient=/tmp/sdr-agent-dev/agx-sweep-2505-0
```

The Runner again wrote `execution_failed`, as required, while P201 PID 2079
remained unchanged before and after the late response.  There was still one
43110 listener.  `EXECUTION_STATUS` reported generation 0, inactive,
`profile_applied=false`, `restore_armed=false` and `faulted=false`; a fresh
Controller observation was online and healthy.  The transient capture path was
absent.  Running the recovery oneshot against this live daemon returned
`already_running` and preserved PID 2079, proving the duplicate-instance gate.

## Final radio state

Read-only P201 sysfs and SDRD/1 checks after the final timeout matched the
pre-action baseline:

```text
LO                         2400000000 Hz
sample rate                30720000 Hz
RF bandwidth               18000000 Hz
gain mode                  slow_attack
RX buffer enable           0
scan elements 0..3         0 0 0 0
sdrd PID / listeners       2079 / 1
SDRD session active/fault  false / false
```

`hardwaregain` is intentionally not compared in `slow_attack`; the separate
production-IIO timeout validation in
[`SDR_AGENT_EXECUTION_METADATA_TIMEOUT_VALIDATION_2026-09-03.md`](SDR_AGENT_EXECUTION_METADATA_TIMEOUT_VALIDATION_2026-09-03.md)
already proved exact manual 20-dB restoration after a real timeout.

## Build, deployment and rollback

The previously downloaded compatible toolchain had been removed with an older
feature directory.  To prevent repeated installation, the official Arm GNU
8.2-2018.08 toolchain and verified archive now live outside Git and feature
cleanup at:

```text
/home/jetson/.local/lib/sdrharness/toolchains/gcc-arm-8.2-2018.08-x86_64-arm-linux-gnueabihf/
/home/jetson/.local/lib/sdrharness/toolchains/downloads/gcc-arm-8.2-2018.08-x86_64-arm-linux-gnueabihf.tar.xz
archive SHA-256: 5b3f20e1327edc3073e545a5bd3d15f33e7f94181ff4e37a76e95924c1b439b9
```

The project skill script pins the amd64 Ubuntu 18.04 builder image
`sha256:152dc042452c496007f07ca9127571cb9c29697f42acbfad72324b2bb2e43c98`,
mounts source/toolchain read-only, disables network and capabilities, compiles
only the Linux/IIO daemon sources and enforces ELF/GLIBC/retired-symbol gates.
The resulting P201 artifact is ELF32 ARM EABI5 hard-float, dynamically linked,
requires only GLIBC 2.4/2.7/2.17, and has SHA-256:

```text
458365bcd2231b622b8175ca618726ed9d7e16efb0e5c5c36f4ea22e30ae44dd
```

It was installed as `/sd/sdr-agent/releases/20260903-sigpipe-nosignal-v1/`
and atomically promoted to `/sd/sdr-agent/current/sdrd`.  The previous daemon
is retained at `/sd/sdr-agent/releases/20260903-pre-sigpipe-v1/sdrd` with
SHA-256 `0b1b6ac63323d4dd81401e3656855428786588aafcca001411a9f21b7f51ada0`.
Rollback is the same PID/listener-gated stop, atomic replacement from that
release, and start/probe sequence.

The deployed AGX Controller is:

```text
/home/jetson/.local/lib/sdrharness/releases/20260903-complete-loop-fault-v1/sdr-agent-controller
/home/jetson/.local/lib/sdrharness/bin/sdr-agent-controller
SHA-256: 3cbad970165b9b86d8bc6441e74ddf0d8bf9740c15e54cfcd94e8786269d16c6
```

The independent Controller rollback is
`/home/jetson/.local/lib/sdrharness/releases/20260903-pre-complete-loop-fault-v1/sdr-agent-controller.previous`,
SHA-256 `9b0d563fa862456ac0eba60e95a66f15b6f1f0d654da24bfd54a492fb7af39de`.

## Automated verification

The final source and deployed artifacts passed:

- Controller library: 53/53 tests.
- Terminal: 11/11 tests.
- Planner Worker: 50/50 tests.
- Native C daemon: `sdrd_tests=pass`.
- Rust formatting and Clippy with warnings denied.
- Project skill syntax, `quick_validate.py`, real cross-build and artifact
  gates.

The first Rust run used the long feature path as `TMPDIR`; one unrelated Unix
recognizer test exceeded the kernel `SUN_LEN` path limit while 52 tests passed.
Repeating the unchanged suite with the documented short feature TMPDIR passed
all 53 tests.  This was an environment path-length failure, not a product-code
failure.
