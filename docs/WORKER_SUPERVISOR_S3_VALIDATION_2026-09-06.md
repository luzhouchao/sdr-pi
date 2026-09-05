# S3 Worker lifecycle validation — 2026-09-06

S3 delivers bounded whole-batch queueing, deadlines, cancellation confirmation,
process restart/ownership fencing and spool cleanup. It was verified with unit
fault tests and a finite real AGX epoch-10 Worker run using one 32,768-byte
synthetic RF-v1 fixture. The installed services were not replaced. Production
recognition remains unavailable; calibration, independent labels, shared GPU
scheduling, Runner integration and sustained resource acceptance remain open.

The clean starting branch was `codex/recognizer-amc-offline-validation` at
`c114c72d4649d4a31fcdadcf4b07c7f040f929fa`. The delivery-order document selected S3;
completed S1/S2/V1a were reused. No P201 connection/capture, transmission, model
training, full precision experiment, locked-test read, FPGA/BOOT or offload work
occurred. The fixed checkpoint/profile/preprocess and FP16/FP32-weight contract
were unchanged.

## Implementation and audit

The old Worker synchronously processed one window per connection. Its backlog
of one did not provide a whole-batch application queue, and it could not receive
cancel while inference blocked. S3 adds an out-of-process Python supervisor that
imports no model runtime and retains the existing RF-v1 Worker as its child.

The supervisor owns one active batch plus one waiting slot, a monotonic entire-
batch deadline, reserved control connections, per-instance/generation fencing,
a bounded idempotent cancellation history, strict spool handoff and bounded
kill/reap/restart. Child health is verified against the pinned candidate receipt.
No input boolean can enable production. Both successful and failed adopted
batches are removed; a cancel acknowledgment cannot precede reaping/removal.
Parent-death SIGKILL and an inherited exclusive lock protect full supervisor
restart. A responsive duplicate is rejected; dead-owner resource teardown may
hold the lock for up to the bounded startup wait before cleanup proceeds.

Rust now supplies a whole-batch Unix Adapter, shared request construction,
strict reply/cleanup correlation, independent cancellation, and explicit
receive-free replay/health/cancel commands. Supervised real-RX selection is an
optional engineering path behind the existing bounded capture checks; no Runner
recognition executor or joined interactive stop is added. Success still converts
through S2 into an unavailable/uncalibrated production observation, with full
experimental outputs kept internal.

See [`WORKER_SUPERVISOR_S3_INTERFACE.md`](WORKER_SUPERVISOR_S3_INTERFACE.md) for
protocol, exact budgets, ownership transitions, failure boundaries and commands.
The finite candidate systemd template is not installable/enabled by this change.

## Automated tests

Ten pure-Python lifecycle tests pass without importing Torch or datasets. They
use separate bounded fake Worker processes and cover:

- startup cancellation retains subprocess ownership until shutdown can reap it;
- four ordered outputs, exact success cleanup and replay rejection;
- one waiting slot, busy rejection, queued vs active cancellation, repeat cancel
  confirmation, real process reaping and next-generation fencing;
- queued expiry independent of a blocked active call, and active deadline cleanup;
- disconnect after handoff, idle Worker SIGKILL/restart and changed child identity;
- malformed shape/hash/source/offset/generation/instance and nonfinite input;
- reserved control responsiveness with eight stalled data peers;
- duplicate ownership refusal and preservation of unknown/symlink data;
- supervisor SIGKILL, child parent-death exit, restart removal of adopted IQ and
  a partial incoming write, and stale supervisor-instance rejection.

The Rust suite passes 89 library tests and 13 terminal tests. A normally ignored
fixture-export test was run separately. New Adapter tests exercise valid output,
stale request/Worker identity, false cleanup acknowledgment, malformed logits,
busy rejection, native cancel confirmation and exact incoming/owned cleanup.
Existing RF-v1/S2 tests verify the shared request construction and result
semantics. All-target Clippy with warnings denied and formatting pass. The
Web dependency compiles with all targets, avoiding the dependent-build omission
found during V1a; no unchanged UI/Planner behavior is claimed as newly validated.

## Finite real AGX Worker validation

`validate-worker-supervisor.py` starts only private finite supervisor/Worker
processes under `/var/tmp/sdrharness-dev/s3-906a/`. It uses the existing synthetic
Rust four-window fixture, not a dataset or independently labeled RF capture.
The fixed file hash and tested native binary hash are in the accompanying audit.
The supervisor uses at most 16 admitted batches, four child restarts and a
600-second lifetime per process; model startup is bounded at 120 seconds.

Final-source evidence shows:

| Case | Observed outcome |
| --- | --- |
| Native Rust replay through real FP16 Worker | Four outputs validated; S2 status unavailable/uncalibrated; all spool paths absent. |
| Blocked real Worker, active and queued deadlines | The queued 100-ms job expired independently; a third job returned busy; the active 1,000-ms call expired, child was killed/reaped and spool removed. |
| Success after deadline restart | New Worker identity/generation; four valid outputs and cleanup. |
| Native Rust queued cancellation | Confirmed cancelled/removal while the blocked active child remained alive. |
| Native Rust active cancellation | Confirmed cancelled only after child exit and removal; repeated cancel remained confirmed. |
| Supervisor SIGKILL with blocked real child | Child exited; exclusive-lock fence prevented overlapping ownership. Restart removed one adopted file and one partial producer file and rejected the stale service instance. |
| Native Rust replay after full supervisor restart | Four valid outputs, false production capability, then clean shutdown with no sockets or spool files. |

The final run loaded four actual Worker processes and two supervisor instances.
The first supervisor was intentionally killed (`-9`); the second exited normally
(`0`). Completed four-window Worker totals were about 155.6, 156.1 and 154.6 ms.
These are bounded synthetic runtime measurements, not field accuracy or a new
precision benchmark. The replay capture timing is fixture metadata, not a live
RF measurement. The final restart acquired the lock in 12 microseconds; the preceding successful
run exercised a 25.2-ms dead-owner wait.

A preliminary real run passed success/deadline/cancel but attempted restart as
soon as the Worker leader appeared dead. The inherited lock was still briefly
held during resource teardown, so restart correctly failed closed. The fix adds
a bounded dead-owner lock wait while retaining immediate duplicate-owner
rejection. The final run repeated the full fault sequence successfully. A /proc
exit race in a test was also corrected by treating disappearance during read as
dead; no kill or lock check was removed. Clippy required moving replay helpers
before the test module. A final startup cancellation guard preserves the child
Process handle across asynchronous creation; its dedicated unit test and the
full real-Worker fault sequence both passed on the final source. No threshold/
model change was made to pass these checks.

## Cleanup and completion boundary

The real run verified all four recorded Worker PIDs dead, normal final supervisor
exit, absence of all three sockets, and empty incoming/owned directories. Feature
process inspection and final exact-path cleanup remove the synthetic IQ,
request/replay files, private kernel caches, logs, test sockets and Cargo staging
under `/var/tmp/sdrharness-dev/s3-906a/`. No SDR-local transient directory was
created, and no application result, corpus, model asset or installed release was
removed. Bounded metrics, hashes and cleanup accounting remain in
[`WORKER_SUPERVISOR_S3_AUDIT_2026-09-06.json`](WORKER_SUPERVISOR_S3_AUDIT_2026-09-06.json).

S3 completes lifecycle correctness/source and isolated real-Worker validation.
It does not complete sustained thermal/resource measurement (S4b), shared GPU
lease serialization (S4a), Runner/interactive joint stop (S5), UI result delivery
(S6), scientific admission or production rollout (A1). The next default
independent unit is S4a; no S4 implementation is included in this commit.
