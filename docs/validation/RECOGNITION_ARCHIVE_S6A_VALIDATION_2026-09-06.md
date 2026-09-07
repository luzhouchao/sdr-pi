# S6a recognition archive validation — 2026-09-06

S6a completes bounded recognition record storage, restore, archive viewing and
manual deletion as source plus isolated native Web/HTTP/terminal/browser
validation. It reuses the application SQLite database and existing result page.
It does not deploy services, perform inference or RF acquisition, implement S5
Runner integration or count as S6b closed-loop acceptance.

The clean starting branch was `codex/recognizer-amc-offline-validation` at
`e8a385268af3dbdecb075826571d309c4949a7ed`. S1/S2/V1a/S3/S4a evidence and frozen
RF-v1/epoch-10/FP16 contracts were reused. No training, accuracy experiment,
locked-test read, TX, FPGA/BOOT or NX offload occurred. Recognition remains
unavailable and text names provisional.

## Audit and implementation

Existing application storage already managed capture and corpus tables with
manual deletion. It had no recognition table or result renderer. S2 already
provided strict full-record validation and a compact observation contract.
S6a adds only an indexed recognition table and reuses the existing database
opening/migration path. It shares the profile decoder with an embedded frozen
metadata entry point, avoiding model/IQ/filesystem access during archive reads.

The import path accepts loopback JSON only and distinguishes experimental replay
from inert synthetic demonstrations. Actual candidate results cannot claim
classified/rejected production decisions. Synthetic decisions are structurally
validated and restricted to explicit synthetic IDs, zero-hash references and
provisional names; every returned row carries `production_result=false`.
Full four-window evidence is retained internally, revalidated on restore, and
excluded from the public archive DTO/Planner. Identical retries are idempotent,
conflicts fail without replacing existing records, and delete touches one row
without source-file or corpus/capture cascades.

See [`RECOGNITION_ARCHIVE_S6A_INTERFACE.md`](../reference/RECOGNITION_ARCHIVE_S6A_INTERFACE.md)
for schemas, limits, lifecycle and CLI commands.

## Tests and bounded native verification

- Web tests: 31 passed, including full-record roundtrip, duplicate retry,
  conflicting write refusal, four inert display states, production forgery,
  changed logits/profile/unknown fields, duplicate keys/truncation/size limits,
  corrupt-read refusal with manual deletion, existing capture preservation and
  50-record pagination. Two explicit fixture exporters remain ignored by default;
  the S6a metadata exporter was separately run successfully.
- Controller tests: 89 library and 13 terminal tests passed; the ordinary ignored
  S3 IQ exporter was not run. The shared profile decoder retained its existing
  validation and runtime behavior.
- Controller and Web all-target Clippy passed with warnings denied; Cargo
  formatting and JavaScript syntax checks passed.
- An isolated native Web binary ran on a private loopback port with all state,
  database, corpus and capture paths under `/var/tmp/sdrharness-dev/s6a-906a/`.
  Its Controller executable was `/bin/false`, SDR address was loopback discard,
  and it had no active conversation. Installed services were not replaced.

The native script imported the retained RF-v1 runtime report already used by S2
and four synthetic metadata fixtures. It used the actual terminal CLI for import,
show and deletion. It verified idempotence, tampered-logit/production-forgery
refusal, 409 conflict, JSON media type/duplicate/bound rejection, invalid IDs,
missing deletion and full four-window payload retention in SQLite. Native Web
restart preserved the same five record IDs and validated results.

Headless Chromium then exercised the actual page, every status and replay badge,
expandable evidence, desktop and 390-pixel mobile layout, and delete dismiss/
confirm. It observed no JavaScript errors or horizontal overflow. Remaining rows
were removed using the terminal client; a further Web restart returned an empty
archive. Application capture/corpus directories stayed empty: zero IQ files were
created by these imports.

The first browser attempt used `networkidle`, which cannot settle while this
console's real `/api/events` SSE connection remains open. The harness now waits
for loaded application state and the real online indicator; it does not stub
SSE/API responses. A storage negative test initially matched the word `logits`
inside the permitted aggregation identity; it was corrected to inspect forbidden
JSON keys. Screenshot review then moved recognition into a same-page result-type
selector and collapsed long evidence fields. The final native/browser run
verified that layout and the complete delete/restore sequence.

## Cleanup and delivery boundary

The feature's native Web processes exited normally; its port and all feature
processes were checked before exact temporary-directory removal. Temporary
metadata fixtures, SQLite/WAL, logs, browser profiles/screenshots and Cargo
staging were removed. No user application result, corpus, IQ or model asset was
removed. Bounded source/binary/log/screenshot hashes and cleanup accounting remain
in [`RECOGNITION_ARCHIVE_S6A_AUDIT_2026-09-06.json`](../evidence/RECOGNITION_ARCHIVE_S6A_AUDIT_2026-09-06.json).

S6a archive source/isolated acceptance is complete. S6b, live observation rendering
and Spark feedback await S5 and actual closed-loop validation; synthetic or replay
acceptance is not promoted to live production evidence. The next default
independent delivery is S5. Calibration, independent labels, sustained resources
and production admission remain open, with `recognizer_available=false`.
