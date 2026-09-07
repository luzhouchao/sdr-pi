# P201 SDRD 30-minute reconnect and fault-recovery validation — 2026-09-03

## Scope and acceptance

This record closes only the Chapter 3 real-SDR long-duration reconnect and
fault-recovery item.  The accepted run used the deployed AGX Controller and the
real P201 Linux/IIO receive path continuously for the full 1,800-second
automatic-cruise hard limit.  It does not claim the Chapter 4 sustained
5/10-MS/s or overload gates, and it is not the separate Chapter 8 24-hour soak.

All hardware operations were single-RX, receive-only and finite.  No second
collector or `sdrd`, transmit path, arbitrary IIO write, FPGA/MMIO/UIO path,
`BOOT.bin`, uramdisk or boot-chain modification was used.  Strict SSH host-key
checking remained enabled.  The legacy Spectrum Web, predictor and resume
units remained inactive and disabled.

The accepted monotonic interval was:

```text
start UTC                 2026-09-03T08:15:41.648Z
end UTC                   2026-09-03T08:45:41.665Z
start/end Asia/Shanghai   2026-09-03 16:15:41.648–16:45:41.665 CST
measured duration         1800.01714348 seconds
acceptance duration       1800 seconds
```

## Preflight and finite plans

The repository started clean at `af2a13d90932a25201bfb3be83deb0ef42717c5e`,
which matched local and remote `origin/main`.  AGX Web, Planner, Spark and the
P201 recovery timer were active and enabled.  The three legacy Spectrum user
units were inactive and disabled, and no legacy/direct-IIOD capture process
existed.  P201 had one expected `sdrd` PID and one 43110 listener; IIOD was the
only other IIO service and had one 30431 listener.  SDRD/1 was healthy and
idle, with no active, armed or faulted session.

The accepted test used AGX feature root
`/var/tmp/sdrharness-dev/sdrd-ch3-long-recovery-20260903/`.  Controller inline
captures used exact P201 transient identifiers below `/tmp/sdr-agent-dev/` and
were deleted by `sdrd` after each response or failure:

- normal: `agx-sweep-309031000-0` through `agx-sweep-309031099-0`;
- IIO timeout: `agx-sweep-309033001-0`;
- transport timeout: `agx-sweep-309033002-0`;
- direct-cancel plan: `agx-sweep-309034001-0` through
  `agx-sweep-309034001-200` as the finite worst case.

Every pre-capture JSONL record was flushed before the request.  It contained
the plan, estimated duration, point/sample count, exact byte bound, current AGX
free bytes, exact AGX/P201 paths, request generation and this direct stop path:

```text
sdr-agent-controller --mode cancel --sdrd 192.168.1.10:43110 \
  --session-generation <recorded-generation> --sdrd-timeout-ms 5000
```

AGX had more than 840,683,000,000 bytes free throughout the gate.  The complete
finite plan was:

| Plan | Profile | Points × samples | Timeout / estimate | Finite maximum |
|---|---|---:|---|---:|
| Normal, every 18 s | 915 MHz, 5 MS/s, 4 MHz, manual 20 dB | 100 × 4,096 | 1,000 ms / 1,005 ms each | 1,638,400 bytes |
| IIO timeout | same, zero settle | 1 × 65,535 | 1 ms / 1 ms | 262,140 bytes |
| Transport timeout | same, zero settle | 1 × 65,535 | 2,000 ms IIO, 10 ms client | 262,140 bytes |
| Direct cancellation | 70–90 MHz/100 kHz, 10 MS/s, 10 MHz, manual 20 dB | 201 × 4,096 | 250 ms/point, 52.26 s worst case | 3,293,184 bytes |

The validated worst case was 303 bounded capture requests and exactly
5,455,864 bytes.  Cancellation stopped on its first capture request, so the
accepted run actually issued 103 capture requests with 2,179,064 requested
bytes: 100 normal requests, two 262,140-byte timeout requests and one
16,384-byte cancelled request.  No raw IQ was retained on AGX.

Initial and required-restored state was 2.4 GHz LO, 30.72 MS/s, 18 MHz RF
bandwidth, `slow_attack`, RX buffer 0 and scan mask `0,0,0,0`.  Hardware gain is
not a stable comparison field under `slow_attack`; every action instead
required and received its fixed manual 20-dB profile readback before capture.

## Acquisition and metadata results

All 100 normal bounded acquisitions succeeded through backend
`agx_iq_software_aggregate`.  There were zero unexpected failures, zero
dropped samples, zero overflow, zero clipped samples, zero successful-result
timeouts and zero unhealthy successful results.  Each successful capture used
request ID 5 on its new connection and its recorded generation
`309031000..309031099`.  Adapter capture time was 2,547–3,857 microseconds
(mean 2,697.6 microseconds); complete Controller calls were
1.571–2.842 seconds (mean 1.608 seconds).

Sequence continuity was checked per actual daemon lifetime:

| PID | Observed sequence | Result |
|---:|---|---|
| 13215 | 44–63 | contiguous; the nonzero start belongs to discarded pre-run captures |
| 21902 | 1–10, 12–53 | sequence 11 is exactly the transport-timeout response deliberately not read by the client; all other values contiguous |
| 29896 | 1–30 | contiguous after the second recovery |

Sequence 32 on PID 21902 was the measured IIO timeout and sequence 43 was the
direct cancellation.  Both were present in order between successful points.
The only gap therefore had a recorded causal request; there was no unexplained
sample/result loss.

## Fault and recovery matrix

Nine scheduled fault events passed, and a normal acquisition succeeded after
each event:

1. Three clients disconnected after `START_SESSION` and successful manual
   profile application, without sending stop.  `sdrd` released ownership and
   restored the radio in 0.394, 0.398 and 0.421 seconds (mean 0.404 seconds).
2. Two unique healthy idle daemons were sent `SIGKILL` only after the
   active/faulted and PID/listener gates passed.  The test observed zero PID and
   zero listener before the enabled timer recovered PID 13215 → 21902 in
   1.143 seconds and PID 21902 → 29896 in 27.949 seconds.  Mean recovery latency
   was 14.546 seconds, inside the 30-second timer period.
3. The transport-timeout request used generation 309033002, request ID 5,
   65,535 samples and a 262,140-byte limit.  The client hit its real 10-ms read
   deadline and closed.  PID 21902 survived unchanged, restoration completed
   in 0.390 seconds, and the next visible Adapter sequence was 12 after the
   deliberately unread sequence 11.
4. The IIO-timeout request used generation 309033001, request ID 5 and sequence
   32.  The 1-ms limit expired after 2,707 microseconds and returned
   `capture_failed_restored`, `dropped_samples=0`, `overflow=false`,
   `timeout.timed_out=true`, `health.healthy=false`, flags 4 and source
   `iio_adapter`.  Restored idle health was confirmed in 0.181 seconds.
5. The 201-point plan was cancelled on an independent Controller connection.
   `CANCEL_SESSION` acknowledged generation 309034001 in 5.647 ms.  The owner
   ended in 0.778 seconds with request ID 5, sequence 43,
   `capture_failed_restored`, `timed_out=false`, zero drop/overflow and
   `SDRD_EXEC_HEALTH_CANCELLED` flags 8; restored idle state was reconfirmed in
   0.183 seconds.
6. A direct `/etc/init.d/S60sdrd start` against running PID 29896 returned exit
   1 and `FAIL (already running or listener occupied)`.  PID and the single
   listener were unchanged.

The earlier complete-loop evidence wrote cancellation “flag 16”.  The source
at both the tested commit and its predecessor defines
`SDRD_EXEC_HEALTH_CANCELLED = 1u << 3`, which is decimal 8.  This accepted live
response and the C enum establish that the older phrase was a documentation
transcription error, not a runtime regression.  The dated older evidence was
left immutable; this record supplies the correction.

## Resource and thermal measurements

The run retained 175 ten-second telemetry samples.  CPU percentages are
interval-derived; network is combined RX+TX throughput.

| Metric | Minimum | Mean | Maximum |
|---|---:|---:|---:|
| AGX total CPU | 0.219% | 0.544% | 1.532% |
| AGX Harness/Planner/Spark RSS | 97,360 KiB | 97,451 KiB | 98,364 KiB |
| AGX network | 7,036 bit/s | 32,355 bit/s | 113,434 bit/s |
| AGX maximum sensor temperature | 47.000 °C | 47.282 °C | 47.625 °C |
| P201 `sdrd` CPU | 0.000% | 0.843% | 2.821% |
| P201 `sdrd` RSS | 1,864 KiB | 1,892 KiB | 1,952 KiB |
| P201 load average (1 min) | 0.03 | 0.162 | 0.33 |
| P201 network | 7,204 bit/s | 32,904 bit/s | 128,446 bit/s |
| P201 AD9361 temperature | 48.246 °C | 57.018 °C | 58.772 °C |
| P201 XADC temperature | 55.122 °C | 56.334 °C | 57.460 °C |

No resource, thermal, health, overflow or storage boundary was approached.

## Final state, verification and boundaries

The final and independently repeated readback showed:

```text
SDRD active/profile/armed/faulted  false / false / false / false
SDRD health/session_faulted        true / false
sdrd PID / 43110 listeners         29896 / 1
deployed executable                /sd/sdr-agent/current/sdrd
LO / sample rate / RF bandwidth    2400000000 / 30720000 / 18000000 Hz
gain mode                          slow_attack
manual gain                        not applicable in restored AGC mode
RX buffer / scan mask              0 / 0,0,0,0
P201 feature leftovers             none
```

The deployed daemon and retained rollback were unchanged:

```text
/sd/sdr-agent/releases/20260903-sigpipe-nosignal-v1/sdrd
/sd/sdr-agent/current/sdrd
SHA-256 458365bcd2231b622b8175ca618726ed9d7e16efb0e5c5c36f4ea22e30ae44dd

/sd/sdr-agent/releases/20260903-pre-sigpipe-v1/sdrd
SHA-256 0b1b6ac63323d4dd81401e3656855428786588aafcca001411a9f21b7f51ada0
```

The native daemon tests returned `sdrd_tests=pass`.  The Controller library
passed 53/53 tests using feature-local build and short Unix-socket temporary
roots.  The accepted run's temporary artifacts, before required cleanup, were:

```text
harness script  2a59cb6816e68a47b4a63e67d3c49d4831fd1d1dd9a11e4097870d83f88feeeb
validated plan  6bf53ce71618fdbafa0901ba7028a86c37a7a8be3640103d235047fdb52f3f1d
JSONL (513 rows) 5e71abcd9657c33265ddf55e65b5489aefb40cfa3b752f68ef7821a1b6a1bdbf
summary          4a0178dbeb09d9dd9f9f49bcd54363a12292f463aeca707b9de0cc7bff427352
```

Two engineering pre-runs were deliberately excluded from acceptance: the
first stopped at 111.57 seconds when an AGX sysfs telemetry read needed a
transient-read guard; the second stopped at 1,081.18 seconds because the test
assertion used the older document's incorrect cancellation value 16.  Both had
healthy final restoration and no P201 leftovers, and each output set was
deleted before the accepted run began.  They explain why the accepted first
sequence was 44 and do not shorten its separately measured 1,800.017 seconds.

The transport-timeout client intentionally cannot report the late response's
body; daemon survival, restored health, no transient path and the single
explained sequence increment are its measurable boundary.  This low-duty
30-minute test does not prove sustained 5/10-MS/s throughput, overload
behavior, or 24-hour stability.  Those checklist items remain open in their
own chapters.

After retaining the hashes and this bounded summary, the exact AGX roots
`/var/tmp/sdrharness-dev/sdrd-ch3-long-recovery-20260903/` (154,220,317 bytes,
including feature-local Cargo/C test output) and
`/var/tmp/sdrharness-dev/c3lr0903/` (4,096 bytes, empty short TMPDIR) were
removed and their absence verified.  No Web result, database, model,
credential, persistent toolchain or rollback release was removed.
