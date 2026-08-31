# P201 FPGA Offload Candidates Beyond FFT

Generated: 2026-06-08

## Current Constraint

V8 remains the highest hardware-validated base. V9A and V9B0 both passed FPGA register checks but failed AD9361/IIO health after power-cycle, so the next hardware-changing work should start from the pre-V9A SUM8 line and keep resource growth small until the AD9361 sensitivity is understood.

## Priority Order

1. V8-derived auto aggregate and event summary

   Best immediate NX-load win. Keep the SUM8 style register contract, add small counters/ready flags/threshold or event summaries, and reduce repeated NX polling and Python aggregation. No FFT, BRAM windows, DMA, or SPEC page in this first step.

2. Multi-lag dual-RX correlation summary

   Extend the already validated cross-power idea to a small fixed set of lags. FPGA does high-rate multiply-accumulate; NX keeps atan2, calibration, geometry, and policy. This directly supports AoA/coherence style work without transferring vectors.

3. Decimation plus low-rate feature summaries

   Add cheap CIC/boxcar-style decimation or frame subsampling before heavier feature extraction. Output only low-rate power, peak, zero-cross, clip, and quality counters. This is useful when the NX needs trend/health rather than raw IQ.

4. Goertzel or few-bin DFT

   If only a few frequencies matter, a fixed-bin Goertzel/DFT kernel is cheaper and safer than a full FFT. It can provide tone/band detectors, prominence, and event gates while avoiding full spectral vector transfer.

5. FFT/PSD summary

   Use Xilinx XFFT as an independent OOC baseline first. Integrate only a summary reducer into the system path: band powers, top-K peaks, noise-floor estimate, prominence, and optional debug bins. Full PSD vectors should remain debug-only until DMA is justified.

6. Threshold, trigger, and capture gating

   FPGA can decide when a frame is interesting enough for NX to read more registers. This is low arithmetic cost and may reduce NX wakeups more than adding more math.

7. DMA or raw-vector path

   Defer until register summaries prove insufficient. DMA adds integration and driver risk, and it is not the right first response to the V9A/V9B0 AD9361 failures.

## Not Worth Moving Yet

- divide, sqrt, atan2, log scaling
- antenna calibration and geometry policy
- adaptive algorithm composition
- ROS/runtime publication
- robot control decisions
- broad ML/classifier logic
- full raw IQ transfer path

These stay on NX until side-by-side validation shows a stable FPGA primitive is both useful and safe.

## Integration Rule

Run FFT as a standalone baseline in parallel, but do not let it block the next V8-derived low-NX-load candidate. Combine only after each candidate passes its own PC artifact gate and the final merged HDL remains timing-clean with no AD9361/IIO regression.
