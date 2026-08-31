# Pi ultra-light recognition model training handoff

Date: 2026-09-01

## What is ready

The Pi-side model-package loading interface is complete and fail-closed. It can
validate an exported package but does not yet include ONNX Runtime, create an
inference session, or advertise recognition availability. Training remains on
the 4090 as requested.

Deliver one directory containing exactly:

```text
model.manifest
model.onnx
labels.txt
```

Also retain off-device reference inputs, logits and evaluation reports; they do
not belong in the deployed package unless explicitly added to a test corpus.

## Fixed tensor contract

- input name: `iq`;
- input dtype: float32;
- input shape: `[1, 2, 1024]` for the first model;
- axis 1: planar I then planar Q;
- sample rate: 2,100,000 samples/s;
- preprocessing ID: `planar_f32_unit_rms_v1`;
- output name: `logits`;
- output shape: `[1, class_count]`;
- one inference thread initially;
- fixed shapes only; no dynamic batch or sample axis for version one.

For each complex window, convert I/Q to float32 and divide both planes by one
shared complex RMS value. Use the same epsilon and edge-case handling in
training/export/reference code and record them with the corpus. Do not perform
an undocumented per-plane normalization, random phase correction, frequency
correction or resampling inside the model package.

## Size and model guidance

The loader hard cap is 32 MiB, but the training target should be much smaller:
prefer a model around 1–5 MiB with a fixed 1024-sample window. Start with a
small 1-D depthwise-separable CNN or similarly bounded architecture. Avoid
operators that require custom kernels, dynamic control flow or large temporary
tensors. Quantization is a later measured option; first export a numerically
stable float32 reference.

The label order is the output-logit order. `labels.txt` contains one unique safe
identifier per line and its line count must equal `class_count`. Include an
explicit unknown/noise policy in the dataset and evaluation even if the first
closed-set artifact cannot yet provide calibrated open-set rejection.

## Manifest generation

Copy
[`model.manifest.example`](../raspberry-pi/sdr-agent/recognizer-worker/config/model.manifest.example)
and replace the model ID, exact byte length, SHA-256 hashes and class count.
The loader accepts only `runtime=onnxruntime`, `.onnx`, and the fixed
preprocessing identifier above.

Before handing the package to Pi integration, provide:

- training corpus/version and train/validation/test separation;
- label definitions and unknown/noise handling;
- preprocessing and augmentation implementation;
- source commit, environment lock and random seeds;
- ONNX exporter/opset and graph checker output;
- model and labels SHA-256;
- workstation reference logits for a bounded IQ corpus;
- confusion matrix, total accuracy and per-class recall;
- parameter count, ONNX bytes and estimated multiply-accumulate count.

## What happens when the model arrives

Run `sdr-model-inspect`, pin the ONNX Runtime build, implement the persistent
one-queue Worker behind the existing `Backend` interface, compare Pi logits to
the 4090 reference corpus, then measure p50/p99 latency, RSS, CPU and thermal
behavior. Only after those gates pass may runtime health set
`recognizer_available=true` and feed results into the Runner.
