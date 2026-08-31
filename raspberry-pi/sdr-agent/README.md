# Raspberry Pi SDR Agent runtime

The runtime is one logical agent split into two processes:

```text
operator / automatic observation
             |
             v
Rust Controller -- JSONL over Unix socket --> Pi Agent Planner Worker
      |                                      |
      |                                      v
      |                              4090 llama.cpp + Qwen
      v
SDRD/1 adapter -> SDR Linux C sdrd -> IIO/FPGA
      |
      +-> LocalRecognizer adapter -> future C++ inference worker
```

The Planner Worker proposes one action. The Rust Controller is the only module
that validates and later executes it. The worker has no shell, filesystem,
SSH, IIO, FPGA-register or SDR tools.

## Current implementation

- `controller/`: pure-Rust protocol and policy validation, Unix-socket Planner
  Adapter, read-only `SdrEngine`, and bounded-IQ `SdrActionExecutor`. Observation
  accepts consistent shadow or controlled SDRD/1 endpoints; execution has replay
  and production SDRD Adapters. It has no libiio or Node dependency and builds
  as a static ARM64 binary.
- `planner-worker/`: headless `pi-agent-core` worker using one `submit_plan`
  tool and the existing 4090 llama.cpp OpenAI-compatible endpoint.
  Its tested, not-yet-deployed `SessionRuntime` reuses Pi Agent's public
  prompt/steer/follow-up/abort/event interface for a future thin terminal while
  retaining the one-shot Planner as the stable path.
- `controller/src/recognizer.rs`: bounded local-recognition protocol with replay
  and Unix-socket Adapters. The production C++ worker and model are not yet
  deployed, so availability remains false.
- `recognizer-worker/`: dependency-free C++20 model-backend interface and replay
  validation. Socket framing and ONNX/ncnn backends remain intentionally
  disabled until their dependencies and model artifacts are pinned.
- `../p201pro-rust/`: current direct libiio acquisition and spectrum
  aggregation executable. It is intentionally not merged into the Controller
  until the ownership seam is implemented.

The deployed SDR still uses its original `BOOT.bin`, so FPGA aggregation remains
disabled. The local-IIO controlled `sdrd` development mode can retune and perform
bounded IQ capture without FPGA support, but it is not installed as a service.
The normal request template therefore remains capability-false; Rust accepts
execution only from live controlled capabilities or an explicitly validated
development envelope.

Safe live health observation:

```bash
sdr-agent-controller \
  --mode observe \
  --sdrd 192.168.1.10:43110 \
  --sdrd-timeout-ms 5000
```

Adding `--sdrd 192.168.1.10:43110` to plan mode replaces template health with
the live shadow or controlled snapshot before the request reaches the Planner. Connection,
schema or correlation failure aborts the plan instead of falling back.

## Protocol

One connection carries one request and one response, each a JSON object ending
in `\n`. Frames are limited to 32 KiB. Every response must echo
`request_id` and `session_generation`. A stale or malformed response fails
closed.

The Planner Worker can return only:

- `hold`;
- `survey_band`;
- `inspect_candidate`;
- `capture_bounded_iq`;
- `run_local_recognition`;
- `stop_session`.

Rust validates current capabilities, state, observation age, candidate
identity, frequency, bandwidth, dwell time and IQ byte count. Large but bounded
IQ requests are marked `approval_required`. The Rust `SdrActionExecutor` can
execute an approved `capture_bounded_iq` plan through a controlled SDRD/1
endpoint; all other action kinds still fail closed in this executor slice.
The same Adapter exposes a generation-correlated cancel operation on an
independent SDRD/1 connection.

## Development checks

Planner protocol tests do not call a model:

```bash
cd raspberry-pi/sdr-agent/planner-worker
npm test
```

These tests also cover the Pi-inspired session command subset, persistent
Agent Adapter, queue bound, abort and stale-generation behavior. The session
socket and terminal are not enabled until one-shot and interactive runs share
one global inference lease.

Rust checks:

```bash
cd raspberry-pi/sdr-agent/controller
cargo fmt -- --check
cargo test --all-targets
```

After deployment, an operator starts the lightweight terminal with no flags:

```bash
sdr-agent
```

One-shot input is also supported:

```bash
sdr-agent "查看当前 SDR 状态"
```

The terminal connects to `/run/sdr-agent/session.sock`; the existing
`planner.sock` remains the stateless fallback. `/pause`, `/resume` and `/stop`
advance the Controller session generation so prior proposals become stale.
`/approve` executes the pending bounded-IQ plan only when the terminal was
started with an explicit controlled endpoint:

```bash
sdr-agent --sdrd 192.168.1.10:43110
```

Without `--sdrd`, approval is recorded but no hardware command is sent. An
execution failure advances the session generation and puts the terminal into
`faulted` state so the stale approval cannot be retried accidentally.
With `--sdrd`, `/approve` moves execution to a bounded background worker so the
line interface remains available. `/stop` sends cancellation directly without
calling Qwen, waits for the owner response that confirms restoration, and then
advances the session generation. It retries only the bounded startup window in
which `START_SESSION` has not yet completed.

For a deterministic development or recovery check, `execute` mode accepts an
envelope containing the original `PlanRequest` and `PlanResponse`, reruns Rust
policy validation, then requires explicit operator approval when needed:

```bash
sdr-agent-controller \
  --mode execute \
  --request controller/config/execution.development.example.json \
  --sdrd 192.168.1.10:43110 \
  --approval operator
```

Recovery tooling can request the same generation-correlated cancellation
without a Planner call:

```bash
sdr-agent-controller \
  --mode cancel \
  --session-generation 77 \
  --sdrd 192.168.1.10:43110
```

The recognition interface and its fixed IQ contract are documented in
[`../../docs/LOCAL_RECOGNIZER_INTERFACE.md`](../../docs/LOCAL_RECOGNIZER_INTERFACE.md).

For a development smoke test, a natural-language instruction can replace the
instruction in a bounded context file without changing its health or limits:

```bash
cargo run -- \
  --socket /run/user/$(id -u)/sdr-agent/planner.sock \
  --request config/request.example.json \
  --instruction "保持当前状态并说明原因"
```

## Configuration

Copy `planner-worker/config/planner.env.example` to
`/etc/sdr-agent/planner.env`. Put the API token in the separate root-owned,
mode-`0600` file `/etc/sdr-agent/qwen-api-token`. The example systemd module
passes it to the unprivileged worker through `LoadCredential`. Do not put it in
the environment example, repository, command line, logs or systemd unit.

The example points at the currently documented Tailnet endpoint:

```text
http://100.104.138.63:27879/v1
model: qwen3.8-27b
```

The 4090 continues to own llama.cpp inference, tokenization and KV cache. The
Pi worker is stateless between planning requests, has one active request at a
time, emits at most 1024 output tokens and is intended to run with a 96 MiB V8
heap cap plus a systemd `MemoryMax` of 192 MiB. These limits are initial gates,
not measured claims; measure RSS on the Pi before tightening them.

## Safety and deployment status

The repository does not install services automatically. The plan-only release
was manually deployed and enabled on the project Pi on 2026-08-31; see
[`../../docs/SDR_AGENT_PI_DEPLOYMENT_2026-08-31.md`](../../docs/SDR_AGENT_PI_DEPLOYMENT_2026-08-31.md).
The read-only SDRD observation slice was subsequently deployed and validated;
see
[`../../docs/SDR_AGENT_SDRD_OBSERVE_VALIDATION_2026-08-31.md`](../../docs/SDR_AGENT_SDRD_OBSERVE_VALIDATION_2026-08-31.md).
The interactive `sdr-agent` terminal was then deployed and validated; see
[`../../docs/SDR_AGENT_TERMINAL_DEPLOYMENT_2026-08-31.md`](../../docs/SDR_AGENT_TERMINAL_DEPLOYMENT_2026-08-31.md).
The Controller now has live-validated bounded-IQ execution and in-flight
`/stop` cancellation. It does not yet execute surveys, candidate-inspection
dwell loops, recognition, or automatic Runner cycles. Controlled `sdrd` is
still a temporary development process rather than an enabled SDR service.
