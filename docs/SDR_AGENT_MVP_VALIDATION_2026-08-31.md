# SDR Agent plan-only MVP validation

Date: 2026-08-31

## Scope

This validation covers only the plan path:

```text
Rust Controller -> Unix socket -> Pi Agent Planner Worker
                -> 4090 llama.cpp/Qwen -> Rust policy validation
```

It did not connect to `sdrd`, retune the AD9361, capture IQ, access FPGA MMIO,
install a service or deploy files to the Raspberry Pi.

## 4090 read-only check

Commands used the established `4090-via-aliyun` SSH operations route. The
`qwen-api.service` user service reported `active`, TCP port `27879` was
listening, and the unauthenticated local `/health` endpoint returned
`{"status":"ok"}`. No 4090 configuration was changed.

The existing project record identifies the Tailnet model path as:

```text
http://100.104.138.63:27879/v1
model id: qwen3.8-27b
```

The API token was read from the existing mode-`0600` WSL credential file. Its
value was not printed, copied into the repository or placed on a command line.

## Offline checks

Environment:

```text
Rust 1.98.0
Cargo 1.98.0
Node.js 22.23.2
npm 10.9.8
pi-agent-core 0.84.4
pi-ai 0.84.4
```

Results:

- Rust Controller: 7 policy/protocol tests passed.
- Planner Worker: 6 protocol/normalization tests passed.
- Rust formatting check passed.
- npm production dependency audit against the npmjs registry reported zero
  vulnerabilities.
- JSONL frames reject unknown top-level request fields and values above the
  configured size limits.

## Live model smoke test

The input instructed the agent to hold. The observation advertised no
candidates, no retune capability, no bounded-IQ capability, no FPGA capability
and no local recognizer. Qwen called the sole `submit_plan` tool with `hold`.
The Rust Controller correlated the request/session IDs and accepted the action
without approval.

The returned reason stated that the requested state should be maintained
because no candidate or safe executable capability was present. No model text
was treated as an executed action.

## Development-host resource sample

After one live request, the persistent Node Worker on x86-64 WSL reported:

```text
RSS: 107076 KiB (about 104.6 MiB)
V8 old-space cap: 96 MiB
```

The process accumulated no additional CPU jiffies during a one-second idle
sample. This is evidence for the development host only, not a Raspberry Pi
measurement. The example systemd gates remain `MemoryHigh=144M`,
`MemoryMax=192M`, and `CPUQuota=25%` until Pi-side RSS/CPU are measured.

## ARM64 artifact

The Controller was cross-built in the verified WSL Rust toolchain:

```text
target: aarch64-unknown-linux-musl
format: ELF 64-bit LSB, ARM aarch64
linkage: statically linked, stripped
size: 606 KiB
sha256: 1d89d9a4a6a08585c0417dc5a85a5b93faee945dc4213ed87ed1402234309a37
```

Artifact path:

```text
raspberry-pi/sdr-agent/controller/target/aarch64-unknown-linux-musl/release/sdr-agent-controller
```

At the time of this initial validation, the artifact had not been copied to or
executed on the Raspberry Pi. It was subsequently deployed and validated; see
[`SDR_AGENT_PI_DEPLOYMENT_2026-08-31.md`](SDR_AGENT_PI_DEPLOYMENT_2026-08-31.md).
