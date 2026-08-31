# P201 Agent-oriented FPGA direction

Date: 2026-08-31

## Decision

Build a project-specific FPGA image only after the Pi/SDR session interface and
measured software baseline are stable. The custom image is justified when it
prevents raw-IQ transfer or removes a complete processing stage, not merely when
an isolated FFT kernel is faster.

The currently loaded image is the protected original `BOOT.bin`. Keep that
exact file as the golden rollback and never overwrite it. Every experimental
image must use a unique artifact name and A/B staging path.

## Intended split

```text
AD9361 -> FPGA fixed streaming kernels -> SDR Linux C sdrd -> Pi Rust Harness
                                                        -> C++ local recognizer
                                                        -> Qwen planner
```

FPGA implements deterministic, fixed-shape data reduction. SDR Linux owns
configuration, validation, session state, FPGA capability discovery and
transport. The Pi owns scan policy, local recognition and Qwen orchestration.

## FPGA slices

### F0: Golden bypass and identity

- Preserve the original AD9361/IIO data path exactly.
- Add only a version/capability page and bypass mux.
- Require positive setup/hold slack and post-boot IIO health.
- Failure or disabled capability always returns to raw-IQ bypass.

### F1: Frame quality and power aggregation

- Frame/sample counters, clipping and overflow.
- I/Q sums, power, dual-RX cross products and bounded multi-frame aggregation.
- Reuse the validated SUM8 ideas, but do not assume its historical address or
  ABI exists in the original image.

### F2: Candidate trigger and reduction

- Optional DDC/FIR/CIC decimation for a selected candidate.
- Energy/noise threshold and event trigger.
- Pre/post-trigger bounded IQ ring descriptor.
- This is the first slice capable of reducing Pi classification load while
  preserving IQ for modulation and emitter recognition.

### F3: Real spectrum summary

- Hann window, true 2048-point FFT, scaled PSD.
- Noise floor, band power, top peaks and 64/96 coarse bins.
- The existing XFFT2048 OOC result proves an IP entry only; it does not prove
  live AD9361 integration or a valid bitstream.

### F4: Optional dual-RX features

- Selected-bin cross phase/coherence and calibrated quality primitives.
- Keep calibration, division, square root, `atan2`, confidence and policy out of
  FPGA.

Do not put the modulation or emitter-identification neural network in the first
FPGA versions. The model changes faster than the fixed streaming primitives and
is better served by the Pi C++ runtime or a larger 4090-side model.

## Runtime language choice

- SDR Linux hardware daemon: C11, static ARMv7 build.
- Use C++ only behind a narrow C ABI when a library such as ncnn or ONNX Runtime
  requires it.
- Pi Harness: Rust.
- FPGA: Verilog/SystemVerilog and versioned Xilinx IP.
- No Python in the SDR or Pi high-rate runtime path.

## Performance acceptance

A new FPGA slice is accepted only if all conditions pass:

- original raw-IQ bypass remains functional;
- IIO health passes before and after testing;
- register/DMA ABI is versioned and capability-negotiated;
- WNS and WHS are non-negative, routing is complete and rollback exists;
- side-by-side results meet numeric tolerances;
- end-to-end scan time, Ethernet bytes or Pi CPU improve materially;
- stale, overflow, mismatch or low-confidence state forces software fallback.

The first project-level target is to reduce ordinary observations from a
continuous raw-IQ stream to compact candidate/PSD records while retaining
triggered short IQ for local recognition.
