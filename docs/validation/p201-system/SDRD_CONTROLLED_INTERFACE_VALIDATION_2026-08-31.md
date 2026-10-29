# SDRD/1 controlled interface validation

Date: 2026-08-31

## Scope

This feature defines and tests the allowlisted controlled-mode protocol and the
Adapter-backed ownership/restore state machine. It does not implement the real
IIO Adapter, retune the radio, capture real IQ, start `sdrd`, install a service,
write FPGA registers, or change `BOOT.bin`. The deployed shadow configuration
continues to advertise `radio_control=false`.

## Interface result

The allowlist is limited to `START_SESSION`, atomic `APPLY_PROFILE`, bounded
`CAPTURE_IQ`, `EXECUTION_STATUS`, and `STOP_SESSION`. Nonzero monotonically
increasing request IDs and session generations reject duplicate and stale work.
The parser enforces the documented radio limits, RX0-only ownership for this
slice, a safe feature identifier, four bytes per complex int16 sample, and a
64 MiB default hard cap. `RETUNE` is not a separate allowlisted primitive.

The radio Adapter owns snapshot, profile apply, capture, direct stop, and
restore. The connection state machine arms restoration before mutation and
tests explicit stop, disconnect, profile failure, capture failure, duplicate
request, bounds rejection, and restore-fault lockout. A controlled configuration
without a complete Adapter fails closed with `radio_control=false` and
`radio_backend_unavailable`.

## Build and test evidence

- Native C11 build with `-Wall -Wextra -Wpedantic -Werror`: PASS.
- Fake-Adapter protocol and state-machine tests: PASS.
- AddressSanitizer and UndefinedBehaviorSanitizer tests: PASS.
- Shadow and controlled-interface configuration validation: PASS.
- Controlled-interface host probe without an Adapter reported both
  `radio_control=false` and `raw_iq_capture=false`: PASS.
- Static stripped ARMv7 artifact SHA-256:
  `42a782522495ffd8dd289c5d7d0a62dd5f657faf9fde0559f74527512ab33f6e`.

## Real-target read-only check

The artifact and existing shadow configuration were staged through the Pi over
LAN and copied to the SDR `/tmp` directory. On the SDR it ran only
`--check-config` and `--probe`:

- target architecture: `armv7l`;
- target artifact hash matched the workstation artifact;
- `mode=shadow` and `fpga_backend=disabled`;
- `ad9361-phy` and `cf-ad9361-lpc` visible;
- `healthy=true`, `health_flags=0`;
- `radio_control=false`, `raw_iq_capture=false`;
- no service or control socket was started.

## Cleanup

The SDR copies `/tmp/sdrd` and `/tmp/sdrd-shadow.conf` were deleted and their
absence verified. The Pi staging directory
`/var/tmp/sdr-agent-dev/sdrd-controlled-schema-v1/` was resolved to that exact
path, deleted, and verified absent. Workstation native, sanitizer, and ARMv7
build directories were deleted after recording the artifact metadata. No raw IQ
or sweep data was produced by this feature.
