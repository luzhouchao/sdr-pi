# AGX SDR Harness migration entry

This directory is the deployment-facing entry for cloning the repository to
`/home/jetson/sdrharness` on the Jetson AGX Orin. It reuses the tested Rust
Controller, Planner Worker and Web Console implementations; it does not fork or
copy those implementations into a second tree.

## Runtime ownership

- AGX owns the Agent, Rust Controller, terminal, Web Console, sweep orchestration
  and future CUDA recognition Adapter.
- P201 Pro owns the radio through `sdrd` at `192.168.1.10:43110`.
- Raspberry Pi remains a stopped/standby rollback target after cutover.
- The Planner uses Pi Agent's provider stack with a Web-managed third-party
  OpenAI-compatible Completions or Responses endpoint.
- CUDA/Mamba model loading is intentionally deferred until the framework is
  live-validated on AGX.

The external recognizer seam remains the bounded request/response contract. A
future CUDA/Mamba Adapter may use PyTorch, custom CUDA or TensorRT internally;
callers must not learn those implementation details.

## Clone and offline verification

```bash
git clone https://github.com/luzhouchao/sdr-pi.git /home/jetson/sdrharness
cd /home/jetson/sdrharness
bash jetson-agx/sdrharness/scripts/verify-checkout.sh
```

The verification script is read-only. It does not contact the SDR or start a
service.

## Build

The user will provision the native AGX toolchain. Recommended baseline: Rust
1.98 (the Controller declares a minimum of 1.75), Node.js 22, npm, Git and a
C/C++20 toolchain. CUDA/PyTorch/Mamba packages are deliberately not prerequisites
for the framework build.

Check the installed toolchain, then build against the checked-in lock files:

```bash
bash jetson-agx/sdrharness/scripts/check-toolchain.sh
bash jetson-agx/sdrharness/scripts/build-agent-runtime.sh
```

Artifacts are staged under `.artifacts/sdrharness/bin/`, which is ignored by
Git. The build script runs the Controller, Planner, Web Console, and
dependency-free C++ recognizer-seam tests before copying binaries. The C++
check uses only replay/model-admission interfaces; it does not install or load
an inference runtime or model.

The validated no-sudo AGX toolchain layout uses rustup under
`/home/jetson/.cargo` and the official Node.js aarch64 archive under
`/home/jetson/.local/lib`, with command links in `/home/jetson/.local/bin`.
The Planner systemd template deliberately uses
`/home/jetson/.local/bin/node`; review that path if Node is provisioned another
way.

## Configuration and deployment gate

Do not install services from an unverified clone. After the AGX is online:

1. record JetPack/CUDA/TensorRT, memory, disk, interfaces and current services;
2. verify `192.168.1.20` can reach SDR `192.168.1.10` read-only;
3. confirm no existing collector owns the SDR;
4. copy `config/runtime.env.example` to `/etc/sdrharness/runtime.env`; its
   user-authorized `0.0.0.0` bind follows LAN address changes but also listens
   on every AGX IPv4 interface, so never port-forward it to the Internet;
5. install `config/request.json` as `/etc/sdrharness/request.json`;
6. install binaries under `/home/jetson/.local/lib/sdrharness/bin/`;
7. install the systemd templates only after reviewing their paths and user;
8. start Planner and Web first, then perform read-only SDR observation.

Installing a unit file does not authorize enabling or starting it. Keep both
units disabled until the private environment, binary hashes, LAN exposure and
SDR ownership gate have been reviewed. Before opening a conversation, use the
Web `MODEL UPLINK` panel to configure API protocol, Base URL, Provider ID,
Model ID and API Key. OpenCode Zen is provided as a quick-fill preset, while
all fields remain editable for other providers.

The Web service atomically stores the upstream in
`/var/lib/sdrharness/web-console/provider.json` with mode `0600`. The key is
never returned by the API or included in Web state. The Planner reloads this
file for each new one-shot or interactive Agent; an active conversation keeps
its original provider. Non-loopback endpoints require HTTPS, and invalid,
oversized, loosely permissioned or unknown-field configurations fail closed.

Tailscale was not installed on the 2026-09-01 AGX baseline, so the units do not
declare a dependency on `tailscaled.service`. The all-interface LAN bind was
explicitly requested after testing both `192.168.50.75` and `192.168.1.20`.
This is plain HTTP: submit real provider credentials only from a trusted LAN.

The 2026-09-01 AGX loopback validation passed. The persistent receive-only
`sdrd` was subsequently restored under explicit authorization after confirming
that neither the process nor TCP port 43110 was already active; the AGX
read-only Controller observation then passed. This does not authorize starting
a collector or changing radio state. Evidence is in
[`../../docs/AGX_FRAMEWORK_VALIDATION_2026-09-01.md`](../../docs/AGX_FRAMEWORK_VALIDATION_2026-09-01.md).

Existing AGX Qwen remains untouched and is no longer the configured default.

## Deferred CUDA recognizer

This migration does not install the earlier 1 MiB DS-CNN ONNX model. The future
production Adapter will target CUDA and the user's trained Mamba model. Model
definition, weights, labels, preprocessing, precision, batch policy, warm-up,
CUDA stream policy, numerical references and resource gates will be delivered
as a separate feature after the Agent framework is stable.
