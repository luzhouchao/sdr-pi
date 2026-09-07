# Spark-X2.5 AGX Planner integration validation — 2026-09-02

## Scope

This validation connected the local Spark-X2.5-4B model to the deployed AGX
SDR Agent Planner. It did not enable transmission, arbitrary IIO access, FPGA
writes, boot-image changes, persistent radio changes or a second collector.

## Runtime identity

- Model: official Spark-X2.5-4B GGUF, BF16, not quantized
- External model path: `/home/jetson/Spark/models/Spark-X2.5-4B.gguf`
- Model bytes: `8,229,920,352`
- Model SHA-256:
  `8cecf405a41a4a10f833530910c2e13fde9fb39c325c8afc3c5d10e4181e1a14`
- Runtime: XHToken llama.cpp commit
  `a698f1cc3252597a541bc1fdd2a9975184ae1684`
- Runtime build: Linux AArch64, CUDA 12.6, CUDA architecture 87
- Endpoint: loopback-only `http://127.0.0.1:8010/v1`
- Context: 32,768 tokens; automatic compaction at 90%
- Inference: all model layers on CUDA, F16 KV cache
- Service state after validation: active and enabled for system startup
- Qwen state during validation: stopped and disabled

The private API key remained in a mode-`0600` file outside Git. Its value was
not printed, copied into this document or included in logs.

## Compatibility finding and implementation

The model and endpoint support native tool calls for small requests. With the
complete Planner prompt and tool schema, however, the Spark llama.cpp template
can generate ordinary assistant content before the required tool call and
reach the output-token limit. Pi Agent's standard text content array also
triggered that behavior while a plain string did not.

The deployed `spark-local` path now removes native tools from the provider wire
request, flattens pure-text content arrays, disables thinking for this
structured turn, uses deterministic sampling and requests one action object
with llama.cpp JSON Schema constrained output. The Adapter converts that object
into the same sole Pi Agent `submit_plan` event. Pi Agent tool validation,
Planner normalization, Rust policy, approval, audit and hardware execution are
unchanged. Other providers do not use this compatibility Adapter.

Visible `hold.reason` values are UTF-8-truncated at a code-point boundary when
necessary so they cannot exceed the Rust Controller's 256-byte limit.

## Verification

Planner Worker tests passed: 42 tests, 0 failures. They include constrained
payload preparation, synthetic `submit_plan` event conversion, multibyte reply
bounding and the existing session/protocol/context suites.

Direct isolated real-model probes passed:

- greeting: `hold` returned in approximately 2.7 seconds;
- candidate inspection: `inspect_candidate` returned in approximately 7.9
  seconds with center, sample rate, RF bandwidth and dwell fields present.

The Web provider was atomically saved as:

- API: `openai-completions`
- Provider: `spark-local`
- Model: `spark-x2.5-4b`
- Context: 32,768
- Compression threshold: 90%

The deployed Web/Planner greeting produced a `hold` plan which passed Rust
validation and returned a visible Agent reply.

## Real SDR closed loop

Before execution, the P201 `sdrd` port was reachable and the development run
used `/var/tmp/sdrharness-dev/spark-integration-20260902/` with a 64 MiB hard
cap. AGX reported `839,348,121,600` bytes free. No raw IQ was retained.

Spark proposed and Rust validated:

- start/stop: 2,420,000,000–2,440,000,000 Hz
- points/step: 5 points at 5,000,000 Hz
- sample rate: 10,000,000 Hz
- RF bandwidth: 10,000,000 Hz
- dwell: 250 ms per point
- fixed receive gain: 20 dB
- maximum processed bytes: 81,920

After explicit manual approval, the real P201 completed the sweep in 2,389 ms.
AGX aggregated all five power points, reported a -53.34516 dBFS noise baseline,
zero clipping and verified radio-state restoration. No candidate exceeded the
current deterministic threshold. The Web state exposed the resulting sweep
plot and complete compact point list.

The temporary Planner sockets and the development feature directory were
removed after validation.
