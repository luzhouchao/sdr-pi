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
- Qwen may be reached through the existing AGX-local OpenAI-compatible endpoint.
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
Git. The build script runs the Controller, Planner and Web Console tests before
copying binaries.

## Configuration and deployment gate

Do not install services from an unverified clone. After the AGX is online:

1. record JetPack/CUDA/TensorRT, memory, disk, interfaces and current services;
2. verify `192.168.1.20` can reach SDR `192.168.1.10` read-only;
3. confirm no existing collector owns the SDR;
4. copy `config/runtime.env.example` to `/etc/sdrharness/runtime.env` and replace
   the loopback Web bind with the actual AGX Tailscale IPv4 only if remote access
   is required;
5. install `config/request.json` as `/etc/sdrharness/request.json`;
6. install binaries under `/home/jetson/.local/lib/sdrharness/bin/`;
7. install the systemd templates only after reviewing their paths and user;
8. start Planner and Web first, then perform read-only SDR observation.

The Qwen credential remains outside Git. Never copy or print the existing AGX
Qwen key while preparing the repository.

## Deferred CUDA recognizer

This migration does not install the earlier 1 MiB DS-CNN ONNX model. The future
production Adapter will target CUDA and the user's trained Mamba model. Model
definition, weights, labels, preprocessing, precision, batch policy, warm-up,
CUDA stream policy, numerical references and resource gates will be delivered
as a separate feature after the Agent framework is stable.
