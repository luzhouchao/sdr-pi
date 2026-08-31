# P201 Parallel Candidate Results

Generated: 2026-06-08

## Branches

| Branch | Commit | Result | Mainline Recommendation |
|---|---|---|---|
| `v8-derived-low-nx-load` | `3483bc2` | V8-derived AGG8 auto-roll experiment. `xvlog` syntax PASS. No FFT/SPEC/BRAM/DMA. | Promote first to OOC/integrated timing candidate. |
| `v8-derived-low-nx-load` | `6a0c4a8` | Offline NX load benchmark. Aggregate-first priority confirmed; 64-frame model reduces devmem commands from 2432 to 46. | Keep; use to justify C++ mmap/UIO hot path. |
| `candidate/v10-fft-kernel` | `1058fb5` | Xilinx `xfft` 256-point OOC PASS, WNS +5.565 ns, 9 DSP, 2 RAMB18. Summary reducer OOC PASS, WNS +0.630 ns, 0 DSP/BRAM. | Keep isolated; next build tiny `xfft -> magnitude -> reducer` OOC top. |
| `candidate/goertzel-fewbin` | `31958a6` | Python self-test PASS; OOC synth PASS; OOC timing FAIL, WNS -20.734 ns, 56 DSP. | Do not merge. Revisit only with pipelined or time-multiplexed architecture. |
| `candidate/multilag-corr` | `6ac7c9f` | Python self-test PASS 36/36; OOC synth PASS; WNS +3.199 ns, WHS +0.240 ns, 1346 LUT, 1903 FF, 16 DSP, 0 BRAM. | Good second hardware-candidate direction after V8 auto-roll ABI/timing review. |

## Decision

Recommended mainline order:

1. Advance V8-derived AGG8 auto-roll to OOC and then integrated timing.
2. Add/plan an offline C++ mmap/UIO reader around the validated SUM8/AGG8 contract, still off-by-default and outside active runtime.
3. Prepare a register ABI draft for multi-lag correlation, reusing SUM8 lag-0/power concepts.
4. Continue FFT only as isolated OOC work until the tiny stream top is timing-clean.
5. Park current Goertzel/few-bin implementation as a negative baseline.

## Why

The strongest near-term NX load reduction comes from reducing control/read/poll loops, not only arithmetic. V8-derived AGG8 auto-roll is closest to the current highest hardware-validated V8 behavior and adds no new per-sample spectral datapath. Multi-lag correlation is promising because it extends existing dual-RX cross primitives with a clean OOC result. FFT has good standalone evidence but should stay isolated until its full stream top is proven. The current Goertzel shape is too expensive and timing-negative.

## Hardware Boundary

No branch above is a burnable hardware artifact except the previously validated rollback versions already documented in `VERSION_ROUTE.md`. No new SDR `/sd` write, ROS/runtime start, or robot-motion path was used for these candidates.
