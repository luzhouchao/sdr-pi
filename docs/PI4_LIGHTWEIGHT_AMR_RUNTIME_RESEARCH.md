# Raspberry Pi 4 lightweight modulation-recognition runtime

Date: 2026-08-31

## Decision

Use Python/PyTorch on the workstation or AGX for training and export the production model to ONNX. Start Raspberry Pi inference with ONNX Runtime's official C or C++ API on the CPU. Rust may call a small stable C ABI wrapper, but pure Rust is not a requirement.

Keep Tencent ncnn as the optimization candidate after the ONNX Runtime reference is correct. It has a small C++ runtime, no third-party runtime dependency, CPU/Vulkan backends, and official PyTorch/ONNX conversion tooling. Use its CPU path on Pi 4 first; the measured V3D behavior in this project does not justify making Vulkan the default.

Python on the Pi is acceptable for prototyping. `onnxruntime` Python still executes model kernels in the native runtime, but production code must avoid Python sample-by-sample loops and unnecessary IQ copies. A persistent C/C++ worker or an in-process C ABI is the deployment target if the prototype meets accuracy requirements.

## Recommended v1 stack

```text
Training/quantization: Python + PyTorch on workstation or AGX
Model interchange:     ONNX
Pi reference runtime:  ONNX Runtime CPU, official C/C++ API
Pi optimized candidate:ncnn C++ CPU
Application boundary:  small versioned C ABI callable from Rust
Model:                 compact 1-D CNN/TCN or 1xK 2-D convolutions
Input:                 bounded I/Q window after detection, DDC and resampling
```

The Python/C++ choice does not make an unbounded 10 MS/s classifier feasible. At 2048 points and 50% overlap, 10 MS/s creates about 9766 windows/s. The classifier must consume selected signal segments, not every FFT window.

## Runtime comparison

| Runtime | Role | Strength | Main risk |
| --- | --- | --- | --- |
| ONNX Runtime C/C++ | reference/default | broad ONNX support, graph optimizations, quantization tooling, official C API | larger deployment and build than ncnn; ARM64 package/build must be pinned and verified |
| ncnn C++ | optimized candidate | lightweight, ARM-oriented C++ runtime, no third-party runtime dependencies, conversion tooling | conversion/operator differences require numerical comparison with ONNX Runtime |
| tract | pure-Rust fallback | runs ONNX/NNEF on embedded ARM and provides ARM SIMD kernels | model/operator coverage and speed must be verified; pure Rust is no longer a project constraint |
| LiteRT C++ | alternative for a TFLite-native model | native C++ runtime and XNNPACK CPU path | adds another model format/conversion path and is not needed for the first ONNX baseline |

## Model and pipeline constraints

- Detect activity first; do not classify empty spectrum continuously.
- Tune or DDC to the candidate, low-pass, decimate/resample, normalize, and produce a fixed input shape such as `[1, 2, 2048]` or `[1, 2, 4096]`.
- Prefer a small 1-D CNN/TCN or express temporal convolution as `1xK` 2-D convolution for portable operator support.
- Establish an FP32 correctness/latency reference before INT8. Promote INT8 only when confusion-matrix accuracy and per-class recall remain acceptable.
- Use a bounded queue and one inference worker initially. Set runtime threads explicitly so inference cannot starve IIO capture and FFT workers.
- Record p50/p99 latency, CPU-core time, RSS, copy/normalization time, dropped segments, and classification accuracy on real SDR captures.
- Training stays off the Pi. Deployment must work without Python even if the prototype uses it.

## Admission gate

A runtime is accepted only if the same exported model and captured-IQ corpus pass:

1. output comparison against the workstation reference;
2. per-class accuracy and confusion-matrix limits;
3. sustained replay at the required triggered classification rate;
4. p99 end-to-end latency including preprocessing and copies;
5. total DSP plus inference CPU below the project's sustained core budget;
6. 30-minute thermal/throttling and dropped-sample test.

## Primary sources

- [ONNX Runtime project](https://github.com/microsoft/onnxruntime)
- [ONNX Runtime C API](https://onnxruntime.ai/docs/get-started/with-c.html)
- [ONNX Runtime model quantization](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html)
- [ONNX Runtime thread management](https://onnxruntime.ai/docs/performance/tune-performance/threading.html)
- [Tencent ncnn project and C++ workflow](https://github.com/Tencent/ncnn)
- [tract project and embedded ARM/SIMD support](https://github.com/sonos/tract)
- [Google AI Edge LiteRT project](https://github.com/google-ai-edge/LiteRT)

