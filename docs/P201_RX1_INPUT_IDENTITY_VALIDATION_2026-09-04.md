# P201 RX1 fixed-input identity validation — 2026-09-04

## Scope and safety

This delivery closes the Chapter 3 physical-input identity gap without adding
any Planner-controlled port selector. The production path remains receive-only:

```text
P201 front-panel RX1
  -> ad9361-phy input voltage0, rf_port_select=A_BALANCED
  -> cf-ad9361-lpc scan voltage0 (I) + voltage1 (Q)
  -> bounded SDRD/1 inline complex-int16 transport
  -> AGX software aggregation
```

The Adapter only reads `rf_port_select`; it contains no write of that attribute.
No TX, FPGA, BOOT image, register, or persistent radio-setting operation was
performed. The operator-independent capture authorization in `AGENTS.md` was
used for one finite receive-only point.

## Contract and failure behavior

SDRD/1 now returns this versioned object in capabilities, health, session start,
profile, capture/summary, and stop responses:

```json
{
  "identity_version": 1,
  "verified": true,
  "front_panel_port": "RX1",
  "logical_channel": "RX0",
  "phy_channel": "voltage0",
  "scan_i_channel": "voltage0",
  "scan_q_channel": "voltage1",
  "rf_port_select": "A_BALANCED",
  "source": "iio_channel_attr"
}
```

The controlled IIO Adapter probes the identity when it opens, before session
ownership, around profile application and every capture, and after
stop/restoration. Missing, unreadable, mismatched, or changed identity disables
`radio_control`/`raw_iq_capture`; an owned session faults closed if its identity
cannot be proved unchanged on exit. Rust clients require the exact identity in
controlled capabilities and correlate it across start, profile, capture and
stop. Old SDRD responses that omit it therefore remain parseable during a
cutover but cannot expose controlled capability.

Host tests covered successful propagation, missing identity, changed identity,
disconnect, apply failure, capture timeout, inline cleanup and restoration:

- `make -C sdr-system/sdrd clean test`: pass;
- Controller `cargo test --all-targets`: 58 library + 11 terminal tests pass;
- Controller `cargo clippy --all-targets -- -D warnings`: pass;
- Web Console `cargo test --all-targets`: 15 tests pass;
- Web Console `cargo clippy --all-targets -- -D warnings`: pass.

## Build and deployment evidence

The project P201 skill build script produced:

```text
77d98a005305a4b7531fc3f133e9b4af521e60b065b29fcc304b4c7db80c45ae  sdrd
ELF 32-bit ARM, EABI5, dynamically linked, hard-float
required GLIBC: 2.4, 2.7, 2.17
retired FPGA/MMIO symbol gate: pass
```

P201 releases:

```text
active:   /sd/sdr-agent/releases/20260904-rx1-identity-v1/
rollback: /sd/sdr-agent/releases/20260904-rx1-identity-rollback-458365bc/
previous sdrd SHA-256: 458365bcd2231b622b8175ca618726ed9d7e16efb0e5c5c36f4ea22e30ae44dd
active sdrd SHA-256:   77d98a005305a4b7531fc3f133e9b4af521e60b065b29fcc304b4c7db80c45ae
```

The old daemon was stopped while its executable was unchanged. Zero PIDs and
zero listeners were proved before one staged `--probe-radio`. That probe
returned `RX1 / RX0 / voltage0+1 / A_BALANCED`. The new file was installed by a
same-directory temporary name and `mv`; startup then produced exactly one PID
(`17136` at validation time), one `192.168.1.10:43110` listener and the expected
active hash. `--check-config`, `--probe`, `--probe-radio`, and live SDRD/1
`HELLO`/`CAPABILITIES`/`HEALTH`/`QUIT` all passed.

AGX rollback/current artifacts:

```text
/home/jetson/.local/lib/sdrharness/releases/20260904-rx1-identity-v1/
d722990c69ebdedfa4dec957f5c7c0ade9989524dfb3f00727c34ccb81f2f702  sdr-agent
35f406579d00d7cbc170e27a00ef861365a122456526b1797300fe597c7c81c3  sdr-agent-web-console
```

The AGX client was installed before the SDRD cutover so a missing identity could
only make receive capability unavailable during the transition. After cutover,
`sdrharness-planner.service`, `sdrharness-web.service`, and `spark-x25.service`
were all active and enabled.

## Bounded live RX validation

Validated plan:

```text
center:                 433,920,000 Hz (one point)
sample rate:            2,100,000 samples/s
RF bandwidth:           1,500,000 Hz
fixed RX gain:          20 dB
samples:                1,024 complex-int16
exact maximum bytes:    4,096
capture timeout:        500 ms
estimated plan time:    505 ms
AGX available bytes:    808,954,900,480
AGX feature root:       /var/tmp/sdrharness-dev/chapter3-rx1-identity-20260904/
P201 transient feature: /tmp/sdr-agent-dev/agx-sweep-20260904033-0/
direct stop:            STOP_SESSION; independent CANCEL_SESSION remains available
```

The first Rust attempt used a 2,000 ms socket budget and timed out during the
multi-step AD9361 control transaction. The session disconnect path restored the
radio and removed its transient directory. The accepted run retained the same
500 ms capture deadline and used the already established 5,000 ms SDRD control
socket budget; its result was:

```text
session_generation: 20260904033
backend:             agx_iq_software_aggregate v1
elapsed plan time:   3,402 ms
capture elapsed:     4,407 us
samples/bytes:       1,024 / 4,096
dropped/overflow:    0 / false
clipped samples:     0
health flags:        0
RX identity:         verified RX1 / RX0 / voltage0+1 / A_BALANCED
raw-IQ dataset:      none
```

A preceding output-filter attempt also closed its client connection early when
the AGX was found not to have `jq`; it was treated as a failure-path event, not
as a result. Immediately afterward the daemon was healthy, the feature directory
was absent and all saved state was restored.

Before and after the accepted run:

```text
RX LO:              2,400,000,000 Hz
sample rate:        30,720,000 samples/s
RF bandwidth:       18,000,000 Hz
gain mode:          slow_attack
scan channel mask:  0 (voltage0..3 all disabled while idle)
rf_port_select:     A_BALANCED
```

The numeric `hardwaregain` readback was not compared under `slow_attack`, where
AGC is expected to change it. The controlled gain mode itself was restored.
The P201 inline feature directory was absent after receipt. A final strict Rust
`observe` returned online/healthy, flags zero, retune/capture true, and the exact
verified RX1 identity.

## Cleanup

The feature's P201 staging directory and AGX `/var/tmp` build/capture tree were
removed after the hashes and bounded metadata above were recorded. Persistent
active and rollback release directories were intentionally retained.
