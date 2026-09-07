# 树莓派早期部署与验证合订记录

仅用于历史和回滚审计，原记录时点为 2026-08-31—09-01。当前运行主机为 AGX，
旧部署命令、旧 CLI、未完成项和 FPGA 字样均不代表当前施工任务或授权。
当前状态见[权威清单](../SDR_AGENT_PROJECT_CHECKLIST.md)，顺序见[推进文档](../SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md)。
以下完整保留九份原记录的正文、失败、指标、制品哈希与清理事实；只修正链接位置。

- [SDR_AGENT_CANCEL_VALIDATION_2026-09-01](#pi-6)
- [SDR_AGENT_TERMINAL_DEPLOYMENT_2026-08-31](#pi-3)
- [SDR_AGENT_EXECUTOR_DEPLOYMENT_2026-08-31](#pi-5)
- [SDR_AGENT_WEB_CONSOLE_DEPLOYMENT_2026-09-01](#pi-7)
- [SDR_AGENT_SDRD_OBSERVE_VALIDATION_2026-08-31](#pi-4)
- [SDR_AGENT_PI_DEPLOYMENT_2026-08-31](#pi-2)
- [SDR_AGENT_MVP_VALIDATION_2026-08-31](#pi-1)
- [PI_SOFTWARE_SWEEP_FALLBACK_2026-09-01](#pi-9)
- [SDR_AGENT_RUNNER_DEPLOYMENT_2026-09-01](#pi-8)



---

<a id="pi-1"></a>

## 合并原记录：SDR_AGENT_MVP_VALIDATION_2026-08-31.md

原文件位于提交 `7115b50` 的 `docs/SDR_AGENT_MVP_VALIDATION_2026-08-31.md`；SHA-256：`d46f8219216155dd6a7b72f6c3104d50270e3d12a52d8b137bb1f5c2c5e5b0f4`。

# SDR Agent plan-only MVP validation

Date: 2026-08-31

## Scope

This validation covers only the plan path:

```text
Rust Controller -> Unix socket -> Pi Agent Planner Worker
                -> 4090 llama.cpp/Qwen -> Rust policy validation
```

It did not connect to `sdrd`, retune the AD9361, capture IQ, access FPGA MMIO,
install a service or deploy files to the Raspberry Pi.

## 4090 read-only check

Commands used the established `4090-via-aliyun` SSH operations route. The
`qwen-api.service` user service reported `active`, TCP port `27879` was
listening, and the unauthenticated local `/health` endpoint returned
`{"status":"ok"}`. No 4090 configuration was changed.

The existing project record identifies the Tailnet model path as:

```text
http://100.104.138.63:27879/v1
model id: qwen3.8-27b
```

The API token was read from the existing mode-`0600` WSL credential file. Its
value was not printed, copied into the repository or placed on a command line.

## Offline checks

Environment:

```text
Rust 1.98.0
Cargo 1.98.0
Node.js 22.23.2
npm 10.9.8
pi-agent-core 0.84.4
pi-ai 0.84.4
```

Results:

- Rust Controller: 7 policy/protocol tests passed.
- Planner Worker: 6 protocol/normalization tests passed.
- Rust formatting check passed.
- npm production dependency audit against the npmjs registry reported zero
  vulnerabilities.
- JSONL frames reject unknown top-level request fields and values above the
  configured size limits.

## Live model smoke test

The input instructed the agent to hold. The observation advertised no
candidates, no retune capability, no bounded-IQ capability, no FPGA capability
and no local recognizer. Qwen called the sole `submit_plan` tool with `hold`.
The Rust Controller correlated the request/session IDs and accepted the action
without approval.

The returned reason stated that the requested state should be maintained
because no candidate or safe executable capability was present. No model text
was treated as an executed action.

## Development-host resource sample

After one live request, the persistent Node Worker on x86-64 WSL reported:

```text
RSS: 107076 KiB (about 104.6 MiB)
V8 old-space cap: 96 MiB
```

The process accumulated no additional CPU jiffies during a one-second idle
sample. This is evidence for the development host only, not a Raspberry Pi
measurement. The example systemd gates remain `MemoryHigh=144M`,
`MemoryMax=192M`, and `CPUQuota=25%` until Pi-side RSS/CPU are measured.

## ARM64 artifact

The Controller was cross-built in the verified WSL Rust toolchain:

```text
target: aarch64-unknown-linux-musl
format: ELF 64-bit LSB, ARM aarch64
linkage: statically linked, stripped
size: 606 KiB
sha256: 1d89d9a4a6a08585c0417dc5a85a5b93faee945dc4213ed87ed1402234309a37
```

Artifact path:

```text
raspberry-pi/sdr-agent/controller/target/aarch64-unknown-linux-musl/release/sdr-agent-controller
```

At the time of this initial validation, the artifact had not been copied to or
executed on the Raspberry Pi. It was subsequently deployed and validated; see
[`SDR_AGENT_PI_DEPLOYMENT_2026-08-31.md`](PI_BASELINE_HISTORY.md#pi-2).


---

<a id="pi-2"></a>

## 合并原记录：SDR_AGENT_PI_DEPLOYMENT_2026-08-31.md

原文件位于提交 `7115b50` 的 `docs/SDR_AGENT_PI_DEPLOYMENT_2026-08-31.md`；SHA-256：`b2134ef9de1729a13df839c9428f99094f227a81f9a3d3dd8cf78ac68798e1ae`。

# SDR Agent Raspberry Pi deployment

Date: 2026-08-31

## Result

The plan-only SDR Agent is deployed and enabled on the Raspberry Pi 4. The
Planner Worker starts at boot and successfully calls the existing 4090
llama.cpp/Qwen endpoint. The Rust Controller accepted a conservative `hold`
proposal in a live end-to-end smoke test.

No SDRD command, AD9361 retune, IQ capture, FPGA access, `BOOT.bin` change or
SDR service modification was performed.

## Connection

Deployment commands and all file transfers used the preferred LAN route:

```text
root@192.168.50.194
hostname: pi4
architecture: aarch64
```

The Tailscale fallback `root@100.102.130.52` was also verified. A dedicated
key at `C:\Users\20642\.ssh\pi4_agent_ed25519` was installed for future
non-interactive access. The login password is not stored in the repository or
the connection skill.

The reusable Codex skill is installed at:

```text
C:\Users\20642\.codex\skills\connect-raspberry-pi
```

Its read-only route checker reports both routes healthy and selects LAN.

## Node.js upgrade

The Pi's effective default Node.js was upgraded directly to the official
Node.js `v22.23.2` Linux ARM64 release:

```text
/usr/local/lib/node-v22.23.2-linux-arm64
/usr/local/bin/node -> ../lib/node-v22.23.2-linux-arm64/bin/node
/usr/local/bin/npm  -> ../lib/node-v22.23.2-linux-arm64/bin/npm
```

The official archive SHA-256 was verified before extraction:

```text
013b59cfd2819703a6f4a14ab891fc46fc2a4e3f5bcd92de3fb4929b43e35b30
```

The Debian package remains intact at `/usr/bin/node` with version `v20.19.2`,
so removing the `/usr/local/bin` links restores the previous default without a
package reinstall.

## Installed layout

```text
/opt/sdr-agent/current -> releases/20260831-plan-v2-sdrd-observe
/opt/sdr-agent/releases/20260831-plan-v2-sdrd-observe/bin/sdr-agent-controller
/opt/sdr-agent/releases/20260831-plan-v2-sdrd-observe/planner-worker
/etc/sdr-agent/planner.env
/etc/sdr-agent/request.example.json
/etc/sdr-agent/qwen-api-token
/etc/systemd/system/sdr-agent-planner.service
```

The release and Node runtime are root-owned. The Worker runs as the dedicated
`sdr-agent` system user. `npm ci --omit=dev --ignore-scripts` installed 93
packages and reported zero vulnerabilities.

The current deployed Controller includes the read-only SDRD observation slice
and matches the locally built ARM64 artifact:

```text
sha256 ed492c4d7a2f5dadec86a4e099d8b25dd21be0bb7d04527c31d681fd1bc89534
```

The original `20260831-plan-v1` release remains installed for rollback. Live
SDRD observation validation is recorded in
[`SDR_AGENT_SDRD_OBSERVE_VALIDATION_2026-08-31.md`](PI_BASELINE_HISTORY.md#pi-4).

## Credential handling

The Qwen token source is root-owned mode `0600`. The service obtains a private
runtime copy through systemd `LoadCredential`:

```text
/run/credentials/sdr-agent-planner.service/qwen-api-token
```

The runtime credential is exposed to the service as a file path, not as a
token value in the environment or command line. The first start exposed a
duplicate environment-file path that tried to read the root-only source
directly. The service was stopped, the duplicate setting was removed, and the
final start uses only `LoadCredential`.

## Service state

```text
service: sdr-agent-planner.service
enabled: yes
active: yes
socket: /run/sdr-agent/planner.sock
socket mode: 0660 sdr-agent:sdr-agent
V8 old-space cap: 96 MiB
MemoryHigh: 144 MiB
MemoryMax: 192 MiB
CPUQuota: 25%
TasksMax: 32
```

The service has no shell, SSH, file-editing, SDR, IIO or FPGA tool. Its only
model tool is `submit_plan`.

## Live smoke test

The deployed Rust Controller sent a bounded context containing no candidates
and no retune, capture, FPGA or recognizer capability. The operator instruction
requested a safe hold. Qwen proposed:

```json
{
  "kind": "hold",
  "reason": "No retune, capture, FPGA, or recognition capabilities are available; maintain safe idle state."
}
```

The Controller matched request/session IDs and accepted the plan with
`approval_required=false`. The Worker remained active afterward.

## Raspberry Pi resource result

After startup and one real planning request:

```text
process RSS: 87744 KiB (about 85.7 MiB)
process RSS high-water mark: 105236 KiB (about 102.8 MiB)
cgroup charged memory current: about 37.9 MiB
cgroup charged memory peak: about 55.7 MiB
tasks: 7
```

`CPUUsageNSec` did not increase over a five-second idle sample. Model inference
and KV cache remained on the 4090. The Pi retained about 3.4 GiB available
memory during validation.

## Rollback

Planner rollback does not require touching the SDR:

1. disable and stop `sdr-agent-planner.service`;
2. point `/opt/sdr-agent/current` to a previous release, or remove the current
   link when no previous release exists;
3. restore the prior unit/config if they were backed up;
4. restart only after `systemd-analyze verify` passes.

Node rollback removes only the four `/usr/local/bin` links. The original
Debian `/usr/bin/node` remains version `v20.19.2`.

The remote deployment staging directory was removed after validation. No
reboot was performed; boot persistence is established by the enabled systemd
unit and still needs a future reboot observation for physical verification.


---

<a id="pi-3"></a>

## 合并原记录：SDR_AGENT_TERMINAL_DEPLOYMENT_2026-08-31.md

原文件位于提交 `7115b50` 的 `docs/SDR_AGENT_TERMINAL_DEPLOYMENT_2026-08-31.md`；SHA-256：`4c24727cf16298944d17a22a65ca6c712cd44f42e2be16ea5748658aee6f945a`。

# SDR Agent interactive terminal deployment

Date: 2026-08-31

## Outcome

The Pi now provides a user-facing `sdr-agent` command backed by a persistent
Pi Agent core session and the existing Qwen endpoint on the 4090. The stable
one-shot Planner socket remains available as a fallback.

```bash
sdr-agent
sdr-agent "查看当前 SDR 状态"
```

Deployed release:

```text
/opt/sdr-agent/current
  -> /opt/sdr-agent/releases/20260831-agent-cli-v1
repository revision: 51c29f5
```

The prior release remains intact at
`/opt/sdr-agent/releases/20260831-plan-v2-sdrd-observe`.

## Artifacts

| Artifact | SHA-256 |
|---|---|
| `sdr-agent-controller` | `cf1193d9f3212c2c13ddcea0eff2e9622332ea8ff8e57b61d4f57b3ef337c372` |
| `sdr-agent` | `38088901c632cdd4297aadfa5c5cddbcc54752af5b91e377f619dc9d91acec04` |

Both are stripped, statically linked AArch64 ELF executables built in the
verified Ubuntu 24.04 WSL Rust toolchain. No compiler was installed on the Pi.

## Runtime

`sdr-agent-planner.service` remains enabled and active. The same bounded Node
process owns both sockets:

```text
/run/sdr-agent/planner.sock  stateless one-shot Planner
/run/sdr-agent/session.sock  one interactive Pi Agent session
```

Both sockets were created as mode `0660`, owned by `sdr-agent:sdr-agent`.
One global inference lease prevents the one-shot Planner and interactive
session from running Qwen requests concurrently.

Observed after deployment:

```text
idle MemoryCurrent: about 35-37 MB
post-smoke MemoryCurrent: about 47 MB
MemoryPeak during smoke: about 65 MB
TasksCurrent: 7
systemd MemoryHigh/Max: 144/192 MB
```

## Validation

Before deployment:

- Rust: 16 tests passed;
- Rust Clippy: zero warnings with `-D warnings`;
- Node: 17 tests passed;
- both ARM64 release binaries built and hashed.

Live validation on the Pi:

1. one-shot `sdr-agent "..."` returned a conservative `hold` proposal;
2. Rust correlated and validated the proposal;
3. interactive `/status`, natural language input, `/history`, `/pause`, second
   `/status`, and `/quit` completed successfully;
4. `/pause` advanced `session_generation` from 1 to 2 and cleared stale state;
5. the original one-shot Controller-to-`planner.sock` path passed a regression
   request after the interactive test;
6. the systemd module remained active.

The deployed request template reports the SDR offline with no capabilities,
so Qwen can only propose safe actions such as `hold`. The smoke test did not
connect to SDRD and did not change IIO attributes, FPGA state, SDR `BOOT.bin`,
radio settings or SDR services.

## Operator commands

```text
/status   /history
/approve  /reject
/pause    /resume   /stop
/help     /quit
```

`/approve` records a human decision only. The separate `SdrActionExecutor` is
not enabled, so no approved proposal can mutate hardware in this release.


---

<a id="pi-4"></a>

## 合并原记录：SDR_AGENT_SDRD_OBSERVE_VALIDATION_2026-08-31.md

原文件位于提交 `7115b50` 的 `docs/SDR_AGENT_SDRD_OBSERVE_VALIDATION_2026-08-31.md`；SHA-256：`49d252bcdeeed6201435a0c0edce6f3eaecdfde3dfa312e6fca0aaf724168c68`。

# SDR Agent SDRD observe-path validation

Date: 2026-08-31

## Result

The Rust Controller now has a real read-only `SdrEngine` seam with two
adapters:

- `ReplaySdrAdapter` for deterministic tests;
- `SdrdAdapter` for live `SDRD/1` shadow observations.

The live Pi-to-SDR path passed. The Adapter reduced HELLO, CAPABILITIES and
HEALTH responses to a small `SdrSnapshot`, and a subsequent planning request
used those live capabilities. No mutating SDRD command was implemented or sent.

## Build and tests

WSL Ubuntu 24.04 validation:

```text
Rust/Cargo: 1.98.0
tests: 11 passed
target: aarch64-unknown-linux-musl
format: ELF 64-bit ARM aarch64, statically linked, stripped
size: 677 KiB
sha256: ed492c4d7a2f5dadec86a4e099d8b25dd21be0bb7d04527c31d681fd1bc89534
```

Tests cover replay exhaustion, valid shadow reduction, mismatched response IDs,
unhealthy capability downgrading and the previous planning-policy gates.

## Pi deployment

The new Controller was transferred over the LAN route and installed as:

```text
/opt/sdr-agent/releases/20260831-plan-v2-sdrd-observe
```

`/opt/sdr-agent/current` points to this release. The previous
`20260831-plan-v1` release remains available for rollback. The already-running
Planner Worker was not replaced and remained active.

## Fail-closed check

Before the shadow daemon was started, observe mode returned:

```text
controller_error=connect: Connection refused (os error 111)
```

The Controller did not substitute template capabilities and did not contact the
Planner.

## Temporary SDR shadow probe

The previously validated ARMv7 `sdrd` artifact was relayed through the Pi to
the SDR `/tmp` directory:

```text
sha256: 99961bb4e0a430e8c21a9e5a58ebbd316f19070f53587612848a12b32c2bba12
mode: shadow
fpga_backend: disabled
```

Before serving, `--check-config` and `--probe` passed. The probe reported both
IIO devices visible, health flags zero, no radio-control capability, no raw-IQ
capture and no FPGA identity/capability.

The daemon listened temporarily on `192.168.1.10:43110`. It was not installed
as a service or boot entry.

## Live observation

The deployed Pi Controller returned:

```json
{
  "online": true,
  "healthy": true,
  "health_flags": 0,
  "iio_visible": true,
  "can_retune": false,
  "can_capture_iq": false,
  "fpga_available": false,
  "fpga_backend": "disabled",
  "fpga_summary_version": 0,
  "fpga_abi_version": 0,
  "fpga_capability": 0
}
```

The Adapter validated schema version, response IDs, server identity, protocol,
shadow mode, read-only status, bounded newline framing and QUIT acknowledgement.

## Live observation-to-plan chain

The Controller replaced the request's template health with the live
`SdrSnapshot` and asked the 4090 Qwen Planner for a safe next step. Qwen
returned `hold`, explicitly citing that retune, IQ capture, FPGA and recognizer
capabilities were unavailable and no candidates existed. Rust accepted the
plan with `approval_required=false`.

## Cleanup

After validation:

- the temporary SDR daemon was stopped and port `43110` closed;
- SDR `/tmp` binary, configuration, PID and log were deleted;
- Pi relay files and uploaded Controller staging file were deleted;
- the persistent Pi Planner Worker remained enabled and active;
- a second observe call failed closed with connection refused, confirming the
  temporary SDR daemon was gone.

No IIO attribute, FPGA register, SDR `BOOT.bin`, init entry or radio state was
changed.


---

<a id="pi-5"></a>

## 合并原记录：SDR_AGENT_EXECUTOR_DEPLOYMENT_2026-08-31.md

原文件位于提交 `7115b50` 的 `docs/SDR_AGENT_EXECUTOR_DEPLOYMENT_2026-08-31.md`；SHA-256：`da9b42e61d5a8ae4f7dd0c2f5ba5ab84faf966a489c6bf7c51b3327ff7448b17`。

# SDR Agent Rust executor deployment

Date: 2026-08-31

## Outcome

The Raspberry Pi Rust Harness now contains a deep `SdrActionExecutor` module.
Its interface accepts a `ValidatedPlan` plus a correlated execution
authorization and returns one `ExecutionObservation`. The implementation hides
SDRD/1 connection setup, identity and capability checks, ownership generation,
profile application, bounded capture, status verification, stop/restore, quit,
and a second post-execution health observation.

Two Adapters exercise the same seam:

- `ReplayActionExecutor` for deterministic policy and caller tests;
- `SdrdActionAdapter` for the production SDRD/1 path.

This first slice supports only `capture_bounded_iq`. Survey, inspection,
recognition, automatic loops, and in-flight cancellation remain explicit
unsupported work rather than implicit behavior.

## Authorization and correlation

The Executor rejects an authorization whose request ID or session generation
does not match the validated plan. A plan marked `approval_required` cannot use
automatic authorization. Standalone execute mode accepts the original
`PlanRequest` plus `PlanResponse`, reruns `ControllerPolicy`, and requires
`--approval operator` for the development fixture.

The derived SDR data feature ID is `agent-<generation>-<request>`. The returned
observation retains request ID, generation, candidate ID, sample/byte counts,
sequence, dropped/overflow metadata, safe relative IQ path, and post-restore SDR
health.

## Build and deployment

Rust 1.98.0 validation passed:

- `cargo fmt -- --check`;
- 20 unit/integration tests, including a two-connection controlled SDRD mock;
- `cargo clippy --all-targets -- -D warnings`;
- stripped static `aarch64-unknown-linux-musl` release build.

Final deployed artifact hashes are:

```text
sdr-agent-controller 95a385bda93a0f770b02f302b3cc147bc4412391bd19841ce8f15b873401b38a
sdr-agent            4bb26bcb86aea858aa6b4b353ef7a4e5aa4eb4e9e7f969291ea1c9ef983e83c7
```

The Pi release is:

```text
/opt/sdr-agent/current -> /opt/sdr-agent/releases/20260831-executor-v1
```

The prior `/opt/sdr-agent/releases/20260831-agent-cli-v1` release remains the
immediate rollback. The Planner Worker was not changed or restarted and stayed
active throughout deployment.

## Live controlled execution

The approved development envelope used:

```text
request_id=101
session_generation=11
candidate=development-2442m
center_hz=2442000000
sample_rate_hz=2100000
rf_bandwidth_hz=2000000
samples=4096
maximum_bytes=16384
```

The Pi production Adapter completed controlled hello/capability checks,
ownership, profile application, bounded capture, execution status, stop and
restoration, quit, and a second health observation. It returned 4096 samples,
16,384 bytes, sequence 1, zero reported drops, no overflow, and
`post_execution_sdr.healthy=true`.

The captured file SHA-256 was
`424c1dacc32602df3db0f12b0e4e47eef5206a3fada64e5f93e996de5f558f96`.
The raw IQ itself was deleted and never entered Git.

After execution, the SDR read back its original 2452 MHz LO, 2.1 MS/s sample
rate, 2 MHz bandwidth, `slow_attack`, and scan mask zero. The known libiio 0.21
buffer-disable warning remained visible, while protocol return, health, state
restoration, and IIOD visibility were successful.

## Cleanup and remaining boundary

The following exact temporary directories were resolved, removed, and verified
absent:

```text
SDR: /tmp/sdr-agent-dev/agent-11-101/
SDR: /tmp/sdr-agent-dev/rust-executor-v1/
Pi:  /var/tmp/sdr-agent-dev/rust-executor-v1/
```

Controlled `sdrd` was stopped and was not installed as a service. The terminal
can be launched with `--sdrd` when a reviewed controlled endpoint is already
running; its normal no-flag invocation does not gain hardware authority.
`/stop` still cannot interrupt a synchronous in-flight capture and remains open
in the project checklist.


---

<a id="pi-6"></a>

## 合并原记录：SDR_AGENT_CANCEL_VALIDATION_2026-09-01.md

原文件位于提交 `7115b50` 的 `docs/SDR_AGENT_CANCEL_VALIDATION_2026-09-01.md`；SHA-256：`d933c301c1a07d07e65a2af27478395342c953373ec447b68a8ce4d341962443`。

# SDR Agent in-flight cancellation validation

Date: 2026-09-01

## Outcome

The Pi terminal now keeps an approved SDR action in a Rust background worker,
so `/stop` can call a separate `SdrActionExecutor.cancel()` Adapter without
waiting for Qwen. The SDR C server keeps one exclusive execution connection and
accepts only `CANCEL_SESSION <request_id> <generation>` on an independent
connection while that generation is active.

The SDR-local IIO Adapter has a mutex-protected session cancellation latch. A
cancel arriving before capture enters refill prevents capture from starting; a
cancel during refill calls `iio_buffer_cancel()`. Both cases return through the
existing `capture_failed_restored` path and unlink the partial IQ file.

## Build and test evidence

Native validation passed with warnings denied:

- C `make clean test all`: `sdrd_tests=pass`;
- Rust `cargo fmt -- --check`;
- Rust 21-test all-target suite;
- Rust `cargo clippy --all-targets -- -D warnings`.

Cross-built artifacts:

```text
sdrd (ARMv7 hard-float, GLIBC 2.17/2.4/2.7)
  8bb0aca478f7e34aff5e3b83899a077888c2af1ba36afc947849886a2aa04474
sdr-agent-controller (static AArch64)
  ed8ccb34387dc316e897b6520f6a080d94873baf3d3469387fe2a3a43270b4cc
sdr-agent (static AArch64)
  e27520837441af819148336d75ca1544ec4237cc8a210a85830bb62010e2efeb
```

## Live receive-only validation

The bounded plan was:

```text
candidate: cancel-validation-2442m
center: 2442000000 Hz
sample rate: 2100000 Hz
RF bandwidth: 2000000 Hz
samples: 4194304 complex int16
maximum bytes: 16777216 (16 MiB)
nominal full-capture time: about 2 seconds
```

The Qwen Planner on the 4090 proposed that exact plan, and the Pi Rust
Controller independently validated it as approval-required. `/approve` and
`/stop` were then submitted consecutively to the staged terminal. The final
implementation reported:

```text
hardware action request=202 started
hardware action cancelled and restoration completed: capture_failed_restored
session stopped; old plan invalidated
```

An earlier trial exposed the real startup race where cancellation preceded
`START_SESSION`. That trial completed a full 16 MiB capture and was not counted
as success. The final terminal fixes the race with a 10 ms bounded retry for at
most 500 ms, only when SDRD returns `stale_or_missing_session` and the execution
worker is still running. SDRD continues to reject stale generations.

After the passing trial:

- the cancellation feature directory existed but contained no IQ file;
- a new health observation reported online and healthy with radio control and
  bounded IQ capture still available;
- readback returned the original 2452 MHz LO, 2.1 MS/s sample rate, 2 MHz RF
  bandwidth, `slow_attack` gain mode, and scan-channel mask zero;
- controlled `sdrd` was stopped and never installed or enabled as a service;
- FPGA registers, `BOOT.bin`, transmission state, and persistent SDR
  configuration were not changed.

## Pi deployment and rollback

The Pi release is:

```text
/opt/sdr-agent/current -> /opt/sdr-agent/releases/20260901-cancel-v1
```

`/opt/sdr-agent/releases/20260831-executor-v1` remains available for immediate
rollback. The Planner service stayed active, and the deployed no-hardware
terminal smoke test passed.

## Cleanup

The failed trial's 16 MiB IQ file was deleted before the passing retry. At
feature completion, the following exact development paths were removed and
verified absent:

```text
SDR: /tmp/sdr-agent-dev/cancel-v1/
SDR: /tmp/sdr-agent-dev/agent-77-202/
SDR: /tmp/sdr-agent-dev/agent-77-203/
Pi:  /var/tmp/sdr-agent-dev/cancel-v1/
```

Only source interfaces, tests, configuration examples, hashes, bounded
evidence, and this validation record are retained.


---

<a id="pi-7"></a>

## 合并原记录：SDR_AGENT_WEB_CONSOLE_DEPLOYMENT_2026-09-01.md

原文件位于提交 `7115b50` 的 `docs/SDR_AGENT_WEB_CONSOLE_DEPLOYMENT_2026-09-01.md`；SHA-256：`b4fd3edc7b7bc156468f83c23ca71d9d4d574c4185fd4cb8c18e412779396726`。

# SDR Agent Rust web console deployment — 2026-09-01

## Scope

This slice adds a personal Tailnet-only control surface for the existing SDR
Agent. The web service does not plan, validate policies, access IIO, or speak
SDRD/1 itself. It starts the deployed Rust `sdr-agent` terminal and exposes its
stdin/stdout through a bounded HTTP/SSE session manager.

## Deployed release and rollback

- Pi: `root@192.168.50.194` during deployment
- Tailnet address: `100.102.130.52`
- release: `/opt/sdr-agent/releases/20260901-web-console-v1`
- active link: `/opt/sdr-agent/current`
- retained rollback: `/opt/sdr-agent/releases/20260901-software-sweep-v1`
- service: `sdr-agent-web-console.service`, enabled and active
- URL: `http://100.102.130.52:8787/`

The service binds `100.102.130.52:8787` directly. `ss` confirmed no wildcard,
LAN, or public listener for port 8787.

## Artifact

The web service was built in the isolated Ubuntu 24.04 WSL Rust toolchain with
Rust 1.98.0 for `aarch64-unknown-linux-musl`.

```text
ELF 64-bit LSB executable, ARM aarch64, statically linked, stripped
SHA-256 d7ba579ac14d241af365cada4e028451a11852a7a7658330b10493cbd12dcf8a
```

The service embeds its HTML, CSS and JavaScript, so the deployed release needs
only `bin/sdr-agent-web-console` plus the systemd unit.

## Bounds and access model

- maximum logical conversations: 2
- live terminal processes: 1
- terminal events retained per conversation: 240 hard cap
- automatic compaction threshold: 160 new events
- visible events after compaction: 48
- carry-forward summary: 6 KiB maximum
- command body: 2 KiB maximum
- persisted state: `/var/lib/sdr-agent/web-console/state.json`, root:root `0600`
- systemd `MemoryHigh=48M`, `MemoryMax=64M`, `CPUQuota=20%`, `TasksMax=48`
- no raw IQ or API token is stored or served by the web console

The Planner Worker allows only one owner of `session.sock`. The Rust service
therefore stores one inactive logical conversation rather than starting a
second competing terminal. A process gate waits for `/stop` plus `/quit` to
release the old socket before a newly activated conversation starts. SIGTERM
also follows the same bounded child shutdown path before systemd restart.

The user-facing UI reports `已连接`, `已保存`, and (only after compaction)
`已压缩 N 次`. The compaction count is not a Qwen model version or conversation
number.

## Verification

Repository checks passed:

- `cargo fmt -- --check`
- `cargo test --all-targets`: 3 passed
- `cargo clippy --all-targets -- -D warnings`
- static ARM64 release build and SHA-256 verification

Browser checks were run against a local isolated instance at desktop width and
390 px width. They covered initial state, responsive layout, SSE connectivity,
session creation, button input visibility and the two-session eviction rule.

Live Pi checks then covered:

1. Windows reached `GET /api/state` over the Tailnet address with HTTP 200.
2. Creating a conversation started the real deployed `sdr-agent` with the
   controlled SDRD endpoint.
3. Clicking status produced both `Operator> /status` and the real Controller
   response in the web terminal.
4. A read-only natural-language request displayed Qwen `Agent>` output and a
   Rust-validated `hold` plan in the same stream. No approval or hardware action
   was requested.
5. Creating a second conversation and reactivating the first safely stopped the
   previous terminal, incremented the web context revision, and connected the
   selected conversation without a busy-session error.
6. The service and Planner remained active. The web service measured about
   1.1 MiB `MemoryCurrent` with three tasks during the check.
7. A systemd restart with an active browser SSE connection completed in five
   seconds without timeout; the old terminal PID disappeared, the new service
   restored one terminal owner, and the browser reconnected automatically.
8. SSE reconnection reloads `/api/state`, preventing stale conversation cards
   after a service restart or state recovery.

## Known boundary

The current `sdr-agent` terminal blocks in the Planner read loop while Qwen is
running. Web input is visibly recorded and queued at the process pipe during
that period, but it is not consumed until the model turn ends. This does not
change the direct `/stop` behavior while hardware execution is active. Making
stdin concurrent during Qwen streaming remains an explicit future terminal
milestone.

## Rollback

Rollback does not delete the new release or its state:

```bash
ln -sfn /opt/sdr-agent/releases/20260901-software-sweep-v1 /opt/sdr-agent/current
systemctl disable --now sdr-agent-web-console.service
```

The prior Planner process and release remain independent of the web service.


---

<a id="pi-8"></a>

## 合并原记录：SDR_AGENT_RUNNER_DEPLOYMENT_2026-09-01.md

原文件位于提交 `7115b50` 的 `docs/SDR_AGENT_RUNNER_DEPLOYMENT_2026-09-01.md`；SHA-256：`3804b01758bd1b3f035263d0fa1e396ad4bbe1122b1fbdad48491e2f2d750f06`。

# SDR Agent bounded Runner deployment

Date: 2026-09-01

## Outcome

The Rust Harness now exposes one deep `Runner.run_once(request, approval)`
interface for the production bounded-IQ action. Its implementation hides the
live SDR observation, Planner call, raw proposal audit, deterministic policy
validation, approval correlation, hardware execution, state-restored follow-up
observation and JSONL audit sequence.

The one-shot CLI is:

```text
sdr-agent-controller --mode run-once \
  --request <plan-request.json> \
  --socket /run/sdr-agent/planner.sock \
  --sdrd 192.168.1.10:43110 \
  --approval pending|automatic|operator \
  --audit-log /var/lib/sdr-agent/audit.jsonl
```

`pending` stops before a plan that needs approval, `automatic` is accepted only
below existing policy thresholds, and `operator` is an explicit approval for
the correlated request and generation. Survey, inspection and recognition
plans remain plan-only until their production executors exist; the Runner does
not pretend that they executed.

## Planner reliability gate

The first two live one-shot attempts returned text without calling the sole
`submit_plan` tool. They failed closed before SDR ownership. The Planner now
sets OpenAI-compatible `tool_choice` to the named `submit_plan` function for
every planning request. A Node test verifies that the provider payload is
copied, not mutated, and forces only that allowlisted tool.

The first forced proposal used an unsupported sample rate. Rust rejected it
before SDR ownership. The final request specified the exact 2.1 MS/s contract,
and the model submitted one policy-valid proposal. These failures remain useful
audit evidence instead of being hidden by retries.

## Live execution

The successful correlated plan was:

```text
request_id=201
session_generation=21
candidate=development-2442m
center_hz=2442000000
sample_rate_hz=2100000
rf_bandwidth_hz=2000000
samples=4096
approval=operator
```

The result contained 4096 complex-int16 samples, 16,384 bytes, sequence 2,
zero dropped samples and no overflow. The transient IQ SHA-256 was
`5cade2fe66865e41bca967b3a548256c293ba7f3c58a18da9c7632bf8c252b30`.
Post-execution health retained retune and capture capability while FPGA and
recognizer capability stayed false.

The radio restored to 2452 MHz, 2.1 MS/s, 2 MHz bandwidth, `slow_attack` and
scan mask zero. The raw file and all Pi/SDR development directories were
removed.

## Audit and deployment

The retained root-only audit file is:

```text
/var/lib/sdr-agent/audit.jsonl
mode=0600
sha256=8b2b68b79d89c088d013944eb42b471a335183bfcec4cb0b399ccaf452b6ae4a
```

The successful cycle records `input_observation`, `planner_proposal`,
`validated_plan`, `authorized` and `execution_observation`. Rejected planning
attempts also remain in the same append-only file.

The Pi release is `/opt/sdr-agent/releases/20260901-runner-v1`. Final controller
SHA-256 is
`1651a0efb844bbee1cdcd70c6e9830bea3837ffa6a5b8981cb3364bde0cea7dd`.
The independently rebuilt `/opt/sdr-agent/releases/20260901-fpga-sweep-gate-v1`
remains the immediate rollback rather than aliasing the current release.

Temporary paths removed and verified absent:

```text
SDR: /tmp/sdr-agent-dev/agent-21-201/
Pi:  /var/tmp/sdr-agent-dev/runner-v1/
Pi:  /var/tmp/sdr-agent-dev/planner-required-tool-v1/
workstation: detached rollback build worktree
```


---

<a id="pi-9"></a>

## 合并原记录：PI_SOFTWARE_SWEEP_FALLBACK_2026-09-01.md

原文件位于提交 `7115b50` 的 `docs/PI_SOFTWARE_SWEEP_FALLBACK_2026-09-01.md`；SHA-256：`f818db65078310131a4c03afb777eb22b768dd35e231885042d275474e2aebbf`。

# Pi software sweep fallback validation

Date: 2026-09-01

## Outcome

`p201pro-test sweep` now provides a bounded Pi CPU fallback while the original
FPGA image reports no aggregation capability. One process owns and reuses the
remote IIOD context, RX buffer, RustFFT plan, Hann window, scratch arrays and
sample blocks for the complete sweep. It changes only the RX profile, produces
compact JSON and restores the initial radio profile on success or ordinary
error. It never writes raw IQ to a file.

The interface accepts an explicit comma-separated center list or a continuous
start/stop/step range. Validation enforces board frequency/rate/bandwidth
limits, a maximum point count, 80% bandwidth coverage for continuous ranges,
an estimated 60-second duration cap and a 64 MiB maximum network-IQ budget.
Each point reuses the FFT implementation through
`SpectrumAggregator.reset_for_center()` instead of rebuilding a plan.

## Build and tests

The Docker-backed native suite passed 11 Rust tests and Clippy with warnings
denied. The ARM64 GNU artifact is dynamically linked against the Pi's existing
`libiio.so.0`:

```text
interpreter=/lib/ld-linux-aarch64.so.1
needed=libiio.so.0,libgcc_s.so.1,libm.so.6,libc.so.6
sha256=8c42bdf9028d9c797b856efa733135770c211b414e161ef7fef88479ef7a9f0a
```

## Live bounded sweep

The development plan was:

```text
range=2448000000..2450000000 Hz
step=1000000 Hz
points=3
sample_rate=2100000 samples/s
rf_bandwidth=2000000 Hz
buffer_samples=8192
FFT=2048
overlap=50%
frames_per_point=4
settle=5 ms
maximum_network_bytes=98304
estimated_duration=27 ms
```

The run completed in 449 ms, returned all three points and three merged compact
candidates, and reported `restored=true`. The first AD9361 readback was
2,447,999,998 Hz for a requested 2,448,000,000 Hz; the existing 10 Hz
quantization tolerance accepted it.

Before and after the sweep, the SDR read back 2452 MHz, 2.1 MS/s, 2 MHz RF
bandwidth, `slow_attack` and scan mask zero. Controlled `sdrd` remained healthy
and continued to advertise bounded retune/capture while FPGA capability stayed
false. No transmission, FPGA, `BOOT.bin` or persistent radio setting changed.

## Deployment and cleanup

The Pi release is:

```text
/opt/sdr-agent/current -> /opt/sdr-agent/releases/20260901-software-sweep-v1
```

`20260901-runner-v1` remains the immediate rollback. The exact temporary Pi
directory `/var/tmp/sdr-agent-dev/software-sweep-v1/`, its 6.3 KiB JSON output
and workstation parsing copy were removed and verified absent. No SDR or Pi raw
IQ file was created.

The current fallback is an operator-invoked utility. Agent `survey_band`
execution and a shared Pi hardware lease remain separate work; until those are
implemented, do not run the utility concurrently with an Agent hardware action.
