# RF-aligned D8 checkpoint AGX validation — 2026-09-05

## Outcome

The user-selected 4090 checkpoint was transferred to a separate Git-ignored
AGX asset directory, strictly loaded with the pinned D8 source, and reproduced
on the complete grouped RML2018A validation split. AGX accuracy exactly matched
the 4090 result:

```text
4090 validation accuracy: 0.6705575951551664
AGX  validation accuracy: 0.6705575951551664
accuracy delta:            0.0

4090 validation NLL:      1.0007131779854817
AGX  validation NLL:      1.0007131099700928
NLL delta:               -0.0000000680153889
```

Both absolute deltas passed the pre-run `0.0001` gates. This completes the
checkpoint handoff and AGX FP32 validation-parity gate. It does **not** enable
production recognition: `recognizer_available=false`, the locked test remains
unopened, precision selection and runtime v1 support remain incomplete, and no
independently labeled known-RF/OOD evidence exists for rejection thresholds.

The bounded machine record is
[`RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_AUDIT_2026-09-05.json`](RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_AUDIT_2026-09-05.json).

## 4090 handoff

The completed run stopped after 17 epochs (`12,552.90 s`, about 3 h 29 min)
with validation early-stopping patience 7. Epoch 10 was selected using the
frozen validation rule:

| Item | Value |
| --- | ---: |
| Training steps | 237,507 |
| Epoch 10 train loss | 0.9685548 |
| Epoch 10 validation accuracy | 67.0558% |
| Epoch 10 validation NLL | 1.0007132 |
| Validation groups | 95,607 |
| Validation source rows | 382,428 |

The selected checkpoint is 1,726,724 bytes with SHA-256:

```text
a3c3e41ba9732171d65b023d7d9f1d334d88b7ca28be3d939b0536878c168054
```

It and ten small delivery/provenance files were retained under:

```text
/home/jetson/sdrharness/local-assets/amc-eval/checkpoints/rml2018a/
  rf-v1-ft-batched-seed44/
```

The directory contains only the selected epoch, not the other 16 training
epochs. Its 11 retained files total 1,791,823 bytes. Every downloaded file was
rehashed on AGX and matched the 4090 completion/provenance manifests. The tracked
fail-closed candidate contract is
[`rml2018a-d8-rf-v1-ft-batched-seed44.candidate.json`](../jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1-ft-batched-seed44.candidate.json),
SHA-256
`a937fc5eba72cc9cb596eb8d86d87917110a2fedf130436b399ceb513779eeb4`.

## Strict-load and governance gates

The AGX validator required all of the following before inference:

- checkpoint envelope class `AMCMambaD8`, variant `amc_mamba_d8`, epoch 10 and
  the real D8 Mamba backend;
- strict loading of all 134,798 parameters;
- exact equality between the checkpoint-embedded training config and the
  downloaded config;
- exact equality between the checkpoint's 147-entry provenance map and the
  downloaded map;
- the 11 retained inference-source hashes at commit
  `8bc6fb5dc58e1b83338bdebb2624824f1e6b0798`;
- complete RML2018A HDF5 rehash and frozen split hash;
- `rf_preprocess_v1` shared-capture RMS, retained DC, four 1,024-sample windows
  and arithmetic mean logits;
- only NPZ `train` and `val` access. The loader rejected `test` before archive
  access and did not open any test-result path.

The validator is
[`validate-rf-aligned-checkpoint.py`](../jetson-agx/sdrharness/scripts/validate-rf-aligned-checkpoint.py),
SHA-256
`de17bc4fa301b8aea94f4f2076fe9b0b0f738e48430e005ffc4440a49facdb95`.

## Validation result

All 95,607 complete class/SNR four-row groups were evaluated; they cover
382,428 validation rows, with only the registered 957 bucket tails excluded.

| Metric | RF-aligned epoch 10 | Old seed44, same transform/groups |
| --- | ---: | ---: |
| All-SNR accuracy | 67.0558% | 57.9748% |
| Nominal SNR ≥ 4 dB accuracy | 98.7993% | 84.9230% |

The like-for-like gains are 9.0809 and 13.8763 percentage points. The new
checkpoint's 15-bin ECE on the complete grouped validation set was 2.0276%.
Four per-window top-1 IDs were all equal for 52.3853% of groups; mean agreement
was 0.7521. Those are observations, not acceptance thresholds.

## Calibration remains non-production

A deterministic validation-only fit/audit split produced a scalar-temperature
candidate of `1.3464721298`. On 48,004 audit groups it changed NLL from
`1.0011531` to `0.9941795` and 15-bin ECE from `2.1244%` to `0.9539%`.

The value is recorded only as `validation_candidate_only_not_production`.
Without independently labeled known-RF and OOD receptions, it cannot establish
field-domain confidence, agreement, SNR, occupied-bandwidth or false-accept
thresholds. All production calibration and rejection fields remain `null`.

## Resource and cleanup result

With the local Spark server resident but not deliberately exercised in
parallel, the complete AGX run took 247.59 seconds, including 199.80 seconds of
model inference. PyTorch reported 581,594,624 peak allocated and 792,723,456
peak reserved CUDA bytes; process max RSS was 4,352,163,840 bytes.

The only generated result was an 8,139-byte JSON summary under the exact
feature directory:

```text
/var/tmp/sdrharness-dev/rf-v1-checkpoint-agx-validation-20260905/
```

Its SHA-256 was
`8aeabd6ccff4119c49221487d2b4f5aa505e13a83da887bc82196b8cfd40637f`.
The exact 12,235-byte directory was removed after the bounded metrics and hash
were recorded, and absence was verified. No raw IQ or per-group logits were
written.

## Remaining order

1. Pre-register and compare FP16/BF16 against this complete FP32 validation
   baseline, then select one AGX inference precision without using test.
2. Implement runtime shared-capture RMS and complete-logit mean aggregation
   behind the existing production-disabled Worker seam.
3. Obtain independently labeled known-RF/OOD evidence without adding a transmit
   action to the Agent or production graph.
4. Freeze model-specific calibration and rejection/quality thresholds.
5. Only then perform one locked-test admission, finish Worker/GPU/cancel/thermal
   gates and derive `recognizer_available` from live admitted health.
