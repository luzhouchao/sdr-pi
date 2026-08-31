# Cross-layer roadmap

## Phase 0: plan-only SDR Agent runtime

- Run a stateless `pi-agent-core` Planner Worker on the Raspberry Pi while
  llama.cpp/Qwen inference remains on the 4090.
- Correlate every proposal by request ID and Controller session generation.
- Validate all proposals in Rust against state, capability and numeric limits.
- Read live shadow health through the read-only SDRD/1 Adapter and abort plans
  on connection, schema or correlation failure.
- Exercise mock/replay contexts before any plan can reach a hardware adapter.
- Keep the current original-BOOT/shadow-SDRD path read-only.

## Phase 1: stable Raspberry Pi acquisition

- Keep a session-owned libiio context and RX buffer.
- Move per-sample DSP out of the acquisition thread.
- Use preallocated bounded IQ blocks and explicit overload policy.
- Add long-duration 2.1/5/10 MS/s tests and reconnect tests.
- Feed only triggered, bounded, model-ready IQ windows through the implemented
  `LocalRecognizer` seam; keep the production C++ worker disabled until a
  pinned model and replay corpus pass the admission gates.

## Phase 2: SDR-system transport baseline

- Add a read-only benchmark mode inside the SDR Buildroot environment.
- Measure IIOD/TCP throughput, IRQ load, context switches and buffer latency.
- Evaluate reversible socket-buffer/affinity changes one at a time.
- Preserve the stock configuration and provide a one-command rollback.

## Phase 3: scan-session optimization

- Reuse context, buffers and FFT plans across channels.
- Measure retune, settle, capture, DSP, scoring and payload time separately.
- Start with an isolated non-ROS 1/6/11 Wi-Fi scan only after explicit live
  retune approval.

## Phase 4: FPGA summary backend

- Start from a hardware-validated V8L1-compatible base, not an unverified
  current image.
- Use local mmap/UIO, never SSH/devmem in the runtime hot path.
- Promote FPGA only when it removes a complete raw-IQ/CPU stage at session
  level.
- Keep CPU/Rust fallback for stale, invalid, overflow or low-confidence data.
