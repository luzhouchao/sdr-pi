# AGX Agent framework validation - 2026-09-01

## Scope and safety

This validation covers the backend-neutral Agent framework on the real Jetson
AGX Orin at `/home/jetson/sdrharness`, starting from Git commit `22cc751` on
`main`. It did not install or load ONNX, Mamba, CUDA model code or model
weights. It did not modify or stop `/home/jetson/agent`, the Spectrum Agent,
the existing capture tasks, `/home/jetson/Qwen`, or Qwen.

No production unit was installed, enabled or started. The only SDR operation
attempted was the Controller's read-only `observe` mode, whose SDRD/1 command
sequence is `HELLO`, `CAPABILITIES`, `HEALTH`, and `QUIT`.

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
file. OpenCode Zen is a quick-fill preset rather than a hard-coded dependency.

The provider interface was validated with a fake key only:

- Web saved `api`, Base URL, Provider ID, Model ID and API Key atomically to a
  regular `0600` file owned by `jetson`;
- GET and DELETE responses never contained `api_key` or the fake key;
- Planner loaded the same strict private file and selected the Pi AI Responses
  path;
- remote HTTP, unknown fields, files above 8 KiB and group/other-readable files
  fail closed; HTTP remains allowed only for loopback providers;
- saving or clearing is rejected while Web owns an active terminal process;
- the configuration is reloaded for each new one-shot or interactive Agent.

No real OpenCode or other subscription key was used and no authenticated model
request was sent, so the live third-party-provider checklist item remains open.

At the user's explicit request, the deployment template now binds Web to
`0.0.0.0:8787` so LAN address changes do not require a configuration edit. A
bounded test listener on port 18787 was reachable through both current AGX
addresses, `192.168.50.75` and `192.168.1.20`, and was then stopped. This bind
also exposes the control plane on every AGX IPv4 interface. It is plain HTTP,
must stay on a trusted LAN, and must not be port-forwarded to the public
Internet. The temporary directory
`/var/tmp/sdrharness-dev/agx-provider-ui-20260901` and fake provider file were
removed and their absence verified.

## Deployment gate

The Planner unit's Node path was corrected to the validated user-local
`/home/jetson/.local/bin/node`. The checked-in environment contains no API key;
the Web-managed private provider file is the primary Planner credential path.
The environment fallback is deliberately unusable until a private provider is
configured.

Because Tailscale is absent, the units no longer order themselves after a
nonexistent `tailscaled.service`. The local Qwen health result remains baseline
evidence but local Qwen is no longer the default upstream. An authenticated
third-party Planner request remains a deployment check after the user enters a
private subscription API key through Web.

The controlled SDR-side `sdrd` listener and read-only observation gates are now
complete. Do not cut SDR acquisition ownership over to AGX until unit paths and
private configuration are reviewed and the current collector ownership state
is rechecked and proven unable to contend for the radio.
