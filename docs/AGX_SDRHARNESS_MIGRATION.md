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

## Ownership and seams

```text
AGX operator/Web
      |
      v
AGX Rust Controller ---- AGX Planner Worker ---- AGX-local or 4090 Qwen
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

- API keys, SSH keys and Qwen credentials;
- original RadioML/HisarMod datasets and raw IQ;
- Python virtual environments, Node modules, Cargo targets and caches;
- model checkpoints and the discarded small-model staging bundle;
- AGX `/home/jetson/agent` data, logs, reports and `.runtime` state;
- Qwen weights and llama.cpp runtime directories.

## First AGX session

AGX was offline while this handoff was prepared. Before any installation:

1. record `uname`, JetPack/L4T, CUDA, TensorRT, PyTorch, memory and disk;
2. record Spectrum Agent, predictor, Qwen and collector status without restarting;
3. record interfaces and routes, especially AGX `192.168.1.20`;
4. test TCP/read-only SDRD health at `192.168.1.10:43110`;
5. prove no existing collector owns the SDR before starting Harness acquisition;
6. install and check the native Rust 1.98, Node 22, Git and C/C++20 toolchain;
7. run the native build and retain its SHA-256 manifest;
8. install Planner and Web only, bound to loopback or the AGX Tailscale IPv4;
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
