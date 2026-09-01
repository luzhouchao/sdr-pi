# Pi ultra-light recognition model training handoff

Date: 2026-09-01

## What is ready

The Pi-side model-package loading interface is complete and fail-closed. It can
validate an exported package but does not yet include ONNX Runtime, create an
inference session, or advertise recognition availability. Training remains on
the 4090 as requested.

## Version-one datasets

Use only these two source corpora for the first model:

- `HisarMod2019.01`;
- `RadioML2018.01A`.

Do not add a RadioML 2016 corpus to version one. Implement one explicit dataset
Adapter per corpus and make each Adapter report the observed source shape,
dtype, class vocabulary, SNR vocabulary and sample count before training. Do
not silently reshape, concatenate independent examples, repeat samples or infer
an absolute sample rate from normalized simulated baseband data.

The first label vocabulary is the intersection of modulation classes whose
semantics match exactly across both corpora. Preserve the raw-to-canonical label
mapping in the training report. Balance batches across source corpus, canonical
class and SNR bucket so that the model cannot use corpus identity as a shortcut
for a label. Split train, validation and test sets by the strongest available
generation-group identity before sampling windows; a random row split alone is
not accepted when related examples can cross the split.

Both Adapters must produce one contiguous complex window as planar float32
`[2, 1024]`. If an inspected source example is not a genuine contiguous 1024
sample window, stop and report the mismatch instead of padding, repeating or
joining unrelated rows. RadioML/HisarMod accuracy is a simulation benchmark,
not proof of operation at the project's physical 2.1 MS/s input. Retain an
Adapter for a later P201 capture corpus and report that corpus separately as
the real-radio domain test.

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

## Task text for the 4090 Codex

The following is the executable handoff, not optional guidance:

1. Audit `HisarMod2019.01` and `RadioML2018.01A`; emit a machine-readable report
   of their actual tensor shapes, dtypes, labels, SNRs, counts and source hashes.
2. Implement separate source Adapters that return planar float32 `[2, 1024]`
   contiguous IQ windows and provenance. Fail on incompatible samples.
3. Build a versioned canonical label map from only the exact semantic class
   intersection. Balance source, class and SNR and use leakage-resistant grouped
   train/validation/test splits.
4. Train a 100k--500k parameter 1-D CNN or depthwise-separable CNN. Record seeds,
   environment, commit, parameter count, MAC estimate, training curves and
   per-SNR metrics. Prefer the smallest model within two percentage points of
   the best validation macro recall.
5. Export fixed-shape float32 ONNX with input `iq` `[1,2,1024]` and output
   `logits` `[1,class_count]`. Run ONNX checker and compare PyTorch/ONNX Runtime
   logits on a bounded reference corpus with maximum absolute error reported.
6. Deliver `model.onnx`, `labels.txt`, `model.manifest`, source audit, canonical
   label map, split manifest, confusion matrices, per-class/per-SNR recall,
   reference IQ windows plus logits, and SHA-256 for every deliverable.
7. Do not claim 2.1 MS/s real-radio readiness from simulated datasets. Leave a
   documented P201 fine-tune/domain-test entry point and report any missing real
   capture data as the remaining limitation.

## What happens when the model arrives

Run `sdr-model-inspect`, pin the ONNX Runtime build, implement the persistent
one-queue Worker behind the existing `Backend` interface, compare Pi logits to
the 4090 reference corpus, then measure p50/p99 latency, RSS, CPU and thermal
behavior. Only after those gates pass may runtime health set
`recognizer_available=true` and feed results into the Runner.
