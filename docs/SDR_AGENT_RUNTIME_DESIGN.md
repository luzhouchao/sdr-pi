# SDR Agent runtime design

Last reviewed: 2026-09-04

## Current decision

Jetson AGX Orin is the primary Agent, control, aggregation, result-storage and
model host. P201 Linux owns one bounded receive path through `sdrd`; it does not
aggregate results. The Raspberry Pi deployment remains a rollback baseline.

```text
operator / trusted-LAN Web
             |
             v
AGX Rust Controller <----> AGX Pi Agent Planner Worker
       |                         |
       |                         +--> local Spark-X2.5-4B BF16 [default]
       |                         +--> OpenAI-compatible API [explicit selection]
       |
       +--> result store / optional per-scan SigMF
       +--> production-disabled bounded CUDA/Mamba recognizer
       |
       v
SDRD/1 --> P201 sdrd --> Linux/IIO RX
```

Pi Agent is the Planner framework, not the hardware authority. The Planner sees
only bounded observations and one structured `submit_plan` tool. It has no
shell, filesystem, SSH, SDR or IIO access. Rust validates every proposed action
against live capabilities and numeric limits before approval or execution.

## Runtime seams

### Controller and policy

The Controller owns state, request/session correlation, freshness checks,
limits, approval classification, cancellation and audit. Invalid, stale,
oversized or unsupported proposals fail closed.

```text
decide(PlanRequest) -> ValidatedPlan | ControllerError
```

### Planner

One-shot `planner.sock` is the stateless fallback. Its Runner performs live
observe, model proposal, Rust validation, approval, bounded-IQ execution or AGX
software `survey_band`/`inspect_candidate` aggregation, restored-health
observation and correlated JSONL audit. Persistent `session.sock` supports
interactive prompt, steering, follow-up, abort and model events while sharing
one global inference lease. Provider details, model-specific payloads,
reasoning deltas and the bounded Spark search adapter remain behind this seam.
The terminal reads stdin on a separate bounded four-line queue while model
events stream. Prompt, steer, follow-up and abort acknowledgements are
correlated asynchronously; `/stop` has an independent priority path and
invalidates queued or late old-generation work.
The Runner records initial SDR observation failures before returning, permits a
bounded 1–5,000-ms per-sweep-point timeout (250 ms by default), preserves real
Adapter timeout/health metadata, and never emits a successful new observation
after a partial or stale result.  The P201 daemon suppresses socket `SIGPIPE` so
a client transport timeout closes and restores only that ownership session; it
does not terminate the sole daemon.
Direct terminals also persist at most 32 normalized conversation entries in an
atomic owner-only file. A restart carries only a bounded unprivileged summary
into the next request; plans, approvals, queues, actions and generations are
never serialized. Web children disable this terminal store because Web retains
its own isolated bounded conversation state.

The Web-managed provider configuration supports OpenAI-compatible Completions
and Responses, an 8,192–1,000,000-token context window and automatic compaction
at 50–95% (90% by default). The current saved deployment selects the local BF16
Spark loopback endpoint. The remote API seam remains available for an explicit
operator change that takes effect on a new conversation; the system does not
automatically send a local request or observation to an upstream service after
a failure. The fixed system prompt is never exposed in the Web UI. Real
upstream reasoning is collapsed by default and omitted when absent.

### SDR observation and execution

```text
SdrEngine.observe() -> SdrSnapshot
SdrActionExecutor.execute(ValidatedSdrAction) -> ExecutionObservation
SweepEngine.run(SweepPlan) -> SweepReport
```

The Controller uses SDRD/1 for read-only health, bounded retune/capture, direct
cancel and verified restoration. P201 acquires and transports finite RX data;
AGX computes power, clipping, noise and merged candidates. There is no active
FPGA/MMIO backend. Protocol-v1 FPGA response fields remain constant false/zero
only so older deployed clients can parse the wire response.

The current `enabled_channels=1` profile proves one software RX0 complex path
through IIO `voltage0,1`; it does not identify a front-panel connector. Before
production recognition, SDRD/1 must probe and fail closed on the fixed
`RX1 / A_BALANCED` physical-input identity and include it in profile/capture or
health audit plus end-of-session unchanged validation. It remains a fixed
Adapter capability, not a Planner-selected or Planner-written RF port.

### Results

The AGX result store currently keeps processed sweep points and candidates in
SQLite. When the operator enables raw-IQ retention, one scan writes one SigMF
metadata/data pair under the managed capture root. The Web aggregate view
displays stored traces and provides an indexed manual-delete path. Bounded
recognition-record persistence and its per-record manual-delete path remain a
Chapter 1 integration item; current experimental recognition output is not a
production stored-result capability.

### Recognition

```text
LocalRecognizer.classify(BoundedIqRef) -> RecognitionOutput
```

The backend-neutral Unix-socket and replay Adapters are implemented. A bounded
experimental `P201 RX1 -> AGX preprocess -> CUDA/Mamba` path has been validated
through the standalone `recognize-live` engine, including private spool cleanup
and radio restoration. It is not connected to the one-shot or interactive
Runner, has no production rejection/profile admission, and therefore keeps
`recognizer_available=false`. IQ remains outside Planner JSON and must be a
bounded, canonical file reference under the configured spool root.

Spark-X2.5-4B is the local receive Planner, while Mamba is the signal
classifier. Both use AGX CUDA. Their normal data dependency is already serial:
a Spark planning turn completes before Mamba classification, whose compact
result is required before the next Spark turn. Both models may remain resident
throughout. A bounded deliberate-overlap test reached 99% GPU utilization and
approximately halved both throughputs without OOM, so production must enforce
the serial invariant rather than depend only on expected call order. Sustained
queue, cancellation and thermal validation remains incomplete; see
[`AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md`](AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md).

## Ownership and concurrency

- The deployment has one trusted human operator. It does not expose separate
  user identities, authorization domains or concurrent human control paths.
- Exactly one interactive Controller owns `session.sock`; a second connection
  is rejected as busy. Web retains at most two bounded conversation histories
  for the same operator, runs only the selected conversation, and rejects
  commands addressed to an inactive conversation.
- One active inference lease serializes one-shot and interactive model runs.
- The current lease covers Planner inference only. Production recognition must
  extend it, or add an equivalent shared AGX GPU gate, before Mamba capability
  can become available. This gate protects cancellation, late-result and
  concurrent-input races; it does not unload either resident model.
- One receive owner is allowed.  The legacy Spectrum Web, predictor and
  reboot-resume user units were disabled during the 2026-09-03 cutover; the AGX
  Harness is the only enabled receive control path.  Any rollback must stop
  Harness acquisition before re-enabling a legacy direct-IIOD collector.
- `/stop` cancels the model and active SDR action without waiting for another
  model turn, then advances session generation so stale plans cannot execute.
- P201 restores LO, sample rate, RF bandwidth, gain mode and channel enables on
  success, error, cancellation and disconnect.

## Failure behavior

- Planner unavailable, busy, timed out, malformed or missing an action: execute
  nothing.
- Response ID or session generation mismatch: reject as stale.
- Missing/old observation or unavailable live capability: require `hold`.
- Invalid frequency, rate, bandwidth, dwell, samples or byte count: reject.
- Bounded IQ above the automatic threshold: require explicit approval.
- Storage without an exact finite bound or successful AGX free-space check:
  reject before acquisition.
- Recognition backend absent or unvalidated: keep its capability false.

## Configuration boundaries

Non-secret runtime templates live under `jetson-agx/sdrharness/`. Provider keys,
SSH credentials, model weights, runtime state, result databases and captures
remain outside Git with restrictive permissions. New conversations reload the
saved provider settings; an active conversation retains the provider snapshot
with which it started.

The Web service is intentionally bound to trusted-LAN interfaces and has no
application authentication. It must not be port-forwarded to the Internet.
Authoritative implementation status and remaining work are in
[`SDR_AGENT_PROJECT_CHECKLIST.md`](SDR_AGENT_PROJECT_CHECKLIST.md); the concise
Chapter 1–6 plan is
[`CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md).
