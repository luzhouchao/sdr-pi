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

- `controller/`: pure-Rust protocol, policy validation, Unix-socket Planner
  Adapter, and read-only `SdrEngine` interface. The two current SDR adapters are
  replay and SDRD/1 shadow observation. It has no libiio or Node dependency and
  can be built as a static ARM64 binary.
- `planner-worker/`: headless `pi-agent-core` worker using one `submit_plan`
  tool and the existing 4090 llama.cpp OpenAI-compatible endpoint.
- `controller/src/recognizer.rs`: bounded local-recognition protocol with replay
  and Unix-socket Adapters. The production C++ worker and model are not yet
  deployed, so availability remains false.
- `../p201pro-rust/`: current direct libiio acquisition and spectrum
  aggregation executable. It is intentionally not merged into the Controller
  until the ownership seam is implemented.

The current original SDR `BOOT.bin` and shadow-only `sdrd` do not permit
retuning or bounded IQ capture through SDRD/1. Example contexts therefore set
`can_retune=false` and `can_capture_iq=false`; the Rust policy rejects any
model proposal that contradicts those capabilities.

Safe live health observation:

```bash
sdr-agent-controller \
  --mode observe \
  --sdrd 192.168.1.10:43110 \
  --sdrd-timeout-ms 5000
```

Adding `--sdrd 192.168.1.10:43110` to plan mode replaces template health with
the live shadow snapshot before the request reaches the Planner. Connection,
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
IQ requests are marked `approval_required` instead of being executed.

## Development checks

Planner protocol tests do not call a model:

```bash
cd raspberry-pi/sdr-agent/planner-worker
npm test
```

Rust checks:

```bash
cd raspberry-pi/sdr-agent/controller
cargo fmt -- --check
cargo test --all-targets
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
The Controller currently validates plans and prints the result; it does not yet
execute SDR actions. That is the safe first slice before adding a mutating
`SdrActionExecutor` and the `LocalRecognizer` adapters.
