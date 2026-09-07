# RF-v1 inference precision selection — 2026-09-05

## Outcome

FP16 autocast was selected for the RF-aligned RML2018A D8 epoch-10 candidate
after a preregistered, complete AGX validation comparison against FP32 and
BF16. FP16 passed every accuracy, numerical, speed and memory gate. It is
22.54% faster than FP32 in the fixed 4,096-group benchmark while changing
complete-validation accuracy by only `-0.00314` percentage points.

This selects the candidate's inference precision; it does **not** admit a
production Recognizer. The tracked FP16 profile keeps
`production_enabled=false` and `recognizer_available=false`. Runtime
shared-capture RMS/full-logit aggregation, independently labeled known-RF/OOD
evidence, calibration, rejection, Worker admission and the locked test all
remain incomplete.

The bounded machine record is
[`RF_V1_PRECISION_SELECTION_AUDIT_2026-09-05.json`](../evidence/RF_V1_PRECISION_SELECTION_AUDIT_2026-09-05.json).

## Frozen inputs and method

The comparison used the preregistered plan
[`rf-v1-precision-selection-plan.json`](../../jetson-agx/sdrharness/config/amc/rf-v1-precision-selection-plan.json),
SHA-256
`552c2a16505bf9ced2d8ab1190fe2cb1b9b8d104cee2b94d9b8c8f108d287306`.
The selection implementation SHA-256 was
`e6f906beffa45f663b00ed8f587e8a7c1684e647d85954f9b5385ebd4e8d07ff`.

All three modes used the same immutable inputs:

- epoch-10 checkpoint SHA-256
  `a3c3e41ba9732171d65b023d7d9f1d334d88b7ca28be3d939b0536878c168054`;
- RML2018A dataset and seed44 split hashes already pinned by the FP32
  checkpoint audit;
- `rf_preprocess_v1`: DC retained, one complex RMS over one contiguous
  4,096-sample capture, four ordered 1,024-sample windows;
- float64 arithmetic mean of all four complete logits, then softmax;
- 95,607 complete validation groups (382,428 source rows), batch size 64;
- FP32 resident weights; FP16/BF16 changed CUDA autocast compute only.

Only the split's `train` and `val` members were accessed. Training was not
performed, no checkpoint was changed, the `test` member and historical test
results were not opened, and no raw IQ or per-group logits were written.

## Complete validation results

| Mode | Accuracy | SNR >= 4 dB accuracy | NLL | ECE-15 | Full validation time |
| --- | ---: | ---: | ---: | ---: | ---: |
| FP32 | 67.05576% | 98.79928% | 1.0007131 | 2.02763% | 190.46 s |
| FP16 | 67.05262% | 98.80316% | 1.0006860 | 2.03187% | 161.28 s |
| BF16 | 67.07145% | 98.81871% | 1.0002387 | 2.00603% | 171.29 s |

The FP16 accuracy difference is one comparison against the same FP32
baseline, not a cumulative or continuing decrease. Its absolute change is
`0.00003138` (about `0.00314` percentage points), and its SNR >= 4 dB result is
slightly higher than FP32.

## Numerical gates

| Comparison to FP32 | Required gate | FP16 | BF16 |
| --- | ---: | ---: | ---: |
| Argmax agreement | >= 0.995 | 0.998682 | **0.990597 fail** |
| Mean-logit absolute difference p99 | <= 0.1 | 0.013516 | **0.141965 fail** |
| Mean-logit absolute difference max | <= 1.0 | 0.100788 | **2.063920 fail** |
| Probability absolute difference p99 | <= 0.005 | 0.000458 | 0.003734 |
| Probability absolute difference max | <= 0.05 | 0.020086 | **0.214237 fail** |

Both low-precision modes passed the registered accuracy, high-SNR accuracy,
NLL, finite-output, speed and reserved-memory gates. FP16 also passed every
numerical parity gate. BF16 did not: its aggregate accuracy happened to be
slightly higher, but too many individual decisions/logits diverged from the
FP32 reference. Therefore aggregate accuracy alone could not qualify BF16.

## Throughput and memory

The benchmark used 4,096 evenly spaced immutable groups, precomputed host
planar-float32 inputs, three interleaved rounds and CUDA synchronization around
each observation.

| Mode | Median groups/s | Ratio to FP32 | Peak allocated | Peak reserved |
| --- | ---: | ---: | ---: | ---: |
| FP32 | 579.628 | 1.0000x | 437,152,768 B | 792,723,456 B |
| FP16 | 710.297 | 1.2254x | 244,296,704 B | 792,723,456 B |
| BF16 | 662.494 | 1.1430x | 244,296,704 B | 792,723,456 B |

FP16's three observations were 710.542, 709.700 and 710.297 groups/s. The
stable median clears the preregistered 10% speedup gate. PyTorch's reserved
pool did not shrink, but peak allocated CUDA memory was lower than FP32.

## Frozen candidate and cleanup

The selected fail-closed candidate is
[`rml2018a-d8-rf-v1-fp16.candidate.json`](../../jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1-fp16.candidate.json),
SHA-256
`35ff99719ab845f33dc7ca2d0e7b666e4f40721ca64a6dd615a671ec6c084f40`.
It specifies FP32 resident weights, CUDA FP16 autocast, FP32 input/returned
logits and float64 four-window aggregation. Calibration and acceptance fields
remain null.

The complete comparison took 725.433 seconds and reached 5,345,988,608 bytes
maximum process RSS. Its only generated file was a 13,106-byte summary at:

```text
/var/tmp/sdrharness-dev/rf-v1-precision-selection-20260905/full.json
```

The summary SHA-256 was
`b58c1b5e096ca11fc2bf1972de92d05724789abeac52d829ff54ccf39136836a`.
The exact 17,202-byte feature directory was removed and absence verified. No
radio or transmitter was used.

## Next implementation unit

Implement runtime `rf_preprocess_v1` shared-capture RMS and return every
window's complete logits so the AGX integration path can reproduce the frozen
float64 mean-logit rule. Keep capability false; calibration and rejection must
wait for independently labeled known-RF/OOD evidence.
