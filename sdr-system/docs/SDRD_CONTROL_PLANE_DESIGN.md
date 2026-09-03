# P201 SDR Linux control-plane design

Last reviewed: 2026-09-03

## Decision

P201 runs a small C11 control process responsible only for bounded receive-side
radio ownership and transport. AGX owns planning, policy, software aggregation,
result storage and model inference.

```text
upstream model -> AGX Planner -> Rust policy/controller
                                      |
                                      v
                               SDRD/1 over TCP
                                      |
                                      v
                         P201 sdrd -> Linux/IIO -> AD9361 RX
```

The model never connects to P201 directly. `sdrd` does not contain model,
storage, FFT, candidate-merging, FPGA/MMIO or transmit code.

## Internal interfaces

| Module | Responsibility |
|---|---|
| Configuration | Strict `key=value` parser and bounded hardware limits |
| Linux/IIO Adapter | Snapshot, apply receive profile, bounded capture, cancel, stop and restore |
| SDRD/1 server | Correlation, ownership, session generation and framed responses |

The external protocol is documented in
[`../sdrd/README.md`](../sdrd/README.md). Protocol-v1 responses retain constant
false/zero FPGA fields solely so already deployed clients can continue parsing
them. No FPGA implementation or configuration path remains.

## Controlled execution

`sdrd_radio_ops_t` is the only interface allowed to touch the receive radio.
The protocol layer validates request ordering, session generation, frequency,
sample rate, bandwidth, gain, channel count, sample count, byte budget and
feature ID before calling the Adapter.

The session snapshots LO, sample rate, RF bandwidth, gain mode, numeric gain
and channel mask before the first mutation. Restoration is armed immediately
and runs on explicit stop, quit, disconnect, apply failure, capture failure or
contract violation. Restore failure faults the session and prevents new
ownership.

One normal connection owns execution. A second connection may issue only a
generation-correlated `CANCEL_SESSION`. The IIO Adapter latches cancellation
and interrupts an active `iio_buffer_refill()`.

## Data ownership

- P201 transient files: `/tmp/sdr-agent-dev/<feature-id>/`.
- AGX development data: `/var/tmp/sdrharness-dev/<feature-id>/`.
- User-visible results: the application-managed AGX result store.
- Raw IQ and intermediate outputs never enter Git.

Every capture needs an exact plan-derived finite byte bound. P201 removes
transient data after confirmed inline transfer. AGX performs free-space checks
before optional SigMF persistence and exposes manual deletion for saved results.

## Performance and safety rules

- Keep one persistent process, socket, IIO context and session buffer.
- Keep allocation, logging, serialization and analysis out of the refill loop.
- Use RX0 by default and never expose arbitrary IIO writes.
- Preserve direct stop and verified state restoration on every path.
- Do not add FPGA, MMIO, `/dev/mem`, `BOOT.bin` or transmit functionality.

## Production status and adjacent gates

AGX sole ownership, IIO-timeout restoration, complete execution metadata,
30-minute reconnect/fault recovery and strict unattended P201 reboot recovery
are live-validated. The persistent startup path uses the vendor `mtd2` JFFS2
key-restore hook and the AGX PID/listener-gated recovery timer without modifying
the boot image.

Sustained 5/10-MS/s throughput, bounded overload behavior and the separate
24-hour autonomous soak remain adjacent checklist gates; they do not change
the P201 control-plane ownership boundary.
