# V1a RF-v1 evidence tools and sampling validation — 2026-09-06

V1a is complete as source tools/specification with isolated native AGX Web,
HTTP client, reference-validator and browser validation. It does not supply real
independent labels, freeze a temperature/rejection threshold, read locked test,
train/re-evaluate a model, acquire RF, or replace installed services.
`recognizer_available=false`; numeric IDs remain authoritative and names
provisional. V1b, V2/V3, production admission and S3–S6 remain incomplete.

## Baseline and audit

The task started on clean branch `codex/recognizer-amc-offline-validation` at
`8bf6ad03a26fb7faec7e63b832e1b39d787dcb79`. All recorded S2 source/asset hashes
matched. V1a's first dependent Web build found that Web history validation still
used S2's removed label/confidence fields. That omission was corrected, tested
in a detached S2-only checkout, cleaned and independently pushed as `8fa9105`;
see [`RECOGNITION_RESULT_S2_WEB_CORRECTION_2026-09-06.md`](RECOGNITION_RESULT_S2_WEB_CORRECTION_2026-09-06.md).
V1a continued on that corrected baseline and is a separate focused commit.

The existing corpus validator already enforced strict manifests/JSONL,
asset hashes, P201 identity and three label provenances. The cross-package
lineage auditor covered train/validation/test, but not calibration/acceptance.
The deployed application used one SQLite table and seven-file legacy packages;
its inlet admitted healthy 4,096-sample RX1 raw captures with unknown labels only.
It retained the capture plan and sequence but omitted the original request
report. Its list/detail/delete page already worked. No new storage system was
needed, and none was created.

## Delivered behavior

- A loopback-only RF-v1 derivation endpoint and bounded CLI reuse the existing
  result table, package lifecycle, metadata/quality validation and delete API.
  Both legacy and RF-v1 use the same package writer and SQL insert helper.
- Newly ingested original packages also retain the original source report and
  its asset hash. Derivation rechecks complete plan/report/source/request/
  generation/sequence, fixed RX1/RX0/A_BALANCED, raw bytes/hash and measured
  spectral quality. Original metadata and on-disk JSON must match the database,
  expected canonical bytes and exact descriptor set. A newly dropped report
  that was never pinned by the parent's manifest cannot confer evidence.
- RF-v1 metadata derivations retain exact parent manifest/record snapshots and
  hashes. Raw content is unchanged; a managed hardlink adds a reference without
  another IQ copy or a stored model-ready tensor. Historical seven-file roots
  are never rewritten and can derive unknown only when request evidence was
  originally absent. Label revisions always point to the original root.
- Independent annotations bind a reviewed report/hash, reviewer/method/time,
  source identities, frozen profile/preprocess/label-space and known/nonclass
  category. Unknown and dataset-ground-truth cannot masquerade as independent
  P201 labels. Known classes use numeric 0–23; noise/idle, OOD, mixed, low-quality
  and ambiguous annotations never force a numeric class. Ambiguity excludes
  calibration/acceptance. Tool integrity checks do not prove the factual truth
  of a reviewer-supplied report.
- An immediate SQLite transaction protects source/session/day/raw-IQ partition
  assignment, package insertion and parent deletion. Hash-only group constraints
  survive deletion. Existing result IDs are never overwritten; write/SQL failures
  remove only new staging/package files and roll back new group claims.
- The reference validator checks versioned sidecars and the existing lineage
  auditor includes calibration/acceptance plus identical-IQ exclusion. Verified
  parent snapshots keep surviving children auditable after parent deletion.
  Coverage tooling counts records, distinct IQ, sessions and days, and never
  reports V1b complete or enables recognition.
- The existing page shows actual provenance/category, known numeric ID,
  provisional-name status and split, with the same visible delete button.
  Deleting a record removes its IQ reference; other records' shared IQ remains.

The interface is documented in
[`RF_V1_CORPUS_EVIDENCE_INTERFACE.md`](RF_V1_CORPUS_EVIDENCE_INTERFACE.md).
The preregistration in
[`RF_V1_KNOWN_RF_OOD_SAMPLING_V1.md`](RF_V1_KNOWN_RF_OOD_SAMPLING_V1.md)
defines coverage axes, label-review independence/ambiguity, fixed calibration
and acceptance campaigns, clustered/effective sample-size accounting, and
statistical planning targets. These are measurement-resolution targets, not
frozen production thresholds. Actual reviewed coverage is still V1b work.

## Verification

Final source passed 27 Web tests (one explicit fixture-export test is normally
ignored and was separately run for HTTP validation), nine corpus-manifest tests,
14 split-isolation tests and three import-client tests. Rust formatting,
all-target Clippy with warnings denied, JavaScript syntax and Git whitespace
checks passed. No Controller/Worker precision experiment or offline dataset
operation was rerun.

New Web tests exercise legal unknown and all five nonambiguous independent
categories, provisional names, immutable parent hashes, same-inode IQ sharing,
parent/child deletion order, legacy package compatibility and rejection of an
unpinned retrospective report. Negative cases cover wrong IQ/manifest hashes,
RX identity, source/request/generation, profile/preprocess, evidence content,
model-based provenance, numeric IDs, ambiguity, oversized basis text,
dataset-label misuse, conflicting source/session/day/identical-IQ partitions,
duplicate result IDs and injected database insertion failure. New package and
group-claim cleanup are asserted. The Python validator is invoked on generated
packages, including eight semantic tamper cases with outer hashes recomputed,
so it cannot pass solely because a manifest hash matches corrupted metadata.

The native Web ran only at `127.0.0.1:18787`, using an isolated SQLite database,
corpus/capture/state directories, `/bin/false` as the agent, an absent session
socket and `127.0.0.1:1` as the SDR endpoint. Three synthetic HTTP imports
(original, unknown derivation, independent known-class calibration derivation)
succeeded. Acceptance import for the same groups returned HTTP 409 both before
and after manual calibration-record deletion. The CLI emitted only summaries.
The coverage tool audited the surviving child even after parent deletion.

A headless Chromium run showed numeric ID 3 with provisional name status and the
correct independent-annotation heading, used the visible per-record delete
button and confirmed database/package removal while the parent's IQ survived.
All synthetic HTTP packages were then deleted via the same API. There were no
browser page errors. The unrelated long-lived `/api/events` stream was stubbed
empty only in the browser harness, after its persistent connection prevented
`networkidle`; corpus endpoints and SQLite/filesystem actions were real.

Initial test selection accidentally included unrelated Worker import tests under
the system Python without Torch. They failed at import, before model/data access.
The final test run explicitly selected the three changed corpus/client suites.
The initial shell-based server helper also left an old isolated Web child alive;
its exact PID was stopped and final validation used direct process ownership,
confirmed final UI content and a clean native-server exit. Clippy's large-enum
diagnostic was resolved by boxing annotation evidence without
changing JSON. Final replay/browser checks include the stricter original-report
and full source validation. No synthetic label is retained as real V1b evidence.

## Delivery and cleanup boundary

All validation builds, synthetic IQ/request fixtures, SQLite files, sidecars,
logs, browser profile/screenshot and staging stayed under the unique root
`/var/tmp/sdrharness-dev/v1a-906a/`. The S2-only checkout/target and its staging
were separately removed before the S2 corrective commit. After V1a verification,
all feature processes exited and the exact resolved V1a root was removed and
verified absent. No P201 transient directory was created; no user corpus,
application result, model asset or installed release was modified/deleted.

Bounded hashes, test/browser results and cleanup accounting are retained in
[`RF_V1_EVIDENCE_V1A_AUDIT_2026-09-06.json`](RF_V1_EVIDENCE_V1A_AUDIT_2026-09-06.json).
The installed Web remains on its prior release. Production rollouts and
recognition admission are separate; this source/isolated validation does not
claim new deployed API availability. The next default independent unit is S3
Worker lifecycle; no S3 work is included in V1a.
