# S4a shared GPU lease validation — 2026-09-06

S4a delivers shared active-inference serialization for an isolated Spark BF16
and epoch-10 RF-v1 Mamba pair. It verifies lease ownership, waiting, cancellation,
process death and recovery. It does not deploy services, enable recognition,
freeze calibration, or complete sustained thermal/resource acceptance.

The clean starting branch was `codex/recognizer-amc-offline-validation` at
`3264bf9b9f20828fddd21bc623b741ca774af2c5`. S1/S2/V1a/S3 completion evidence was
reused; the delivery order selected S4a. The next independent unit is S6a.

## Implementation and review

The Node in-process Planner turn lease and S3 Mamba queue were insufficient to
control a still-running Spark HTTP generation after client cancellation. S4a
therefore places a shared Linux flock in the actual model supervision layers.
Both child processes inherit their supervisor's gate descriptor. The gate covers
model startup/warm-up and complete inference; Mamba acquires once for all four
windows. Explicit release checks an instance/serial token. Cancellation or a
failed backend exchange kills/reaps the owned child before release. Parent-death
SIGKILL retains the inherited gate until the child exits.

The new owned Spark gateway reuses the existing local OpenAI-compatible provider
and JSON adapter. It buffers the backend response until generation has completed,
then returns JSON or a final SSE chunk. Disconnect/timeout cannot cause an early
unlock. A reap failure explicitly makes health unavailable while retaining the
lease. Cancellation across asynchronous child creation preserves the process
handle, and shutdown cancels an in-progress startup task before closing ownership.
The private backend key is validated before truncation; keys/prompts are not
included in lease telemetry.

See [`GPU_LEASE_S4A_INTERFACE.md`](../reference/GPU_LEASE_S4A_INTERFACE.md) for exact budgets,
HTTP/lease contracts, deployment boundaries and why every production local GPU
caller must eventually use the same admitted pair. Existing standalone paths and
installed services are not claimed to participate in this candidate gate.

## Automated verification

- 22 S4a Python tests passed: cross-process/inherited-descriptor exclusion,
  waiting deadlines/cancellation, wrong/stale release tokens, inode/permissions,
  buffered SSE compatibility, busy rejection, Spark disconnect/timeout/crash,
  retained ownership across startup cancellation and closed health/gate on reap
  failure. This count includes the ten S3 lifecycle cases rerun with the Mamba
  gate enabled, plus explicit whole-batch and waiting-owner checks.
- The original ten standalone S3 lifecycle tests also passed.
- All 52 existing Node Planner tests passed. A separate finite live Node script
  exercised the actual provider SDK and `createSparkJsonPlanningStream` through
  the gateway, including the streaming compatibility path.
- The unchanged Rust native Controller was built, and the existing ignored S3
  synthetic fixture export passed. Native RF-v1 replay through the gated real
  Worker independently validated four-window results and S2 unavailable status.
  No Rust implementation or Web code changed; their prior full suites are not
  represented as newly run in S4a.
- Python parsing and `git diff --check` passed. No systemd unit was changed,
  installed or enabled by S4a.

## Finite real AGX validation

The validation script uses one 32,768-byte synthetic RF-v1 fixture and finite
local prompts under `/var/tmp/sdrharness-dev/s4a-906a/`. The fixed native binary,
input and changed-source hashes are retained in the audit. No P201 access, RF
capture, training, full precision experiment, dataset/test read, FPGA/BOOT or
NX offload occurred. The existing frozen epoch-10 FP16 autocast/FP32 weights and
RF-v1 model/preprocessing identities were preserved.

A separate BF16 llama child uses the current Spark binary/model and deployment
arguments, with private candidate ports and keys. The installed `spark-x25`
service stayed active at PID 1150 with its original 2026-09-02 start time; its
provider configuration was not changed. This proves serialization of the
candidate pair, not exclusion of unrelated GPU programs or a deployed global
policy.

| Case | Observed outcome |
| --- | --- |
| Concurrent model startup | Spark and Mamba startup/warm-up acquired the shared lease sequentially. |
| Actual Node Spark → native Mamba → Node Spark | Both Planner calls returned the bounded offline `hold` tool call; Mamba returned four validated windows and S2 unavailable. Both child PIDs stayed resident across normal work. |
| Concurrent Spark completion and Mamba request | Mamba waited for Spark's completion/release, then returned a valid batch. |
| Blocked real Mamba with a waiting Planner | No Spark lease was acquired while Mamba held it. Mamba cancel confirmed only after child death; the waiting Planner then completed. |
| Blocked real Spark with a waiting Mamba | Disconnect killed/reaped Spark before release; Mamba completed, and a later Planner call restarted Spark successfully. |
| Spark supervisor SIGKILL with blocked child | Inherited flock/parent-death fencing allowed waiting Mamba to complete after child exit. A new gateway instance recovered. |
| Mamba supervisor SIGKILL with blocked child | Waiting Planner completed after child exit. Mamba restart removed its recognized orphan and accepted a new replay generation. |
| Final recovery and shutdown | Both native Mamba and actual Node Planner succeeded; all recorded children exited and candidate sockets/spools were cleared. |

Monotonic acquire/release events verify 21 lease intervals, including two
intentional parent-death intervals with no explicit release. For those two,
the waiting process can acquire the same flock only after the killed model
child closes its inherited descriptor. Explicit release order is checked;
interleaved or stale release events fail validation. Six actual model child
PIDs were recorded over four supervisor processes; two supervisors were
intentionally killed, and the final pair exited normally. These are finite
correctness observations, not accuracy, throughput or thermal acceptance.

Review-driven additions covered rare startup-cancellation and failed-reaping
paths with targeted tests. The final-source real fault sequence was repeated
successfully. No model/threshold/precision change was made to pass validation.

## Cleanup and completion boundary

All feature processes and candidate listener ports were checked before exact
removal of `/var/tmp/sdrharness-dev/s4a-906a/`. The removed data comprises only
this unit's synthetic fixture, private candidate keys, logs, sockets, private
CUDA/Triton caches and Cargo staging. No application results, historical corpus,
model assets, installed releases or SDR-local data were removed. Bounded hashes,
lease events, metrics and cleanup accounting remain in
[`GPU_LEASE_S4A_AUDIT_2026-09-06.json`](../evidence/GPU_LEASE_S4A_AUDIT_2026-09-06.json).

S4a completes source and finite real shared-lease correctness. S4b sustained
resources/thermal behavior, S5 Runner and joint stop, S6a/S6b result delivery,
independent label coverage, calibration and A1 production admission remain
open. `recognizer_available=false`; numeric classes remain authoritative and
names provisional. The next default independent delivery is S6a, which is not
implemented in this commit.
