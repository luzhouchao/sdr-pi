# Recognizer admission and approval gate (S1) — 2026-09-06

## Delivery boundary

S1 implements the capability source and manual-approval boundary in the
Controller, one-shot Runner and interactive terminal, with real AGX Worker
health validation. The shipped epoch-10 receipt remains a **candidate** and
actual `recognizer_available` remains false. This is a software delivery and
isolated Worker validation; the installed Planner/Web/Controller services were
not replaced. Production deployment and positive admitted capability remain A1.

No P201 connection, RX capture, dataset access, locked test, training or complete
precision comparison was performed. The real model was loaded only for bounded
Worker startup/warm-up and health queries. Existing FP16/preprocess/checkpoint
selection evidence was reused without changing its frozen files.

## Capability and receipt contract

The new backend-neutral `RecognizerCapability` interface supplies fresh
`RecognizerCapabilityObservation` values. Missing implementations default to
`UnavailableRecognizer`, so raw request/template booleans confer no capability.
`Controller.decide`, `Runner.run_once`, raw CLI `execute`, terminal prompt and
queued input, returned proposals, feedback observations and recognition approval
all use the responsible probe. Runner audit adds correlated
`recognizer_admission` events with availability and a bounded reason.

`recognizer_admission_v1` is a strict, bounded local validation receipt with an
admission ID, `candidate`/`admitted` status, model/profile/preprocess/precision/
shape/aggregation identity and gate evidence references. The shipped candidate
has no evidence references. An `admitted` receipt must contain exactly one
reference for each of these gates:

- `input_profile`;
- `calibration`;
- `known_rf_ood`;
- `locked_test`;
- `worker_runtime`;
- `deployment`.

Each reference must resolve beneath the receipt directory and match SHA-256.
Each referenced `recognizer_admission_evidence_v1` record must identify the same
admission, gate and full model identity, report `outcome=pass`, and reference an
existing hash-matched underlying report. Receipts and gate records are capped at
16 KiB, and each underlying report at 1 MiB. Nonregular, final-component symlink,
empty, oversized or group/world-writable files fail closed. Use mode 0644 or
0600 for non-secret receipt/report files; never weaken this check to make an
unreviewed receipt load.

These are **local approval receipts issued by the responsible validation and
release workflow**, not cryptographic attestations of scientific correctness.
The loader verifies receipt integrity and completeness; the actual calibration,
known-RF/OOD, locked-test and Worker acceptance criteria belong to S2–S4/V1–V3/A1.
No passing production gate receipt is shipped or manufactured by S1. Merely
editing a status or collecting file hashes does not make the real Worker
production-ready.

## Fresh Worker health

The Worker retains its legacy experimental `health` operation and adds
`admission_health`. Its request carries protocol version, request ID, Controller
generation and a fresh 256-bit challenge. The strict `recognizer_health_v1`
response echoes all correlation fields and includes:

- per-process random Worker instance ID and start/observation timestamps;
- ready/busy state and loaded full RF-v1 identity;
- the exact admission-receipt SHA-256;
- Worker-controlled `production_enabled` (always false in this candidate).

The Unix Adapter uses a nonblocking bounded connection, a 250-ms monotonic
socket-exchange deadline and a 16-KiB frame bound. A full listen backlog,
truncated/oversized/malformed/duplicate-key response, stale/future timestamp,
wrong nonce/request/generation, wrong asset/precision/receipt hash, unavailable
Worker or missing evidence all yield false. No failed probe reuses a prior
successful availability result.

The first verified Worker instance and receipt are pinned to the Controller
generation. Worker restart or changed receipt invalidates that generation;
repeated queries cannot silently re-enable it. A new generation requires a new
probe, and going back to an older generation fails. An admitted receipt only
permits availability when the independently queried Worker also reports the
same admitted identity, production readiness and ready state.

The current Python Worker hash-pins the new candidate receipt and checks its
checkpoint/profile/preprocess against the strictly loaded model. Unknown
request keys such as `production_enabled` are rejected. Legacy backends report
no matching admission identity through this operation and cannot qualify.

The diagnostic command is receive-free:

```text
sdr-agent-controller --mode recognizer-health
  --recognizer-socket /path/to/private/worker.sock
  --recognizer-admission /path/to/receipt.json
  --request-id 71001 --session-generation 20260905071
```

Both Controller and terminal accept the socket/receipt options. The AGX default
receipt is `jetson-agx/sdrharness/config/amc/rf-v1-recognizer-admission.candidate.json`
under the fixed `/home/jetson/sdrharness` repository. An unavailable receipt or
Worker disables recognition while other valid actions remain available.

## Approval behavior

`RunLocalRecognition` now requires operator approval after capability and
candidate checks. Step mode holds the plan pending approval; active automatic
cruise stops with `ApprovalRequired`. One-shot automatic authorization also
fails before the unsupported-executor path can hide the approval requirement.
Terminal approval rechecks the current Worker and generation.

S5 has not supplied the production recognition executor yet. Therefore even a
synthetic admitted/approved test plan remains `planned_only`/unexecuted; tests
do not claim hardware or production inference happened. The real candidate
cannot reach an accepted production recognition plan at all.

## Verification

Final source passed 86 Rust library tests, 13 terminal tests, seven RF-v1 Python
runtime tests and three legacy Worker Python tests. Formatting, Clippy with
warnings denied and diff whitespace checks passed. Tests exercise all capability
failures above, six-gate evidence completeness/content tampering, fake admitted
positive control, source boolean forgery, invalidation while Planner work is in
flight, step/cruise approval, approval revocation and default-unavailable plain
Controller behavior. Positive controls use only explicitly synthetic receipts,
reports and Worker replies; they never load actual locked-test data.

Initial test-fixture failures were corrected: files created under the host's
shared-group umask needed explicit private permissions; audit tests needed to
account for new admission events; a terminal fixture's old over-wide span was
made valid before exercising `submit`. Fake Worker listeners now have bounded
accept deadlines so a failed client assertion cannot leave a hanging test.

The final real-Worker run and artifact hashes are retained in
[`RECOGNIZER_ADMISSION_S1_AUDIT_2026-09-06.json`](RECOGNIZER_ADMISSION_S1_AUDIT_2026-09-06.json).
It verifies absent → candidate Worker → absent behavior, correct full identities
and challenge echo, two distinct actual Worker instances, rejection of a forged
status-only receipt and of a request trying to supply `production_enabled`.
Every real capability observation is false with an explicit reason. Both finite
Workers exit, remove their sockets, and leave empty spools. A preliminary run
preceded the final receipt-change/old-generation invalidation review; the final
artifact was rebuilt and the bounded health run repeated after those changes.

## Cleanup and next unit

The audit records exact process and directory cleanup for
`/var/tmp/sdrharness-dev/s1-905a` (build/tests/preliminary validation) and
`/var/tmp/sdrharness-dev/s1-906b` (final live validation). All generated binaries,
synthetic reports, socket fixtures and Worker logs are development data and are
removed after retaining the bounded summary. No SDR-local directory was created.
Model assets, runtime cache and application-owned results remain intact.

The next software unit is **S2: unified recognition result/observation contract**.
Production lifecycle, shared GPU scheduling, independent known-RF/OOD evidence,
calibration/rejection, locked test and deployment remain incomplete. S1 does
not enable a production Recognizer or substitute for those gates.
