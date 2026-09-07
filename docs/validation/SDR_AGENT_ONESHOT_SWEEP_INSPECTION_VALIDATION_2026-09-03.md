# Stateless one-shot survey and inspection validation — 2026-09-03

## Implemented path

The existing generic Rust `Runner` now accepts the existing `SweepBackend`
alongside `SdrActionExecutor`. It no longer returns `planned_only` for
`survey_band` or `inspect_candidate`. Both actions follow this path:

```text
live SDRD observation
  -> real upstream Planner proposal
  -> Rust request/response/action validation
  -> automatic or operator authorization
  -> existing SdrdSoftwareSweepAdapter and AGX SweepEngine
  -> post-stop SDRD health observation
  -> fresh compact Planning observation
  -> bounded mode-0600 JSONL audit
```

The Runner report contains the measured `SweepReport`; the audit result keeps
the backend, point/candidate counts, elapsed time, post-execution SDR snapshot
and compact next observation. Raw IQ and arbitrary paths are never supplied to
the Planner. Unsupported non-hardware actions remain explicitly non-executing.

## Automated verification

Two Runner tests prove that a replay `survey_band` produces aggregate
candidates/latest-sweep context and that `inspect_candidate` refreshes only the
selected candidate. Both assert `executed`, a real sweep result, a final
`execution_observation` audit event and absence of `planned_only`.

```text
controller library: 48 passed
terminal binary:     11 passed
controller main:      0 tests
cargo clippy --locked --all-targets -- -D warnings: passed
```

## Live receive-only plans

All data was held only in bounded memory and the development directory
`/var/tmp/sdrharness-dev/oneshot-runner-20260903/`. P201 used
`CAPTURE_IQ_INLINE`; no P201 or AGX raw-IQ file was requested.

The first smoke survey used 88–92 MHz, 2 MHz step, 3 MS/s sample rate,
2.5 MHz RF bandwidth, fixed 20 dB gain, 20 ms settle and 4,096 complex-int16
samples at each of three points. Its finite maximum was 49,152 bytes and its
validated duration bound was 810 ms. AGX had 841,860,485,120 bytes available.

The candidate-producing survey used 70–90 MHz, 1 MHz step and the same radio,
gain, settle and sample shape at 21 points. Its finite maximum was 344,064
bytes and duration bound 5,670 ms. It produced the current candidate
`request-2402-1` at 90 MHz, 4.5 MHz bandwidth, −34.875 dBFS and 23.350 dB SNR.

The inspection accepted only that candidate, used 90 MHz, 3 MS/s, 2.5 MHz
bandwidth, fixed 20 dB, 100 ms settle and 4,096 complex-int16 samples. Its
finite maximum was 16,384 bytes and duration bound 350 ms. The refreshed
candidate measured −34.457 dBFS and 23.769 dB SNR.

All three real proposals came from the deployed local Spark provider/model
`spark-local` / `spark-x2.5-4b` and exactly matched the Rust-validated request.
Measured execution results were:

| request | action | points | bytes | elapsed | dropped | overflow | clipped |
|---|---|---:|---:|---:|---:|---|---:|
| 2401 | `survey_band` | 3 | 49,152 | 2,735 ms | 0 | false | 0 |
| 2402 | `survey_band` | 21 | 344,064 | 4,621 ms | 0 | false | 0 |
| 2403 | `inspect_candidate` | 1 | 16,384 | 2,568 ms | 0 | false | 0 |

Each Adapter point reported `health.source=iio_adapter`, healthy true, flags 0,
a nonzero measured sequence/request ID and measured timeout elapsed time.

## Audit and restoration evidence

The audit was a regular owner-only `0600` file. Requests 2401, 2402 and 2403
each contained exactly this correlated phase sequence under its own generation:

```text
input_observation
planner_proposal
validated_plan
authorized
execution_observation
```

Every final audit event recorded backend `agx_iq_software_aggregate`, backend
version 1, the measured point/candidate counts, post-execution healthy SDR
snapshot and next observation.

The P201 read-only sysfs state before and after all actions matched:

```text
LO                     2400000000 Hz
sample rate            30720000 Hz
RF bandwidth           18000000 Hz
gain mode              slow_attack
RX buffer enable       0
scan elements 0..3     0 0 0 0
```

The instantaneous `hardwaregain` value is allowed to change in `slow_attack`
mode and is not a saved manual-gain setting. After validation there was one
`sdrd` PID (1366), one `192.168.1.10:43110` listener, no active buffer and no
matching SDR-local transient directory.

## Deployment and rollback

The live-validated native AGX artifact was atomically installed at:

```text
/home/jetson/.local/lib/sdrharness/bin/sdr-agent-controller
SHA-256 9b0d563fa862456ac0eba60e95a66f15b6f1f0d654da24bfd54a492fb7af39de
```

The recovery timer was stopped during replacement and restarted afterward. A
read-only production-path `--mode observe` returned online, healthy, IIO
visible, retune true and bounded-IQ true. Rollback is retained at:

```text
/home/jetson/.local/lib/sdrharness/releases/20260903-pre-oneshot-sweep-v1/sdr-agent-controller.previous
SHA-256 51094232ff74bd3158a124b08ffa7e5d7bfc076b8b294ba9e1889245041fdba2
```

## Delivery cleanup

After AGX receipt, audit inspection and documentation, the exact 55 MiB
feature directory and 332 MiB repository-local Cargo output were deleted and
verified absent:

```text
/var/tmp/sdrharness-dev/oneshot-runner-20260903/
raspberry-pi/sdr-agent/controller/target/
```

No Web result, model, credential, `node_modules`, deployed release or rollback
artifact was removed.
