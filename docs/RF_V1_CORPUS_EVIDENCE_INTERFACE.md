# RF-v1 corpus evidence derivation v1

This V1a extension reuses `p201_corpus_results`, the application corpus directory,
and the existing list/detail/manual-delete endpoints. It creates new immutable
records; it does not overwrite historical packages or run recognition. The
installed Web service is not replaced by the source/isolated validation delivery.
Build/run the updated Web release before using its new loopback endpoint.

## API and client

`POST /api/corpus/{parent-result-id}/derive-rf-v1` is loopback-only and uses the
existing 384-KiB request bound. The parent must be a complete original legacy
capture package in the same store. Revisions point back to that root rather than
creating arbitrary ancestry chains. `schema_version=1` requests contain exactly:

```text
result_id                       new safe identifier, at most 96 bytes
parent_manifest_sha256          hash of the original manifest bytes
parent_iq_sha256                hash of the original 16,384 raw IQ bytes
source_report                   complete correlated SweepReport
split                           receive_domain | calibration | acceptance
label                           tagged object described below
```

The receive-free client validates framing and submits to an explicit loopback IP:

```bash
python3 jetson-agx/sdrharness/scripts/import-rf-v1-corpus.py \
  --endpoint http://127.0.0.1:8787 \
  --parent-result PARENT_ID --request /path/to/reviewed-derivation.json
```

It rejects duplicate/nonfinite/oversized request JSON, nonloopback endpoints,
credentials and redirects, and emits only the result summary. The authoritative
service repeats all capture, IQ, profile, lineage and label checks. It reads no
model or offline dataset; no locked test or new radio operation is invoked.

The unknown label is `{ "provenance":"unknown", "reason":"no_independent_label" }`
(or an existing bounded unknown reason). It is receive_domain only. Independent
labels contain `provenance=independent_annotation`, `category`, nullable
`numeric_id`, and a strict `evidence` object. The categories are `known_class`,
`noise_idle`, `out_of_label_space`, `mixed`, `low_quality`, and `ambiguous`.
Only known_class has a numeric ID (0–23). Text names come from the existing
provisional table and never become trusted. No category can copy a model top-1
or turn an unknown reason into annotation evidence. Dataset-ground-truth labels
remain supported only in the original offline corpus validator; the P201 API
rejects them.

`rf_v1_independent_annotation_v1` evidence carries schema version/ID, annotation
ID, reviewer, method (`external_decoder`, `instrument_reference`, `human_review`),
UTC review time, an explicit `independent_of_model=true` declaration, nullable
ambiguity, bounded UTF-8 `basis_report` (16 KiB) and its content SHA-256. It also
binds source_sample_id, capture_session_id/day, raw IQ SHA-256, request ID,
session generation, sequence, profile/preprocess/label-space hashes, category
and numeric ID. Nonempty ambiguity (up to 1 KiB) restricts the row to
receive_domain. An ambiguous category must explain the ambiguity.

These are reviewer-supplied evidence receipts. Tools validate their structure,
integrity and source association; a declaration or a hash does not prove that
an external report is true. Reviewers must follow
[`RF_V1_KNOWN_RF_OOD_SAMPLING_V1.md`](RF_V1_KNOWN_RF_OOD_SAMPLING_V1.md), including
independence from predictions and unresolved numeric-ID/name evidence.

## Preservation, source evidence and cleanup

New original `POST /api/corpus` packages still use the legacy raw acquisition
profile and unknown label but now also preserve `source-report.json` as a hashed
`capture_report` asset. Older seven-file packages remain byte-for-byte unchanged.
Their missing original request report cannot be manufactured later: only unknown
RF-v1 derivation is allowed, with `request_correlation=legacy_reconstructed`.
New parents with a hash-pinned original report use
`request_correlation=original_report_hash_verified`; the submitted report must
match the original in full before independent annotation is accepted.

The API reuses existing plan/report/preflight/cleanup and IQ spectral/quality
validation. It verifies the original package against its SQLite record and
expected manifest/IQ hashes, embedded legacy profile/preprocess/labels, every
asset hash, fixed RX1 identity and finite 4,096-sample acquisition. Report fields
join capture/source/request/session and are immutable after root ingestion.

Each new record binds the frozen RF-v1 profile/preprocess and retains the raw
ci16 bytes. This is a **metadata/profile derivation** (`rf_v1_profile_binding_v1`),
not a claim that raw IQ was transformed into a stored float tensor. Applying
shared RMS later remains governed by the existing RF-v1 preprocessing runtime.
No model-ready tensor or extra raw copy is stored. `raw.iq` is a managed hardlink
on the same filesystem; creating it must succeed without a copy fallback.

`derivation.json` (`rf_v1_corpus_derivation_v1`, role `lineage_evidence`) preserves
exact original manifest/record UTF-8 snapshots and their hashes, root result ID,
source report/correlation status, raw IQ hash and frozen transform identities.
Independent evidence adds `annotation.json`; both sidecars are descriptor-hashed.
The existing manifest/record schema stays v1 with explicit new asset roles,
acceptance split and category-aware annotation variant. Historical v1 records
retain their original schema and hashes. Old readers reject unsupported fields;
use the updated validator for new packages.

The derived record inherits all three lineage groups, points to its parent
record and keeps the original source/window fields. Only the new result ID,
profile binding, split and reviewed label change. Parent snapshots remain
checkable after the operator deletes the original package. A child remains
valid and owns its IQ reference until independently deleted.

Creation reuses one package writer and SQL insertion path for both legacy and
RF-v1. An immediate SQLite transaction serializes derivation, split assignment
and deletion. Group constraints cover source sample, session, UTC day and raw
IQ hash; calibration/acceptance conflicts fail before commit. Staging or SQL
failure removes the exact new package, leaving the parent and its bytes intact.
Existing result IDs are never replaced. Hash-only partition constraints survive
record deletion to prevent re-import into a different evaluation partition;
no IQ or annotation report is retained in that ledger.

The visible corpus page shows actual provenance/category, known numeric ID,
provisional-name state and split. Its existing delete button removes the row and
owned package links; shared IQ is freed only after the final reference is removed.
The deletion response's byte count is logical unlinked-file bytes, not a promise
that shared disk blocks were released. Unknown files/symlinks still block deletion.

## Validation and coverage tools

```bash
python3 jetson-agx/sdrharness/scripts/validate-amc-corpus-manifest.py \
  --manifest /path/to/package/manifest.json --asset-root /path/to/package --verify-assets

python3 jetson-agx/sdrharness/scripts/summarize-rf-v1-evidence.py \
  --corpus-root /path/to/application/p201-corpus
```

The reference validator checks new sidecars and frozen identities, numeric/label
semantics, original-report evidence, parent inheritance and original IQ hashes.
The existing cross-package split auditor now includes calibration/acceptance
and reconstructs absent parent metadata from verified snapshots. It does not
read training arrays when used by the coverage tool. Mixed offline roots are
rejected before bulk asset verification. Coverage output counts records, distinct
IQ, sessions and days by split/category/numeric class and always leaves V1b and
recognition capability false.
