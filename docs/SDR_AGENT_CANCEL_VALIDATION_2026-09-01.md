# SDR Agent in-flight cancellation validation

Date: 2026-09-01

## Outcome

The Pi terminal now keeps an approved SDR action in a Rust background worker,
so `/stop` can call a separate `SdrActionExecutor.cancel()` Adapter without
waiting for Qwen. The SDR C server keeps one exclusive execution connection and
accepts only `CANCEL_SESSION <request_id> <generation>` on an independent
connection while that generation is active.

The SDR-local IIO Adapter has a mutex-protected session cancellation latch. A
cancel arriving before capture enters refill prevents capture from starting; a
cancel during refill calls `iio_buffer_cancel()`. Both cases return through the
existing `capture_failed_restored` path and unlink the partial IQ file.

## Build and test evidence

Native validation passed with warnings denied:

- C `make clean test all`: `sdrd_tests=pass`;
- Rust `cargo fmt -- --check`;
- Rust 21-test all-target suite;
- Rust `cargo clippy --all-targets -- -D warnings`.

Cross-built artifacts:

```text
sdrd (ARMv7 hard-float, GLIBC 2.17/2.4/2.7)
  8bb0aca478f7e34aff5e3b83899a077888c2af1ba36afc947849886a2aa04474
sdr-agent-controller (static AArch64)
  ed8ccb34387dc316e897b6520f6a080d94873baf3d3469387fe2a3a43270b4cc
sdr-agent (static AArch64)
  e27520837441af819148336d75ca1544ec4237cc8a210a85830bb62010e2efeb
```

## Live receive-only validation

The bounded plan was:

```text
candidate: cancel-validation-2442m
center: 2442000000 Hz
sample rate: 2100000 Hz
RF bandwidth: 2000000 Hz
samples: 4194304 complex int16
maximum bytes: 16777216 (16 MiB)
nominal full-capture time: about 2 seconds
```

The Qwen Planner on the 4090 proposed that exact plan, and the Pi Rust
Controller independently validated it as approval-required. `/approve` and
`/stop` were then submitted consecutively to the staged terminal. The final
implementation reported:

```text
hardware action request=202 started
hardware action cancelled and restoration completed: capture_failed_restored
session stopped; old plan invalidated
```

An earlier trial exposed the real startup race where cancellation preceded
`START_SESSION`. That trial completed a full 16 MiB capture and was not counted
as success. The final terminal fixes the race with a 10 ms bounded retry for at
most 500 ms, only when SDRD returns `stale_or_missing_session` and the execution
worker is still running. SDRD continues to reject stale generations.

After the passing trial:

- the cancellation feature directory existed but contained no IQ file;
- a new health observation reported online and healthy with radio control and
  bounded IQ capture still available;
- readback returned the original 2452 MHz LO, 2.1 MS/s sample rate, 2 MHz RF
  bandwidth, `slow_attack` gain mode, and scan-channel mask zero;
- controlled `sdrd` was stopped and never installed or enabled as a service;
- FPGA registers, `BOOT.bin`, transmission state, and persistent SDR
  configuration were not changed.

## Pi deployment and rollback

The Pi release is:

```text
/opt/sdr-agent/current -> /opt/sdr-agent/releases/20260901-cancel-v1
```

`/opt/sdr-agent/releases/20260831-executor-v1` remains available for immediate
rollback. The Planner service stayed active, and the deployed no-hardware
terminal smoke test passed.

## Cleanup

The failed trial's 16 MiB IQ file was deleted before the passing retry. At
feature completion, the following exact development paths were removed and
verified absent:

```text
SDR: /tmp/sdr-agent-dev/cancel-v1/
SDR: /tmp/sdr-agent-dev/agent-77-202/
SDR: /tmp/sdr-agent-dev/agent-77-203/
Pi:  /var/tmp/sdr-agent-dev/cancel-v1/
```

Only source interfaces, tests, configuration examples, hashes, bounded
evidence, and this validation record are retained.
