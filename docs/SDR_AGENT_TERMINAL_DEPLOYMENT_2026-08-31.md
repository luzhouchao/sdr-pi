# SDR Agent interactive terminal deployment

Date: 2026-08-31

## Outcome

The Pi now provides a user-facing `sdr-agent` command backed by a persistent
Pi Agent core session and the existing Qwen endpoint on the 4090. The stable
one-shot Planner socket remains available as a fallback.

```bash
sdr-agent
sdr-agent "查看当前 SDR 状态"
```

Deployed release:

```text
/opt/sdr-agent/current
  -> /opt/sdr-agent/releases/20260831-agent-cli-v1
repository revision: 51c29f5
```

The prior release remains intact at
`/opt/sdr-agent/releases/20260831-plan-v2-sdrd-observe`.

## Artifacts

| Artifact | SHA-256 |
|---|---|
| `sdr-agent-controller` | `cf1193d9f3212c2c13ddcea0eff2e9622332ea8ff8e57b61d4f57b3ef337c372` |
| `sdr-agent` | `38088901c632cdd4297aadfa5c5cddbcc54752af5b91e377f619dc9d91acec04` |

Both are stripped, statically linked AArch64 ELF executables built in the
verified Ubuntu 24.04 WSL Rust toolchain. No compiler was installed on the Pi.

## Runtime

`sdr-agent-planner.service` remains enabled and active. The same bounded Node
process owns both sockets:

```text
/run/sdr-agent/planner.sock  stateless one-shot Planner
/run/sdr-agent/session.sock  one interactive Pi Agent session
```

Both sockets were created as mode `0660`, owned by `sdr-agent:sdr-agent`.
One global inference lease prevents the one-shot Planner and interactive
session from running Qwen requests concurrently.

Observed after deployment:

```text
idle MemoryCurrent: about 35-37 MB
post-smoke MemoryCurrent: about 47 MB
MemoryPeak during smoke: about 65 MB
TasksCurrent: 7
systemd MemoryHigh/Max: 144/192 MB
```

## Validation

Before deployment:

- Rust: 16 tests passed;
- Rust Clippy: zero warnings with `-D warnings`;
- Node: 17 tests passed;
- both ARM64 release binaries built and hashed.

Live validation on the Pi:

1. one-shot `sdr-agent "..."` returned a conservative `hold` proposal;
2. Rust correlated and validated the proposal;
3. interactive `/status`, natural language input, `/history`, `/pause`, second
   `/status`, and `/quit` completed successfully;
4. `/pause` advanced `session_generation` from 1 to 2 and cleared stale state;
5. the original one-shot Controller-to-`planner.sock` path passed a regression
   request after the interactive test;
6. the systemd module remained active.

The deployed request template reports the SDR offline with no capabilities,
so Qwen can only propose safe actions such as `hold`. The smoke test did not
connect to SDRD and did not change IIO attributes, FPGA state, SDR `BOOT.bin`,
radio settings or SDR services.

## Operator commands

```text
/status   /history
/approve  /reject
/pause    /resume   /stop
/help     /quit
```

`/approve` records a human decision only. The separate `SdrActionExecutor` is
not enabled, so no approved proposal can mutate hardware in this release.
