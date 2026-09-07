# RF-v1 runtime parity validation — 2026-09-05

## Outcome

The RF-aligned epoch-10 FP16 candidate now runs through the bounded P201 RX1 →
AGX four-window integration path using the frozen offline transform. This unit
implements runtime parity; it does not admit production recognition.

The audit is [RF_V1_RUNTIME_PARITY_AUDIT_2026-09-05.json](../evidence/RF_V1_RUNTIME_PARITY_AUDIT_2026-09-05.json).
The runtime profile is
[`rml2018a-d8-rf-v1.runtime-profile.json`](../../jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json).
The frozen precision candidate and offline specification were not edited.

## Audited changes

The previous Worker required unit RMS on each individual window and returned
only top-k probabilities. The batch engine made a majority vote. Neither could
reproduce the shared-capture normalization and full-logit offline contract.

The runtime now:

- computes one float64 complex RMS over exactly 4,096 continuous complex-int16
  RX1 samples, retains DC, applies no digital shift/filter/resampling, and casts
  the shared-scaled samples to float32;
- emits four ordered, non-overlapping 1,024-sample planar windows at offsets
  `0,8192,16384,24576`, preserving relative amplitudes and permitting a silent
  window when the capture clears its numerical RMS floor;
- loads the exact checkpoint/source/config/provenance/label identities using
  the existing strict model loader, retains FP32 weights and uses CUDA FP16
  autocast for both warm-up and inference;
- checks exact profile/preprocess/checkpoint hashes, full-spool content hash,
  source and capture lineage, request/generation, window index/order and shape;
- returns 24 complete FP32 logits per window, then computes their arithmetic
  mean and softmax in float64 on AGX; no temperature or rejection is applied;
- explicitly removes spool on success/error/cancel, surfaces unlink errors,
  drops late replies after cancellation, and retains the existing independent
  generation-bound SDR cancel and radio restoration path.

The Worker rejects stale/replayed batches and permits only one active batch,
with a five-second inter-window expiry and finite validation request count.
The CLI checks available spool space before capture and records the exact plan,
byte bounds, temporary paths and direct stop command.

## Reproducibility and tests

| Identity | SHA-256 |
| --- | --- |
| Epoch-10 checkpoint | `a3c3e41ba9732171d65b023d7d9f1d334d88b7ca28be3d939b0536878c168054` |
| Frozen FP16 candidate | `35ff99719ab845f33dc7ca2d0e7b666e4f40721ca64a6dd615a671ec6c084f40` |
| Frozen preprocess | `18428d72beb8c0e7e83d24d57a02d5f6b68f3428cb3f096a219a87b67dbc900f` |
| Runtime profile | `6c1dac991b45e3738e19a6a55a9f3a1b6d3db8510ceef35ee77cdd34e2982dab` |
| Golden model-ready bytes | `937c7c9497ca9f7990ee4256c617d5c57739e66da3da7498de1ab9d1618d2db2` |

Rust runtime output matches the frozen 32,768-byte golden hash exactly; an
independent NumPy implementation reproduces the same hash. A second synthetic
capture with DC amplitudes `[0,100,200,400]` proves retained DC, silent-window
support and preserved cross-window amplitude ratios. A logit counterexample
with three votes for class 0 correctly aggregates to class 1.

Final checks passed: 73 Rust library tests, 11 terminal tests, 3 legacy Worker
Python tests, 5 new runtime Python tests, `cargo fmt --check`, Clippy with
warnings denied and `git diff --check`. Negative tests cover profile/hash
mutation, missing/reordered windows, source/request/generation mismatch,
wrong precision, short/non-finite logits, Worker exit, in-flight late-result
cancellation and empty spool after every outcome. The new restore-comparison
test still rejects manual-gain, LO and gain-mode changes.

Two existing Unix-socket tests initially exceeded `SUN_LEN` under the long
feature path. They passed with the shorter private feature root; their
implementation was not weakened. No dataset or split was loaded. A real-model
FP16 smoke and the bounded live captures below were the only model execution;
the FP32/FP16/BF16 complete experiment was not repeated.

## Finite live RX evidence

P201 retained exactly one daemon, PID `17136`, with deployed SHA-256
`77d98a005305a4b7531fc3f133e9b4af521e60b065b29fcc304b4c7db80c45ae`.
No daemon replacement, persistent service change or production Worker install
was needed. The AGX validation Controller artifact was
`7874c21377c8a2e2c9942e584d9a6b9a8c2bf694a6f44e1c214f318698504535`;
subsequent code review tightened only rejection of an unsupported preprocess
ID/normalization combination and reporting a failed partial-file unlink. The
final source passed the checks above.

Each case used one inspection centered at 433.920 MHz, followed by at most one
fresh-target capture: RX1/RX0/A_BALANCED, 2.1 MS/s, 1.5 MHz RF bandwidth, manual
50 dB, 100 ms settle, 4,096 samples/16,384 bytes each, 1,000 ms capture deadline
and 5,000 ms control/individual model deadline. P201 restored before dispatch.
All three run plans, including validation-harness retries, bounded RX by a
combined **196,608 bytes**; no unbounded capture occurred. Each spool was capped
at 32,768 bytes, and the first free-space check found 809,992,896,512 bytes.

| Case | Capture generation | Result |
| --- | ---: | --- |
| Success | 202609051511 | Four complete logits; independently recomputed mean/softmax; spool removed |
| Worker exit after window 0 | 202609051531 | Window 1 returned explicit `connect` error; spool removed |
| Direct capture cancellation | 202609051551 | `cancel_requested=true`, `capture_failed_restored`; no spool remained |

The success capture was 433,331,169 Hz with sequence 149, zero drops/overflow/
clipping/health flags and 16,384 bytes transferred. Its four normalized RMS
values were `0.96745136,1.02312795,1.03443044,0.97324236`; this is the expected
shared-capture behavior. It returned numeric class 18 with uncalibrated
probability `0.9986453` and four-window agreement 1.0. The reception has no
independent label: these values are **not an accuracy or correctness claim**.
Window inference times were approximately 190.0, 43.5, 37.8 and 37.6 ms, including
transfer. They are bounded integration observations, not a new throughput study.

The validation driver needed two corrections, both retained in the audit. Its
first Worker-exit snapshot comparison incorrectly treated autonomous AGC gain
as a fixed setting: `slow_attack` was restored, but hardware gain read 49 dB
instead of the earlier 71 dB. LO/rate/bandwidth/mode/port/scan/buffer state
matched. Inspection of the unchanged IIO Adapter confirmed that only manual
gain is restored as a fixed numeric value. The corrected comparison follows
that rule and records both readings. The first cancel command preceded session
ownership; the driver now retries only `stale_or_missing_session` within a
finite 30-attempt bound. These were harness corrections, not changes to SDR
safety or restoration. The failure and cancellation cases were individually
repeated to obtain complete evidence.

## Cleanup and remaining scope

Cleanup evidence is recorded in the audit. Feature Workers and capture clients
were stopped, ten exact P201 transient directories were confirmed absent, and
all fixed saved radio settings and RX1 identity were reverified. The three AGX
feature roots `/var/tmp/sdrharness-dev/rf1-905a`, `rf1-905b` and `rf1-905c`,
including the initial failed-test leftovers, were removed after retaining only
the bounded audit. Controller build artifacts and generated runtime-helper
bytecode were removed. Persistent model assets, Triton runtime cache,
application corpus/results and deployed services were retained.

`recognizer_available=false`, production temperature/rejection fields stay
unset, numeric IDs remain authoritative and text names provisional. The locked
test remains unopened. Independently labeled known-RF/OOD evidence is still
needed for calibration/acceptance, followed by locked-test and production
Worker admission. Forced crash/restart cleanup, production cancellation and
thermal/queue admission, shared Spark/Mamba GPU scheduling, Runner capability
and recognition UI are not completed by this unit.
