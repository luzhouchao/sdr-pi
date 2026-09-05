# S6a recognition result archive

S6a adds a recognition table to the **existing** application SQLite database
(`SDR_WEB_RESULT_DB_PATH`). It preserves capture/corpus tables and their manual
delete paths. It stores bounded S2 records, exposes a compact archive view in
Web and a local terminal client, and never opens or copies IQ files. It does not
execute recognition, feed Planner context, deploy services or enable admission.

## Admission and record contract

`POST /api/recognition-results` accepts `application/json` from a loopback peer.
The request is a strict object of at most 66,560 bytes:

```json
{
  "schema_version": 1,
  "session_id": "engineering-session-1",
  "origin": "experimental_replay",
  "result": { "...": "complete RecognitionResult v1" }
}
```

`session_id` is an application archive grouping identifier (1–96 ASCII letters,
digits, dots, underscores or hyphens). It does not authorize or resume an active
Controller conversation. The full result itself remains bounded at 64 KiB.
Typed deserialization rejects duplicate/unknown fields and invalid status
semantics. Origin has only two permitted values:

- `experimental_replay`: validates the entire result using the existing S2
  candidate validator, including frozen RF-v1 profile/preprocess/model identity,
  ordered four-window logits, mean-logit aggregation, quality and correlation.
  Classified/rejected production decisions are rejected under this candidate.
  Unavailable/error records are allowed; uncalibrated predictions remain clearly
  experimental and never become independent labels.
- `synthetic_fixture`: inert demonstrations of the four display states. It
  forbids experimental batches/probabilities/predictions, requires a `synthetic-`
  candidate/source prefix, provisional nameless classes and `synthetic-only`
  decision references with all-zero SHA-256. Any supplied model identity must
  match the same frozen candidate. These fields are demonstration values, not
  scientific evidence; the server and UI always label the record nonproduction.

There is no production import origin. Providing a status or frozen-looking
reference cannot enable recognition. A future admitted executor must have its
own verified delivery path; S6a does not weaken S2's production checks.

Archive validation uses the same profile decoder as the filesystem loader, with
embedded frozen profile/preprocess bytes. It reads no model weights, IQ, dataset,
locked test or arbitrary path from the imported JSON.

## Persistence, recovery and deletion

`recognition_results` is an additive schema migration in the existing SQLite
file, with an indexed creation time and an immutable unique key of application
session, generation, request and candidate. An immediate transaction serializes
writers. Identical retries return the same record ID; conflicting content gets
409 and never overwrites history. Import failures produce no sidecar files.

The full typed request/result is stored as bounded JSON. List/detail reads parse
and validate it again, failing closed on corruption. The public DTO exposes only
archive identity/origin, `production_result=false`, `iq_retained=false`, the S2
observation and the separately marked experimental prediction/probability. Full
window outputs/logits remain internal; neither archive read nor restore adds
anything to a Planner conversation.

Endpoints:

| Request | Result |
| --- | --- |
| `GET /api/recognition-results` | Latest 50 validated summaries, descending ID. |
| `GET /api/recognition-results?before=ID` | Up to 50 older records; no unbounded list. |
| `GET /api/recognition-results/ID` | Validated archive detail; 404 if absent. |
| `POST /api/recognition-results` | Loopback-only bounded replay/demo import; 201 on success or identical retry. |
| `DELETE /api/recognition-results/ID` | Delete one row; 404 if absent; zero files removed. |

Deletion does not parse a possibly corrupt payload, so an unreadable record is
still manually deletable by ID. It enables SQLite secure-delete for that write
but makes no forensic erasure claim about WAL/backups. There is no cascade into
source capture/corpus records and no filesystem deletion derived from imported
paths. Restoring Web state does not restore removed rows or execute old actions.

## Web and terminal use

The existing result page now has “扫频采集 / 识别记录” controls. Recognition lists
show provenance and status; detail displays numeric class/name trust, reason,
calibration/uncalibrated probability, quality and timing. Model/source/hash
references are available in an expandable section. Synthetic classified/rejected
rows carry an explicit nonmeasurement/nonproduction explanation. User-visible
manual delete has confirm/cancel, and pagination keeps older records reachable.
No IQ paths, tensors or full logits are rendered.

The local terminal client uses the same HTTP store:

```bash
python3 jetson-agx/sdrharness/scripts/recognition-results.py \
  --endpoint http://127.0.0.1:8787 import /absolute/path/recognition-import.json
python3 jetson-agx/sdrharness/scripts/recognition-results.py list
python3 jetson-agx/sdrharness/scripts/recognition-results.py show 1
python3 jetson-agx/sdrharness/scripts/recognition-results.py delete 1
```

`--json` before the subcommand returns the same bounded public DTO. `list
--before ID` paginates. The client rejects redirects, proxy routing, nonloopback
endpoints and oversized bodies/responses; it reads only the explicitly selected
JSON import file. `delete ID` is an explicit operator action. There is no silent
automatic retention cleanup of user records.

The interactive Controller/Runner's live recognition persistence and joined
stop remain S5. Actual closed-loop Web/Planner acceptance remains S6b. The
installed Web binary/provider settings are unchanged by this source delivery.
