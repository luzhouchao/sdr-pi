# Local recognizer interface

Date: 2026-08-31; status updated 2026-09-04

> Current status: the backend-neutral Controller seam and an experimental
> CUDA/Mamba Worker are implemented and have passed one real P201 RX1 end-to-end
> capture on AGX. Production admission remains disabled because trusted labels,
> RF preprocessing, precision and rejection gates are not complete.

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

## Experimental RML2018A live profile

The bounded profile currently used only for integration testing is exactly
1,024 complex samples at 2.1 MS/s, one P201 RX path, planar float32, no DC
removal and no resampling. P201 complex-int16 ADC codes must have at least one
code RMS and no 12-bit clipping, then AGX applies per-window complex unit-RMS
normalization before creating the private 8,192-byte spool file.

This normalization is not the checkpoint's training transform. On the same
8,192 held-out RML rows, raw dataset input achieved `63.5986%`, while unit RMS
achieved `53.2959%`; DC removal was worse. Those are parallel preprocessing
experiments, not accuracy decaying with repeated inference. The transform is
retained only as an explicit bridge from uncalibrated ADC codes to the old
checkpoint. A production model must be retrained or fine-tuned using the frozen
RF transform and then re-evaluated on the complete split.

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
The Worker template is
`jetson-agx/sdrharness/systemd/sdrharness-amc-mamba-experimental.service`; it
has no `[Install]` section and must not be enabled while production admission
is false.

## Next admission slice

The selected checkpoint, pinned source, offline corpus and experimental
P201-to-Worker path are now available. The next admission work must resolve
trusted RML labels, retrain or fine-tune against a frozen RF preprocessing and
sample-rate policy, choose low precision if appropriate, define rejection, and
validate queue drops, cancellation, concurrency and sustained thermal behavior
before installing a production Worker or setting `recognizer_available=true`.
The field ownership and ordered Chapter 4-to-6 delivery gates are maintained in
[`CHAPTER_4_6_INTEGRATION_PLAN.md`](CHAPTER_4_6_INTEGRATION_PLAN.md).

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
