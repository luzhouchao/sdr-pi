# S3 RF-v1 Worker lifecycle interface

S3 adds whole-batch supervision around the existing epoch-10 FP16 Worker. The
parent imports no Torch/CUDA runtime and owns scheduling, timeouts, cancellation
and transient IQ. The child remains the hash-pinned, production-disabled RF-v1
Worker with FP32 resident weights and ordered four-window full-logit output.
No model, threshold, physical RX input or Planner action changes.

## Runtime and finite candidate budgets

Run the supervisor with a new dedicated mode-0700 runtime root, never the shared
legacy spool or a corpus/result directory:

```bash
python3 jetson-agx/sdrharness/scripts/amc-worker-supervisor.py \
  --runtime-root /absolute/private/recognizer-runtime \
  --max-batches 128 --max-restarts 4 --lifetime-seconds 600
```

During development, place this root under the unique
`/var/tmp/sdrharness-dev/<feature-id>/` directory required by AGENTS.md. The
`/run` systemd path belongs to a future explicitly installed release.

The current candidate requires finite budgets: at most 10,000 admitted batches,
16 child restarts and 3,600 seconds per invocation. Defaults are 128/4/600. Child
request limits are derived from the finite batch budget; the RF-v1 Worker's
positive finite request requirement stays intact. Startup health has a 120-second
limit. A failed startup/identity check or exhausted restart budget fails closed.
`ready` is scheduling health, never scientific admission;
`recognizer_available` is always false.

The non-installable candidate systemd template additionally uses a control-group
kill boundary and resource limits. It was not installed/enabled by S3. Production
release configuration and positive capability remain A1; sustained resource
acceptance remains S4b/O1. The existing experimental Worker command remains
available for its documented standalone engineering use; supervised callers must
use the supervisor interface, not bypass scheduling via its private child socket.

The runtime contains:

```text
supervisor.lock       exclusive lifetime lock inherited by the child
control.sock          reserved health/cancel listener
supervisor.sock       batch listener
worker.sock           private unchanged per-window Worker protocol
incoming/             producer staging, before ownership handoff
owned/                supervisor-owned batches
```

Only the supervisor manipulates `owned/`. A producer writes one private regular
32,768-byte file, named `batch-{instance_id}-{generation}-{request_id}.f32`, under
`incoming/`. Submission validates all four requests, fixed identities, exact
ordered offsets and request IDs, same capture lineage, actual file hash and
unit shared RMS. The complete file is renamed into `owned/`; the model receives
only the corresponding bounded offsets. Symlinks, hardlinks, permissions,
shape/hash mismatches, mixed batches and stale identities fail closed. Rejected
or not-yet-submitted incoming files remain the producer's responsibility.

## Scheduling and lifecycle

There is one active batch and **one waiting slot**. A third valid submission
returns `busy` without taking ownership. A different generation cannot queue
behind active work. A monotonic `(generation, batch request ID)` high-water mark
rejects replay; the entire ordered four-window batch remains the scheduling unit.

The 50–5,000-ms batch deadline starts on submission validation and includes queue
wait and all four child calls. An independently timed queued expiry removes its
spool promptly; it does not wait for the active call. No per-window response can
reset the batch deadline. Late/cancelled outputs are discarded. Metrics separate
inference deadline from the bounded child-reap/cleanup confirmation interval.

Active cancellation, deadline or Worker failure kills the owned child process
group and waits up to two seconds for reaping, then removes the exact adopted
spool inode. Queued cancellation only removes that queued spool. A cancel reply
is successful only after these actions finish. A bounded eight-entry terminal
summary cache makes repeated confirmed cancellation idempotent; completed work
is never falsely reported as cancelled. Disconnect after handoff also cancels
work. Shutdown closes listeners, reaps the child and completes accepted jobs as
shutdown errors after cleanup.

After child replacement, queued work from the old epoch is discarded and the
minimum generation advances beyond all admitted work. Clients must refresh
health and use a new generation. Supervisor restart creates a new service
instance ID; child restart creates a new Worker instance ID. Both are required
on submit/cancel, and replies echo request/generation and both identities.

Linux parent-death SIGKILL terminates the model child if the supervisor is killed.
The inherited flock prevents a replacement supervisor from racing old process/
GPU resource teardown. Startup rejects a still-responsive owner immediately; for
a dead owner it allows at most three seconds for the inherited lock to release.
It never breaks the lock or kills a guessed PID. After exclusive ownership,
startup verifies and removes at most 16 recognized regular orphan files in each
spool directory, including bounded partial incoming writes. Unknown files,
symlinks or inconsistent ownership fail closed and are preserved for inspection.
This intentionally does not delete arbitrary application data. Cleanup/reaping
failure cannot produce a confirmed-success reply or a ready capability.

There are at most eight data connections and four separately reserved control
connections. Complete request frames are limited to 64 KiB (child frames remain
16 KiB), incomplete frames time out in one second, and reply writes are bounded.
The control listener accepts only health/cancel. Saturating data readers cannot
consume the reserved control connection budget.

## Metadata protocol

Each connection carries one strict JSON object and one newline-terminated reply.
Health uses `{"schema_version":1,"operation":"health"}` on `control.sock`.
The response includes service/Worker instance IDs, ready/fault state, active
request/window, queue depth/capacity, minimum generation, child PID and counters.
Counters include admitted/completed/busy/cancelled/expired/failed work, crashes,
restarts, removed spools, queue wait/total microseconds, connection drops and
startup lock wait. They reset explicitly with a new supervisor instance.

Submit on `supervisor.sock` carries:

```text
schema_version=1, operation=submit
instance_id, worker_instance_id
request_id, session_generation, timeout_ms
requests[4]                 existing strict RF-v1 RecognitionRequest objects
```

Cancel on `control.sock` carries the same version/instance/request/generation
identity with `operation=cancel`, without requests/timeout. Submit/cancel replies
carry status, `spool_removed`, and four validated outputs only for successful
inference; all failure/cancel outputs are empty. Request-level rejections carry
`operation=error` and a bounded code. This is internal execution metadata, not a
Planner observation or a production class decision.

## Rust integration and engineering commands

The Rust whole-batch Adapter uses bounded Unix connect/read/write, checks both
instance IDs and request/generation, confirms spool disappearance, and repeats
per-window validation plus S2 full-result conversion. It polls cancellation
between bounded I/O operations and uses the independent control socket for
confirmation. An unconfirmed cancel/cleanup remains an explicit error; the
client never deletes a file that may still belong to an active Worker.

The existing `recognize-batch-live` engineering command can select this Adapter
with `--recognizer-supervisor-root PATH`. It checks ready/generation and exact
spool free space before any RX work. No S3 live RX was performed. Existing direct
SDR cancellation remains unchanged; joining SDR/Worker cancellation in Runner
and interactive `/stop` is S5, not claimed here.

Receive-free diagnostics are:

```text
sdr-agent-controller --mode recognizer-supervisor-health
  --recognizer-supervisor-root /absolute/private/runtime

sdr-agent-controller --mode recognizer-supervisor-cancel
  --recognizer-supervisor-root /absolute/private/runtime --request cancel.json
```

`recognize-supervised-replay` additionally accepts a bounded JSON
`{batch: ModelReadyBatchSummary, model_bytes_file: absolute_path}` plus the frozen
`--recognition-profile`, `--recognizer-supervisor-root` and an explicit
`--recognizer-spool-root` containing the replay file. It reads only a private
regular direct-child file of exactly 32,768 bytes; it has no dataset/split loader and cannot perform radio work. Its output is explicitly wrapped as
`mode=supervised_replay, synthetic_input=true`. Inference results pass S2 and
remain unavailable/uncalibrated for production. The ignored Rust fixture-export
test and finite validation script provide reproducible synthetic input without
checking IQ into Git or accessing locked test.

## S4a optional shared inference lease

The supervisor now accepts `--gpu-lease-root` for a gate shared with the owned
Spark candidate gateway. This option adds startup and whole-batch serialization,
with inherited ownership through child/parent death. The default standalone S3
path remains unchanged. See [`GPU_LEASE_S4A_INTERFACE.md`](GPU_LEASE_S4A_INTERFACE.md)
for the verified candidate pair and its separate deployment boundary.

## S5 native handoff cancellation correction

On a failed native submit, close/remove producer-owned incoming before checking
service-owned IQ. This prevents a later rename from racing a completed ownership
check. If handoff already won, cancellation and owned cleanup must be confirmed
by the service. The wire contract is unchanged; the delayed-handoff regression
is part of the S5 candidate validation.
