# P201 Pro SDR + Raspberry Pi 4B performance plan

Date: 2026-08-31

## Decision summary

Use the Raspberry Pi as a persistent session owner and policy/DSP host, not as a process-per-capture wrapper. Keep raw IIO reception isolated from DSP, use two reusable FFT workers, and treat 20 MS/s as the first production target and 25 MS/s as a measured stretch target. Do not modify FPGA or SDR boot state until the software pipeline and network ceiling have been measured.

The current high-value sequence is:

1. make the Rust acquisition path lossless under concurrent DSP;
2. establish the maximum stable IIOD/TCP sample rate;
3. budget the complete FFT/PSD/classification chain on two Pi cores;
4. tune CPU/network affinity only when counters identify a bottleneck;
5. offload to FPGA only when it removes raw-IQ transfer or more DSP work than the Pi can safely sustain.

## Current evidence

| Layer | Evidence | Consequence |
| --- | --- | --- |
| IIO/TCP | 10 MS/s pure refill measured 9.988 MS/s and 38.102 MiB/s with no short read or timeout | Rust/libiio transport already meets the 10 MS/s request. |
| Current scalar analysis | 10 MS/s with per-sample statistics in the acquisition loop fell to 9.601 MS/s | DSP must leave the acquisition thread. |
| Link | Both ends are 1000 Mb/s full duplex, MTU 1500, with no observed error/drop counters | Do not change MTU or offloads without a higher-rate A/B test. |
| Pi | Four Cortex-A72 cores at up to 1.5 GHz, 3.8 GiB RAM, 37.9 °C, no throttle flags | Two cores can be reserved for DSP without thermal evidence requiring overclocking. |
| Pi Ethernet | RX IRQ work currently lands on CPU0; GRO and checksum offloads are enabled; RPS is disabled | Reserve CPU0 for IRQ/softirq first; do not enable RPS blindly. |
| SDR | Zynq ARMv7 dual core, about 1 GiB RAM; Ethernet IRQ currently lands on CPU0; IIOD 0.21 has three tasks | SDR-side IIOD/network scheduling may limit the highest rate before the Pi does. |
| FPGA | Current loaded `BOOT.bin` is not the documented V8L1/V10S0 image and the historical summary MMIO range is unavailable | No FPGA optimization claim is valid until boot identity and rollback are restored. |

One complex RX stream uses four payload bytes per sample (`i16 I + i16 Q`). The raw payload rates are therefore:

| Sample rate | Raw payload | Raw bit rate |
| ---: | ---: | ---: |
| 10 MS/s | 40 MB/s | 320 Mb/s |
| 20 MS/s | 80 MB/s | 640 Mb/s |
| 25 MS/s | 100 MB/s | 800 Mb/s |
| 30.72 MS/s | 122.88 MB/s | 983.04 Mb/s |

The mathematical Gigabit-Ethernet ceiling is 31.25 MS/s before Ethernet, IP, TCP, and libiio protocol overhead. Consequently 30.72 MS/s cannot be a reliable remote-IQ target on this link. A measured 20–25 MS/s ceiling is the useful range.

## Runtime architecture

```text
SDR AD9361/DMA -> IIOD/TCP -> Pi CPU0 IRQ/softirq
                                  |
                                  v
                         CPU1 acquisition thread
                    refill -> sequence/timestamp -> bounded block pool
                                  |
                       +----------+----------+
                       v                     v
                 CPU2 FFT worker       CPU3 FFT worker
                 window/FFT/PSD        window/FFT/PSD
                       +----------+----------+
                                  v
                      features / classifier / output
```

Rules:

- One thread owns the libiio context, channels, and RX buffer for the whole session.
- The acquisition thread performs no floating-point per-sample analysis and no allocation, logging, serialization, or file I/O.
- Because the current safe Rust IIO buffer cannot move between threads, copy once into a preallocated interleaved IQ block pool and pass block ownership through a bounded SPSC/MPSC queue.
- Give overload an explicit policy and counter: stop with an error for lossless capture, or drop the oldest block for latest-spectrum monitoring. Never allow unbounded queue growth.
- Each FFT worker owns its planner, scratch memory, window coefficients, output buffer, and feature workspace. Parallelize independent frames across workers instead of creating threads inside a 2048-point FFT.
- Keep classifier/output work out of the acquisition thread and measure it separately.

## FFT compute budget

The measured RustFFT 6.4.1 AArch64 NEON baseline includes `i16 IQ -> Hann -> Complex32 FFT -> power sum/max`. At NFFT 2048 it measured 46.352 µs p50 and 51.408 µs p99 per frame.

```text
hop_samples = NFFT * (1 - overlap)
FFTs_per_second = sample_rate / hop_samples
required_CPU_cores = FFTs_per_second * measured_stage_seconds * RX_channels
```

| Rate | Overlap | One-RX core cost p50 | One-RX core cost p99 | Route |
| ---: | ---: | ---: | ---: | --- |
| 10 MS/s | 0% | 0.226 | 0.251 | One worker is ample. |
| 20 MS/s | 0% | 0.453 | 0.502 | One worker fits. |
| 25 MS/s | 0% | 0.566 | 0.628 | One worker fits with reduced headroom. |
| 10 MS/s | 50% | 0.453 | 0.502 | One worker fits. |
| 20 MS/s | 50% | 0.905 | 1.004 | Use two workers. |
| 25 MS/s | 50% | 1.132 | 1.255 | Requires two workers. |
| 10 MS/s | 75% | 0.905 | 1.004 | Use two workers. |
| 20 MS/s | 75% | 1.811 | 2.008 | Nearly consumes the complete two-core DSP budget. |
| 25 MS/s | 75% | 2.263 | 2.510 | Reduce overlap/rate or use FPGA offload. |

Double these figures for two independent RX FFTs. The benchmark does not yet include `fftshift`, logarithmic dB conversion, noise-floor/median estimation, top-k peaks, band aggregation, recording, or modulation recognition. Production admission should keep the two DSP cores below 70% sustained utilization after all stages are included.

NFFT 2048 was the best measured general point for this workload: one-core capacity at 50% overlap was 22.092 MS/s, versus 21.268 for NFFT 1024, 19.433 for 4096, and 19.212 for 8192.

## FFT implementation shortlist

1. **[RustFFT 6.4.1](https://github.com/ejmahler/RustFFT/tree/6.4.1):** default route. Its official README documents automatic AArch64 NEON selection, it is pure Rust with permissive MIT/Apache licensing, and it has a measured Pi baseline. Plan once and reuse.
2. **[PFFFT 1.1.0](https://github.com/marton78/pffft/tree/v1.1.0):** benchmark candidate for fixed power-of-two `f32` complex FFTs. Its official build options support ARM NEON and its license permits source/binary redistribution. It requires a small, isolated C FFI wrapper and an ordered-output benchmark matching the PSD use case.
3. **[FFTW 3.3.11](https://github.com/FFTW/fftw3/tree/fftw-3.3.11):** reference candidate built as single precision with AArch64 NEON (`--enable-float --enable-neon`) and a persistent measured plan. It adds a C ABI/build dependency, and its [GPL license](https://github.com/FFTW/fftw3/blob/fftw-3.3.11/COPYING) is incompatible with distributing an MIT-only combined binary unless the project changes license or obtains a separate FFTW license.
4. **[Arm Ne10](https://github.com/projectNe10/Ne10):** not a primary route. Its latest formal release is old and its current AArch64 optimization coverage is less clear than the alternatives.
5. **[AMD/Xilinx FFT IP](https://docs.amd.com/v/u/en-US/pg109-xfft):** FPGA route for workloads that exceed the two-core budget or can replace raw IQ with compact PSD/top-k/band-power summaries.

Do not switch libraries based on upstream benchmark claims. Run RustFFT, ordered PFFFT, and single-precision FFTW with identical input, window, output reduction, planner reuse, CPU affinity, governor, and 1024/2048/4096 sizes on this Pi.

## Raspberry Pi GPU track

The Pi GPU is a third compute tier; it does not replace either CPU NEON or SDR-side FPGA:

```text
CPU/NEON:       small batches and lowest FFT latency
Pi GPU/Vulkan:  batched FFT/PSD after IQ has already reached the Pi
SDR FPGA:       reduction before Ethernet, removing both network and Pi work
```

The current Pi cannot run a GPU benchmark yet. Read-only inspection found no `/dev/dri`, no loaded `v3d`/`vc4` module, no Vulkan/OpenCL tools or driver packages, and no `vc4-kms-v3d` overlay in `/boot/firmware/config.txt`; the headless configuration reserves only 16 MiB legacy GPU memory. Enabling the modern V3D/KMS path requires a separately approved boot-configuration/package change and reboot with a recorded rollback.

Use [VkFFT 1.3.4](https://github.com/DTolm/VkFFT/tree/v1.3.4) over Vulkan as the first GPU candidate. Its official project supports the Raspberry Pi 4 GPU, complex transforms, batches, and custom command-buffer integration under the MIT license. A thin C ABI should hide the Vulkan/VkFFT implementation from Rust.

OpenCL is not the primary route. Mesa [Rusticl](https://docs.mesa3d.org/rusticl) advertises no device by default and requires explicit driver opt-in while its documentation warns that premature default enablement can affect stability; Mesa's documented support/default-enable information does not establish V3D as a supported Rusticl target. Vulkan/V3DV has the clear Pi 4 path.

The GPU benchmark must include the complete path:

```text
interleaved i16 IQ
  -> GPU-visible input
  -> i16-to-f32 + Hann
  -> batched complex FFT
  -> power/PSD + accumulation + top-k/bandpower
  -> compact result readback
```

Uploading `Complex32`, running only FFT, and reading a complete spectrum back is not an acceptable performance comparison. It shifts conversion and reduction back to the CPU and can double memory traffic. Prefer a persistently mapped ring, explicit sequence ownership, pre-recorded command buffers where supported, and compact result readback. Unified physical memory does not remove Vulkan synchronization or cache-ownership costs.

For NFFT 2048 and 50% overlap at 10 MS/s, batching itself adds at least:

| Batch | Input accumulation time |
| ---: | ---: |
| 1 | 0.1024 ms |
| 8 | 0.8192 ms |
| 32 | 3.2768 ms |
| 64 | 6.5536 ms |
| 128 | 13.1072 ms |

Compare batch sizes `1/8/32/64/128`, FFT sizes `1024/2048/4096/8192`, and single/dual RX. Record CPU preparation, Vulkan submission, GPU execution timestamp, synchronization/readback, end-to-end p50/p95/p99, CPU cores freed, temperature/throttle flags, and total application latency. Compare against the existing RustFFT checksum/tolerance and full-pipeline measurement.

GPU GO requires all of the following:

- the complete GPU pipeline is correct against the Rust reference;
- it reduces end-to-end core time or raises sustainable throughput by a meaningful measured margin, not just a faster isolated FFT kernel;
- the selected batch latency fits the product deadline;
- long-duration queue, driver, suspend/restart, and thermal behavior are stable;
- CPU capacity released by GPU is actually needed for dual RX, high overlap, classification, rendering, or recording.

Keep CPU NEON when one RX at 10 MS/s/50% overlap is the target: its p99 FFT pipeline uses only about 0.502 core and avoids GPU batching latency. Evaluate GPU first for dual RX, 20–25 MS/s with substantial downstream classification, larger transforms, or a waterfall/PSD path that can remain GPU-resident. If Ethernet/IIOD is the bottleneck, skip Pi GPU tuning and move reduction to the SDR FPGA instead.

## Measurement and optimization phases

### Phase A — lossless Rust pipeline

- Add reusable IQ block pool, bounded queue, sequence number, capture timestamp, queue high-water mark, and dropped-block counter.
- Add two FFT workers with reusable 2048-point planners/scratch and configurable 0/50/75% overlap.
- Report per-stage p50/p95/p99, per-core CPU, RSS, queue depth, and complete-output rate.
- Validate 10 MS/s for at least 30 minutes before increasing the rate.

Gate: 10 MS/s full FFT pipeline has no capture shortfall, no unexpected drop, stable memory, and no throttle flag.

### Phase B — find the transport ceiling

For pure refill, sweep:

```text
sample rates: 10, 15, 20, 22, 24, 25 MS/s
buffer sizes: 16K, 64K, 256K complex samples
duration:     60 seconds first, then 1 hour at the selected ceiling
```

Record measured samples/s, refill latency distribution, client/server CPU by core, Ethernet bytes/errors/drops, `/proc/net/softnet_stat`, TCP retransmissions, temperature, and throttle flags.

Gate: select the highest rate that sustains at least 99.5% of read-back rate with zero refill errors and no growing drop/retransmit counters. Do not label 25 MS/s production-ready from a three-second run.

### Phase C — reversible system tuning

Test one change per benchmark and restore it before the next comparison:

1. Pi `performance` governor during the capture service, with temperature logging.
2. Pin Ethernet IRQ/softirq to CPU0, acquisition to CPU1, and FFT workers to CPU2–CPU3.
3. Only if CPU0 softnet counters grow, compare RPS/IRQ alternatives; otherwise retain current cache-local single-queue behavior.
4. Compare larger SDR/Pi TCP socket limits only if sender blocking, TCP window, or retransmission evidence indicates pressure.
5. Compare IRQ coalescing only after identifying latency versus interrupt-rate tradeoffs.
6. Test jumbo frames only if both drivers explicitly accept the same MTU and rollback is immediate; MTU 1500 remains the baseline.

Avoid overclocking until the normal 1.5 GHz pipeline has been profiled. Active cooling is cheaper and safer than relying on an overclock for correctness.

### Phase D — Pi GPU evaluation

- Requires a separately approved, recoverable V3D/KMS and Mesa Vulkan setup with reboot.
- Verify the renderer and Vulkan device before building VkFFT; never accept a software Vulkan renderer as a GPU result.
- Run the complete VkFFT batch matrix above and retain RustFFT as the correctness and rollback backend.
- Promote GPU only after end-to-end and long-duration gates pass.

### Phase E — SDR system

- Keep IIOD context and DMA buffer persistent; historical SDR-local measurements show about 28–31 ms context creation and 2–3 ms buffer creation, while refill/copy itself was sub-millisecond.
- Profile the two Zynq cores, Ethernet IRQ, IIOD worker tasks, TCP send blocking, and DMA interrupts during the Phase B sweep.
- Compare IIOD task/IRQ affinity only with before/after counters.
- Do not upgrade the old Buildroot/libiio image merely because it is old; upgrade only if a source-level change addresses a measured bottleneck and has a bootable rollback image.

### Phase F — FPGA offload decision

FPGA is justified when at least one of these is true:

- dual RX or high-overlap FFT exceeds the two Pi DSP cores;
- modulation recognition needs additional CPU after the FFT budget;
- the application only needs spectrum/features, so sending raw IQ wastes the Ethernet link;
- deterministic latency matters more than retaining every raw sample.

Preferred streaming kernels are DC/quality statistics, window, FFT, power, coarse PSD, top-k peaks, band powers, and dual-RX cross-power/phase aggregates. Return sequence, timestamp, overflow, valid/stale, scale exponent, and dropped-frame metadata. Use constant-size summary pages for compact results; use AXI DMA/ring buffers for vectors. Never read a full spectrum through repeated AXI-Lite `devmem`/SSH calls.

Start from an identified, hardware-validated V8L1-compatible boot baseline and retain Rust CPU fallback. The current unverified FPGA image is not an optimization base.

## Production targets

- First stable target: one RX, 10 MS/s, NFFT 2048, 50% overlap, continuous Rust FFT/PSD.
- Next target: one RX, 20 MS/s, NFFT 2048, 50% overlap, two FFT workers.
- Stretch target: one RX, 25 MS/s, NFFT 2048, 50% overlap, only if the network ceiling and full classifier budget pass.
- Pi GPU candidate: dual RX at 10 MS/s, or one RX at 20–25 MS/s when batched spectrum/classification needs to release ARM cores and can accept measured batch latency.
- FPGA-required candidate: dual RX at 20–25 MS/s with 50% overlap, or one RX at 20–25 MS/s with 75% overlap and substantial downstream recognition.

Raw recording at 20–25 MS/s requires sustained 80–100 MB/s plus headroom; use a USB 3 SSD and a separate bounded writer queue. Do not treat a microSD card as a guaranteed lossless sink at those rates.
