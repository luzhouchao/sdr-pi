# AGX SDR Harness migration

Last updated: 2026-09-05

## Decision

Jetson AGX Orin is the primary runtime for the SDR Harness. The intended clone
root is `/home/jetson/sdrharness`. Raspberry Pi 4B is no longer the target for
new Agent, acquisition or inference work. AGX receive ownership and the P201
SDRD/1 acquisition cutover are live-validated; the Pi release remains only a
rollback baseline.

The migration covered the Agent framework first. CUDA/Mamba remains a separate
production feature, although the selected D8 checkpoints and complete offline
FP32 corpora now pass on AGX. The earlier ultra-light ONNX package is not part
of the AGX migration bundle and must not be used to open
`recognizer_available`.

The real AGX clone was natively built and loopback-validated on 2026-09-01.
After an explicitly authorized recovery of the persistent receive-only `sdrd`,
the AGX also completed a healthy read-only Controller observation on TCP 43110.
See
[`AGX_FRAMEWORK_VALIDATION_2026-09-01.md`](AGX_FRAMEWORK_VALIDATION_2026-09-01.md).

## Ownership and seams

```text
AGX operator/Web
      |
      v
AGX Rust Controller ---- AGX Pi Agent Worker ---- local Spark / model API
      |
      +---- Recognizer interface ---- CUDA/Mamba Adapter (production deferred)
      |
      v
SDRD/1 client 192.168.1.20 -> 192.168.1.10:43110
      |
      v
P201 Pro sdrd -> Linux/IIO RX
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
- tracked model checkpoints, datasets and runtime environments; current
  machine-local assets live only under ignored `local-assets/amc-eval/`;
- AGX `/home/jetson/agent` data, logs, reports and `.runtime` state;
- Qwen weights and llama.cpp runtime directories.

## Historical first-session gates

The first AGX build baseline is recorded. These were the installation and
acquisition-cutover gates; keep them as regression checks even though the
receive-only cutover is now complete:

1. retain the recorded `uname`, JetPack/L4T, CUDA, TensorRT, PyTorch, memory and
   disk baseline;
2. recheck legacy Spectrum Agent, predictor, Qwen and collector status without
   restarting anything;
3. recheck interfaces and routes, especially AGX `192.168.1.20`;
4. recheck the persistent `sdrd` and TCP/read-only health at
   `192.168.1.10:43110` after any P201 reboot;
5. prove no existing collector owns the SDR before starting Harness acquisition;
6. preserve the verified native Rust 1.98, Node 22, Git and C/C++20 toolchain;
7. rerun the native build for the deployment commit and retain its SHA-256 manifest;
8. install Planner and Web only after review; the user-authorized AGX template
   binds all IPv4 interfaces for changing trusted LANs and must not be exposed
   through public port forwarding;
9. retain the completed read-only Controller observation evidence;
10. plan the acquisition cutover and Pi rollback separately.

Do not start a second collection simply because the clone and build succeed.

## CUDA/Mamba status and remaining production work

Completed offline on 2026-09-04:

- selected RML2018A seed44 and HisarMod2019 seed43 checkpoints with exact
  clean model source and SHA-256;
- Jetson PyTorch, Mamba2 and causal-conv1d runtime on Orin `sm_87`;
- complete FP32 test splits, confusion/per-class/per-SNR metrics, latency,
  memory and thermal measurements;
- same-IQ FP32 logits comparison against the 4090 training environment.

Still required for production:

- label order and unknown/noise/open-set policy;
- IQ window, sample-rate/resampling and normalization contract;
- FP16/BF16 comparison and final precision/threshold policy;
- bounded Worker queue, cancellation, drop accounting and sustained thermals;
- real P201 calibration and an explicit capability gate.

The evidence is in
[`AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md`](AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md).
No production model is enabled by this migration document.
