# P201 → AGX bounded software-acquisition overload validation (2026-09-05)

## Scope and result

This receive-only validation closes the Chapter 4 bounded AGX software-
acquisition overload gate. It exercised the deployed P201 Linux/IIO SDRD/1
transport and the current AGX `SdrdSoftwareSweepAdapter`; it did not transmit,
retain raw IQ, use FPGA/MMIO/UIO, modify `BOOT.bin`, replace the P201 daemon or
change the fixed physical receive input.

The gate passed:

- an oversized per-point request was rejected by `SweepPlan` validation before
  any backend or radio connection;
- 128 consecutive maximum-size inline windows delivered exactly 32 MiB to AGX
  with continuous sequence numbers and zero drops, overflow, clipping, timeout,
  health, identity or correlation failures;
- a maximum window with a 1-ms deadline failed explicitly and restored the
  radio;
- terminating the AGX client during another maximum-window run caused the P201
  connection-close path to restore the radio and release the session;
- a fresh post-failure capture succeeded, and every success/failure path left
  one daemon/listener, the original radio state and no IQ or capture directory.

This is bounded request/response acquisition evidence, not proof of continuous
30.72-MS/s streaming. The separate sustained 5/10-MS/s acceptance gate remains
retired by the operator's 2026-09-03 decision.

## Source boundary and pre-hardware rejection

`ValidatedSweepPlan` now derives and retains:

```text
samples_per_point = frame_samples * aggregate_frames
iq_bytes_per_point = samples_per_point * 4
maximum_iq_bytes = iq_bytes_per_point * point_count
```

All arithmetic is checked. A point above the SDRD/1 inline limit of 262,144
bytes returns `agx_capture_size` from `validate_plan`; the Adapter reuses the
validated counts instead of discovering the excess after `START_SESSION`.

The boundary fixture used 4,096 × 16 = 65,536 complex samples and exactly
262,144 bytes per point. The overload fixture used 4,096 × 17 = 69,632 samples
and 278,528 bytes. Running that fixture with the deliberately unreachable
endpoint `127.0.0.1:9` still returned:

```text
controller_error=agx_capture_size: one AGX software-aggregate point exceeds the 256 KiB transport frame
exit_code=1
```

The regression backend panics if called and therefore proves that this error is
raised before backend work. The Controller library suite passed 69 tests,
including
`derives_finite_iq_bounds_and_rejects_point_overload_before_backend`.

## Target, initial state and finite plan

The P201 endpoint was `192.168.1.10:43110`. The credential file was a regular
mode-0600 file and was used only through `sshpass -f`; its contents were not
read or logged. Preflight found exactly one `sdrd` PID (`17136`), one listener,
the three expected persistent release files and this deployed daemon:

```text
77d98a005305a4b7531fc3f133e9b4af521e60b065b29fcc304b4c7db80c45ae  sdrd
```

The fixed input and idle state were:

```text
front panel / logical RX: RX1 / RX0
RF port select:            A_BALANCED
LO:                        2,400,000,000 Hz
sample rate:               30,720,000 Hz
RF bandwidth:              18,000,000 Hz
gain mode:                 slow_attack
RX buffer enable:          0
scan mask:                 0000
```

The successful overload-control plan was:

```text
generation:          20260905032
centers:             915,000,000–1,042,000,000 Hz, 1-MHz step, 128 points
sample rate:         30,720,000 Hz
RF bandwidth:        30,720,000 Hz
gain:                fixed manual 20 dB
settle:              0 ms
samples per point:   4,096 × 16 = 65,536 complex-int16
bytes per point:     262,144
maximum samples:     8,388,608 complex-int16
maximum IQ bytes:    33,554,432 (32 MiB)
point deadline:      2,000 ms
estimated duration:  256,000 ms
external watchdog:   290 seconds
direct stop:         independent cancel for generation 20260905032
```

Before the capture, AGX had 808,833,507,328 bytes available and P201 `/tmp`
had 514,632 KiB available. Development artifacts were confined to:

```text
AGX:  /var/tmp/sdrharness-dev/ch4-agx-overload-20260905/
P201: /tmp/sdr-agent-dev/ch4-agx-overload-20260905/
IQ:   /tmp/sdr-agent-dev/agx-sweep-20260905032-<point>/ (one transient point at a time)
```

The tested AArch64 Controller binary SHA-256 was:

```text
2f00cbb194d4b9fb9b205c9ac4ee23e042f25d9a58e5d34e50eb46be376ea791
```

## Maximum-window control result

The Controller returned backend `agx_iq_software_aggregate` and all 128 points:

| Measurement | Result |
| --- | ---: |
| Wall time | 6,910 ms |
| Exact complex samples | 8,388,608 |
| Exact raw IQ bytes processed | 33,554,432 |
| Mean request/aggregate time | 53.984 ms/window |
| Effective raw-payload rate | 4.631 MiB/s (38.847 Mb/s) |
| First / last sequence | 11 / 138 |
| Sequence gaps | 0 |
| Dropped samples | 0 |
| Overflow points | 0 |
| Clipped samples | 0 |
| Timeout failures | 0 |
| Unhealthy/status-flag points | 0 |
| RX identity/correlation failures | 0 |
| SDR IIO elapsed min/median/max | 4,011 / 4,371 / 5,848 µs |
| Persisted dataset | none |

The effective payload rate is materially higher than the 2026-09-02 historical
1.862-Mb/s profile, so that older number must not be treated as a permanent
transport constant. Conversely, this short 32-MiB request/response run does not
establish a continuous streaming rate or expand Planner limits.

## Bounded resource evidence

One-second samples covered the complete 6.91-second control run:

- AGX Controller: sampled peak 23.1% CPU, 4,720-KiB RSS and 6,436-KiB VSZ;
- P201 `sdrd`: 307 CPU ticks over six sampled seconds at `CLK_TCK=100`
  (about 51.2% of one core), peak 2,512-KiB RSS/HWM and two threads;
- P201 `/tmp`: 514,628 KiB available at every stress sample; the 4-KiB change
  from preflight was the monitor directory, not retained IQ;
- AGX board: system RAM peaked at 24,146/62,841 MiB, CPU/TJ at 49.093 °C and
  GR3D at 0%. No recognition or Planner GPU inference was part of this gate.

After all paths, `sdrd` returned to one thread and 2,152-KiB RSS. Its HWM
remained 2,512 KiB, which is 572 KiB above the 1,940-KiB preflight HWM.

## Failure-close matrix

### IIO deadline overload

Generation `20260905033` requested one maximum 65,536-sample/262,144-byte
window with a 1-ms deadline. It failed as intended:

```text
controller_error=remote_error: capture_failed_restored
sequence=139
dropped_samples=0
overflow=false
timeout.limit_ms=1
timeout.elapsed_us=2116
timeout.timed_out=true
health.healthy=false
health.flags=4
health.source=iio_adapter
```

The P201 immediately read back the original LO/rate/bandwidth/gain mode/RF
port, `buffer=0`, `scan mask=0000`, one PID/listener and no generation-matching
capture directory. A 4,096-sample recovery control then succeeded at sequence
140 with zero quality/status failures.

### AGX transport disconnect

Generation `20260905035` was a finite 64-point maximum-window plan: 4,194,304
complex samples, 16,777,216 maximum bytes and a 128-second estimate. An external
0.3-second watchdog terminated the AGX Controller with exit 124 while the SDRD
session was active. The next successful capture at sequence 146 proves that the
Adapter counter advanced through 145 during the interrupted plan; because the
client returned no point report, those partial windows are not claimed as
delivered results. After observing the closed connection, the SDRD session-close
path stopped capture and restored the saved state.

One second later the normal observe path reported healthy RX1 capability. The
radio state, buffer and scan mask matched the idle snapshot, no generation
directory remained, and a new 4,096-sample generation `20260905036` succeeded
at sequence 146. This proves that a client/transport loss cannot leave the SDR
owned or poison the next generation.

## Host regression

The final source and regenerated Web lock closure passed:

```text
Controller library:       69 passed
Controller terminal:      11 passed
Web Console:              15 passed
Controller all-target Clippy -D warnings: passed
Web all-target Clippy -D warnings:        passed
locked dependency reruns:                 passed
checkout verifier / diff whitespace:      passed
```

## Final restoration and cleanup

The final target check found exactly one PID and one listener with the same
daemon hash. LO, sample rate, bandwidth, gain mode, `A_BALANCED`, buffer and
scan mask all matched the initial state. No `agx-sweep-2026090503*` directory
and no IQ-like file remained below the P201 development root. The AGX reports
contained summaries only, never base64 IQ or model tensors.

After recording the bounded results and hashes, the AGX and P201 feature
directories, Cargo outputs, plans and monitor logs were removed and their
absence verified. No user-visible result, model asset, credential, persistent
P201 release or service was deleted.
