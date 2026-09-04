# Local recognizer interface

Date: 2026-08-31; status updated 2026-09-04

> Current status: the backend-neutral Controller seam is implemented on AGX.
> Selected D8 checkpoints and complete offline FP32 corpus validation now pass;
> the production CUDA/Mamba Adapter is not yet integrated.

## Implemented boundary

The Rust Controller now has a provider-neutral `LocalRecognizer` interface with
two adapters:

- `ReplayRecognizerAdapter` for deterministic tests and captured-corpus replay;
- `UnixRecognizerAdapter` for a persistent out-of-process inference worker.

The current AGX deployment does not include a production recognizer worker, so
it reports `recognizer_available=false`. This interface establishes the input,
result, correlation and containment rules without claiming that modulation or
emitter recognition is operational.

## Data path

```text
triggered candidate
    -> bounded DDC/resample/normalization
    -> file-backed IQ window in /run/sdr-agent/iq
    -> Rust validates path, range and shape
    -> JSONL metadata over /run/sdr-agent/recognizer.sock
    -> worker maps the bounded IQ range
    -> AGX CUDA/Mamba backend Adapter
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
C++ worker must independently repeat the spool-root and range checks before
mapping the file.

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

## Next admission slice

The selected checkpoint, pinned source and offline corpus are now available and
their FP32 numerical comparison, confusion matrix, p50/p99 latency, GPU memory,
RSS, CPU and short-run thermal measurements pass. The next implementation must
resolve trusted RML labels, RF preprocessing/sample-rate policy, low-precision
and rejection thresholds, then build a bounded queue of one and validate drop,
cancellation, concurrency and sustained thermal behavior before setting
`recognizer_available=true`.

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
