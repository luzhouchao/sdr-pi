# P201 RX-only corpus store validation — 2026-09-05

## Outcome

The AGX now owns a bounded, versioned P201 receive-corpus lifecycle between
Chapter 4 acquisition and Chapter 5/6 evaluation. The deployed Web console
stores one immutable `amc_corpus_manifest_v1` package per capture, indexes its
manifest/record and searchable metadata in SQLite, renders it under the visible
`接收语料` page and exposes a per-record delete button that removes both the
database row and the exact managed files.

This delivery did not transmit, use N210/B210, change a model checkpoint,
enable recognition capability or touch FPGA/BOOT state. The retained live row
is an ambient P201 RX1 capture with label provenance `unknown` and reason
`no_independent_label`; it is receive-domain evidence, not an accuracy sample.

## Storage and admission contract

Application results live outside Git at:

```text
/var/lib/sdrharness/web-console/p201-corpus/<result-id>/
```

Every package contains exactly seven private files:

```text
capture-plan.json
input-profile.json
labels.json
manifest.json
preprocess.json
raw.iq
records.jsonl
```

The root is mode `0700`; every package file is mode `0600`. The package embeds
the exact integration profile, legacy preprocessing spec and provisional label
table that were compiled into the Web release. Their expected hashes are
verified when the service starts. SQLite stores the complete bounded manifest
and record JSON plus the session/day, RF profile, fixed input, samples/bytes,
sequence, content hash and quality fields. It does not copy IQ into the
database.

`POST /api/corpus` is limited to a 384-KiB HTTP body and an AGX loopback peer.
It currently accepts exactly the frozen engineering acquisition shape:

```text
one center
P201 front panel input: RX1
logical/PHY/scan input: RX0 / voltage0 / voltage0,1
rf_port_select: A_BALANCED
sample rate: 2,100,000 samples/s
RF bandwidth: 1,500,000 Hz
manual gain: 50 dB
samples: 4,096 complex ci16_le
maximum IQ: 16,384 bytes
settle: 100 ms
capture timeout: 1,000 ms
```

Before commit, the service revalidates the complete plan/report correlation,
requires the fixed P201 identity and clean Adapter health, decodes the exact
finite IQ length, and recomputes power, Welch/Hann spectrum and clipping from
the submitted bytes. It also requires confirmed radio restoration, removal of
the derived P201 transient path and absence of the recorded AGX temporary path.
Only the five bounded `unknown` reasons can be submitted; there is no
model-prediction or dataset-ground-truth path.

Package creation uses mode-`0700` staging, mode-`0600` create-new files,
`sync_all`, and an atomic directory rename before the SQLite insert. A failed
database insert removes only that exact owned package. Deletion validates the
package as one real child directory containing only the seven known regular
files; an unexpected file or symlink fails closed before removal.

## Automated verification

The following gates passed on AGX:

```text
controller cargo test --all-targets: 70 library + 11 terminal tests
controller cargo clippy --all-targets --all-features -- -D warnings: pass
web-console cargo test --all-targets: 19 tests
web-console cargo clippy --all-targets --all-features -- -D warnings: pass
app.js node --check: pass
```

The new Web tests cover:

- package/SQLite round-trip and exact manual deletion;
- independent validation of the generated package with the Chapter 5 Python
  validator and `--verify-assets`;
- rejection of incomplete cleanup, wrong receive identity and IQ/report
  mismatch;
- refusal to delete a package containing an unexpected file;
- strict UTC, safe-ID and AGX temporary-path handling.

A Playwright smoke test opened the new page at 1,440 × 1,000, observed its
empty state, exercised `GET /api/corpus` and found no browser-console errors.
The live-record test then rendered every RF/quality/identity field, the
manifest and record panels, and used the visible confirmation button to delete
the row. The list changed from one record to zero and the exact package path was
verified absent. The same byte-identical validated capture was subsequently
re-imported so one useful application result remains.

## Live RX-only plan and preflight

The one live acquisition used local feature ID
`p201-corpus-store-20260905`. Before touching the radio:

```text
center: 433,920,000 Hz
point count: 1
sample rate: 2,100,000 samples/s
RF bandwidth: 1,500,000 Hz
manual RX gain: 50 dB
samples: 4,096 complex
maximum bytes: 16,384
conservative duration: 1,100 ms
AGX free bytes immediately before capture: 808,143,536,128
AGX transient: /var/tmp/sdrharness-dev/p201-corpus-store-20260905/capture-staging/
P201 transient: /tmp/sdr-agent-dev/agx-sweep-2026090501-0/
direct stop: SDRD/1 STOP_SESSION 2026090501
```

The credential file was verified as a regular mode-`0600` file and used only
through `sshpass -f`. P201 had exactly one `sdrd` PID (`17136`), exactly one
listener at `192.168.1.10:43110`, and deployed daemon SHA-256:

```text
77d98a005305a4b7531fc3f133e9b4af521e60b065b29fcc304b4c7db80c45ae
```

The read-only radio snapshot before capture was:

```text
RX LO: 2,400,000,000 Hz
sample rate: 30,720,000 samples/s
RF bandwidth: 18,000,000 Hz
gain mode: slow_attack
reported hardware gain: 71 dB
rf_port_select: A_BALANCED
buffer enable: 0
scan voltage0/voltage1: 0/0
```

## Live result

The controlled AGX software sweep completed only after SDRD confirmed
`STOP_SESSION/restored`. The service admitted this result:

```text
result ID: p201-p201-corpus-20260905-rx1-433m-147
captured UTC: 2026-09-04T18:18:46Z
capture day: 2026-09-04
sequence: 147
samples / bytes: 4,096 / 16,384
raw RMS: -54.432029724121094 dBFS
measured SNR: 33.73674011230469 dB
clipped / dropped / overflow / health flags: 0 / 0 / false / 0
healthy: true
label: unknown / no_independent_label
raw IQ SHA-256: 19b9b543188e1a3092e29eeed1232da5586a8c10fe9cd2fa21318d6365993ccb
```

The strict reference validator returned:

```json
{"asset_count":5,"assets_verified":true,"corpus_kind":"p201_receive","label_provenance_counts":{"unknown":1},"manifest_id":"p201-p201-corpus-20260905-rx1-433m-147","record_count":1,"schema_id":"amc_corpus_manifest_v1","source_counts":{"p201_receive":1},"split_counts":{"receive_domain":1},"status":"frozen"}
```

Content hashes for the retained index are:

```text
manifest.json     174df3a32cb05304979233cf0eb577a6032011c657fc9ce8cea24c5397851b83
records.jsonl     541c40067da5d705a5a8e4e4df02f6fd0074d37f1881c0b0925f28227910604b
capture-plan.json cdf02827976b5b72ad0561ecaf7f22213ad86a60323ce31c6f7ab3ef0df11329
raw.iq            19b9b543188e1a3092e29eeed1232da5586a8c10fe9cd2fa21318d6365993ccb
```

Two deployed API failure gates were also exercised without touching the radio:
incomplete cleanup metadata returned HTTP 400, and submitting the otherwise
valid envelope through the AGX LAN address returned HTTP 403. This proves the
write path is not exposed by the visible unauthenticated LAN UI.

After capture, both transient directories were absent. The P201 readback was
byte-for-byte the same state listed above, with PID `17136`, one listener,
buffer `0` and scan mask `00`. The retained application result is deliberately
not development temporary data and remains available to the operator's Web
delete button.

## Deployment and rollback

The active service is `sdrharness-web.service`, with zero restarts after the
final replacement. Deployed artifacts are:

```text
/home/jetson/.local/lib/sdrharness/releases/20260905-p201-corpus-store-v1/sdr-agent-web-console
SHA-256 4e2a56ebe7e303c560046c5dde2bbcc169226201b9e01b19f9454b3472ff2834

/home/jetson/.local/lib/sdrharness/releases/20260905-p201-corpus-store-v1/sdr-agent-controller
SHA-256 6815166ebeec18f92e2a8e69b810bf49a514b61001e42727a383bcc615f2fc29
```

The immediately previous Web binary remains at:

```text
/home/jetson/.local/lib/sdrharness/releases/20260905-pre-p201-corpus-store-v1/sdr-agent-web-console
SHA-256 35f406579d00d7cbc170e27a00ef861365a122456526b1797300fe597c7c81c3
```

The P201 daemon, persistent release, config and startup path were not replaced.

## Cleanup

The capture-stage SigMF pair was deleted before ingestion, and both its AGX
directory and the exact P201 feature directory were verified absent before the
record could be committed. After final tests and deployment, the exact
261,322,908-byte AGX feature root (including the request envelope with base64
IQ, browser scripts/screenshots and release build) was deleted and verified
absent. The Controller and Web Cargo target trees were also cleaned (about
1.3 GiB and 960.5 MiB respectively) and verified absent. A final test-only Web
rebuild created another 630.4 MiB target and was cleaned again.
The retained 16,384-byte application IQ result and the deployment/rollback
releases are outside that cleanup boundary and remain present.
