# AMC corpus manifest v1

## Purpose and boundary

`amc_corpus_manifest_v1` is the Chapter 5 data contract shared by:

1. labeled offline dataset windows;
2. bounded P201 RX-only corpus windows;
3. deterministic golden vectors used for preprocessing/parity checks.

The machine-readable source is
[`amc-corpus-manifest-v1.schema.json`](../jetson-agx/sdrharness/config/amc/amc-corpus-manifest-v1.schema.json).
The schema contains both the top-level manifest and `$defs.record`, the schema
for every JSONL row. The dependency-free reference validator is
[`validate-amc-corpus-manifest.py`](../jetson-agx/sdrharness/scripts/validate-amc-corpus-manifest.py).

This contract governs metadata and lineage. It does not enable the production
Recognizer, choose `rf_preprocess_v1`, resolve the RML2018A display-name order,
authorize RF transmission or make an unlabeled field prediction into truth.

## Package layout

One corpus package has a small JSON manifest plus a content-addressed JSONL
record index:

```text
corpus-root/
  manifest.json
  records.jsonl
  ... referenced metadata and bulk assets ...
```

The manifest pins `records.jsonl` by schema ID, exact byte count, row count and
SHA-256. Keeping rows outside the manifest permits streaming validation of large
offline datasets without loading millions of entries into memory. Every JSONL
line must end in LF, remain at most 64 KiB and be one strict record object.

Paths are normalized relative paths below the operator-supplied asset root.
Absolute paths, traversal, final-component symlinks, duplicate JSON keys,
unknown fields, non-finite JSON numbers and mismatched counts/hashes fail
closed. The record index is always verified; `--verify-assets` additionally
hashes every referenced asset, including large datasets when explicitly used.

## Manifest fields

The top-level object is exact and versioned:

| Field | Meaning |
| --- | --- |
| `schema_version/schema_id` | fixed to `1` / `amc_corpus_manifest_v1` |
| `manifest_id` | stable safe identifier for this package |
| `created_at_utc` | explicit UTC `Z` timestamp |
| `status` | `draft` or `frozen` |
| `corpus_kind` | `labeled_offline`, `p201_receive`, `golden_vectors` or an explicitly mixed package |
| `contract` | content-hashed input profile, preprocessing spec and numeric label space |
| `split_policy` | allowed splits and the fixed group-exclusive lineage keys |
| `assets` | relative path, role, bytes, SHA-256, storage class and delete policy |
| `record_index` | exact JSONL schema/path/count/bytes/SHA-256 |
| `governance` | fixed false/true safety assertions that cannot be relaxed by a manifest |

The three contract references are immutable tuples:

```text
input profile: id + path + SHA-256 + integration_only|production
preprocessing: id + path + SHA-256 + integration_only|frozen
label space:   id + path + SHA-256 + numeric IDs authoritative + name status
```

Each tuple must match exactly one asset descriptor by path, role and hash. A
production input profile cannot reference integration-only preprocessing.
`status=frozen` also requires frozen split assignment and a locked test set;
P201 rows in a frozen package must confirm that P201 and AGX transient data were
removed.

## Per-window record

Each `amc_corpus_record_v1` row contains exactly:

```text
record_id
split
lineage
window
label
source
```

`lineage` always carries all three grouping fields, using JSON `null` only when
the concept does not apply:

```text
source_sample_id
capture_session_id
capture_day
parent_record_id
transforms[]
```

`window` pins the canonical decoded IQ bytes, not an HDF5 container's internal
chunk representation. It records window/sample offsets, complex-sample count,
exact byte count, `ci16_le|f32_le`, `interleaved_iq|planar_iq`, little endian,
SHA-256 and one storage locator:

- `dataset_row`: dataset asset, HDF5 path and global row index;
- `managed_asset`: content asset and byte offset;
- `deterministic_generator`: generator ID and canonical parameter hash.

Shape arithmetic is mandatory: ci16 complex IQ is 4 bytes/sample and float32
complex IQ is 8 bytes/sample. Golden tensors support `[2,N] planar_iq` and
`[W,2,N] window_major_planar_iq`; their total complex-sample and byte counts
must equal the raw window.

## Label provenance

Exactly one of the following tagged objects is allowed. There is deliberately
no `model_prediction` provenance.

| Provenance | Required evidence | Allowed use |
| --- | --- | --- |
| `dataset_ground_truth` | dataset ID/hash, label field and exact global row | labeled offline rows only; closed-set metrics are allowed in the assigned frozen split |
| `independent_annotation` | annotation ID, method, UTC time and evidence SHA-256 | independently correlated P201/golden rows; may support labeled receive-domain metrics |
| `unknown` | one bounded reason and no numeric/name fields | unlabeled field IQ, noise, ambiguous/out-of-space signals or quality failures; never accuracy |

An offline row must use `dataset_ground_truth`. A P201 row may use only
`independent_annotation` or `unknown`; copying a source dataset label onto an
over-air reception is forbidden. Independent annotation evidence must match an
`annotation_evidence` asset. A provisional manifest label table cannot be
upgraded to `display_name_status=trusted` by an individual row.

For current RML2018A data, numeric IDs remain authoritative and display names
remain provisional. This schema preserves that distinction but does not settle
the disputed name order.

## Source-specific contracts

### Labeled offline dataset

An offline source pins dataset and split asset IDs/hashes, global row index and
dataset nominal SNR. The dataset row locator, source metadata and label evidence
must all name the same row. `nominal_snr_db` remains a dataset field; it is not
P201 gain or a measured receive SNR.

### P201 receive-only corpus

A P201 source records:

- capture session/time/day plus capture-plan asset ID/plan ID/SHA-256;
- center, sample rate, RF bandwidth, gain mode and `rx_gain_db`;
- sequence, captured samples and transferred bytes;
- the complete fixed `RX1 / RX0 / voltage0,1 / A_BALANCED` identity;
- separate `raw_rms_dbfs` and `measured_snr_db` values;
- clipping, dropped samples, overflow, health flags and health state;
- result visibility/manual delete plus P201/AGX transient cleanup state.

Capture counts must match the indexed interleaved ci16 window. RF bandwidth
cannot exceed sample rate. Healthy metadata cannot simultaneously report
nonzero health flags, drops or overflow. User-visible data requires an
application result ID and working manual-delete path. Bulk IQ stays outside
Git.

### Golden vector

A golden source pins a `golden_fixture` asset and the exact expected float32
tensor shape/bytes/SHA-256. Synthetic or transform-only fixtures without a true
modulation label must use `unknown`; numerical reproducibility is not label
evidence.

## Split isolation rule

The fixed split strategy is `group_exclusive` over:

```text
source_sample_id, capture_session_id, capture_day
```

The validator rejects any non-null group value appearing in more than one of
`train`, `validation`, `test`, `calibration` and `acceptance`. Crops, augmentations and repeated windows must
inherit the same `source_sample_id`; receptions from one capture must retain the
same `capture_session_id`; one receive day cannot be divided across those three
evaluation partitions. `receive_domain` and `golden` remain separate declared
uses and are never silently counted as test accuracy.

For retained offline assets, the reproducible source identity is the full
dataset SHA-256, HDF5 `/X` path and global row. The source containers expose no
latent generator parent ID, so a global row is the explicit audit boundary;
all project-created derivatives must retain its exact identity. The AGX
cross-package audit tool additionally requires unknown P201 rows to remain
`receive_domain` and verifies parent inheritance and cycles before evaluating
group ownership.

The complete RML2018A/Hisar split files and current P201 corpus passed this
audit, including full bulk-asset hashing and independent negative cases for all
three group keys. See
[`AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md`](AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md)
and its
[`machine-readable summary`](AMC_SPLIT_ISOLATION_AUDIT_2026-09-05.json).

## RF-v1 evidence extension (V1a)

The current source adds `capture_report` and `lineage_evidence` asset roles,
`acceptance` as an explicit split, and a category-aware independent annotation
variant. Calibration and acceptance now participate in the same group-exclusion
checks as train/validation/test. P201 unknown rows remain receive_domain only.

For RF-v1 derived P201 packages, the reference validator checks the frozen
profile/preprocess and bounded versioned sidecars. `known_class` requires numeric
ID 0–23; noise/idle, out-of-space, mixed, low-quality and ambiguous categories
carry no forced numeric class. Every category requires independently correlated
annotation evidence, except unknown which never enters calibration/acceptance.
The original offline dataset-ground-truth contract is unchanged.

Derivation preserves original raw content and parent hashes; it does not copy IQ
or convert model predictions to labels. New original captures retain a hash-pinned
request report. Historical packages without that receipt remain eligible only
for unknown derivation. The existing application table, directory and manual-
delete path are reused. These tools have isolated Web/HTTP/browser validation;
the installed Web service remains on its prior release.

The current contract and command line are detailed in
[`RF_V1_CORPUS_EVIDENCE_INTERFACE.md`](RF_V1_CORPUS_EVIDENCE_INTERFACE.md), and the
preregistered sampling/coverage/grouping rules in
[`RF_V1_KNOWN_RF_OOD_SAMPLING_V1.md`](RF_V1_KNOWN_RF_OOD_SAMPLING_V1.md).
Independent reviewers use external evidence; TX and N210/B210 are not project
truth-source dependencies or actions. V1a supplies tools/specification, not V1b
labels, calibrated thresholds or production capability.

## AGX application-owned P201 store

The deployed Web console implements the first concrete P201 store at:

```text
/var/lib/sdrharness/web-console/p201-corpus/<result-id>/
```

One result directory is a self-contained frozen v1 package containing
`manifest.json`, `records.jsonl`, `raw.iq`, the exact capture plan and copies of
the compiled integration profile, preprocessing spec and provisional label
table. SQLite stores the manifest/record JSON plus bounded searchable metadata;
the IQ bytes remain only in the application result directory and outside Git.

The ingestion API is loopback-only, capped at 384 KiB, and currently admits
exactly one 4,096-complex-sample `ci16_le` P201 window at 2.1 MS/s, 1.5 MHz RF
bandwidth and 50 dB fixed RX gain. It revalidates plan/report correlation,
recomputes power, spectral quality and clipping from the submitted bytes,
requires the fixed RX1 identity, zero drops/overflow/health flags, confirmed
radio restoration and completed P201/AGX transient cleanup. The installed legacy entry supports only an
`unknown` label reason. The V1a source adds the separately validated RF-v1
derivation/independent-evidence endpoint described above.

The visible `接收语料` page reads `GET /api/corpus` and
`GET /api/corpus/{result-id}`. Its per-record delete button calls
`DELETE /api/corpus/{result-id}` and removes the database row together with the
exact managed package. Deletion refuses symlinks or unexpected files instead
of traversing an untrusted directory.

## Validator

```bash
python3 jetson-agx/sdrharness/scripts/validate-amc-corpus-manifest.py \
  --manifest /path/to/corpus/manifest.json \
  --asset-root /path/to/corpus \
  --verify-assets
```

On success the tool emits only a compact summary of schema/manifest identity,
asset/record counts, splits, source kinds and label-provenance counts. It does
not print IQ, labels row by row or model output. On failure it exits nonzero as
`contract_error=<code>: <field>: <reason>`.

The focused tests are in
[`test_amc_corpus_manifest.py`](../jetson-agx/sdrharness/tests/test_amc_corpus_manifest.py).
They cover all three provenance variants plus hash/path tampering, label/source
misuse, provisional-name escalation, P201 identity, frozen cleanup and
train/test lineage leakage.

Full split and cross-package lineage auditing is provided by
[`audit-amc-split-isolation.py`](../jetson-agx/sdrharness/scripts/audit-amc-split-isolation.py),
with focused collision/derivation tests in
[`test_amc_split_isolation.py`](../jetson-agx/sdrharness/tests/test_amc_split_isolation.py).
