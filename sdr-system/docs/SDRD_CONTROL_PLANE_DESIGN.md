# P201 Pro SDR Linux control-plane design

Date: 2026-08-31

## Decision

Use the SDR's ARMv7 Linux as the hardware-control module between the Raspberry
Pi Harness and the AD9361/FPGA data path:

```text
Pi Rust Harness
  -> one SDRD/1 execution connection + independent cancellation connection
SDR Linux C sdrd
  -> local IIO adapter for AD9361 and bounded IQ capture
  -> local UIO/mmap adapter for validated FPGA pages (future)
FPGA
  -> fixed-shape streaming primitives
```

The Pi never writes FPGA registers over SSH and Qwen never talks to the SDR.
Qwen returns a high-level scan intent to the Pi; the Pi validates it and calls
the `SdrEngine` interface; the remote adapter translates that interface into
SDRD messages.

## Current original-BOOT constraint

The SDR `/sd/BOOT.bin` and the protected original backup have the same SHA-256:

```text
02c7f8f84f003879fda27021bb243517ccf8e9b85e7404a37db2e4dda1d8b951
```

The 2026-08-31 read-only baseline also found no `0x43c00000` resource in
`/proc/iomem`; reads of that historical page caused bus errors. The current
image therefore must not advertise SUM8/FFT/PSD capabilities. `sdrd` starts
with `fpga_backend=disabled` and does not touch MMIO.

## Module interfaces

`sdrd` owns four internal interfaces:

| Module | Version 1 | Later controlled mode |
|---|---|---|
| Configuration | strict `key=value`, shadow default | signed/versioned profile allowlist |
| Linux/IIO Adapter | IIO visibility, local context, state restore, bounded IQ | temperature, drops, long-run ownership |
| FPGA adapter | disabled, optional read-only identity | UIO mapping and atomic profile generation |
| Wire server | HELLO/CAPABILITIES/HEALTH plus tested controlled schema | binary observation stream |

The external interface remains small: discover capabilities, apply one validated
profile, receive observations, request bounded IQ, obtain health, stop or cancel
a session.
Register offsets, IIO attribute ordering, state restoration, stale detection,
and backend selection stay inside the SDR Linux implementation.

## Controlled execution seam

The implemented `sdrd_radio_ops_t` Adapter is the only code allowed to touch a
radio backend. The protocol/session layer validates request ordering, generation,
frequency, rate, bandwidth, channel count, byte budget, feature ID, and returned
relative path before or after calling it. The Adapter owns seven operations:
begin session, snapshot, atomic profile apply, bounded IQ capture, in-flight
cancel, direct stop, and restore.

`sdrd_session_t` is connection-owned. It arms restoration immediately after a
successful snapshot and restores on explicit stop, quit, disconnect, profile or
capture failure, and Adapter contract violation. Restore failure enters a
fail-closed fault state. Unit tests use a fake Adapter; controlled mode cannot
advertise `radio_control=true` until a complete production Adapter is injected.

The wire server assigns exactly one normal connection as the execution owner.
While it is active, other normal requests receive `server_busy`; only an
independent `CANCEL_SESSION` connection may cross that boundary. Cancellation
requires the exact active generation. Pi retries only the narrow startup race
where its worker has not completed `START_SESSION`; `sdrd` itself never accepts
a stale or not-yet-active generation. The IIO Adapter latches cancellation once
the session begins and calls `iio_buffer_cancel()` when a refill is active.

Development capture files are namespaced below
`/tmp/sdr-agent-dev/<feature-id>/`, capped at 64 MiB by default, excluded from
Git, and removed after the feature validation. Source interfaces, tests,
configuration examples, design decisions, compact metrics, and validation
evidence are retained and pushed with the feature.

## Performance rules

- C implementation on SDR ARMv7; no Python runtime path.
- Persistent process, socket, IIO context, buffers, and future UIO mapping.
- Preallocated fixed-size request/response buffers.
- No SSH polling, `devmem` subprocess loop, per-frame process launch, or log spam.
- No allocation in the future capture/observation hot loop.
- Summary/control traffic uses the persistent control connection.
- Raw IQ remains a separate bounded binary data plane and is candidate-triggered.

## Ownership and migration

Only one process may own the RX buffer. Migration is staged:

1. Current IIOD remains the only acquisition owner; `sdrd` is health-only.
2. Pi implements a `RemoteSdrAdapter` against SDRD/1 and tests mock/replay.
3. The development-controlled `sdrd` now opens one local IIO context and creates
   one session buffer only after ownership, with live-tested snapshot/restore.
4. After disconnect, timeout, in-flight cancel, reconnect, and repeated-session
   tests, `sdrd` may become the enabled sole session owner and provide bounded
   raw-IQ references plus compact observations.
5. FPGA capability is enabled only after the loaded image, address page, UIO or
   `/proc/iomem` resource, ABI, build ID, and rollback image are verified.

## FPGA enable gate

`fpga_backend` may change from `disabled` only when all of these are recorded:

- loaded `BOOT.bin` hash and expected FPGA build ID match;
- the physical address is present in `/proc/iomem`, or a dedicated UIO device
  exposes the page;
- read-only identity succeeds without a bus error;
- IIO still exposes `ad9361-phy` and `cf-ad9361-lpc` afterward;
- the configured ABI and capability bitmap match the code;
- rollback is available.

UIO is preferred. `/dev/mem` additionally requires `allow_devmem=true` and the
`require_iomem_region` gate. Version 1 never writes either backend.

## Language split

| Location | Language | Reason |
|---|---|---|
| FPGA kernels | Verilog/Xilinx IP | deterministic streaming hardware |
| SDR Linux `sdrd` | C11 | smallest ARMv7/Buildroot dependency surface |
| Pi Harness | Rust | safe async orchestration and protocol/state modeling |
| Pi local recognizer | C++ ONNX Runtime/ncnn adapter | native optimized inference |
| Training | Python/PyTorch off-device | training only, not runtime |

## Version 1 acceptance

- Native C tests pass with warnings treated as errors.
- Static ARMv7 binary is produced and inspected.
- Original-BOOT configuration validates with FPGA disabled.
- On the SDR, manual `--probe` reports both required IIO devices and no FPGA
  capability without accessing `0x43c00000`.
- No service, boot entry, IIO attribute, FPGA register, or bitstream is changed.
