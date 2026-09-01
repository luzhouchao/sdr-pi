# AGX Agent framework validation - 2026-09-01

## Scope and safety

This validation covers the backend-neutral Agent framework on the real Jetson
AGX Orin at `/home/jetson/sdrharness`, starting from Git commit `22cc751` on
`main`. It did not install or load ONNX, Mamba, CUDA model code or model
weights. It did not modify or stop `/home/jetson/agent`, the Spectrum Agent,
the existing capture tasks, `/home/jetson/Qwen`, or Qwen.

During the initial baseline, no production unit was installed, enabled or
started. The only SDR operation attempted in that phase was the Controller's
read-only `observe` mode, whose SDRD/1 command sequence is `HELLO`,
`CAPABILITIES`, `HEALTH`, and `QUIT`. Later deployment and authenticated
health-only validation are recorded below.

## AGX baseline

Recorded at `2026-09-01T12:59:36+08:00`:

- Architecture/kernel: `aarch64`, Linux `5.15.148-tegra`.
- OS: Ubuntu 22.04.5 LTS.
- JetPack/L4T base: L4T R36.4.4, GCID 41062509.
- CUDA compiler: 12.6.68; TensorRT packages: 10.3.0.30.
- Python: 3.10.12; PyTorch is not installed and was not added.
- Power mode: `MODE_50W`.
- Memory: 61 GiB total, 31 GiB available at capture time.
- Root/workspace filesystem: 915 GiB total, 797 GiB available.
- SDR interface: `eno1`, `192.168.1.20/24`, direct route to
  `192.168.1.10`.
- `spectrum-agent-web.service`, `spectrum-agent-predictor.service`, and
  `qwen.service` reported inactive. The existing Qwen `llama-server` process
  remained running and untouched. Existing kernel capture tasks were observed
  and left untouched.
- Tailscale was not installed and `tailscaled.service` did not exist. The
  existing local Qwen listener was present on TCP 8000, and its unauthenticated
  read-only `/health` endpoint returned HTTP 200 with status `ok`. No inference
  request was sent and no Qwen credential was read.

## Toolchain installation

The preflight script initially failed with `missing=rustc`. The following
user-local tools were installed without sudo:

- rustup stable `1.98.0` for `aarch64-unknown-linux-gnu`, including Cargo,
  rustfmt, and Clippy, under `/home/jetson/.rustup` and
  `/home/jetson/.cargo`;
- official Node.js `v22.19.0` aarch64 archive under
  `/home/jetson/.local/lib/node-v22.19.0-linux-arm64`, with npm `10.9.3`;
- command links under `/home/jetson/.local/bin`, which was already on `PATH`.

The Node archive SHA-256 matched the official release manifest:

```text
0b2d9f564b6594222a62c82e1df2efe119dd4a4aff29644f4dd325bf360b6bcc
```

A stale, dangling `/home/jetson/.local/bin/node` link to the absent legacy path
`/home/jetson/pi/runtime/node/bin/node` was replaced with the verified AGX Node
binary. GCC/G++ 11.4.0, make 4.3, pkg-config 0.29.2, libc development headers,
OpenSSL development headers, CA certificates, and curl were already present;
the framework required no additional system development library.

After installation:

```text
rustc 1.98.0
cargo 1.98.0
node v22.19.0
npm 10.9.3
cc/c++ 11.4.0
toolchain_ok architecture=aarch64
checkout_ok root=/home/jetson/sdrharness target=/home/jetson/sdrharness
```

## Native build and tests

`bash jetson-agx/sdrharness/scripts/build-agent-runtime.sh` passed on the AGX:

- Controller: 29 passed, 0 failed;
- Web Console: 5 passed, 0 failed;
- Planner Worker: 22 passed, 0 failed;
- dependency-free C++ recognizer backend and model-loader tests passed;
- Rust formatting checks passed;
- Clippy passed for all targets with warnings denied;
- npm reported 0 known vulnerabilities;
- release builds completed natively on aarch64.

Artifact hashes from `.artifacts/sdrharness/SHA256SUMS`:

```text
16684cf85d38e5f6dd844388ad0bb8611b5f2f2896834505cfbb1c833616e330  sdr-agent
3df16449eafb2662329b7fecc8c53b7005fb54583e768d90ba48b387e6782207  sdr-agent-controller
24684bac6b61e8e1b94271306bab86b3f463a28be6be6032b32586b3fbe16fb6  sdr-agent-web-console
```

The artifacts, Cargo targets, and `node_modules` are ignored build outputs and
are not retained in Git.

## Loopback runtime validation

Planner and Web were started directly from the verified build without
installing systemd units:

- Planner created its one-shot and session Unix sockets with mode `0660`.
- A malformed one-shot request returned a bounded fail-closed protocol error
  without contacting Qwen.
- Web listened only on `127.0.0.1:18787`.
- Web `/` and `/api/state` returned successfully; the initial session count was
  zero.
- A non-secret dummy value was used only to satisfy Planner startup validation;
  no real Qwen credential was read, copied, or printed.

Both temporary processes were stopped directly. The two validation sockets and
`/var/tmp/sdrharness-dev/agx-loopback-20260901` were removed, and their absence
was verified. The Node installer staging directory
`/var/tmp/sdrharness-dev/agx-toolchain-node-20260901` was also removed after its
29,175,461-byte contents were checked against the 64 MiB cap.

## P201 Pro read-only connectivity

Before connection, `ss` showed no existing TCP session between this AGX and
`192.168.1.10:43110`. The direct route selected source `192.168.1.20` on
`eno1`, and one bounded ICMP probe succeeded in 0.385 ms.

The read-only Controller observation then failed closed:

```text
controller_error=connect: Connection refused (os error 111)
```

This proved the direct IP path but not SDRD health at that point: port 43110 was
not listening. No attempt was made during the initial baseline to start `sdrd`,
start another collector, claim radio ownership, change an IIO/radio value,
capture IQ, or stop an existing process.

### Authorized persistent SDRD recovery

At `2026-09-01T13:37:18+08:00`, the user explicitly authorized recovery of the
persistent receive-only service. Before startup, the AGX verified that TCP
43110 was not reachable and had no existing connection. The remote guarded
operation independently rejected an existing `sdrd` PID or IPv4 listener,
verified the executable, configuration and init script under
`/sd/sdr-agent/current/`, and only then installed the init-script copy and
started the service. Its status reported `sdrd is running`.

The AGX TCP probe then succeeded, followed by the Controller's bounded
read-only `HELLO`, `CAPABILITIES`, `HEALTH`, `QUIT` sequence:

```json
{"online":true,"healthy":true,"health_flags":0,"iio_visible":true,"can_retune":true,"can_capture_iq":true,"fpga_available":false,"fpga_backend":"disabled","fpga_summary_version":0,"fpga_abi_version":0,"fpga_capability":0}
```

No acquisition, retune, IIO write, FPGA-register access, `BOOT.bin`/uramdisk
change, or second `sdrd` instance was attempted. The temporary password-helper
directory was deleted and its absence verified; the password content was not
printed, logged, copied into the repository or committed. Because `sdrd` does
not automatically survive a P201 reboot, repeat the same duplicate-instance
and persistent-file gates before any future recovery.

## Third-party Planner and LAN Web follow-up

The initial local-Qwen template was superseded after the user requested a
configurable third-party upstream. The implementation continues to use
`pi-agent-core` and the pinned `@earendil-works/pi-ai` provider/stream stack;
it does not add a parallel inference HTTP client. Each new Agent can select
OpenAI-compatible Chat Completions or Responses through a Web-managed provider
file. OpenCode Go is a quick-fill preset rather than a hard-coded dependency.

The provider interface was first validated with a fake key:

- Web saved `api`, Base URL, Provider ID, Model ID and API Key atomically to a
  regular `0600` file owned by `jetson`;
- GET and DELETE responses never contained `api_key` or the fake key;
- Planner loaded the same strict private file and selected the Pi AI Responses
  path;
- remote HTTP, unknown fields, files above 8 KiB and group/other-readable files
  fail closed; HTTP remains allowed only for loopback providers;
- saving or clearing is rejected while Web owns an active terminal process;
- the configuration is reloaded for each new one-shot or interactive Agent.

The follow-up model-inventory path was tested against an isolated fake
OpenAI-compatible HTTP service. Web successfully reused the saved `0600` fake
credential to query `/models`, returned a sorted/deduplicated model inventory,
adopted bounded context-window metadata when the upstream supplied one, and
never returned the credential. Unit coverage also verifies Bearer delivery
through the private stdin pipe and both common `data` and `models` response
shapes. Browser automation was unavailable because Python Playwright is not
installed on the AGX; static JavaScript syntax and real HTTP integration were
used instead.

The intermediate model-inventory Web binary had SHA-256
`cc9410ab5a3be6cff8f3cd4f28d4e27350b3858352285cc723b9422b35401701`
and was atomically placed at the user-local runtime path. It was subsequently
superseded by the final build and privileged service restart recorded below; no
active Web conversation existed when the intermediate artifact was replaced.

After the user installed and enabled the production templates, the first
Planner start exposed a path-policy mismatch: systemd correctly created
`/run/sdrharness`, while the shared Planner still allowed only the legacy
`/run/sdr-agent` name. The validation was extended to an exact allow-list for
both dedicated names and their per-user development equivalents, with lexical
resolution that rejects traversal and nested paths. The installed Planner then
created both mode `0660` sockets under `/run/sdrharness`; Planner and Web
reported active, and Web listened on `0.0.0.0:8787`. The checked-in AGX
template was then standardized on the shared canonical `/run/sdr-agent` name;
the exact first-template name remains accepted only as a migration path.

The final authenticated validation used the user's OpenCode Go subscription
through the deployed Web and Planner services:

- API `openai-completions`, Base URL `https://opencode.ai/zen/go/v1`, Provider
  ID `opencode-go`, and Model ID `deepseek-v4-flash`;
- context window `196608` and automatic compaction at 90%;
- private provider file `/var/lib/sdrharness/web-console/provider.json`, owned by
  `jetson:jetson` with mode `0600`; the API key was never printed or returned by
  a public API;
- authenticated `/models` returned 33 model IDs, including
  `deepseek-v4-flash`, and no context metadata, so Web correctly retained the
  operator-entered context window;
- a new formal Web conversation observed the real SDR and produced the
  Rust-validated plan `hold`: SDR online, retune and bounded IQ capture
  available, zero candidates, FPGA aggregation unavailable and recognizer
  unavailable;
- the next live generation was stopped while upstream generation was active;
  Web observed the abort and stale-plan invalidation in 381 ms.

Real-provider compatibility required preserving Pi AI's built-in model
`reasoning` and `compat` metadata whenever provider, model, API and Base URL
match its catalog. Unknown third-party endpoints still use the conservative
generic profile. One-shot and interactive runtimes now surface an explicit
upstream error when generation ends without `submit_plan` instead of reporting
only a missing proposal.

This was a health-only receive-side validation. It performed no new IQ capture,
retune, radio/IIO write, FPGA operation or transmission. The current observation
had no candidate, and the Controller correctly forbids inventing one to force a
capture.

At the user's explicit request, the deployment template now binds Web to
`0.0.0.0:8787` so LAN address changes do not require a configuration edit. A
bounded test listener on port 18787 was reachable through both current AGX
addresses, `192.168.50.75` and `192.168.1.20`, and was then stopped. This bind
also exposes the control plane on every AGX IPv4 interface. It is plain HTTP,
must stay on a trusted LAN, and must not be port-forwarded to the public
Internet. The temporary directory
`/var/tmp/sdrharness-dev/agx-provider-ui-20260901` and fake provider file were
removed and their absence verified.

## Bounded cruise authorization and natural-language console

The automatic-control design was checked against the same Pi Agent project
already used by the Planner Worker before implementation. The reviewed
`pi-mono` revision was
`853a80d26c90a14c1886f0ebb8ffaae133ca2185` under the MIT License. The Harness
continues to use pinned `@earendil-works/pi-agent-core` 0.84.4 rather than adding
a second Agent framework. The implementation follows Pi's public abort,
steer/follow-up queue and pre-tool gate patterns; SDR retry accounting remains
in deterministic Rust because Pi Agent has no radio authority.

The AGX console now defaults to step approval, where every action supported by
the production executor waits for `/approve` or `/reject` even when it is below
the automatic threshold. `/auto start <mission>` creates a new session
generation and starts a bounded cruise with all of these independent limits:

- an operator-selected completed-step limit, default 8 and hard maximum 128;
- an operator-selected duration, default 120 seconds and hard maximum 1,800
  seconds;
- cumulative IQ bytes no greater than the request template's `max_iq_bytes`;
- at most five consecutive failed SDR health checks, 10 seconds apart;
- at most five consecutive Planner runs without one validated next action, 10
  seconds apart;
- automatic authorization only below the existing Rust approval threshold;
- immediate Pi Agent abort and direct SDRD cancel from `/stop`.

Any required approval, unsupported/plan-only action, invalid plan, exhausted
budget or fault stops the cruise. In particular, `survey_band` remains
plan-only in the current production executor. The UI and Controller explicitly
say that it was not executed. A true AGX CPU software-sweep Adapter remains
open until acquisition ownership can be cut over without contending with the
existing collector.

The Controller suite passed 35 tests, including separate retry-counter reset,
operator-budget boundary and command-parser tests. The Planner suite passed 33
tests, including the expanded SDR-boundary system prompt, default 90%
context-compaction policy and built-in model-profile preservation. The Web suite
passed 8 tests, including bounded upstream context metadata parsing and private
API-key reuse at the unchanged Base URL. Earlier isolated end-to-end fake-runtime
scenarios proved fifth-failure exit for an unavailable SDR, fifth-failure
exit when the Planner emitted no next action, and operator stop while the
upstream run was active. The fake SDRD served only `HELLO`, `CAPABILITIES`,
`HEALTH` and `QUIT`; no P201 connection, IQ capture or radio write occurred.
All temporary state and sockets under
`/var/tmp/sdrharness-dev/auto-cruise-control/` were deleted and absence was
verified.

The Web console adds a dedicated authorization rail for step approval,
automatic mission entry, operator-editable steps and seconds, and an
always-visible stop button. `/status`, validated
plans, execution results and event-kind labels are shown as natural Chinese;
raw correlation details remain available to the audit path. Python Playwright
was not installed, so validation used JavaScript syntax checking, Web unit
tests and a real isolated HTTP server. Its temporary directory
`/var/tmp/sdrharness-dev/auto-cruise-web/` and the context/UI staging directory
`/var/tmp/sdrharness-dev/auto-cruise-context-ui-20260901/` were removed, and
their absence was verified.

The final AGX artifacts are:

```text
d4b0330412b228b99d11767c3578d14f67af710dae1a612ee85d55d7951cec59  sdr-agent
3df16449eafb2662329b7fecc8c53b7005fb54583e768d90ba48b387e6782207  sdr-agent-controller
9a9a6df261d1c8189f8ebe56e4c625010ab7a5676aaf830cfa463e5269bbde03  sdr-agent-web-console
```

The final artifacts were atomically deployed and Planner and Web were restarted
at `2026-09-01 16:05:49 CST`. Both remained active with zero service restarts;
Web listened on `0.0.0.0:8787`, served the Go preset, editable context window,
90% compression threshold, bounded-cruise controls and immediate-stop button,
and completed the authenticated model/SDR checks above. Spectrum services,
`qwen.service`, the independent `/home/jetson/Qwen` `llama-server`, and existing
capture state were not modified or stopped.

## Deployment gate

The Planner unit's Node path was corrected to the validated user-local
`/home/jetson/.local/bin/node`. The checked-in environment contains no API key;
the Web-managed private provider file is the primary Planner credential path.
The environment fallback is deliberately unusable until a private provider is
configured.

At the user's request, the local `jetson` account was configured for
passwordless sudo with `/etc/sudoers.d/90-jetson-nopasswd`. The installed file is
owned by `root:root`, has mode `0440`, passes `visudo -cf`, and `sudo -n true`
succeeds. The staging copy under
`/var/tmp/sdrharness-dev/passwordless-sudo-20260901/` and the user-runtime test
Planner sockets under `/run/user/1000/sdr-agent/` were removed and their absence
verified.

Because Tailscale is absent, the units no longer order themselves after a
nonexistent `tailscaled.service`. The local Qwen health result remains baseline
evidence but local Qwen is no longer the default upstream. The authenticated
OpenCode Go deployment check is complete; the private key remains outside Git.

The controlled SDR-side `sdrd` listener and read-only observation gates are now
complete. Do not cut SDR acquisition ownership over to AGX until unit paths and
private configuration are reviewed and the current collector ownership state
is rechecked and proven unable to contend for the radio.
