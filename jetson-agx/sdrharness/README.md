# AGX SDR Harness migration entry

This directory is the deployment-facing entry for cloning the repository to
`/home/jetson/sdrharness` on the Jetson AGX Orin. It reuses the tested Rust
Controller, Planner Worker and Web Console implementations; it does not fork or
copy those implementations into a second tree.

## Runtime ownership

- AGX owns the Agent, Rust Controller, terminal, Web Console, sweep orchestration
  and the production-disabled experimental CUDA/Mamba recognition Worker.
- P201 Pro owns the radio through `sdrd` at `192.168.1.10:43110`.
- Raspberry Pi remains a stopped/standby rollback target after cutover.
- The Planner defaults to the local Spark-X2.5-4B BF16 endpoint. Pi Agent's
  Web-managed OpenAI-compatible Completions/Responses seam remains available
  for an explicit operator switch; there is no automatic cloud failover.
- Offline CUDA/Mamba loading, full held-out corpus validation and one bounded
  P201 RX1-to-Worker integration capture now pass on AGX. Production Worker
  deployment remains deferred until the RF preprocessing, trusted labels,
  precision and rejection gates are frozen.

The external recognizer seam remains the bounded request/response contract.
The experimental Worker uses PyTorch/CUDA/Mamba internally without exposing
runtime objects or model operators through the Controller interface.

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
8. optionally install the P201 recovery oneshot/timer after strict SSH identity
   and the `/sd/sdr-agent/current` release are verified;
9. start Planner and Web, then perform read-only SDR observation.

Installing a unit file does not authorize enabling or starting it. Keep both
units disabled until the private environment, binary hashes, LAN exposure and
SDR ownership gate have been reviewed. The deployed private selection already
points to local Spark. To make an explicit provider change for a new
conversation, use the Web `MODEL UPLINK` panel to configure API protocol, Base
URL, Provider ID, Model ID and API Key. OpenCode Go is provided as a quick-fill
preset, while all fields remain editable for other providers.

Use `查询上游模型` after entering the Base URL and API Key to request the
provider's standard `{Base URL}/models` inventory. If the same Base URL was
already saved, the Web service reuses the private stored key without returning
it to the browser. Select a returned model to fill Model ID, or keep typing a
manual ID when a provider does not expose a compatible model-list endpoint.
The same panel accepts the model context window (8,192–1,000,000 tokens) and an
automatic compaction threshold (50–95%, default 90%). When `/models` returns a
bounded `context_window`, `context_length`, `max_context_length`, `max_model_len`
or common nested equivalent, selecting that model fills the context field;
otherwise the manual value remains authoritative.
Discovery is serialized and bounded to one request, 8 seconds, 512 KiB and 512
model IDs. Redirects are rejected. The key is sent to the bounded `curl`
process through stdin rather than its command line or environment.

The Web service therefore requires `curl` at runtime; the AGX toolchain check
verifies it. AGX now uses the shared canonical `/run/sdr-agent/` directory for
Planner and session sockets. The exact `/run/sdrharness/` name remains accepted
only for migration from the first installed template; other, nested and
traversal paths remain rejected.

The Web service atomically stores the upstream in
`/var/lib/sdrharness/web-console/provider.json` with mode `0600`. The key is
never returned by the API or included in Web state. The Planner reloads this
file for each new one-shot or interactive Agent; an active conversation keeps
its original provider. Non-loopback endpoints require HTTPS, and invalid,
oversized, loosely permissioned or unknown-field configurations fail closed.
For the same saved Base URL, a blank API Key preserves the private stored key,
so the operator can change only the model, context window or 90% compression
setting without making the service return the secret.

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

## P201 SDRD recovery

`systemd/sdrharness-p201-sdrd-recovery.service` and its timer run the bounded
AGX-side recovery path. They never start a collector. The script requires the
mode-`0600` password file and strict pinned host key, serializes itself with a
runtime flock, accepts only one expected daemon/listener or a fully stopped
zero/zero state, and uses the retained `/sd/sdr-agent/current/S60sdrd` entry.
The Web unit wants this oneshot so an AGX/Web restart performs the same check.

P201 currently regenerates its Dropbear key when its RAM root reboots. The
recovery service intentionally fails closed on that change; verify the direct
link and P201/release identity before repinning. Do not disable host-key checks.
Unattended cross-P201-reboot recovery remains blocked until the operator
explicitly chooses whether to initialize the vendor's blank persistent-key NVM
filesystem. See
[`../../docs/SDR_AGENT_SDRD_STARTUP_RECOVERY_VALIDATION_2026-09-03.md`](../../docs/SDR_AGENT_SDRD_STARTUP_RECOVERY_VALIDATION_2026-09-03.md).

## Local Spark Planner

The live AGX deployment uses the official Spark-X2.5-4B BF16 GGUF without
quantization. Model weights, the XHToken llama.cpp runtime and the private API
key remain outside this repository under `/home/jetson/Spark/`. The checked-in
`systemd/spark-x25.service` exposes only `127.0.0.1:8010`, uses a 32,768-token
context, F16 KV cache and full CUDA layer offload. Qwen is stopped and disabled;
Spark is the saved Web provider with a 90% context-compaction threshold.

A bounded 2026-09-04 benchmark confirmed that Spark BF16 and seed44 Mamba fit
in AGX memory together. Deliberately overlapping active inference reduced both
throughputs by approximately half, so the production data dependency remains
`Spark plan -> RX/capture -> Mamba -> next Spark turn` while both models may
stay resident. Community Q8 improved token generation but failed more of the
small Planner smoke set; MTP was unavailable in both GGUFs and n-gram
speculation had no stable median gain. BF16 therefore remains the default. See
[`../../docs/AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md`](../../docs/AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md).

Spark's llama.cpp chat template can emit unbounded assistant prose before a
required native tool call. The Planner therefore asks this provider for one
JSON-Schema-constrained adapter action. It converts a final plan object into Pi
Agent's sole `submit_plan` tool event. When explicitly enabled, the other
adapter action can only submit a text query to the fixed loopback SearXNG
service; the host returns bounded, untrusted snippets and then asks Spark for
the final plan. The model cannot choose the search endpoint, fetch an arbitrary
result URL, follow redirects, or use search results to override the system
prompt, measured SDR state, hardware limits or Rust policy.

The AGX template enables at most two searches per planning turn, eight sources
per search, a 15-second search timeout and a 512 KiB response ceiling. Search
queries and source URLs are visible in the Web terminal under `网络搜索`. The
model still has no shell, file, unrestricted network, SDR, IIO or FPGA
authority, and the existing Rust policy and manual approval gates remain
authoritative. Other providers retain their native Pi Agent tool-call path and
do not receive this Spark-specific host adapter.

The 2026-09-02 live test covered Web configuration, a normal greeting, model
selection of all sweep parameters, Rust validation, manual approval, real P201
execution, AGX aggregation, zero clipping and verified radio restoration. See
[`../../docs/SPARK_X25_AGX_INTEGRATION_VALIDATION_2026-09-02.md`](../../docs/SPARK_X25_AGX_INTEGRATION_VALIDATION_2026-09-02.md).
The bounded local web-search deployment and real browser/model validation are
recorded in
[`../../docs/SPARK_X25_WEB_SEARCH_VALIDATION_2026-09-02.md`](../../docs/SPARK_X25_WEB_SEARCH_VALIDATION_2026-09-02.md).

## Experimental CUDA/Mamba validation and deferred production recognizer

This migration does not install the earlier 1 MiB DS-CNN ONNX model. The
experimental Adapter targets CUDA and the user's trained AMC-Mamba D8 model;
it remains explicitly outside production admission.

The AGX-local, Git-ignored `local-assets/amc-eval/` directory now contains the
verified RML2018A/HisarMod2019 datasets, selected seed44/seed43 checkpoints,
fixed split files, minimum frozen model source, Python 3.10 `venv`, locally
compiled ARM64/sm_87 wheels and complete FP32 evaluation artifacts. Re-run a
bounded deterministic smoke subset with:

```bash
local-assets/amc-eval/runtime/venv/bin/python \
  jetson-agx/sdrharness/scripts/evaluate-amc-mamba.py \
  --dataset rml2018a --precision fp32 --batch-size 256 --limit 512
```

This tool reads only the pinned offline corpus and does not contact an SDR.
Complete accuracy, logits parity, latency, memory and thermal evidence is in
[`../../docs/AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md`](../../docs/AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md).

The strict experimental Worker can be checked without an SDR using:

```bash
local-assets/amc-eval/runtime/venv/bin/python -B \
  jetson-agx/sdrharness/scripts/amc-mamba-worker.py --self-test
```

The Controller also exposes an explicit engineering-only `--mode
recognize-live` path using
`raspberry-pi/sdr-agent/controller/config/live-recognition.experimental.example.json`.
Its one real P201 RX1 capture, preprocessing limitation, result, radio
restoration and cleanup are recorded in
[`../../docs/P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md`](../../docs/P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md).

The systemd template
`systemd/sdrharness-amc-mamba-experimental.service` has no `[Install]` section
and must not be enabled. Trusted labels, an RF-to-training preprocessing and
retraining contract, precision, rejection, concurrency and sustained thermal
gates are still pending, so the runtime capability remains false.
The current checked Chapter 1–6 order and exact remaining integration gates are
in
[`../../docs/CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](../../docs/CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md).
