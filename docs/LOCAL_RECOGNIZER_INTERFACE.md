# Local recognizer interface

Date: 2026-08-31

## Implemented boundary

The Rust Controller now has a provider-neutral `LocalRecognizer` interface with
two adapters:

- `ReplayRecognizerAdapter` for deterministic tests and captured-corpus replay;
- `UnixRecognizerAdapter` for a future persistent C++ inference worker.

The current Pi deployment does not include a model or recognizer worker, so it
must continue to report `recognizer_available=false`. This slice establishes
the input, result, correlation and containment rules without claiming that
modulation or emitter recognition is operational.

## Data path

```text
triggered candidate
    -> bounded DDC/resample/normalization
    -> file-backed IQ window in /run/sdr-agent/iq
    -> Rust validates path, range and shape
    -> JSONL metadata over /run/sdr-agent/recognizer.sock
    -> C++ worker mmaps the IQ range
    -> ONNX Runtime CPU or ncnn CPU backend
    -> bounded labels, confidence, model identity and timing
```

IQ samples are never embedded in JSON and never enter the Planner Worker or
Qwen context. The v1 model-ready input is little-endian float32 planar
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
the C++ worker. Changing from the ONNX Runtime reference backend to ncnn must
not change the Controller interface. A separate process was selected for the
first production implementation so model-runtime faults and memory can be
contained and the backend can be replaced without relinking the Controller.

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

The next implementation needs a pinned ONNX model and an offline IQ corpus.
The C++ worker should start with one inference thread and a bounded queue of
one, then pass numerical comparison, confusion-matrix, replay throughput,
p50/p99 latency, RSS, CPU and 30-minute thermal gates before its health can set
`recognizer_available=true`.

## Implemented model-package loader

The Pi C++ module now has a `ModelPackageLoader` interface with filesystem and
replay Adapters. Loading returns canonical model/label paths plus validated
metadata; it deliberately does not construct an inference session. The
filesystem implementation requires direct child files under one package root,
rejects symlinks and traversal, caps the model at 32 MiB, checks exact byte
length and streaming SHA-256, and validates label count and uniqueness.

The version-one manifest is strict `key=value` text with no unknown or duplicate
keys. It fixes ONNX Runtime, `planar_f32_unit_rms_v1`, tensor names, sample
count/rate, class count and thread limit. This means a model trained on the 4090
can be admitted without changing the Rust Controller or filesystem interface.
