# RF preprocessing v1 validation-only selection — 2026-09-05

## Outcome

The Chapter 4-to-6 signal transform and window contract is now frozen for the
user's next 4090 retraining/fine-tuning run:

```text
P201 RX1 / RX0 / A_BALANCED
  -> 2.1 MS/s, 1.5 MHz RF bandwidth, 4,096 interleaved ci16 samples
  -> hardware retune to the candidate center
  -> no digital frequency shift, extra AGX filter or resampling
  -> retain DC
  -> one complex-RMS scale shared by the complete four-window capture
  -> 4 contiguous, non-overlapping windows of 1,024 samples
  -> window-major planar float32
  -> run D8 once per window
  -> arithmetic mean of four complete logit vectors
  -> softmax and later scalar-temperature calibration
```

The frozen machine contract is
[`rf-preprocess-v1.json`](../../jetson-agx/sdrharness/config/amc/rf-preprocess-v1.json),
SHA-256
`18428d72beb8c0e7e83d24d57a02d5f6b68f3428cb3f096a219a87b67dbc900f`.
It is deliberately `frozen_for_retraining` with `production_enabled=false` and
`recognizer_available=false`.

This does not replace the current `legacy_adc_unit_rms_v0` integration profile.
Seed44 was trained on unmodified HDF5 amplitude, the current Controller scales
each window separately, and the current Worker does not return full logits.
Those mismatches remain fail-closed until a new checkpoint is supplied and the
runtime contract is implemented and admitted.

## Pre-registration and test lock

The candidate set, ranking tolerance and data roles were committed and pushed
before new inference as commits `5673ba1` and `7dc752f`. The final preregistered
plan SHA-256 was:

```text
52320186d17dbd2dade4c8452c0538ea8d3b7a6a55c1caed199fa35d323842bc
```

The selection tool opens individual NPZ members and rejects `test` before
archive access. The complete run loaded, in order:

```text
num_samples, train_ratio, val_ratio, test_ratio, seed, train, val
```

It listed `test.npy` from the ZIP directory but never decompressed or indexed
it. No `metrics_test.json` or prior full-test result path was opened by the
selection code. Historical seed44 test results already existed and were known;
they were not used in candidate ranking. The committed negative test proves
that valid train/val members still load when `test.npy` contains a deliberately
invalid payload, while an explicit request for `test` fails before opening the
archive.

Train rows were used only for distribution statistics. Candidate ranking,
multiwindow ablation and experimental calibration used validation. The P201
record remained `receive_domain/unknown` and was never counted as accuracy.

## Dataset and parity gates

The run rehashed the complete 21,449,148,312-byte RML2018A HDF5 as:

```text
e3dd0bef66a3426959ee66a1709a8c0a95d4f8395d18aaf6f1214bdbc763bd38
```

It scanned all 1,789,132 train rows and loaded all 383,385 validation rows. The
624 numeric-class/SNR buckets formed 95,607 complete four-window pseudo
sessions covering 382,428 source rows; only 957 bucket-tail rows were excluded
from like-for-like transform comparison. Every pseudo session contains four
different validation source rows with the same numeric class and nominal SNR.

The unmodified-input diagnostic reconstructed all validation rows, including
the 957 tails. AGX accuracy was `0.6378575062`, versus the pinned 4090 validation
reference `0.6378522895`; the absolute delta `0.0000052167` passed the
pre-registered `0.0001` gate.

Train amplitude is not a fixed ADC scale: complex-RMS p01/p50/p95/p99 was
`0.9561 / 1.0039 / 1.9733 / 10.3014`. DC fraction p01/p50/p95/p99 was
`0.000535 / 0.054586 / 0.866656 / 0.998005`, consistent with a corpus that
contains carrier-bearing classes. These distributions support an explicit RF
normalization contract and argue against indiscriminate DC removal.

## Transform ablation

The same 382,428 validation rows were evaluated under every candidate using the
same seed44 FP32 model. Raw identity is shown only as a sensitivity/parity
diagnostic and was prohibited from winning because it cannot align arbitrary
P201 ADC gain.

| Transform | All-SNR single-window accuracy | SNR ≥ 4 dB single-window accuracy |
| --- | ---: | ---: |
| per-window unit RMS, retain DC | 53.5366% | 79.8170% |
| per-window unit RMS, remove DC | 41.5234% | 62.1491% |
| four-window shared RMS, retain DC | 54.6887% | 81.8182% |
| four-window shared RMS, remove DC | 42.1431% | 63.1429% |

DC removal lost `17.67` to `18.68` percentage points in the primary high-SNR
range, far beyond the 0.25-point preference tolerance. `remove_dc=false` is
therefore frozen.

For calibration-eligible mean-logit aggregation:

| RMS scope | Windows | All-SNR accuracy | SNR ≥ 4 dB accuracy |
| --- | ---: | ---: | ---: |
| per-window | 1 | 53.5366% | 79.8170% |
| per-window | 2 | 55.1398% | 81.3208% |
| per-window | 4 | 56.3505% | 82.1582% |
| shared four-window capture | 1 | 54.6887% | 81.8182% |
| shared four-window capture | 2 | 56.5136% | 83.6144% |
| shared four-window capture | 4 | 57.9748% | 84.9230% |

Four shared-RMS windows with mean logits were the unique best registered
candidate, exceeding the corresponding per-window normalization by `1.6244`
all-SNR points and `2.7648` primary-range points. It was not selected by a
post-hoc preference.

The offline four-row groups are pseudo sessions, not claims that the HDF5 rows
were one continuous transmission. The one retained P201 capture provides a
runtime shape/stability check: its four raw RMS values were
`3.8074 / 3.8180 / 3.9699 / 3.9540` ADC codes. It does not provide class truth.

## Calibration remains open

To exercise the intended method, four-window validation groups were divided
into 47,795 temperature-fit and 47,812 audit groups by a deterministic hash of
the first source row. For the old seed44 sensitivity baseline, scalar
temperature `2.0251127723` changed audit NLL from `1.54569` to `1.42768` and
15-bin ECE from `3.8524%` to `3.2031%`.

That temperature is explicitly diagnostic and non-transferable. It cannot be
the production value because:

1. seed44 was not trained with `rf_preprocess_v1`;
2. the final checkpoint does not exist;
3. the receive corpus has no independently labeled known-RF or OOD rows;
4. closed-set validation precision cannot establish an open-set false-accept
   rate.

Consequently the frozen spec keeps production temperature, confidence,
agreement, SNR and occupied-bandwidth acceptance thresholds as `null`. These
must be fit after retraining using validation plus independently labeled
known-RF/OOD evidence, still without consulting the new checkpoint's locked
test result.

The P201 unknown row produced numeric top-1 `18` with baseline-temperature
confidence `0.23048`. Its accuracy and correctness fields remained JSON `null`;
the value is a domain observation, not evidence that class 18 was present.

## Reproducible artifacts

The bounded machine summary is
[`RF_PREPROCESS_V1_SELECTION_AUDIT_2026-09-05.json`](../RF_PREPROCESS_V1_SELECTION_AUDIT_2026-09-05.json),
6,014 bytes, SHA-256
`b82163e1855b6031f54d5ef3ad35e2f60400386e18002a4e37d9297fb94f5bea`.

The full temporary result was 120,780 bytes with SHA-256:

```text
3e1fd6b7711d484bda064a55d8b5d7fa31af4d482662b119d56f72608ada18f8
```

It ran for `979.77 s`, including `875.78 s` for 1,912,140 transformed-window
inferences. Peak CUDA allocated/reserved memory was
`2,145,283,072 / 2,575,302,656` bytes; process max RSS was `4,889,874,432`
bytes. No per-row logits or IQ copies were written to disk.

The full run used selection-tool SHA-256
`9b189d70a2ca5df7166b39f22d6c786c9785a7d072f8353adef61d61812a44c8`.
Afterward, fail-closed model class/revision/backend checks, exact temporary-root
validation and self-hash reporting were added without changing transform or
ranking math. Final tool SHA-256
`4b6a17b24305feb4be5a8faf2bf193c412be989e531fddbeabce400daebad578`
then reproduced the same 64-group smoke selection; that smoke result SHA-256
was `710858b7ab67ef8ea129311c5ee220f9adfb7281922633d4925e5e62a0f08e35`.

The new golden fixture reuses the existing 4,096-sample affine ci16 generator:

```text
raw:   16,384 B / 9ddea8749993725208a8828bc68294396a9a50e4b5a4d242625d462913e518b6
model: 32,768 B / 937c7c9497ca9f7990ee4256c617d5c57739e66da3da7498de1ab9d1618d2db2
shared raw complex RMS:        754.9337855122212 ADC codes
normalized capture RMS:        1.000000000275311
normalized per-window RMS:     1.0009273 / 0.9998162 / 0.9994639 / 0.9997921
```

The individual normalized windows intentionally need not have RMS exactly one;
the invariant applies to the complete four-window capture. This distinction is
why the existing per-window integration implementation cannot silently claim
v1 parity.

## 4090 training handoff

The user-owned retraining loader should implement this order:

1. use only frozen train IDs for parameter updates;
2. construct four-row groups within the same numeric class and nominal SNR;
3. compute one float64 complex RMS over all `4 × 1,024` samples, without mean
   subtraction;
4. multiply all four windows by the same reciprocal scale and cast to planar
   float32;
5. keep every crop/augmentation under its source row's existing split;
6. train/fine-tune D8, but aggregate validation inference by mean logits over
   four windows;
7. change the existing training default from automatic `val,test` evaluation to
   validation only, and do not instantiate or iterate the locked test loader;
8. return a checkpoint plus exact source/config/split/spec/label hashes without
   opening the locked test split.

After that handoff returns, AGX must strictly load the new checkpoint, refit
temperature and rejection thresholds on validation/known-RF/OOD evidence,
compare precisions, implement shared-capture RMS and full-logit output, and only
then run a single frozen-test admission evaluation.

## Cleanup

All generated output was confined to the exact 361,263-byte feature root:

```text
/var/tmp/sdrharness-dev/rf-preprocess-v1-selection-20260905/
```

The full result and two smoke summaries were deleted with that exact directory
after their hashes and bounded metrics were recorded, and absence was verified.
The source datasets, splits, checkpoint, runtime, and application-owned P201
result were retained unchanged.
