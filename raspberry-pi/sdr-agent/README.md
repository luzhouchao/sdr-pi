# Raspberry Pi SDR Agent runtime

> Historical/rollback runtime: new development targets the Jetson AGX clone at
> `/home/jetson/sdrharness`. The implementations in this directory remain the
> shared Controller, Planner and Web modules used by the AGX migration; the Pi
> deployment itself is no longer the primary runtime.

The runtime is one logical agent split into two processes:

```text
operator / automatic observation
             |
             v
Rust Controller -- JSONL over Unix socket --> Pi Agent Planner Worker
      |                                      |
      |                                      v
      |                              third-party model API
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
  tool and a Web-managed third-party OpenAI-compatible endpoint.
  Its deployed `SessionRuntime` reuses Pi Agent's public
  prompt/steer/follow-up/abort/event interface for the thin terminal while
  retaining the one-shot Planner as a stateless fallback.
- `controller/src/recognizer.rs`: bounded local-recognition protocol with replay
  and Unix-socket Adapters. The production C++ worker and model are not yet
  deployed, so availability remains false.
- `recognizer-worker/`: dependency-free C++20 model-backend interface and replay
  validation. Socket framing and ONNX/ncnn backends remain intentionally
  disabled until their dependencies and model artifacts are pinned.
- `web-console/`: static ARM64 Rust HTTP/SSE service with an embedded responsive
  frontend. It owns at most one live `sdr-agent` child, retains at most two
  logical conversations, and persists bounded terminal events plus compressed
  context without duplicating Controller policy or SDR access.
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
identity, frequency, sample rate, RF bandwidth, sweep coverage, dwell time and
IQ byte count. `survey_band` requires the Planner to provide start/stop/step,
sample rate, RF bandwidth and dwell; `inspect_candidate` requires candidate,
center, sample rate, RF bandwidth and dwell. There are no hidden 10-MHz radio
profile defaults in those model-selected actions. Large but bounded
IQ requests are marked `approval_required`. The Rust `SdrActionExecutor` can
execute an approved `capture_bounded_iq` plan through a controlled SDRD/1
endpoint; all other action kinds still fail closed in this executor slice.
The same Adapter exposes a generation-correlated cancel operation on an
independent SDRD/1 connection.

`SweepEngine.run(plan)` now validates a bounded range or explicit center list,
executes all points through one SDRD ownership session, consumes fixed FPGA
aggregate summaries, validates sequence/shape/quality, derives a cross-point
noise floor, merges adjacent active points, and converts compact candidates to
the existing Planner observation. Replay and production SDRD Adapters exercise
the same seam. The production Adapter fails before `START_SESSION` while the
loaded image reports `fpga_aggregate=false`.

## Development checks

Planner protocol tests do not call a model:

```bash
cd raspberry-pi/sdr-agent/planner-worker
npm test
```

These tests also cover the Pi-inspired session command subset, persistent
Agent Adapter, queue bound, abort, stale-generation behavior, one global
inference lease and explicit missing-next-plan events.

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
`/approve` executes a pending bounded-IQ, `survey_band` or
`inspect_candidate` plan only when the terminal was started with an explicit
controlled endpoint:

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

The terminal defaults to step approval. An operator starts bounded automatic
cruise with optional budgets:

```text
/auto start --steps 16 --seconds 300 在允许频段内寻找活动并根据结果继续
```

Steps are limited to 1–128 and duration to 10–1,800 seconds. Omitting both uses
8 steps and 120 seconds. Consecutive SDR-unavailable and missing-upstream-action
failures are counted independently; each retries at 10-second intervals and the
fifth failure exits. `/stop` remains immediately available during the interval.
Automatic `survey_band` uses the fixed RX gain saved on the settings page,
counts its maximum processed sample bytes and one completed step against the
cruise budgets, and writes both compact deterministic candidates and the
complete bounded measured sweep as compact `[center_hz, power_dbfs]` pairs into
the next Planner turn. Raw IQ is persisted only when the Web storage switch is
enabled.
`inspect_candidate` revisits one current candidate for at most 1,000 ms using
the same fixed gain and one 4,096-sample inline-IQ window aggregated on AGX. It
processes at most 16 KiB, persists no IQ, updates the selected candidate for the
next Planner turn, and counts against automatic-cruise step/byte budgets. Rust
passes the validated center/sample-rate/RF-bandwidth profile to SDRD/1
`APPLY_PROFILE` and verifies exact readback before capture.

Every model proposal is rendered as a visible `Agent>` reply only after Rust
has validated its structured action. Greetings, status questions and
explanations use a validated `hold.reason` in the operator's language. In
step-approval mode, an executable `survey_band`, `inspect_candidate` or
bounded-IQ reply explicitly asks the operator to click approve or enter
`/approve`; sending the natural-language request alone does not bypass that
gate. SDRD capability parsing remains strict while accepting the declared
`software_summary` field shared by the sweep and bounded-IQ production paths.

The Planner system prompt explains every live `observation` and hard `limits`
field, the complete measured sweep, the tested P201/AGX fixed profile and its
non-sustained 30.72-MHz ceiling, current candidate signals, the overall tunable
band, maximum single-survey span and per-action bandwidth. The private provider
configuration
can set an 8,192–1,000,000-token context window or adopt compatible metadata
from `/models`. Old planning turns are automatically removed at the configured
50–95% threshold (90% by default); the newest complete Rust-validated context is
retained instead of asking a summarizer to invent radio facts.

For the AGX-local `spark-local` provider, the Planner uses llama.cpp's JSON
Schema constrained output because this Spark template may otherwise emit prose
until the output limit before entering a required native tool call. The bounded
JSON action is wrapped back into the same sole Pi Agent `submit_plan` event, so
normal action normalization, Rust validation, approval and audit behavior do
not change. Pure greetings and executable plans were live-validated through
the deployed Web console and real P201 on 2026-09-02.

## Web console

The current Rust web console is deployed on the AGX and listens on trusted-LAN
interfaces at port 8787. The earlier Pi Tailnet deployment remains a rollback
baseline.

```text
http://192.168.50.75:8787/
```

The AGX template binds `0.0.0.0`; it is unauthenticated plain HTTP and must not
be port-forwarded to the Internet. The page shows the raw terminal stream,
including operator input, upstream-model messages, Rust-validated plans,
execution results, sweep-related lines and errors. `/stop`,
`/approve`, `/reject`, `/pause`, `/resume` and `/status` are buttons, but each
click still appears as `Operator> <command>` before the Controller response.

Only one logical conversation is active because `session.sock` permits one
interactive owner. One additional conversation may be stored. A third evicts
the least-recently-used inactive conversation. Switching stops the old terminal
safely and summarizes its bounded event history; histories are also compacted
at 160 new events, keep 48 recent visible events, and cap carried context at 6
KiB. The UI labels this as `已压缩 N 次`; it is not a model version. No raw IQ is
stored by this service.

The top bar places a gear-shaped `设置` entry directly beside the LAN live
connection indicator. It opens a separate settings page instead of expanding
configuration inside the run console. Model/API selection, upstream model
inventory, the 8,192–1,000,000-token context boundary, the default 90% context
compaction threshold and the first-conversation survey profile are edited
together. Changes remain local form state until the operator presses
`保存设置`; an unsaved marker and leave confirmation prevent accidental loss.
The atomic mode-`0600` private file update affects only the next new
conversation and does not restart the active one.

A new conversation defaults to one receive-only 70 MHz–6 GHz initial survey
with an 8 MHz step, 5 ms settle time and one fixed 20 dB manual RX gain for the
whole sweep. The settings page can select a custom
bounded range or disable the survey and previews points, conservative duration
and maximum received sample bytes before saving. Gain remains editable in
full-band mode over the bounded 0–60 dB range. Each session snapshots this
choice and persists `pending`, `running`, `complete`, `failed` or `skipped`, so
switching conversations and restarting the Web service never repeats a survey.
The terminal accepts the equivalent explicit options:

```text
sdr-agent --sdrd 192.168.1.10:43110 \
  --initial-survey-start-hz 70000000 \
  --initial-survey-stop-hz 6000000000 \
  --initial-survey-step-hz 8000000 \
  --initial-survey-dwell-ms 5 \
  --initial-survey-gain-db 20
```

The software summary path returns only scalar power, clipping, sequence and
timing data; it does not create raw-IQ files. `/stop` cancels the active point
and verifies SDRD restoration. Every point must read back the requested manual
gain; any mismatch or clipped sample invalidates the run and tells the operator
to lower gain. Fixed-gain dBFS is comparable only while gain, bandwidth, sample
rate, antenna and environment remain unchanged; it is not calibrated dBm.
Wide contiguous active regions remain visible
in the sweep report, while the peak-centered candidate window passed to the
Planner is capped at the configured 10 MHz policy boundary.

The Planner acknowledges a model run before generation begins, so the terminal
continues to consume input. `/stop` can abort an active upstream run and can
also cancel a hardware action directly through an independent SDRD connection.

Development checks and the static Pi build are:

```bash
cd raspberry-pi/sdr-agent/web-console
cargo test --all-targets
cargo clippy --all-targets -- -D warnings
cargo build --locked --release --target aarch64-unknown-linux-musl
```

The one-shot Runner performs one live
observe-plan-validate-approve-execute-observe cycle and appends a root-only
JSONL audit trail:

```bash
sdr-agent-controller \
  --mode run-once \
  --request controller/config/runner.development.example.json \
  --socket /run/sdr-agent/planner.sock \
  --sdrd 192.168.1.10:43110 \
  --approval operator \
  --audit-log /var/lib/sdr-agent/audit.jsonl
```

Use `--approval pending` to stop at the manual gate or `automatic` only for a
plan below the existing automatic threshold. The current production execution
Adapter supports bounded IQ capture; other plan kinds are returned as
`planned_only` rather than being reported as executed.

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

The FPGA-summary sweep entry point uses the same validated plan file in tests
and operations:

```bash
sdr-agent-controller \
  --mode sweep \
  --request controller/config/sweep.fpga-summary.example.json \
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
The original Tailnet Rust web console was deployed and live-validated on
2026-09-01; see
[`../../docs/SDR_AGENT_WEB_CONSOLE_DEPLOYMENT_2026-09-01.md`](../../docs/SDR_AGENT_WEB_CONSOLE_DEPLOYMENT_2026-09-01.md).
The AGX Controller now has live-validated bounded-IQ execution, in-flight
`/stop` cancellation, fixed-gain software surveys, step-approved candidate
inspection and a bounded automatic cruise that feeds real measurements into
the next OpenCode Go turn; see
[`../../docs/SDR_AGENT_AUTOMATIC_SURVEY_VALIDATION_2026-09-01.md`](../../docs/SDR_AGENT_AUTOMATIC_SURVEY_VALIDATION_2026-09-01.md).
Candidate state now survives Web restart independently of compacted terminal
text; see
[`../../docs/SDR_AGENT_CANDIDATE_INSPECTION_VALIDATION_2026-09-01.md`](../../docs/SDR_AGENT_CANDIDATE_INSPECTION_VALIDATION_2026-09-01.md).
Recognition remains plan-only. The
persistent P201 `sdrd` endpoint was recovered and the bounded receive-only
survey path was live-validated from AGX; a broader acquisition-ownership
cutover remains separately gated.
