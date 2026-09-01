# AGX SDR Harness migration

Last updated: 2026-09-01

## Decision

Jetson AGX Orin is the primary runtime for the SDR Harness. The intended clone
root is `/home/jetson/sdrharness`. Raspberry Pi 4B is no longer the target for
new Agent, acquisition or inference work; its deployed release remains a
rollback baseline until AGX cutover is live-validated.

The migration covers the Agent framework first. CUDA/Mamba recognition is a
separate later feature. The earlier ultra-light ONNX package is not part of the
AGX migration bundle and must not be used to open `recognizer_available`.

The real AGX clone was natively built and loopback-validated on 2026-09-01.
Direct network reachability to the SDR was healthy, but TCP port 43110 refused
the read-only Controller observation because `sdrd` was not listening. See
[`AGX_FRAMEWORK_VALIDATION_2026-09-01.md`](AGX_FRAMEWORK_VALIDATION_2026-09-01.md).

## Ownership and seams

```text
AGX operator/Web
      |
      v
AGX Rust Controller ---- AGX Pi Agent Worker ---- third-party model API
      |
      +---- future Recognizer interface ---- CUDA/Mamba Adapter (deferred)
      |
      v
SDRD/1 client 192.168.1.20 -> 192.168.1.10:43110
      |
      v
P201 Pro sdrd -> IIO/FPGA
```

The Controller interface remains the authority for policy, limits, approvals,
stale-session rejection and cancellation. Moving the runtime does not grant the
Planner, Web Console or future CUDA Adapter direct radio authority. `sdrd`
continues to own radio state restoration.

The recognizer seam remains backend-neutral. CUDA, PyTorch, Mamba, TensorRT or
ONNX Runtime are Adapter implementation choices and do not belong in Planner or
Controller call sites.

## Repository handoff

Clone without copying Windows workspaces or runtime state:

```bash
git clone https://github.com/luzhouchao/sdr-pi.git /home/jetson/sdrharness
cd /home/jetson/sdrharness
bash jetson-agx/sdrharness/scripts/verify-checkout.sh
```

Excluded intentionally:

- API keys, SSH keys and provider credentials;
- original RadioML/HisarMod datasets and raw IQ;
- Python virtual environments, Node modules, Cargo targets and caches;
- model checkpoints and the discarded small-model staging bundle;
- AGX `/home/jetson/agent` data, logs, reports and `.runtime` state;
- Qwen weights and llama.cpp runtime directories.

## First AGX session

The first AGX build baseline is recorded. Before production installation or
acquisition cutover, retain these gates:

1. retain the recorded `uname`, JetPack/L4T, CUDA, TensorRT, PyTorch, memory and
   disk baseline;
2. recheck Spectrum Agent, predictor, Qwen and collector status without restarting;
3. recheck interfaces and routes, especially AGX `192.168.1.20`;
4. make `sdrd` available through a separately controlled SDR-side operation,
   then repeat TCP/read-only health at `192.168.1.10:43110`;
5. prove no existing collector owns the SDR before starting Harness acquisition;
6. preserve the verified native Rust 1.98, Node 22, Git and C/C++20 toolchain;
7. rerun the native build for the deployment commit and retain its SHA-256 manifest;
8. install Planner and Web only after review; the user-authorized AGX template
   binds all IPv4 interfaces for changing trusted LANs and must not be exposed
   through public port forwarding;
9. validate one read-only Controller observation;
10. plan the acquisition cutover and Pi rollback separately.

Do not start a second collection simply because the clone and build succeed.

## Deferred CUDA/Mamba feature

After the framework is stable, define and deliver:

- the exact trained Mamba checkpoint, model code and SHA-256;
- label order and unknown/noise/open-set policy;
- IQ window, sample-rate/resampling and normalization contract;
- FP16/BF16/FP32 numerical references;
- CUDA architecture, PyTorch/mamba-ssm/Triton versions and AGX compatibility;
- warm-up, batch, CUDA stream, memory, p50/p99 latency and thermal limits;
- same-IQ comparisons against the training environment;
- real P201 calibration and an explicit capability gate.

No model is enabled by this migration document.
