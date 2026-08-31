# P201 NX Load Benchmark Baseline

Date: 2026-06-08

Scope: offline/local benchmark only. No SSH was used by the new benchmark, no SDR
`/sd` was touched, no ROS, SDR streaming runtime, mapping, RTAB-Map,
`robot_controller`, `cmd_vel`, or active `robot_control` path was started or
modified.

## Inputs

- Required project docs: `AGENTS.md`, `VERSION_ROUTE.md`, `HANDOFF.md`,
  `README.md`, `NX_SDR_READONLY_ANALYSIS.md`, `OFFLOAD_VALIDATION_PLAN.md`.
- Current SUM8 evidence:
  - `reports/sum8_aggregate_client_20260608.json`
  - `reports/sum8_aggregate_batch_ssh_20260608.json`
  - `reports/sum8_fpga_assisted_shadow_backend_20260608.md`
- Offline benchmark output:
  - `reports/stage_nx_load_benchmark_baseline/nx_load_benchmark_baseline_20260608.json`

Command used:

```powershell
python experiments\nx_load_benchmark_baseline\benchmark_nx_load_baseline.py --iterations 100 --warmup 10 --out-json reports\stage_nx_load_benchmark_baseline\nx_load_benchmark_baseline_20260608.json
```

## Decision

Priority order for mainline planning:

1. `aggregate`: keep pushing the V8-derived low-NX-load aggregate/event-summary
   path first.
2. `fft_summary_top_bin_band_power`: next highest compute value, but only as an
   isolated timing-reviewed kernel with summary registers, not full-spectrum
   AXI-Lite readback.
3. `per_frame_summary`: keep as ABI base and fallback, but it is lower
   incremental value than AGG8 for scan/AoA windows.

Reason: SUM8/AGG8 is already hardware-validated and gives the best risk-adjusted
load reduction now. FFT/PSD summary removes larger math blocks, but V9A/V9B0
showed AD9361/IIO sensitivity after added logic, so FFT-class work should wait
until the low-load V8-derived path is clean and isolated.

## SUM8 Aggregate Burden Reduction

Existing measured transport:

| Path | Median per aggregate |
|---|---:|
| Paramiko/devmem style client | 0.837 s |
| One batched SSH exec per AGG8 capture | 0.287 s |

Observed median transport improvement: `2.92x` faster, `65.7%` elapsed reduction.

Modeled burden for `frame_len=64`:

| Aggregate window | Per-frame summary devmem commands | AGG8 devmem commands | Devmem reduction | Batched SSH reduction vs 1 exec/frame | Raw-IQ payload vs AGG8 MMIO payload |
|---:|---:|---:|---:|---:|---:|
| 16 frames | 608 | 46 | 92.4% / 13.2x | 16x | 52.5x |
| 64 frames | 2432 | 46 | 98.1% / 52.9x | 64x | 210x |
| 256 frames | 9728 | 46 | 99.5% / 211.5x | 256x | 840x |

Interpretation: AGG8 is not just saving arithmetic. It collapses repeated
per-frame control/read/poll loops into one stable aggregate page. The remaining
big gap is transport: a C++ mmap/UIO path should replace Python/devmem/SSH before
any live shadow/assist work.

## CPU Work Removed By Candidate

Local PC synthetic-IQ timing, 100 iterations:

| Work item | Median |
|---|---:|
| SUM8-style dual-RX aggregate primitives, 64x64 samples | 0.103 ms |
| SUM8-style dual-RX aggregate primitives, 256x64 samples | 0.600 ms |
| Spectrum FFT/PSD reference, NFFT 2048 | 0.347 ms |
| Dual-RX AoA reference with FFT, NFFT 2048 | 0.794 ms |
| Future FFT summary consumer only | 0.0008 ms |
| SUM8 summary consumer only | 0.0023 ms |

These are PC-local numbers, not final NX runtime numbers. They are useful for
relative shape: FFT/AoA FFT blocks are the largest pure compute target, while
AGG8 is the lowest-risk target and the strongest SSH/devmem/polling reduction.

If FPGA provides FFT top-bin/band-power/noise/prominence summaries, NX can skip:

- int16-to-float FFT input normalization for every window.
- Hanning window application.
- complex FFT and `fftshift`.
- PSD magnitude/log conversion.
- peak bin search.
- median noise floor and peak prominence reduction.
- repeated PSD compression for UI payloads.
- for AoA, two-channel FFT, RX0 peak search, and cross-spectrum summation around
  peak bins if the FPGA summary includes a matched cross-bin summary.

NX should still keep calibration, policy, fallback, final AoA geometry, logging,
and publication.

## C++ mmap/UIO Hot Path

Recommended runtime shape for a later off-by-default shadow/assist backend:

1. Discover the tap through UIO metadata or a fixed experiment config. Open and
   `mmap` once during backend initialization.
2. Read and validate identity once: `SUM8`, ABI `0x00010002`, capabilities,
   `QUA8`, `AGG8`, build IDs, and aggregate limit.
3. In the hot loop, use only MMIO loads/stores:
   - write `FRAME_LEN`
   - write `AGG_TARGET`
   - write `AGG_CONTROL = clear|enable`
   - trigger `CONTROL`
   - poll `AGG_CONTROL.done` with a bounded timeout
   - read the aggregate page into a stack struct
4. Reject and fall back immediately on timeout, stale `last_frame`, wrong
   `agg_frames`, wrong `agg_samples`, overflow bit, invalid capability/build,
   low confidence, or clipped/quality-gated result.
5. Compute only light scalar composition on NX: dBFS, `sqrt`, `hypot`, `atan2`,
   calibration, and final AoA/policy.

Hot loop rules:

- No SSH.
- No `devmem` subprocess.
- No Python in the runtime decision path.
- No fork or malloc in the loop.
- No blocking network dependency.
- No log spam.
- CPU/GPU result remains the source of truth until shadow validation passes.

## Recommendation

Prioritize aggregate first. Specifically, convert the SUM8/AGG8 read path from
Python/devmem/SSH into a C++ mmap/UIO hot path and use it as an off-by-default
shadow primitive provider. This gives immediate, hardware-validated load
reduction and preserves rollback.

Plan FFT summary second: top bins, band powers, noise floor, prominence, and
optionally cross-bin summaries. Keep it summary-only and isolated; do not add
full FFT/PSD vector readback or DMA until the register-summary path proves value
under shadow logs.
