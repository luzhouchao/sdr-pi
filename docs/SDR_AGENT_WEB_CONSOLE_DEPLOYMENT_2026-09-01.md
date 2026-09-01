# SDR Agent Rust web console deployment — 2026-09-01

## Scope

This slice adds a personal Tailnet-only control surface for the existing SDR
Agent. The web service does not plan, validate policies, access IIO, or speak
SDRD/1 itself. It starts the deployed Rust `sdr-agent` terminal and exposes its
stdin/stdout through a bounded HTTP/SSE session manager.

## Deployed release and rollback

- Pi: `root@192.168.50.194` during deployment
- Tailnet address: `100.102.130.52`
- release: `/opt/sdr-agent/releases/20260901-web-console-v1`
- active link: `/opt/sdr-agent/current`
- retained rollback: `/opt/sdr-agent/releases/20260901-software-sweep-v1`
- service: `sdr-agent-web-console.service`, enabled and active
- URL: `http://100.102.130.52:8787/`

The service binds `100.102.130.52:8787` directly. `ss` confirmed no wildcard,
LAN, or public listener for port 8787.

## Artifact

The web service was built in the isolated Ubuntu 24.04 WSL Rust toolchain with
Rust 1.98.0 for `aarch64-unknown-linux-musl`.

```text
ELF 64-bit LSB executable, ARM aarch64, statically linked, stripped
SHA-256 b1b2cd8666cff235215d4627975c51cbd42a9a673736847de3c1d0a0662ba4ea
```

The service embeds its HTML, CSS and JavaScript, so the deployed release needs
only `bin/sdr-agent-web-console` plus the systemd unit.

## Bounds and access model

- maximum logical conversations: 2
- live terminal processes: 1
- terminal events retained per conversation: 240 hard cap
- automatic compaction threshold: 160 new events
- visible events after compaction: 48
- carry-forward summary: 6 KiB maximum
- command body: 2 KiB maximum
- persisted state: `/var/lib/sdr-agent/web-console/state.json`, root:root `0600`
- systemd `MemoryHigh=48M`, `MemoryMax=64M`, `CPUQuota=20%`, `TasksMax=48`
- no raw IQ or API token is stored or served by the web console

The Planner Worker allows only one owner of `session.sock`. The Rust service
therefore stores one inactive logical conversation rather than starting a
second competing terminal. A process gate waits for `/stop` plus `/quit` to
release the old socket before a newly activated conversation starts. SIGTERM
also follows the same bounded child shutdown path before systemd restart.

The user-facing UI reports `已连接`, `已保存`, and (only after compaction)
`已压缩 N 次`. The compaction count is not a Qwen model version or conversation
number.

## Verification

Repository checks passed:

- `cargo fmt -- --check`
- `cargo test --all-targets`: 3 passed
- `cargo clippy --all-targets -- -D warnings`
- static ARM64 release build and SHA-256 verification

Browser checks were run against a local isolated instance at desktop width and
390 px width. They covered initial state, responsive layout, SSE connectivity,
session creation, button input visibility and the two-session eviction rule.

Live Pi checks then covered:

1. Windows reached `GET /api/state` over the Tailnet address with HTTP 200.
2. Creating a conversation started the real deployed `sdr-agent` with the
   controlled SDRD endpoint.
3. Clicking status produced both `Operator> /status` and the real Controller
   response in the web terminal.
4. A read-only natural-language request displayed Qwen `Agent>` output and a
   Rust-validated `hold` plan in the same stream. No approval or hardware action
   was requested.
5. Creating a second conversation and reactivating the first safely stopped the
   previous terminal, incremented the web context revision, and connected the
   selected conversation without a busy-session error.
6. The service and Planner remained active. The web service measured about
   1.1 MiB `MemoryCurrent` with three tasks during the check.
7. A systemd restart with an active browser SSE connection completed in five
   seconds without timeout; the old terminal PID disappeared, the new service
   restored one terminal owner, and the browser reconnected automatically.

## Known boundary

The current `sdr-agent` terminal blocks in the Planner read loop while Qwen is
running. Web input is visibly recorded and queued at the process pipe during
that period, but it is not consumed until the model turn ends. This does not
change the direct `/stop` behavior while hardware execution is active. Making
stdin concurrent during Qwen streaming remains an explicit future terminal
milestone.

## Rollback

Rollback does not delete the new release or its state:

```bash
ln -sfn /opt/sdr-agent/releases/20260901-software-sweep-v1 /opt/sdr-agent/current
systemctl disable --now sdr-agent-web-console.service
```

The prior Planner process and release remain independent of the web service.
