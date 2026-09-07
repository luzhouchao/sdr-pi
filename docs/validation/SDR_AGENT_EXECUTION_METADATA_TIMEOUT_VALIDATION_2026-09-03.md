# SDR execution metadata and IIO-timeout validation — 2026-09-03

## Scope and ownership gate

This delivery adds measured execution metadata to the P201 Linux/IIO → AGX
software path and live-validates the timeout restoration path. All captures
were receive-only and finite. No FPGA, MMIO, UIO, transmit, boot-image or
arbitrary IIO-write path was used.

The repository started at clean commit `8946491` after the separate AGX RX
ownership cutover. Before every capture, all three legacy Spectrum units were
still `inactive` and `disabled`, no legacy/direct-IIOD capture process existed,
and the P201 reported one `sdrd` PID and one private-link 43110 listener. The
AGX direct route and P201 MAC remained `192.168.1.20 -> 192.168.1.10` and
`00:0a:35:00:01:22`.

The P201 had regenerated its SSH host keys after reboot. The direct-link MAC,
platform and documented replacement ECDSA fingerprint
`SHA256:eXntSviT1uu5JxsNFSfujE1VnBQpjdZPukdUgMxR57k` were rechecked before the
user-authorized global `known_hosts` update. Strict checking then passed; the
previous file remains at
`/home/jetson/.ssh/known_hosts.pre-p201-20260903`, mode `0600`.

## Implemented result contract

The C Adapter now produces, and SDRD/1 returns, the following for bounded IQ,
inline IQ and power-summary execution:

- correlated `request_id` and `session_generation`;
- Adapter sequence, measured short-refill drop count and overflow state;
- active timeout limit, monotonic elapsed microseconds and timed-out state;
- Adapter health boolean, bit flags and `iio_adapter` source.

Timeout, overflow, cancellation, I/O, shape and radio-state flags come from the
Adapter error/result path. They are not configured as healthy constants. The
Rust action and software-sweep Adapters validate these fields, reject stale,
dropped, overflowed, timed-out or unhealthy success responses, retain remote
failure metadata through `SdrError` and `SweepError`, include it in Runner
JSONL failure audit records, and expose successful metadata in every
`SweepPoint`. The AGX no longer invents zero status or zero elapsed time.

`CAPTURE_IQ` and `CAPTURE_IQ_INLINE` accept an optional bounded per-request
timeout. Existing clients may omit it and retain the configured IIO timeout;
the production sweep sends its Rust-validated `point_timeout_ms`.

Real timeout testing also found and fixed a pre-existing manual-gain restore
bug. IIO reads `hardwaregain` as text such as `20.000000 dB`, but its write
interface rejects that unit suffix. The production Adapter now parses the
snapshot and stores a bounded canonical numeric value, allowing an original
manual gain to be written back after failure.

## Build and deployment gates

The AGX `/usr/bin/arm-linux-gnueabihf-gcc` exists but its default sysroot emits
GLIBC 2.33/2.34 requirements, so it was not used for deployment. The official
Arm GNU 8.2-2018.08 hard-float archive was downloaded inside the feature root
and matched its published SHA-256:

```text
5b3f20e1327edc3073e545a5bd3d15f33e7f94181ff4e37a76e95924c1b439b9
```

The final P201 artifact was built in an amd64 container from only `main.c`,
`sdrd.c` and `sdrd_iio.c`. It is stripped ELF32 ARM EABI5 hard-float,
dynamically linked, contains no FPGA/MMIO/UIO symbol, and requires only
`GLIBC_2.4`, `GLIBC_2.7` and `GLIBC_2.17`. Staging hash verification plus
`--check-config`, `--probe` and read-only `--probe-radio` passed before the
single running daemon was stopped and replaced.

Host/focused validation passed:

```text
sdrd native tests:  pass
Controller library: 46 passed
Controller CLI:      5 passed
Controller clippy:   -D warnings passed
Controller release:  passed
```

The preceding complete runtime build on the same source series also passed 15
Web tests, 48 Planner tests, the recognizer backend/model-loader tests, Web
strict Clippy and release builds. The final follow-up changed only the C
Adapter, its explicit live checker and Rust error-metadata preservation; their
focused suites were rerun after those edits.

Final retained releases and hashes are:

```text
P201 /sd/sdr-agent/releases/20260903-execution-metadata-v3/sdrd
0b1b6ac63323d4dd81401e3656855428786588aafcca001411a9f21b7f51ada0

P201 /sd/sdr-agent/current/sdrd
0b1b6ac63323d4dd81401e3656855428786588aafcca001411a9f21b7f51ada0

P201 /sd/sdr-agent/current/sdrd.conf
ac96a9e01173e63b48acfb8dd6834125b3397a0e2823da380a855df6b894893c

P201 /sd/sdr-agent/current/S60sdrd
c95a9c92a0a24f723f5b05844355bc9757ce9397bbd788e040ab70ecc5e3a4e7

AGX /home/jetson/.local/lib/sdrharness/releases/20260903-execution-metadata-v2-final/sdr-agent
02f13e83be32e0f6ae659a9474266b42308c8c1561aaee09f47fefc8d89fa34c

AGX /home/jetson/.local/lib/sdrharness/releases/20260903-execution-metadata-v2-final/sdr-agent-controller
51094232ff74bd3158a124b08ffa7e5d7bfc076b8b294ba9e1889245041fdba2

AGX /home/jetson/.local/lib/sdrharness/releases/20260903-execution-metadata-v2-final/sdr-agent-web-console
c1ab5ad9d05351ebc8430d974688c8de92b1d2fee7bad568337125d2ea151402
```

P201 rollback releases retain the pre-feature daemon, the first metadata
daemon and the pre-manual-gain-fix daemon under
`20260903-pre-execution-metadata-v1`, `20260903-execution-metadata-v1` and
`20260903-execution-metadata-v2`. The AGX pre-feature and first metadata
deployments remain in their corresponding release directories.

## Live bounded plans and results

Before the production timeout capture the recorded plan was one point at 915
MHz, 5 MS/s, 4 MHz RF bandwidth, fixed manual 20 dB, 65,535 complex-int16
samples, 262,140 maximum bytes, 1 ms point timeout, 6 ms plan estimate and a
5-second client fault bound. AGX had `839569915904` bytes free. The feature root
was `/var/tmp/sdrharness-dev/sdrd-metadata-startup-20260903/`; the exact P201
capture directory was `/tmp/sdr-agent-dev/agx-sweep-2026090307-0/`. Direct stop
was the deployed Controller cancel mode for generation `2026090307`.

The final deployed v3 response failed as intended and preserved every measured
field through the AGX CLI:

```text
error=capture_failed_restored
request_id=5
session_generation=2026090307
sequence=1
dropped_samples=0
overflow=false
timeout.limit_ms=1
timeout.elapsed_us=3360
timeout.timed_out=true
health.healthy=false
health.flags=4
health.source=iio_adapter
```

The success control used one 915-MHz point, 5 MS/s, 4 MHz bandwidth, fixed 20
dB, 4,096 samples, 16,384 maximum bytes and a 1,000-ms point timeout, while the
P201 configuration remained 2,000 ms. Its exact P201 directory was
`/tmp/sdr-agent-dev/agx-sweep-2026090308-0/`. The returned point proved the
request deadline was honored rather than hard-coded:

```text
request_id=5
session_generation=2026090308
sequence=2
dropped_samples=0
overflow=false
captured_samples=4096
timeout.limit_ms=1000
timeout.elapsed_us=2596
timeout.timed_out=false
health.healthy=true
health.flags=0
health.source=iio_adapter
```

AGX performed the IQ aggregation and returned backend
`agx_iq_software_aggregate`; no raw IQ was persisted on AGX.

## Manual-gain timeout restoration

Because the normal idle radio uses `slow_attack`, its changing hardware-gain
readback is not a manual setting. A transient `live_timeout_restore` checker
was therefore cross-built from the exact production Adapter and SDRD/1 state
machine. It was not installed as a service. Its ABI/hash gate passed, the
normal daemon was stopped, and zero PID/zero listener was proved before the
checker touched IIO.

The checker preserved the original state, established an idle manual 20-dB
baseline at the original 2.4 GHz / 30.72 MS/s / 18 MHz / scan mask 0, applied
915 MHz / 5 MS/s / 4 MHz / manual 30 dB, and requested the same 65,535-sample,
262,140-byte, 1-ms bounded capture. The result was:

```text
capture_failed_restored
sequence=1 dropped_samples=0 overflow=false
timeout.limit_ms=1 timeout.elapsed_us=3327 timeout.timed_out=true
health.flags=4 health.source=iio_adapter

manual_timeout_restore=pass
center_hz=2400000000 sample_rate_hz=30720000 rf_bandwidth_hz=18000000
gain_mode=manual hardware_gain=20.000000 scan_channel_mask=0

original_restore=pass
center_hz=2400000000 sample_rate_hz=30720000 rf_bandwidth_hz=18000000
gain_mode=slow_attack scan_channel_mask=0
```

libiio 0.21 still prints its historical buffer-disable warning during destroy,
but the Adapter returned successful restore, the sysfs buffer was zero, and all
state readbacks passed. The checker exited zero. A 15-second watchdog and
feature PID file supplied the direct stop path; the actual run finished in
about three seconds. The prestart duplicate gate then proved no daemon/listener
before exactly one production `sdrd` was restarted.

## Final state and cleanup

Final P201 readback was 2.4 GHz, 30.72 MS/s, 18 MHz, `slow_attack`, buffer
enable 0 and all four scan elements 0. SDRD/1 reported no active or faulted
session, healthy IIO, one daemon and one 43110 listener. The production timeout,
success and manual-test capture directories were absent.

The exact P201 staging directory
`/tmp/sdr-agent-dev/sdrd-metadata-20260903/`, AGX feature directory
`/var/tmp/sdrharness-dev/sdrd-metadata-startup-20260903/`, downloaded
toolchain/archive, cross/native build outputs, runtime `.artifacts`, Cargo
targets, recognizer build output and the temporary host-key scan were removed
after their retained hashes and evidence were recorded. Planner `node_modules`
was retained because the deployed `sdrharness-planner.service` currently loads
its worker from the repository and needs that runtime dependency tree on its
next restart. No Web result, database, raw IQ, model, credential or retained
release was deleted.

Finally, `sdrharness-web`, `sdrharness-planner` and `spark-x25` were active and
enabled; `/api/state` returned HTTP 200. The legacy Spectrum Web, predictor and
resume units remained inactive and disabled.
