# S2 recognition result and Planner observation — 2026-09-06

S2 is a source/interface delivery, verified by deterministic batch replay and
conversion of the retained real RF-v1 four-window report. It does not replace
installed services, run the production recognition executor, save application
results, or validate a new live capture. Those remain S5/S6/A1. The actual
candidate stays unavailable; no temperature, rejection threshold, label mapping
or admission asset changed. No model, dataset, locked test or radio was opened.

## Audit and resulting contract

Before S2, `protocol::RecognitionSummary` contained only candidate/label/
confidence. Rust policy and the Node Planner parser accepted that same shape.
`recognizer::RecognitionOutput` is a per-window Worker transport object: its
`ok` status only means inference succeeded. The batch engine already validated
ordered RF-v1 lineage and computed float64 mean logits plus uncalibrated softmax.
Neither transport success nor the batch's integration-only result was a
production class decision. Runner feedback/execution and user result storage
were not implemented and are not claimed here.

`recognition_result.rs` now defines strict schema-version-1 contracts:

- `RecognitionResult`: full internal record, capped at 64 KiB when imported.
  It retains the complete existing experimental batch, capture/window quality,
  Worker backend/timing, logits, aggregate probabilities and hashes. An explicit
  `experimental_prediction` carries the trusted numeric ID with provisional name
  status; epoch-10 provides no text name, so `name=null`. Its probability is
  explicitly named `uncalibrated_probability`.
- `RecognitionObservation`: at most 4 KiB; the only recognition type allowed in
  PlanningContext (`RecognitionSummary` remains a Rust source alias). It includes
  request/session/candidate/time, optional source inspection and capture IDs/
  sequences, model/profile/preprocess IDs and hashes, compute/aggregation,
  four-window agreement and quality flags, and measured timing. It has no path,
  tensor, full logits, per-window result or experimental prediction field.
- `ResultReference`: bounded ID plus SHA-256, never a local path. Decision
  references separately identify calibration, rejection and admission; verified
  names additionally require name evidence. The enclosing result identifies the
  model/profile/preprocess to which these references apply. S2 checks structure
  and correlation, not the scientific content of these future evidence objects.
  The production executor must resolve and verify them against the admitted
  identity before issuing a decision; no passing evidence is created by S2.

| Status | Required interpretation |
| --- | --- |
| `classified` | Accepted model decision, numeric class 0–23, calibrated confidence, frozen calibration/rejection/admission references, healthy quality and full result identity. Not ground truth. |
| `rejected` | No accepted class; bounded reason code and frozen decision references, identity and measured quality/timing. |
| `unavailable` | Production recognition unavailable; no accepted class, calibrated confidence or frozen decision reference. A completed uncalibrated experiment uses `production_admission_missing`. |
| `error` | Execution failed; bounded reason code, no accepted class or calibrated confidence. Missing measurements stay null. |

Calibration status is explicit: `uncalibrated`, `frozen` or `unavailable`.
A frozen status and complete decision references must occur together. Text-name
status is `provisional`, `verified` or `unavailable`; verified text requires a
reference. Numeric ID is always the authoritative model class identity, not
proof of the signal's independently labeled class. Future noise/OOD/quality
reasons are codes, not a new forced class. Reason/reference identifiers are
bounded tokens and cannot carry worker error messages, local paths or prompts.

The full-record validator rejects production decisions under the currently
loaded integration-only profile, even if a caller supplies syntactically valid
frozen references. Four-state positive controls exercise only synthetic
observation structure; they do not admit or run a production classifier.

## Conversion and Planner boundary

`RecognitionResult::from_experimental_batch` accepts only the hash-checked RF-v1
profile and completed, cleaned integration batch. It rechecks profile/preprocess/
checkpoint, fixed RX1 capture, exact four windows and offsets, ordered request
IDs, source/capture correlations, finite quality and shared RMS, backend identity,
FP16/full-logit shape, per-window top-1 and alternative probabilities, and timing.
It recomputes the complete mean-logit aggregate; altered probabilities, class ID
or agreement fail closed. Float64 JSON round-trip parsing preserves the exact
retained aggregate for revalidation. Imported records have a byte limit and typed
unknown/duplicate-field rejection; stored summaries are rederived before Planner
projection. This validates consistency of retained metadata, not a new IQ hash
verification after transient IQ has already been deleted.

The existing RF-v1 `recognize-batch-live` CLI now emits this full record, with the
old report under `experimental_batch`. Legacy seed44 retains its existing output.
External engineering consumers of RF-v1 top-level `batch/windows/mean_logit` must
read them under `experimental_batch`; the Worker wire protocol remains unchanged.
`planner_observation()` validates the full record and returns only the separate
summary. There is no automatic Runner dispatch or Spark turn in S2.

The result timestamp is observation completion time, not the inspection capture
time. Stored/replayed observations retain their historical session identity;
callers must not retag them as a fresh live session. Inspection and recognition
can legitimately have different generations (the retained real report does).
Every window must echo the actual inspection lineage and current recognition
request/generation. Rust policy and Node independently require the recognition
result's generation to match PlanningContext, a current candidate, and a
nonfuture timestamp within the configured observation age. Node's nested
allowlists reject internal result fields. The overall Planner frame remains
32 KiB; oversized combinations fail closed. Old nonempty three-field recognition
summaries fail validation rather than being silently upgraded. Empty/absent
recognition contexts remain compatible; deploy both protocol sides together at A1.

Timing distinguishes SDR capture elapsed time, sum of four Worker total times,
and sum of four inference times. These are measured component times, not a new
end-to-end latency claim; scheduling/queue/aggregation wall-time metrics remain
S3/S4/S5. Full capture/window metadata retains gain, RMS, DC, rate and bandwidth;
the Planner quality summary retains only four-window agreement and capture
health/drop/overflow/clipping flags, without interpreting them as field accuracy.

## Verification

Final verification: 88 Rust library tests, 13 terminal tests and 52 Node
Planner/session tests pass. Rust formatting, all-target Clippy with warnings
denied, and Git whitespace checks pass. The existing successful replay batch
now exercises conversion, round-trip import, Planner projection, four-state
semantics and 23 batch mutation cases. Additional checks cover stale/future
observations, mismatched candidate/generation, oversized/truncated/unknown/
duplicate JSON, name-trust escalation, malformed numeric classes/confidence,
uncalibrated-to-classified forgery and internal-field leakage. The Rust policy
and Node parser both exercise rejection at their actual PlanningContext boundary.

The retained real report at `cases[0].report` in
[`RF_V1_RUNTIME_PARITY_AUDIT_2026-09-05.json`](RF_V1_RUNTIME_PARITY_AUDIT_2026-09-05.json)
converts and round-trips through the same validator. This is replay of existing
live evidence, not a new live Worker/capture test. Frozen epoch-10/FP16/RF-v1
assets and the scientific limitations remain unchanged.

During development, the initial long temporary root exceeded an existing Unix
socket test's pathname limit. The root was renamed to the exact shorter feature
path below. Round-trip tests exposed the need for serde_json `float_roundtrip`.
The retained live fixture also corrected an overstrict assumption that inspection
and recognition must share a generation; their individual correlated identities
are preserved instead. Projection tests check forbidden JSON keys, so legitimate
model IDs/aggregation method strings are not mistaken for internal data fields.

## Cleanup

Builds, synthetic IQ/socket fixtures and test logs were confined to the unique
feature root `/var/tmp/sdrharness-dev/s2-906c/` (initially
`/var/tmp/sdrharness-dev/s2-20260906-result/`, renamed, not duplicated).
The final cleanup record is in
[`RECOGNITION_RESULT_S2_AUDIT_2026-09-06.json`](RECOGNITION_RESULT_S2_AUDIT_2026-09-06.json).
Both exact paths are verified absent after completion; all feature test processes
have exited. No SDR-local files, training assets, application results or installed
services were modified. No workstation staging artifact is retained.
