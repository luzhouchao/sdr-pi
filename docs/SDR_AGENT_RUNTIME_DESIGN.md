# SDR Agent runtime design

Date: 2026-08-31

## Decision

The complete SDR Agent is a distributed logical module whose Pi-side runtime
contains a deterministic Rust Controller and a lightweight Pi Agent Planner
Worker. Qwen remains in the existing llama.cpp process on the 4090.

```text
Raspberry Pi 4B                              4090 server
---------------------------------------      -----------------------
Rust Controller                              llama.cpp
  - authoritative state                         - qwen3.8-27b
  - policy and capability validation             - inference/KV cache
  - timeout, approval and audit            <---- OpenAI-compatible HTTP
  - future SdrEngine execution
          |
          +-- Unix socket --> Planner Worker
                                  - pi-agent-core
                                  - one submit_plan tool
                                  - no persistent conversation
                                  - no hardware or shell authority
```

The repository named `pi` is an agent framework; it does not move Qwen
inference onto the Raspberry Pi. The Pi stores only one bounded planning
context and streams the remote result.

## Deep modules and seams

### Controller module

Its external interface is deliberately small:

```text
decide(PlanRequest) -> ValidatedPlan | ControllerError
```

Behind it are frame correlation, stale-generation rejection, capability and
state checks, numeric limits, candidate matching and approval classification.
Callers do not need to repeat those rules.

### Planner seam

The Controller depends on one `Planner` interface. The Unix-socket adapter is
the production adapter; tests can use an in-memory adapter. Provider selection,
Pi Agent events, Qwen compatibility and token handling stay behind this seam.

### SDR observation seam

The read-only `SdrEngine` interface is now implemented:

```text
SdrEngine.observe() -> SdrSnapshot
```

It has an SDRD/1 shadow Adapter and a replay Adapter. Protocol framing,
correlation, server identity, capability reduction and fail-closed behavior are
hidden behind the interface.

### Future execution seams

Mutation and recognition remain future, separate interfaces:

```text
SdrActionExecutor.execute(ValidatedSdrAction) -> Observation
LocalRecognizer.classify(BoundedIqRef) -> RecognitionSummary
```

The existing direct-libiio acquisition executable remains separate until only
one process owns the RX buffer.

## Resource budget

The hot data path does not enter Pi Agent. Spectrum aggregation remains in Rust
and future recognition remains in C++. Only compact candidates, health and one
operator instruction cross the planner seam.

Initial worker gates:

| Resource | Gate |
|---|---:|
| active planning requests | 1 |
| JSONL frame | 32 KiB |
| candidates per request | 32 |
| operator instruction | 1024 bytes |
| generated tokens | 1024 |
| request timeout | 30 s |
| V8 old-space cap | 96 MiB |
| systemd memory high/max | 144/192 MiB |
| systemd CPU quota | 25% of one host CPU |

The Worker creates a fresh Agent state for each request and does not persist a
conversation or SQLite session. The 196608-token model context describes the
remote model's capacity; the Pi never attempts to fill it.

## Failure behavior

- Planner unavailable, busy, timed out or malformed: no action is executed.
- Response request ID or session generation mismatch: reject as stale.
- Current shadow `sdrd` reports no retune/capture capability: reject those
  proposals even when the model requests them.
- Faulted Controller state: only `hold` and `stop_session` are accepted.
- IQ proposal exceeds the hard byte/sample limit: reject.
- IQ proposal is bounded but above the automatic threshold: require explicit
  operator approval.
- Emergency pause/stop is implemented directly in Rust later and never waits
  for the model.

## Configuration ownership

Non-secret endpoint and model settings live in `planner.env`. The token lives
in a separate permission-restricted file. The current endpoint is reached over
Tailscale; the 4090's Aliyun reverse SSH route remains an operations fallback,
not a model-data path.
