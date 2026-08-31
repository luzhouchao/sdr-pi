# Pi-first terminal Agent research for SDR Agent

Date: 2026-08-31

## Scope and source baseline

This note answers how the Raspberry Pi terminal should behave like `pi` or
`codex` without copying a general coding agent's weight or authority into the
SDR runtime. It uses primary source code and first-party documentation.

- Pi: `earendil-works/pi` at commit
  [`853a80d26c90a14c1886f0ebb8ffaae133ca2185`](https://github.com/earendil-works/pi/tree/853a80d26c90a14c1886f0ebb8ffaae133ca2185),
  MIT, Copyright (c) 2025 Mario Zechner.
- DeepSeek Harness: `deepseek-ai/deepseek-harness` at commit
  [`0a53fb55bea101816fa226bb964ae2bed71c343b`](https://github.com/deepseek-ai/deepseek-harness/tree/0a53fb55bea101816fa226bb964ae2bed71c343b),
  MIT, Copyright (c) 2026 DeepSeek.
- Current SDR Planner Worker: `@earendil-works/pi-agent-core` and `pi-ai`
  0.84.4, already deployed on the Pi.

Both upstream licenses allow use, copying and modification, but copied source
must retain the applicable copyright and MIT notice. Direct dependency reuse is
preferred because it preserves upstream fixes and reduces local maintenance.

## What Pi actually separates

Pi is not one terminal state machine. It separates the Agent loop, session
orchestration, storage, terminal presentation and process-integration modes.
Its first-party README explicitly offers interactive, print/JSON, RPC and SDK
modes rather than forcing every caller through the TUI
([README modes](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/coding-agent/README.md#L15-L19)).

This separation is the main design to reuse. The SDR terminal should not put
model execution, queues, hardware policy and terminal drawing in one module.

### Agent core is the real conversation engine

`pi-agent-core` already provides the semantics needed by an SDR conversation:

- `subscribe()` publishes typed Agent events;
- `prompt()` starts work only when no run is active;
- `steer()` queues a message for the next steering drain point;
- `followUp()` queues work after the Agent would otherwise finish;
- `abort()` cancels the active run;
- steering and follow-up queues can use `one-at-a-time` or `all` drain modes.

These operations are implemented by Pi's
[`Agent`](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/agent/src/agent.ts#L171-L380),
while the queue drain points live in the
[`agent loop`](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/agent/src/agent-loop.ts#L161-L212).
Reimplementing those queues in Rust would create a second, divergent source of
truth for whether the model is running or when a message will be delivered.

Pi's documented user semantics are also precise: Enter queues steering while
the Agent is busy, Alt+Enter queues a follow-up, and Escape aborts while
restoring queued input
([queue interaction](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/coding-agent/README.md#L223-L233)).
The SDR terminal can keep these semantics even with a simpler line UI.

### AgentSession is orchestration, not the TUI

Pi's coding Agent adds an `AgentSession` over `Agent`. It exposes event
subscription, prompt routing, steering, follow-up, abort, compaction and
session operations independently of the interactive renderer
([AgentSession implementation](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/coding-agent/src/core/agent-session.ts#L311-L403),
[prompt and queues](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/coding-agent/src/core/agent-session.ts#L1155-L1465),
[abort](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/coding-agent/src/core/agent-session.ts#L1620-L1624)).

The full `AgentSession` also knows about coding-agent extensions, compaction,
retry and session storage. The first SDR version does not need all of that.
Reuse `Agent` directly first; add only the proven `AgentSession` behavior that
becomes necessary.

### Pi RPC is a useful protocol catalogue

Pi's headless RPC mode uses JSONL on stdin/stdout. Its command union includes
`prompt`, `steer`, `follow_up`, `abort`, `clear_queue`, `new_session` and
`get_state`, followed by optional model, compaction, Bash and session commands
([RPC types](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/coding-agent/src/modes/rpc/rpc-types.ts#L1-L99)).

The SDR protocol should copy only the small prompting/state subset. It must not
copy Pi RPC's Bash, filesystem, model switching, HTML export or arbitrary
extension UI surface. The useful pattern is correlated commands plus a stream
of events, not the entire command union.

### Sessions, trees and compaction are deliberately separate

Pi stores sessions as append-oriented JSONL tree entries with IDs and parent
IDs, allowing branches without rewriting the full transcript. Compaction is
lossy for model context while the original history stays available
([session behavior](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/coding-agent/README.md#L239-L281),
[session format](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/coding-agent/docs/session-format.md)).

The SDR first version should be ephemeral and bounded. Persistent history is a
later adapter, not a precondition for an interactive terminal. When added, an
append-only event log is preferable to serializing one mutable state blob.

### Slash commands and extensions are registries

Pi maintains a command catalogue and lets extensions register commands, tools,
keyboard shortcuts, event handlers and UI. Its built-in command list is data,
not a large `if` chain
([slash command catalogue](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/coding-agent/src/core/slash-commands.ts),
[extension documentation](https://github.com/earendil-works/pi/blob/853a80d26c90a14c1886f0ebb8ffaae133ca2185/packages/coding-agent/docs/extensions.md)).

The SDR CLI should use a small command registry. Safety commands remain native
Rust commands and are never sent to the model. New presentation-only commands
can be added without editing the Agent loop.

## What DeepSeek Harness adds

DSH reinforces two ideas but should not be the runtime copied onto the Pi:

1. interaction features are separately packaged modules rather than one UI
   state machine;
2. approval is its own domain module with invariants and tests, separate from
   the chat renderer.

Relevant first-party modules are
[`interaction/user-approval`](https://github.com/deepseek-ai/deepseek-harness/tree/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/interaction/user-approval),
[`interaction/commands`](https://github.com/deepseek-ai/deepseek-harness/tree/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/interaction/commands),
and
[`core/session`](https://github.com/deepseek-ai/deepseek-harness/tree/0a53fb55bea101816fa226bb964ae2bed71c343b/packages/core/session).

For SDR, approval must stay in Rust next to policy and session generation. A
Node UI or model must never be able to turn its own proposal into approval.

## Current project gap

The deployed Planner Worker already uses Pi `Agent`, but it creates a new Agent
for every request with `messages: []`. One socket connection accepts one
request, the only tool is `submit_plan`, and that tool terminates the Agent
after exactly one proposal. This is intentionally safe and stateless, but it
cannot provide Pi-style steering, follow-up, abort or conversational continuity.

Adding a local Rust `ConsoleSession` state machine alone would be wrong. It
would remember terminal state while the actual Pi Agent is recreated and knows
nothing about that history or queue. The state sources would disagree.

## Options

| Option | Reuse | Pi cost | Safety/locality | Decision |
|---|---|---:|---|---|
| install full `pi-coding-agent` TUI | maximum UI reuse | highest | includes irrelevant coding surfaces | reject |
| Pi Agent core + thin Rust terminal | reuses Agent loop and queue semantics | low | Rust retains hardware authority | choose |
| keep one-shot Planner and add a Rust REPL | little meaningful reuse | low | duplicate conversation state | reject |
| copy Pi Agent loop into Rust | code copy only | uncertain | forks mature upstream logic | reject |

At version 0.84.4, the official npm package metadata reports an unpacked size
of about 1.9 MB for `pi-agent-core` and 21.5 MB for `pi-coding-agent`. The latter
also depends on TUI, client/protocol, syntax highlighting, Mermaid and image
packages. The deployed core-based Planner currently measures about 31 MB
`MemoryCurrent` at idle on the project Pi. This supports reusing core without
installing the full coding TUI. Package size is not a runtime-RSS claim; the
new worker still needs Pi measurement.

## Recommended architecture

```text
sdr-agent (Rust line terminal)
    | correlated JSONL commands/events over Unix socket
    v
Pi Agent Session Adapter (Node, pi-agent-core)
    | prompt / steer / followUp / abort / subscribe
    | only tool: submit_plan
    v
4090 llama.cpp + Qwen

submit_plan event
    -> Rust Controller policy + session_generation validation
    -> pending approval or safe validated plan
    -> future SdrActionExecutor
```

The terminal does not own the Agent run state. It renders events and sends
commands. The Node Session Adapter does not own hardware state. It owns the Pi
Agent instance and queues. The Rust Controller owns authoritative SDR state,
approval, session generation, emergency pause/stop and future execution.

Use a separate `/run/sdr-agent/session.sock` initially so the proven one-shot
`planner.sock` remains backward compatible and available as a fail-closed
fallback.

### Minimal copied protocol shape

Commands, each with protocol version, command ID and session generation:

- `open_session`;
- `prompt`;
- `steer`;
- `follow_up`;
- `abort`;
- `clear_queue`;
- `get_state`;
- `close_session`.

Events:

- command acknowledgement or error;
- Agent start/end;
- assistant text delta/end;
- tool call start/end;
- plan submitted;
- queue state;
- aborted/unavailable.

Native Rust commands such as `/status`, `/approve`, `/reject`, `/pause`,
`/resume`, `/stop` and `/quit` are not Agent commands. They execute locally or
change Controller policy. An assistant message can never impersonate one.

Initial gates:

- one interactive session and one active Agent run;
- at most four queued steering/follow-up messages;
- 1024 bytes per operator message and bounded event frames;
- ephemeral transcript with a fixed message/token budget;
- one `submit_plan` tool, no Bash/filesystem/network tools;
- `abort` available while inference is streaming;
- all proposals correlated to the current Rust session generation;
- no hardware execution until the Rust executor exists and approval is valid.

## Reuse classification

### Direct dependency reuse

- Pi `Agent`, event subscription and queue methods from `pi-agent-core`;
- Pi model/provider streaming from `pi-ai`;
- TypeBox schema for the sole `submit_plan` tool.

### Source that may be adapted under MIT notice

- the prompting/state subset of Pi's RPC command and response types;
- queue-mode naming and event-to-terminal mapping;
- small command-registry patterns.

Any copied substantial source must record the upstream repository, commit and
MIT copyright in the vendored file or third-party notices.

### Design only, do not copy wholesale

- Pi interactive TUI and coding tools;
- Pi Bash/filesystem/model-switching RPC commands;
- Pi full session tree, HTML export, themes and image rendering;
- DSH frontend, plugin host and general session controller.

## Implementation order

1. Remove the speculative Rust-only conversation state draft.
2. Add tests for a bounded Pi Session Adapter using a fake stream/model.
3. Add the minimal session JSONL protocol on a new Unix socket.
4. Add a Rust event client and line terminal named `sdr-agent`.
5. Validate prompt, steer, follow-up, abort and stale-generation rejection
   without hardware execution.
6. Cross-build and deploy alongside the current Planner; do not replace the
   one-shot path until Pi memory, timeout and reconnect tests pass.
