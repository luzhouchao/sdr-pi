# SDR Agent bounded Runner deployment

Date: 2026-09-01

## Outcome

The Rust Harness now exposes one deep `Runner.run_once(request, approval)`
interface for the production bounded-IQ action. Its implementation hides the
live SDR observation, Planner call, raw proposal audit, deterministic policy
validation, approval correlation, hardware execution, state-restored follow-up
observation and JSONL audit sequence.

The one-shot CLI is:

```text
sdr-agent-controller --mode run-once \
  --request <plan-request.json> \
  --socket /run/sdr-agent/planner.sock \
  --sdrd 192.168.1.10:43110 \
  --approval pending|automatic|operator \
  --audit-log /var/lib/sdr-agent/audit.jsonl
```

`pending` stops before a plan that needs approval, `automatic` is accepted only
below existing policy thresholds, and `operator` is an explicit approval for
the correlated request and generation. Survey, inspection and recognition
plans remain plan-only until their production executors exist; the Runner does
not pretend that they executed.

## Planner reliability gate

The first two live one-shot attempts returned text without calling the sole
`submit_plan` tool. They failed closed before SDR ownership. The Planner now
sets OpenAI-compatible `tool_choice` to the named `submit_plan` function for
every planning request. A Node test verifies that the provider payload is
copied, not mutated, and forces only that allowlisted tool.

The first forced proposal used an unsupported sample rate. Rust rejected it
before SDR ownership. The final request specified the exact 2.1 MS/s contract,
and the model submitted one policy-valid proposal. These failures remain useful
audit evidence instead of being hidden by retries.

## Live execution

The successful correlated plan was:

```text
request_id=201
session_generation=21
candidate=development-2442m
center_hz=2442000000
sample_rate_hz=2100000
rf_bandwidth_hz=2000000
samples=4096
approval=operator
```

The result contained 4096 complex-int16 samples, 16,384 bytes, sequence 2,
zero dropped samples and no overflow. The transient IQ SHA-256 was
`5cade2fe66865e41bca967b3a548256c293ba7f3c58a18da9c7632bf8c252b30`.
Post-execution health retained retune and capture capability while FPGA and
recognizer capability stayed false.

The radio restored to 2452 MHz, 2.1 MS/s, 2 MHz bandwidth, `slow_attack` and
scan mask zero. The raw file and all Pi/SDR development directories were
removed.

## Audit and deployment

The retained root-only audit file is:

```text
/var/lib/sdr-agent/audit.jsonl
mode=0600
sha256=8b2b68b79d89c088d013944eb42b471a335183bfcec4cb0b399ccaf452b6ae4a
```

The successful cycle records `input_observation`, `planner_proposal`,
`validated_plan`, `authorized` and `execution_observation`. Rejected planning
attempts also remain in the same append-only file.

The Pi release is `/opt/sdr-agent/releases/20260901-runner-v1`. Final controller
SHA-256 is
`1651a0efb844bbee1cdcd70c6e9830bea3837ffa6a5b8981cb3364bde0cea7dd`.
The independently rebuilt `/opt/sdr-agent/releases/20260901-fpga-sweep-gate-v1`
remains the immediate rollback rather than aliasing the current release.

Temporary paths removed and verified absent:

```text
SDR: /tmp/sdr-agent-dev/agent-21-201/
Pi:  /var/tmp/sdr-agent-dev/runner-v1/
Pi:  /var/tmp/sdr-agent-dev/planner-required-tool-v1/
workstation: detached rollback build worktree
```
