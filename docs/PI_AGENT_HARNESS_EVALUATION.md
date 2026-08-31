# Pi Agent as the SDR Planner Worker

Date: 2026-08-31

## Decision

Use `@earendil-works/pi-agent-core` together with the required parts of
`@earendil-works/pi-ai` for a separate Planner Worker. Do not use the complete
`pi-coding-agent` CLI as the SDR Harness, and do not give the Planner Worker
direct SDR, shell, filesystem, IIO, FPGA or SSH authority.

The complete project agent is the closed loop formed by the Planner Worker,
the Rust Harness, the local recognizer and `sdrd`:

```text
operator / automatic policy                4090 server
          |                                Qwen / DeepSeek / another model
          v                                      ^
Pi Agent Planner Worker on Pi -------------------|
          |
          | ProposedAction only
          v
Rust Controller: state machine, validation, limits, approval, audit, timeout
          |                              |
          v                              v
C++ LocalRecognizer                C SDRD adapter
                                         |
                                         v
                                SDR Linux C sdrd -> FPGA/IIO
```

Process separation does not make these separate logical agents. The Planner
Worker supplies nondeterministic reasoning and the Rust Controller supplies the
deterministic perception-action loop and safety authority.

## Why Pi Agent fits the planner seam

- `pi-agent-core` supplies tool calling, state management, event streaming,
  custom application messages, provider-stream injection and pre/post tool
  hooks.
- `pi-ai` supports custom OpenAI-compatible providers and model endpoints, so a
  Qwen endpoint can later be replaced by or routed alongside DeepSeek without
  changing SDR control code.
- Tool calls are validated before `beforeToolCall`; calls can be blocked and a
  turn can be terminated. This is useful as a planner guard, but it is not a
  security boundary.
- The packages support Node.js on Linux, and the upstream binary build includes
  a `linux-arm64` target. The package manifests require Node.js 22.19 or newer.

## Why the complete coding agent does not fit

`pi-coding-agent` is optimized for source-tree work. Its built-in tools can
read, write, edit and run shell commands. Upstream explicitly states that Pi
has no built-in sandbox and runs with the permissions of its process. Those
capabilities are unnecessary and unsafe in the SDR control process.

The coding-agent package also brings TUI, file-editing and shell dependencies
that do not help the headless embedded loop. Although it has RPC mode and can
run without built-in tools, embedding the smaller core gives the project a
clearer contract and less accidental authority.

The upstream `pi-server` and CBOR protocol are marked experimental, provide no
standalone service, and have no compatibility guarantee. They should not become
the project's stable hardware-control ABI. The project should own a small,
versioned Planner protocol instead.

## Recommended process contract

Use a local Unix-domain socket between Rust and the Planner Worker. Versioned
newline-framed JSON is sufficient for the first implementation. Bound frame
size, duration and proposal count.

Rust sends only a compact `PlanningContext`:

- current Harness state and session generation;
- SDR capabilities and health, never raw register access;
- aggregated spectrum candidates;
- local-recognizer labels and confidence;
- operator instruction and applicable policy limits.

The Worker returns only a discriminated `ProposedAction`, for example:

- `SurveyBand`;
- `InspectCandidate`;
- `CaptureBoundedIq`;
- `RunLocalRecognition`;
- `Hold`;
- `StopSession`.

Rust validates frequency, bandwidth, gain, dwell, IQ byte budget, state
transition, capability generation, freshness and authorization. Only after
validation does it call `SdrEngine` or `LocalRecognizer`. Unknown fields,
unknown action types, stale generations and out-of-range values fail closed.

Do not expose generic `bash`, `read`, `write`, `edit`, `ssh`, `devmem`, IIO or
FPGA-register tools to the model. Pi Agent tools should collect structured
planning information or submit a proposal; they should not perform the hardware
action themselves.

## Provider independence

Keep provider selection entirely inside the Planner Worker. The Rust interface
should be provider-neutral:

```text
plan(PlanningContext) -> ProposedAction | NoPlan | PlannerUnavailable
```

Configuration may choose provider, model, base URL, API type and an environment
variable holding the API key. Qwen and DeepSeek endpoints that implement OpenAI
Chat Completions can use `openai-completions`. Normalize provider differences
inside the Worker, including tool-call support, structured-output reliability,
reasoning fields, context length, timeout and retry behavior.

Failing over between providers must start a new bounded planning attempt; it
must never replay a possibly executed action. The Rust session generation and
action id provide idempotency.

## Human intervention

Support three input paths:

1. automatic policy events;
2. operator natural-language instructions routed through the Planner Worker;
3. deterministic safety commands handled directly by Rust.

Natural-language instructions produce proposals and still pass the same Rust
validator. `pause`, `stop`, session release and emergency inhibit must bypass
the model so they remain available during API or network failure. High-impact
actions can require explicit operator approval after the structured proposal is
shown.

Record the original instruction, model/provider, normalized proposal,
validation result, approval identity, action id, observations and final result.
Do not store API keys or SDR credentials in the transcript.

## Initial implementation slice

1. Define `PlanningContext`, `ProposedAction`, `PlannerResult` and protocol
   version in Rust, with exhaustive validation tests.
2. Build a small TypeScript Planner Worker using `pi-agent-core` and `pi-ai`.
3. Give it only `submit_plan`, `request_observation` and `hold` tools.
4. Test with a mock planner and recorded spectrum observations before connecting
   Qwen.
5. Add natural-language operator input plus Rust-native pause/stop commands.
6. Add Qwen first; test DeepSeek as a second provider against the same replay
   suite.

## Primary sources inspected

The evaluation used official source at commit
`853a80d26c90a14c1886f0ebb8ffaae133ca2185`:

- [repository overview](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/README.md)
- [`pi-agent-core` API](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/agent/README.md)
- [custom provider and model configuration](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/coding-agent/docs/models.md)
- [extension and custom-tool API](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/coding-agent/docs/extensions.md)
- [security model](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/coding-agent/docs/security.md)
- [experimental server package](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/server/README.md)
- [Linux ARM64 binary build](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/scripts/build-binaries.sh)
