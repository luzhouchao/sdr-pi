# Local recognizer interface

Date: 2026-08-31; status updated 2026-09-06

> Current status: the backend-neutral Controller seam and an experimental
> CUDA/Mamba Worker are implemented and have passed real P201 RX1 single-window
> and versioned four-window end-to-end captures on AGX. Production admission
> remains disabled pending independent known-RF/OOD calibration, rejection and
> production Worker admission. RF-v1 runtime parity and FP16 selection are complete.

## Implemented boundary

The Rust Controller now has a provider-neutral `LocalRecognizer` interface with
two adapters:

- `ReplayRecognizerAdapter` for deterministic tests and captured-corpus replay;
- `UnixRecognizerAdapter` for a persistent out-of-process inference worker.

The Worker is intentionally marked `experimental_rf_only`; the current AGX
runtime still reports `recognizer_available=false`. The direct live command is
therefore an engineering-validation path, not an autonomous Planner capability
and not evidence that modulation or emitter recognition is production-ready.

## Data path

```text
selected candidate or explicit engineering plan
    -> bounded P201 RX1 inline-IQ capture
    -> AGX validation and experimental normalization
    -> file-backed IQ window in /run/sdr-agent/iq
    -> Rust validates path, range and shape
    -> JSONL metadata over /run/sdr-agent/recognizer.sock
    -> worker maps the bounded IQ range
    -> AGX CUDA/Mamba Worker
    -> bounded labels, confidence, model identity and timing
```

IQ samples are never embedded in JSON and never enter the Planner Worker or
upstream-model context. The v1 model-ready input is little-endian float32 planar
`[I, Q]`, unit-RMS normalized, with a power-of-two length from 256 through
16384 samples per channel. The referenced file range must contain exactly
`2 * samples_per_channel * sizeof(float)` bytes.

The file is canonicalized before the worker is contacted, and the resolved path
is placed in the wire request. It must be a regular file under the configured
spool root, and its aligned byte range must fit in the file. This prevents a
model request from turning the worker into an arbitrary local-file reader. The
selected backend Worker must independently repeat the spool-root, permission,
type and range checks before reading the file. The experimental Python Worker
does so with `lstat`, canonical-root containment, mode/owner checks and
`O_NOFOLLOW` plus inode/device revalidation.

## Legacy seed44 experimental live profile

The bounded profile currently used only for integration testing is exactly
four contiguous, non-overlapping windows of 1,024 complex samples at 2.1 MS/s,
one P201 RX path, planar float32, no DC removal and no resampling. P201
complex-int16 ADC codes must have at least one code RMS and no 12-bit clipping,
then AGX applies per-window complex unit-RMS normalization before creating one
private 32,768-byte spool file. Four requests reference exact 8,192-byte
offsets in that same file; all calls are sequential and the file is removed on
success or failure.

Candidate eligibility is derived from a fresh, fixed-50-dB inspection. Its
center, occupied bandwidth, peak, spectral noise floor and measured SNR come
from the same AGX IQ window. The versioned integration profile and preprocessing
specification are hash-checked before any capture. This removes the earlier
error of combining a new inspection power with an old sweep noise estimate.

This normalization is not the checkpoint's training transform. On the same
8,192 held-out RML rows, raw dataset input achieved `63.5986%`, while unit RMS
achieved `53.2959%`; DC removal was worse. Those are parallel preprocessing
experiments, not accuracy decaying with repeated inference. The transform is
retained only as an explicit bridge from uncalibrated ADC codes to the old
checkpoint. A production model must be retrained or fine-tuned using the frozen
RF transform and then re-evaluated on the complete split.

## RF-v1 epoch-10 runtime extension

The independent `rml2018a-d8-rf-v1.runtime-profile.json` remains
`integration_only`. It pins the epoch-10 checkpoint and the exact frozen
`rf_preprocess_v1` specification. The frozen FP16 candidate and offline
specification remain immutable evidence snapshots.

AGX divides all 4,096 complex samples by one float64 capture RMS, preserves DC,
and emits four ordered planar-float32 windows without digital frequency shift,
filtering or resampling. A silent individual window is permitted if the whole
capture clears the numerical RMS floor; individual window RMS values need not
be one. The full capture's normalized RMS must be within `1e-6` of one.

For this profile, each v1 request must include `rf_v1: RfV1WindowContract` and
`iq.normalization=capture_unit_rms`. The extension joins profile/preprocess/
checkpoint/batch SHA-256, parent batch request, inspection sweep/request/
generation/sequence, capture request/sequence and window index. The Worker
checks all 32,768 spool bytes and their RMS on every call, requires exact
`0,8192,16384,24576` offsets, and rejects missing/reordered/mixed or replayed
windows. Its single active batch has a five-second inter-window expiry.

The response echoes that contract plus request/generation, records
`compute=cuda_fp16_autocast`, and returns 24 complete FP32 logits in numeric
class-ID order. FP32 weights remain resident. The AGX report has `mean_logit`
instead of the legacy `vote`: it averages complete logits in float64 and then
applies a stable softmax. `window_agreement` counts window argmax values equal
to the aggregate argmax. These probabilities are explicitly uncalibrated;
there is no admitted temperature, rejection threshold or field accuracy claim.
Names remain provisional, and `production_recognizer_available=false`.

Use the existing `recognize-batch-live` command with the new runtime profile
and start `amc-mamba-worker.py --rf-v1-profile PATH --max-requests N` with a
positive finite request limit (health requests count). Use one dedicated
private feature spool and socket. The CLI checks free space and records exact
capture bounds and paths before radio work. SIGINT/SIGTERM discards a pending
batch or late Worker reply and cleans the spool after the bounded call;
`--mode cancel --session-generation N` remains the direct in-flight radio stop.
Spool unlink failures are explicit errors. The optional S3 supervised path below
now adds process death/restart cleanup and Worker cancellation. The standalone
extension does not provide them; S5 engineering Runner integration and S4a GPU
serialization are documented below, while production admission remains separate.

See [`RF_V1_RUNTIME_PARITY_VALIDATION_2026-09-05.md`](RF_V1_RUNTIME_PARITY_VALIDATION_2026-09-05.md)
for golden, fault-injection and real RX1 evidence.

## Framing and validation

One Unix-socket connection carries one JSON request and one JSON response, each
terminated by a newline and limited to 16 KiB. The response must echo both
`request_id` and `session_generation`. Unknown fields, stale correlations,
candidate mismatches, duplicate labels, non-finite confidence, invalid model
hashes, excessive thread counts and inconsistent timing all fail closed.

A successful output records:

- primary label and confidence plus at most eight alternatives;
- runtime, runtime version, model ID and model SHA-256;
- runtime thread count;
- file-map, preprocessing, inference and total latency.

The model-specific operators, tensor names and runtime objects remain inside
the worker. CUDA, PyTorch, Triton or TensorRT choices must not change the
Controller interface. A separate process contains model-runtime faults and
memory and allows backend replacement without relinking the Controller.

## Controller smoke command

After a worker and IQ fixture exist, the interface is invoked with:

```bash
sdr-agent-controller \
  --mode recognize \
  --request config/recognition-request.example.json \
  --recognizer-socket /run/sdr-agent/recognizer.sock \
  --recognizer-spool-root /run/sdr-agent/iq \
  --recognizer-timeout-ms 5000
```

The real receive-only engineering path is invoked separately so an arbitrary
file-only request cannot silently acquire hardware:

```bash
sdr-agent-controller \
  --mode recognize-live \
  --request raspberry-pi/sdr-agent/controller/config/live-recognition.experimental.example.json \
  --sdrd 192.168.1.10:43110 \
  --sdrd-timeout-ms 5000 \
  --recognizer-socket /run/sdr-agent/recognizer.sock \
  --recognizer-spool-root /run/sdr-agent/iq \
  --recognizer-timeout-ms 5000
```

The Controller validates and prints the complete plan and exact 4,096-byte
P201/8,192-byte AGX limits before starting the session. An independent
`--mode cancel --session-generation N` connection is the direct stop path.

The newer integration-only path first converts one timestamped inspection
report and updated candidate into a `RecognitionTarget`, then captures and
classifies the four-window batch:

```bash
sdr-agent-controller --mode derive-recognition-target --request target-input.json

sdr-agent-controller \
  --mode recognize-batch-live \
  --recognition-profile jetson-agx/sdrharness/config/amc/rml2018a-d8-current.integration-profile.json \
  --recognition-target target.json \
  --repository-root /home/jetson/sdrharness \
  --request-id 44002 \
  --session-generation 20260904045 \
  --sdrd 192.168.1.10:43110 \
  --recognizer-socket /run/sdr-agent/recognizer.sock \
  --recognizer-spool-root /run/sdr-agent/iq
```

`--recognition-target -` accepts the bounded target on stdin so a fresh target
does not need to be persisted. The result includes every provisional window
output and a clearly named integration-only top-1 majority vote. It always
reports `production_recognizer_available=false`; see
[`P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md`](P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md).

The Worker template is
`jetson-agx/sdrharness/systemd/sdrharness-amc-mamba-experimental.service`; it
has no `[Install]` section and must not be enabled while production admission
is false.

## S1 capability and approval boundary

The Controller and terminal now derive recognition availability from
`RecognizerCapability`, backed by a strict local `RecognizerAdmission` receipt
and a fresh `admission_health` Worker response. Requests and templates cannot
assert availability. The probe verifies nonce/request/generation/time, full
model/profile/preprocess/precision identity and the receipt hash, with bounded
transport and fail-closed restart/receipt-change invalidation. The real RF-v1
Worker and shipped candidate receipt remain production-disabled.

`RunLocalRecognition` requires manual approval in step and cruise; an automatic
request cannot bypass this gate, and terminal approval rechecks capability.
S5 now supplies an explicit engineering executor; admitted production deployment
remains A1. See
[`RECOGNIZER_ADMISSION_S1_VALIDATION_2026-09-06.md`](RECOGNIZER_ADMISSION_S1_VALIDATION_2026-09-06.md)
for the receipt/health schemas, exact verification boundary and live evidence.
S1 is implemented and isolated-Worker validated; replacing deployed Controller/
Web/Planner services and validating admitted positive capability remain A1.

## S2 full result and compact observation

RF-v1 `recognize-batch-live` now emits `RecognitionResult` schema v1. Its
`experimental_batch` preserves the former full report; `experimental_prediction`
and `uncalibrated_probability` explicitly identify internal experiment output.
Its separate `observation` is always `unavailable` with
`reason=production_admission_missing` for this candidate, never production
`classified`. Numeric IDs remain authoritative and text names provisional.
Legacy seed44 and the per-window Worker wire contract are unchanged.

`RecognitionObservation` replaces the three-field Planner recognition summary.
It represents classified/rejected/unavailable/error with explicit calibration
status, decision/name evidence references, request/session/source correlation,
model/profile/preprocess identity, bounded quality and component timing. Only
this allowlisted summary enters PlanningContext; IQ paths/tensors/full logits
and experimental predictions cannot enter it. Both Rust and Node validate its
state semantics and freshness. Full imports are limited to 64 KiB, observations
to 4 KiB, and nested unknown fields fail closed. Production decisions cannot be
imported under the current candidate profile. Frozen reference verification and
scientific threshold selection remain later admission work.

See [`RECOGNITION_RESULT_S2_VALIDATION_2026-09-06.md`](RECOGNITION_RESULT_S2_VALIDATION_2026-09-06.md)
for field semantics, compatibility changes and replay/negative-test evidence.
S2 does not deploy services, execute the production Runner, or implement result
storage/UI. Old nonempty three-field Planner recognition objects are rejected;
both protocol sides must be deployed together at A1.

## S3 supervised whole-batch lifecycle

The optional supervised engineering path now owns one active four-window batch
and one waiting slot, a monotonic whole-batch deadline, reserved control socket,
confirmed queued/active cancellation, child/supervisor restart fencing and
verified transient-file cleanup. It wraps the unchanged frozen RF-v1 Worker;
production capability stays false. The Rust Adapter and receive-free replay/
health/cancel commands passed finite actual AGX Worker fault validation.

See [`WORKER_SUPERVISOR_S3_INTERFACE.md`](WORKER_SUPERVISOR_S3_INTERFACE.md) and
[`WORKER_SUPERVISOR_S3_VALIDATION_2026-09-06.md`](WORKER_SUPERVISOR_S3_VALIDATION_2026-09-06.md).
The earlier standalone per-window command remains experimental. Supervised
callers use `--recognizer-supervisor-root`; they do not bypass the supervisor's
private child socket. The optional S4a shared gate is documented below; installed
services and sustained thermal acceptance remain separate work. S5 now supplies
engineering Runner execution and joined SDR/Worker `/stop`.

## S4a shared GPU lease

The S3 supervisor can now take `--gpu-lease-root` to share one inherited
cross-process inference lock with the owned Spark candidate gateway. Startup and
entire four-window inference are serialized; cancellation/failure reaps the real
model child before release, and parent-death fencing prevents early unlock.
Actual Node Spark → native Mamba → Spark and both-side cancellation/SIGKILL
recovery passed isolated AGX validation. This remains a candidate source path,
with recognition unavailable and installed services unchanged. See
[`GPU_LEASE_S4A_INTERFACE.md`](GPU_LEASE_S4A_INTERFACE.md) and
[`GPU_LEASE_S4A_VALIDATION_2026-09-06.md`](GPU_LEASE_S4A_VALIDATION_2026-09-06.md).

## S6a application recognition archive

S6a now persists full bounded S2 records in the existing application SQLite
file and exposes validated compact archive views in Web and a local terminal
client. Replay and inert synthetic demos are explicitly nonproduction; current
candidate classified/rejected production imports are rejected. Restart restore,
conflict/idempotence, manual deletion and actual browser validation passed,
without IQ retention or Planner context injection. See
[`RECOGNITION_ARCHIVE_S6A_INTERFACE.md`](RECOGNITION_ARCHIVE_S6A_INTERFACE.md) and
[`RECOGNITION_ARCHIVE_S6A_VALIDATION_2026-09-06.md`](RECOGNITION_ARCHIVE_S6A_VALIDATION_2026-09-06.md).
S5 now provides live engineering Runner persistence. Browser closed-loop acceptance
remains S6b.

## Remaining delivery work

Current completion status is maintained in
[`SDR_AGENT_PROJECT_CHECKLIST.md`](SDR_AGENT_PROJECT_CHECKLIST.md), and execution
order in
[`SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md`](SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md).
This interface document does not maintain a separate next-step plan.

## Existing package-validation seam

The C++ module has a `ModelPackageLoader` interface with filesystem and
replay Adapters. Loading returns canonical model/label paths plus validated
metadata; it deliberately does not construct an inference session. The
filesystem implementation requires direct child files under one package root,
rejects symlinks and traversal, caps the model at 32 MiB, checks exact byte
length and streaming SHA-256, and validates label count and uniqueness.

The version-one manifest is strict `key=value` text with no unknown or duplicate
keys. The production CUDA/Mamba package contract may replace its old
ONNX-specific fields while preserving the Rust request/result boundary.

## S5 engineering integration

The explicit engineering Runner now integrates S3/S4a/S6a, with operator approval,
cruise budgets, joined cancellation and one automatic compact Spark feedback turn.
Source tests, bounded real RX/Worker/Spark validation and exact cleanup passed,
without enabling production capability or replacing installed services. See
[interface](RUNNER_RECOGNITION_S5_INTERFACE.md) and
[validation](RUNNER_RECOGNITION_S5_VALIDATION_2026-09-06.md).
