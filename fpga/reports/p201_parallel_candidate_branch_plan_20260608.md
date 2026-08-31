# P201 Parallel Candidate Branch Plan

Generated: 2026-06-08

## Rule

Run candidates as independent branches or isolated write scopes. Merge into the mainline only after explicit acceptance. Hardware-changing candidates must pass PC artifact gates before any SD staging discussion.

## Active Candidates

| Candidate | Work Area | Purpose | Merge Gate |
|---|---|---|---|
| V10 FFT summary | current worktree, `experiments/v10_fft_kernel_baseline` | Prove Xilinx XFFT/OOC spectral-summary path | OOC timing/util evidence and summary-only ABI recommendation |
| V8 low-NX-load | current worktree, `experiments/v8_derived_low_nx_load` | Small V8-derived auto aggregate/event summary | No SPEC/FFT/BRAM/DMA, tiny resource growth, SUM8 compatibility |
| NX benchmark | current worktree, `experiments/nx_load_benchmark_baseline` | Quantify NX polling/aggregation cost and C++ mmap/UIO payoff | Offline-safe benchmark and interface recommendation |
| Few-bin Goertzel/DFT | `candidate/goertzel-fewbin` worktree | Lightweight detector alternative to full FFT | OOC or static resource evidence, clear fixed-bin summary ABI |
| Multi-lag correlation | `candidate/multilag-corr` worktree | Extend validated dual-RX cross summary to fixed lag set | OOC or static resource evidence, clear lag budget and ABI |

## Mainline Selection

Prefer the smallest candidate that materially reduces NX load without disturbing AD9361/IIO health:

1. V8-derived auto aggregate/event summary if it stays close to SUM8.
2. NX benchmark changes if they improve validation or client read cost without touching active runtime.
3. Multi-lag correlation if resource/timing budget is small.
4. Few-bin Goertzel/DFT if it gives useful spectral detection cheaper than XFFT.
5. Full XFFT summary only after standalone feasibility is clean.

## Non-Merge Until Approved

Do not merge candidates that require:

- active NX robot/runtime integration
- ROS or streaming startup
- SDR `/sd` writes
- DMA/raw vector runtime
- large BRAM debug windows
- full HDL integration without prior OOC or artifact evidence

## Closeout

Each subagent must report branch or write scope, commit hash if applicable, files changed, validation run, residual risk, and merge recommendation. Close subagents after their result is captured.
