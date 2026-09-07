# AMC corpus contract validation (2026-09-05)

## Result and scope

The first independent Chapter 5 item is complete: labeled offline windows,
P201 RX-only corpus rows and golden vectors now share one versioned manifest /
JSONL-record schema, strict reference validator and negative-test matrix.

This delivery did not read the complete training project, iterate either full
HDF5 dataset, control P201/N210, transmit, train a model, change a checkpoint or
enable `recognizer_available`. It defines and tests data governance only.

Tracked artifacts:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `amc-corpus-manifest-v1.schema.json` | 18,808 | `2de45edfba634ecea66f488706f2b1032081e5c285d6efa5c6aa8122d50e30d9` |
| `validate-amc-corpus-manifest.py` | 43,076 | `4c27e7e74cf96615a7d015dff84f4f698e938bd621147fad6ef7d5b51e6d121d` |
| `test_amc_corpus_manifest.py` | 17,662 | `01b7ac06c57e8f3d5e97f38e89c91580736fd55f6e222f4ccee9a9e7db12da8b` |

The normative explanation is
[`AMC_CORPUS_MANIFEST_V1.md`](../reference/AMC_CORPUS_MANIFEST_V1.md).

## Contract properties proved

The validator uses only Python 3.10 standard-library modules. It verifies:

- exact manifest and record keys, fixed schema identities and bounded file/line
  sizes;
- duplicate-key and non-finite-number rejection;
- normalized relative paths contained by an explicit asset root, with no final
  symlink;
- exact JSONL byte count, row count and SHA-256 through streaming reads;
- unique asset/record IDs and optional exact bytes/SHA-256 for every asset;
- one of only `dataset_ground_truth`, `independent_annotation` or `unknown` for
  every window;
- label/source/evidence relationships, including the prohibition on treating a
  P201 reception as dataset ground truth;
- numeric-label authority versus trusted/provisional/absent display names;
- canonical IQ sample-format/layout/byte arithmetic and golden tensor shape;
- the complete fixed P201 `RX1 / RX0 / voltage0,1 / A_BALANCED` identity;
- separate dataset nominal SNR, P201 RX gain, raw RMS and measured receive SNR;
- P201 health/overflow/drop consistency, result/manual-delete metadata and
  mandatory transient cleanup for frozen rows;
- `source_sample_id`, `capture_session_id` and `capture_day` exclusivity across
  train/validation/test;
- frozen preprocessing whenever an input profile claims production admission.

As a separate development-only schema check, temporary `jsonschema 4.25.1`
validated the document with `Draft202012Validator.check_schema`, then validated
both the bounded golden manifest and `$defs.record` instance:

```text
draft2020_12_schema=valid manifest=valid golden_record=valid
```

That package and its pip cache stayed inside the feature directory and are not
runtime dependencies.

## Focused test matrix

Nine new corpus-contract tests passed, followed by the three existing
experimental Worker contract/containment tests (12/12 combined):

```text
valid mixed manifest with all three provenance variants             pass
unknown label carrying a numeric/model-like identity                rejected
P201 row using dataset_ground_truth                                 rejected
provisional label table upgraded to trusted by one row              rejected
same source sample copied from train to test                        rejected
P201 front-panel identity changed from RX1 to TRX1                  rejected
frozen P201 row with transient cleanup incomplete                   rejected
production profile with integration-only preprocessing             rejected
record-index hash mismatch and ../ traversal                        rejected
```

The mixed success fixture verified all nine temporary assets by bytes and
SHA-256 and returned one count for each provenance type. These are synthetic
contract tests; the lineage negative test proves the gate works but is not the
still-open full RML/Hisar/P201 split-isolation audit.

## Existing golden-fixture validation

A separate bounded validation package copied only four existing tracked
metadata files into:

```text
/var/tmp/sdrharness-dev/ch5-amc-corpus-contract-20260905/actual-golden/
```

It pinned and verified:

```text
rml2018a-d8-current-integration-v1 profile
legacy_adc_unit_rms_v0 preprocessing
RML2018A numeric/provisional-name table
model-ready-batch-v1-affine-modulo golden fixture
```

The record represented 4,096 generated ci16 complex samples and the exact
`[4,2,1024]` window-major planar float32 tensor:

```text
raw bytes / SHA-256:    16,384 / 9ddea8749993725208a8828bc68294396a9a50e4b5a4d242625d462913e518b6
model bytes / SHA-256:  32,768 / 30a315ea74bbb39719e58498651f9e54e24d28129e10367d01dc3a602a1275df
```

Because the affine generator has no modulation truth, its label was explicitly
`unknown/out_of_label_space`; tensor reproducibility was not misrepresented as
accuracy. Full asset verification returned:

```json
{"asset_count":4,"assets_verified":true,"corpus_kind":"golden_vectors","label_provenance_counts":{"unknown":1},"manifest_id":"seed44-integration-golden-contract-v1","record_count":1,"schema_id":"amc_corpus_manifest_v1","source_counts":{"golden_vector":1},"split_counts":{"golden":1},"status":"frozen"}
```

No raw IQ was written to Git. The deterministic generator and expected byte
hashes remain the reproducible source.

## N210 and next boundary

The schema reserves `independent_annotation / known_waveform_schedule` for a
later N210-backed receive corpus. A valid labeled P201 row will require a
content-hashed waveform/schedule evidence asset plus capture/session/time
correlation. Without that evidence it remains `unknown`, even when Mamba emits
a high-confidence top-1.

N210 remains an external test signal source, not an Agent action or Chapter 1–6
runtime dependency. No transmission was needed for this contract delivery.

The next Chapter 5 item is still open: implement the bounded application-owned
P201 corpus store and visible per-result deletion, then collect versioned rows
under this schema. Full source/session/day split proof and `rf_preprocess_v1`
selection remain later, separate gates.

## Cleanup

Tests placed Python caches, temporary assets and the copied golden validation
package only below
`/var/tmp/sdrharness-dev/ch5-amc-corpus-contract-20260905/`. After recording the
hashes and bounded summary, that exact feature directory was removed and its
absence verified. No local dataset, split, checkpoint, evaluation result,
runtime environment or user-visible SDR result was changed or deleted.
