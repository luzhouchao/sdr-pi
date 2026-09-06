# S4a shared GPU inference lease

The candidate execution contract serializes active local Spark and RF-v1 Mamba
work across processes. It allows both models to remain resident when idle.
S4a does not deploy either service, enable recognition, implement Runner joint
stop, or accept sustained memory/thermal behavior. The production model assets,
FP16 autocast/FP32 Mamba weights and RF-v1 preprocessing stay unchanged.

## Audit and ownership boundary

The Node `RunLease` only serializes Planner turns within one Node process.
The S3 supervisor only serializes Mamba batches. Neither prevents Spark's HTTP
server from continuing GPU generation after the Planner disconnects. A lock
released by a JavaScript `finally` would therefore be insufficient.

`gpu_lease.py` implements a nonblocking Linux flock over one permanent
`inference.lock` inode in a private, owner-only shared directory. Every candidate
model supervisor opens that same inode and passes its descriptor to its owned
model child. Startup/model warm-up and inference acquire the lease. The Mamba
lease covers the entire ordered four-window batch, including GPU transfer and
CPU materialization of all logits. Spark holds the lease until its private
llama server has finished the nonstream completion response.

Explicit release uses a per-supervisor random instance and increasing serial;
a stale, duplicate or foreign token cannot unlock a new lease. Each descriptor
shares its open file description with its child. If the supervisor is killed,
its child retains the flock until Linux parent-death SIGKILL closes the last
inherited descriptor. Both wrappers set this signal and check the fork/parent
race. Normal cancellation or failure kills the owned child process group and
waits for reaping **before** unlocking. A reap failure keeps the gate closed.
Startup cancellation preserves the subprocess handle across async creation.

Never unlink, rotate or replace the shared lock while either service can run.
Do not configure two different gate directories for the two models. Symlink,
hardlink, owner/mode and inode mismatches fail closed. The private same-user
runtime is an application cooperation boundary, not isolation against malicious
processes running as the same Unix user or root.

## Mamba integration

Use the S3 supervisor with `--gpu-lease-root /absolute/private/shared-gate`.
Without that explicit option, the earlier S3 standalone engineering path is
unchanged and makes no shared-GPU claim. An S4a pair requires the option.

The existing one-active/one-waiting admission bound remains in force. Waiting
for the GPU consumes the original 50–5,000-ms entire-batch budget. Cancellation
or expiry while waiting cannot unlock Spark's lease. Failed work follows S3
cleanup and generation advancement. Worker startup/restart also acquires the
gate, with its existing 120-second startup wait budget. Health metrics add
`gpu_acquired/released/wait_us/held_us/cancelled/expired/held`; production
`recognizer_available` stays false. Existing Rust strict health decoding accepts
these numeric metrics, and the unchanged native whole-batch Adapter is reused.

## Owned Spark gateway

`spark-gpu-gateway.py` starts a **separate candidate** BF16 llama server on a
private loopback backend port. It uses the existing binary/model paths, 32,768
context, parallel=1 and current BF16 deployment arguments. A random private
backend key is generated for each gateway instance. The operator supplies a
separate owner-only 16–128 character alphanumeric API key for the gateway.
Neither key is logged. The gateway never controls the installed Spark process.

It exposes authenticated loopback HTTP:

- `GET /health`: instance/child identity, active state and bounded lease metrics;
- `POST /v1/chat/completions`: the existing local Spark provider seam, model
  `spark-x2.5-4b`, one completion, up to 128 messages, a 64-KiB request and an
  explicit 1–1,024 output-token limit;
- other routes, duplicate headers/JSON keys, chunked request bodies and
  unsupported framing fail closed. The backend response is bounded at 2 MiB.

One Spark request may be active or waiting for the shared gate; a second returns
429. At most eight HTTP connections are admitted, incomplete requests have a
one-second read deadline, and completion/lease waiting has a 120-second total
request deadline. Model startup is separately bounded at 180 seconds, with at
most four child starts per gateway invocation. The candidate defaults to 32
requests and 600 seconds of serving, configurable only up to 128/3,600. Initial
lease wait and startup each have their own 180-second cap before serving begins.
There is no unbounded retry or forced lease expiry.

The backend receives `stream=false`. On success the gateway returns the full
JSON completion, or a buffered final SSE chunk followed by `[DONE]` for the
existing streaming SDK. Thus candidate clients receive output only after actual
generation completes. Streaming token latency is not claimed. Client disconnect,
request deadline, malformed/failed backend response, or task cancellation kills
and reaps the candidate llama process before release. A subsequent request may
restart it under the same shared gate. Queued cancellation leaves an idle model
resident. Unknown shutdown/reap state must never be treated as successful release.

Request cancellation does not authorize inference overlap: the next caller may
wait for teardown/restart. Waiting is bounded, not FIFO; overload may expire a
Mamba request while Spark owns the GPU. Fair scheduling and representative
latency/resource acceptance are not inferred from the finite correctness tests.

## Isolated validation and future deployment

Use one unique `/var/tmp/sdrharness-dev/<feature-id>/` root for development,
with sibling `gate`, `spark`, `mamba` and `tmp` directories. The two wrappers must
share the exact same gate root. The candidate gateway and backend ports must be
unused loopback ports. Point a private Planner provider configuration at the
**gateway** `/v1` endpoint, retaining `provider=spark-local` and the standard
local JSON adapter. Do not point Planner at the private backend.

`validate-gpu-lease.py` reuses the S3 ignored Rust synthetic fixture exporter
and native replay command. `planner-worker/scripts/validate-gpu-planner.mjs`
uses the actual provider SDK and `createSparkJsonPlanningStream` to validate a
bounded offline hold plan; it has no SDR executor. No dataset or locked-test
reader is involved. Tests record metadata-only lease acquire/release events
with monotonic timestamps, owner/instance/serial, wait/hold counters and child
PIDs. The in-memory event tail is bounded to 32 per supervisor; stdout volume
is bounded by finite candidate lifetime/request/restart limits.

The old installed Spark endpoint and standalone Mamba command do not participate
in this candidate lock. A1 must route **all** production local GPU inference
through the admitted pair, prevent bypass, provision a stable shared runtime
inode with correct service permissions, and perform coordinated deployment and
rollback. This source delivery does not change saved provider settings or claim
host-wide serialization of unrelated GPU programs. Remote provider selection
remains an explicit existing operator choice, with no automatic fallback.

Example candidate invocations (create the unique feature parent first and choose
unused loopback ports; key file is an explicitly prepared private file):

```bash
python3 jetson-agx/sdrharness/scripts/spark-gpu-gateway.py \
  --runtime-root /var/tmp/sdrharness-dev/FEATURE/spark \
  --gpu-lease-root /var/tmp/sdrharness-dev/FEATURE/gate \
  --port 18016 --backend-port 18017 \
  --api-key-file /var/tmp/sdrharness-dev/FEATURE/gateway-key.txt \
  --max-requests 32 --lifetime-seconds 600

python3 jetson-agx/sdrharness/scripts/amc-worker-supervisor.py \
  --runtime-root /var/tmp/sdrharness-dev/FEATURE/mamba \
  --gpu-lease-root /var/tmp/sdrharness-dev/FEATURE/gate \
  --max-batches 128 --max-restarts 4 --lifetime-seconds 600
```

The retained S3 candidate systemd template has no shared gate configured; it
remains a standalone lifecycle example and is not an S4a deployment recipe.

## S4b candidate CPU prompt-cache bound

The owned candidate Spark command now explicitly sets `--cache-ram 256` (MiB).
The installed llama binary otherwise defaults to an 8-GiB host prompt cache,
which grew as S4b alternated short and long histories. This bound covers the
host prompt cache; it does not shrink the existing 32,768 context GPU KV buffer
or change BF16 weights/f16 KV types. Installed Spark services remain unchanged.
The resource plan and completion boundary are tracked in
[the S4b plan](GPU_RESOURCE_S4B_PLAN_2026-09-06.md) and the authoritative checklist.
