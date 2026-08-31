# SDR Agent SDRD observe-path validation

Date: 2026-08-31

## Result

The Rust Controller now has a real read-only `SdrEngine` seam with two
adapters:

- `ReplaySdrAdapter` for deterministic tests;
- `SdrdAdapter` for live `SDRD/1` shadow observations.

The live Pi-to-SDR path passed. The Adapter reduced HELLO, CAPABILITIES and
HEALTH responses to a small `SdrSnapshot`, and a subsequent planning request
used those live capabilities. No mutating SDRD command was implemented or sent.

## Build and tests

WSL Ubuntu 24.04 validation:

```text
Rust/Cargo: 1.98.0
tests: 11 passed
target: aarch64-unknown-linux-musl
format: ELF 64-bit ARM aarch64, statically linked, stripped
size: 677 KiB
sha256: ed492c4d7a2f5dadec86a4e099d8b25dd21be0bb7d04527c31d681fd1bc89534
```

Tests cover replay exhaustion, valid shadow reduction, mismatched response IDs,
unhealthy capability downgrading and the previous planning-policy gates.

## Pi deployment

The new Controller was transferred over the LAN route and installed as:

```text
/opt/sdr-agent/releases/20260831-plan-v2-sdrd-observe
```

`/opt/sdr-agent/current` points to this release. The previous
`20260831-plan-v1` release remains available for rollback. The already-running
Planner Worker was not replaced and remained active.

## Fail-closed check

Before the shadow daemon was started, observe mode returned:

```text
controller_error=connect: Connection refused (os error 111)
```

The Controller did not substitute template capabilities and did not contact the
Planner.

## Temporary SDR shadow probe

The previously validated ARMv7 `sdrd` artifact was relayed through the Pi to
the SDR `/tmp` directory:

```text
sha256: 99961bb4e0a430e8c21a9e5a58ebbd316f19070f53587612848a12b32c2bba12
mode: shadow
fpga_backend: disabled
```

Before serving, `--check-config` and `--probe` passed. The probe reported both
IIO devices visible, health flags zero, no radio-control capability, no raw-IQ
capture and no FPGA identity/capability.

The daemon listened temporarily on `192.168.1.10:43110`. It was not installed
as a service or boot entry.

## Live observation

The deployed Pi Controller returned:

```json
{
  "online": true,
  "healthy": true,
  "health_flags": 0,
  "iio_visible": true,
  "can_retune": false,
  "can_capture_iq": false,
  "fpga_available": false,
  "fpga_backend": "disabled",
  "fpga_summary_version": 0,
  "fpga_abi_version": 0,
  "fpga_capability": 0
}
```

The Adapter validated schema version, response IDs, server identity, protocol,
shadow mode, read-only status, bounded newline framing and QUIT acknowledgement.

## Live observation-to-plan chain

The Controller replaced the request's template health with the live
`SdrSnapshot` and asked the 4090 Qwen Planner for a safe next step. Qwen
returned `hold`, explicitly citing that retune, IQ capture, FPGA and recognizer
capabilities were unavailable and no candidates existed. Rust accepted the
plan with `approval_required=false`.

## Cleanup

After validation:

- the temporary SDR daemon was stopped and port `43110` closed;
- SDR `/tmp` binary, configuration, PID and log were deleted;
- Pi relay files and uploaded Controller staging file were deleted;
- the persistent Pi Planner Worker remained enabled and active;
- a second observe call failed closed with connection refused, confirming the
  temporary SDR daemon was gone.

No IIO attribute, FPGA register, SDR `BOOT.bin`, init entry or radio state was
changed.
