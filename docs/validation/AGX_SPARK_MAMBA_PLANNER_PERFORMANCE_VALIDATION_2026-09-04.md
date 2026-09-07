# AGX Spark/Mamba resource and Planner validation — 2026-09-04

## Outcome

Keep the deployed local Spark-X2.5-4B BF16 model as the default Planner. Keep
the existing Web-managed OpenAI-compatible Completions/Responses provider seam
available for an explicit operator switch, but do not add automatic cloud
failover. Keep Spark and the future production Mamba Worker resident in AGX
memory and serialize their active GPU inference.

This decision follows three bounded observations:

1. BF16 Spark and FP32 Mamba fit in AGX memory together, but deliberately
   overlapping their active inference approximately halves both throughputs.
2. Community Q8 improves Spark token generation speed, but failed more of the
   small receive-planning smoke set than BF16 and is not admitted as the
   production Planner.
3. The available Spark GGUFs do not contain MTP/NextN tensors, and llama.cpp
   n-gram speculation did not provide a stable median improvement.

The normal Agent data dependency is already sequential:

```text
Spark plan -> bounded P201 RX/capture -> Mamba result -> next Spark turn
```

The shared inference gate is therefore a safety invariant for cancellation,
late results and concurrent operator input. It is not intended to unload either
model or add an artificial delay to the normal pipeline.

## Scope and safety

- Host: Jetson AGX Orin, 50 W dynamic-frequency mode.
- No P201 access, RF acquisition, IIO write or transmission was performed.
- The deployed BF16 `spark-x25.service` remained enabled and was never replaced
  by the experimental Q8 server.
- Tests used only finite prompts, a finite 32,768-row RML2018A subset and three
  repetitions per Spark timing condition.
- Test data was isolated under
  `/var/tmp/sdrharness-dev/spark-mamba-concurrency-20260904/` and
  `/var/tmp/sdrharness-dev/spark-q8-mtp-eval-20260904/`.
- Raw IQ, datasets, weights and temporary logs are not committed to Git.

## Pinned assets

| Asset | Bytes | SHA-256 / revision |
| --- | ---: | --- |
| Official Spark-X2.5-4B BF16 GGUF | 8,229,920,352 | `8cecf405a41a4a10f833530910c2e13fde9fb39c325c8afc3c5d10e4181e1a14` |
| XHToken llama.cpp runtime | — | `a698f1cc3252597a541bc1fdd2a9975184ae1684` |
| Community `Spark-X2.5-4B-Q8_0.gguf` | 4,375,020,352 | `58a4fc627cc2b2cbea02f81fb22960938e86bf3e62a2b3ae01c55a678481d46b` |
| Community Q8 repository revision | — | `abenzerps/Spark-X2.5-4B-GGUF@467e8c670675d33bcbc47427c997032781415b29` |
| RML2018A seed44 FP32 checkpoint | 1,691,357 | `e5a1bccdaf4b0290f41b26cb05b8b98565df9d5b07147727d79bbf43f6cb42dd` |

The Q8 file's architecture metadata, 36 layers, 1,000,000-token advertised
context and 290 tensors were readable before testing. Its presence and hash do
not make it a trusted production artifact. The model and dataset lineage for
seed44 remains in
[`AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md`](AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md).

## Timing method

Spark received the same approximately 2,543-token Planner-shaped prompt and
was capped at 128 generated tokens. Each table entry is the median of three
runs. Mamba used seed44 FP32, batch size 256 and 32,768 evenly spaced rows from
the frozen RML2018A test split. The deployed BF16 service stayed resident in
every Mamba and Q8 condition; “idle” below means it had no active generation,
not that its weights were unloaded. The overlap cases intentionally ran both
active GPU workloads at once; they are a contention stress case, not the
intended production sequence.

### Spark results

| Condition | Prompt token/s | Generation token/s | 128-token wall time |
| --- | ---: | ---: | ---: |
| BF16 alone | 1,297.53 | 14.57 | 10.75 s |
| BF16 while Mamba is active | 668.28 | 7.35 | 21.14 s |
| Q8 alone | 1,121.02 | 19.82 | 8.73 s |
| Q8 while Mamba is active | 595.15 | 9.92 | 17.31 s |

Against BF16 alone, active overlap reduced BF16 prompt throughput by 48.50%,
generation throughput by 49.58% and increased wall time by 96.64%. Q8 alone
reduced prompt ingestion by 13.60%, improved generation by 36.07% and shortened
this fixed 128-token wall time by 18.80%.

### Mamba results

| Condition | Pure inference sample/s | Batch inference p50 | Single-sample p50 |
| --- | ---: | ---: | ---: |
| Mamba active; BF16 resident and idle | 2,337.68 | 109.45 ms | 34.28 ms |
| While BF16 Spark is active | 1,167.03 | 225.61 ms | 33.68 ms |
| While Q8 Spark is active | 1,341.49 | 199.91 ms | 34.28 ms |

Active BF16 overlap reduced Mamba batch throughput by 50.08% and increased its
batch p50 by 106.13%. Q8 overlap was less severe but still reduced throughput by
42.61% versus Mamba alone. Single-sample timing is not a concurrency claim: the
repeated microbenchmark can outlive the overlapping Spark request.

During BF16/Mamba overlap, `tegrastats` recorded 99% peak GPU utilization,
18,346 MiB peak system RAM use and 54.031 °C peak `tj`. There was no OOM,
process crash or service failure. This proves short co-residency and bounded
overlap fit, not the still-required production queue/cancellation or sustained
thermal gate. The Q8 run occurred while the production BF16 service was also
resident, so its 24,886 MiB system-RAM peak must not be used as an estimate of
memory saved by replacing BF16.

## Receive-planning smoke

Both variants were exercised through the real Planner Worker and Rust policy
using five synthetic receive-only cases: offline hold, bounded survey,
candidate inspection, unavailable recognizer and explicit stop.

| Planner | Passed | Policy-rejected failures |
| --- | ---: | --- |
| BF16 | 4/5 | Candidate inspection proposed a 48 MS/s sample rate outside the controlled range. |
| Q8 | 3/5 | Survey proposed `dwell_ms=250000`; candidate inspection proposed 43.392 MS/s. |

Rust rejected every invalid proposal and no hardware action occurred. Five
cases are only a smoke test, not a statistically useful quality evaluation.
They are sufficient to block an immediate Q8 production replacement, not to
claim that BF16 has completed a production Planner regression suite.

## MTP and n-gram speculation

The XHToken llama.cpp runtime accepts `--spec-type draft-mtp`, but the official
Spark configuration has no `nextn_predict_layers`, and neither tested GGUF
contains MTP/NextN tensors. Startup failed closed with:

```text
context type MTP requested but model doesn't contain MTP layers
```

`ngram-simple` proposed 134 draft tokens per run and accepted only four
(2.99%); median generation stayed effectively unchanged at 19.82 token/s and
wall time was 0.35% worse than ordinary Q8. `ngram-mod` produced one 36.52
token/s outlier after accepting 64/64 draft tokens, but the other runs accepted
at most one or showed no usable draft data; its median was 19.72 token/s.
Neither mode is enabled.

## Provider decision and retained upstream interface

The repository already has one provider-neutral Planner seam rather than two
Planner implementations. It accepts `openai-completions` or
`openai-responses`, validates remote endpoints as HTTPS, stores credentials in
an owner-only file and reloads a provider selection only for a new
conversation. The Web `/models` query and OpenCode Go upstream path were
previously live-validated.

The retained interface was rechecked without contacting an upstream service:
all eight targeted Planner provider/model-profile tests passed, including both
API protocols, conservative unknown-provider compatibility, loopback-only HTTP
and private-file permission rejection. Both targeted Web provider tests passed,
including remote HTTPS enforcement and omission of the saved key from API
serialization.

On 2026-09-04 the saved deployment configuration was verified, without
printing its key, as:

```text
api=openai-completions
base_url_origin=http://127.0.0.1:8010
provider=spark-local
model=spark-x2.5-4b
context_window=32768
compression_threshold_percent=90
```

The file remained mode `0600`, `spark-x25.service` remained active/enabled and
its authenticated `/health` response was `{"status":"ok"}`. The upstream
interface stays in code and Web settings, but there is no automatic fallback:
changing provider is an explicit operator configuration action and applies to
a newly opened conversation. Rust policy, approvals, receive-only capability
checks and P201 authority do not change with the selected provider.

## Production implications

- Keep BF16 as the current default Planner; retain Q8 only as a reproducible
  experimental candidate until it passes a larger fixed Planner regression.
- Once an admitted Mamba Worker is deployed, load it once and keep it resident
  beside Spark. Do not unload/reload weights between recognition and planning.
- Enforce `Spark turn complete -> Mamba -> result -> next Spark turn`; also make
  `/stop`, timeout and stale-generation paths release or invalidate the shared
  inference lease.
- Keep the upstream API seam available for deliberate operator use. A future
  upstream benchmark may measure network latency and planning quality, but is
  not required for the selected local-first path.
- Do not enable `recognizer_available` from this benchmark. RF preprocessing,
  labels, rejection, production Worker health and end-to-end Runner gates remain
  incomplete.

## Cleanup

The temporary Q8 server on port 18015 was stopped; ports 18012–18015 were
verified closed while the production loopback server on port 8010 remained
listening. After the retained metrics were transcribed, both exact development
directories listed above were deleted with path checks and verified absent.
The 4.1 GiB Q8 copy and temporary benchmark scripts/logs are therefore not
recoverable from this host, but the repository revision, byte count and SHA-256
above permit an exact redownload. No unique dataset or capture was deleted.
