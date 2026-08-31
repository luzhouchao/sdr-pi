# Raspberry Pi 4 V3D/VkFFT live result — 2026-08-31

## Outcome

The Pi 4 GPU was successfully enabled and identified as real V3D hardware. VkFFT ran on Mesa V3DV and demonstrated useful batch throughput, but it did not beat CPU NEON for low-latency 2048-point work. An oversized 8192-point/batch32 command buffer caused SSH starvation and is a hard NO-GO.

No SDR, IIOD, AD9361 or FPGA setting was changed during the GPU test.

## Recoverable system change

Original boot configuration:

```text
/boot/firmware/config.txt SHA-256
3695efa22b5a0b2495070fcab5811288133a4bef1a357b925d039adba32666fa
```

Backups were created before modification:

```text
/boot/firmware/config.txt.pre-v3d-20260831
/root/config.txt.pre-v3d-20260831
```

Both backup hashes matched the original. The only config change was:

```diff
-#dtoverlay=vc4-kms-v3d,noaudio
+dtoverlay=vc4-kms-v3d,noaudio
```

New config SHA-256:

```text
fd87f6f78e235e157e268ac13d1ac9ae290a5bb74bd2bbc2327cb5ccb2f80cb5
```

Installed packages added 25 new packages, upgraded none and removed none. Directly requested versions were:

```text
mesa-vulkan-drivers 26.2.0-1~bpo13+0~rpt3
vulkan-tools 1.4.304.0+dfsg1-1
libvulkan-dev 1.4.309.0-1
glslang-dev 15.1.0+1.4.309.0-1
```

Rollback command after obtaining a working shell:

```bash
cp -a /root/config.txt.pre-v3d-20260831 /boot/firmware/config.txt
sync
reboot
```

The packages do not need removal for the overlay rollback; without a V3D DRM render node they are inactive.

## Post-reboot validation

Passed:

- `/dev/dri/renderD128` exists;
- `v3d`, `vc4`, DRM and GPU scheduler modules loaded;
- SDR direct Ethernet restored and `192.168.1.10` replied with zero ping loss;
- Wi-Fi management address restored;
- temperature `37.9 °C`, throttle flags `0x0`;
- `vulkaninfo` enumerated hardware `V3D 4.2.14.0` with Mesa V3DV `26.2.0`;
- V3D reported Vulkan API `1.3.354`, integrated GPU, Broadcom vendor `0x14e4`;
- llvmpipe was also present but was not used for the benchmark.

## Build and artifact

VkFFT was pinned to:

```text
release v1.3.4
commit 066a17c17068c0f11c9298d848c2976c71fad1c1
```

The test suite was cross-built locally for ARM64 GNU/Linux with Vulkan/glslang. Artifact:

```text
ELF 64-bit LSB PIE, ARM aarch64, dynamically linked
interpreter /lib/ld-linux-aarch64.so.1
needed: libvulkan.so.1, libstdc++.so.6, libm.so.6, libgcc_s.so.1, libc.so.6
SHA-256 2567b68d20cef9adbfccb81d6367a51dcc469389245aab613fb59b7eba9fe43a
```

The runtime forced `/usr/share/vulkan/icd.d/broadcom_icd.json` and selected device 0, whose name was `V3D 4.2.14.0`.

## VkFFT kernel result

The upstream user benchmark records one forward FFT and one inverse FFT per step. The derived single-forward time below is:

```text
avg_time_per_step / (2 * batch)
```

It excludes IQ input conversion, Hann, PSD/reduction, buffer handoff and result readback.

| NFFT | Batch | FFT+iFFT batch step | Derived one FFT/frame |
| ---: | ---: | ---: | ---: |
| 2048 | 1 | 0.230 ms | 115.000 µs |
| 2048 | 4 | 0.461 ms | 57.625 µs |
| 2048 | 8 | 0.726 ms | 45.375 µs |
| 2048 | 16 | 1.189 ms | 37.156 µs |
| 2048 | 32 | 2.134 ms | 33.344 µs |
| 2048 | 64 | 4.022 ms | 31.422 µs |
| 4096 | 1 | 0.267 ms | 133.500 µs |
| 4096 | 8 | 1.039 ms | 64.938 µs |
| 4096 | 32 | 3.351 ms | 52.359 µs |
| 8192 | 1 | 0.853 ms | 426.500 µs |
| 8192 | 8 | 4.255 ms | 265.938 µs |
| 8192 | 32 | no result | system responsiveness failure |

Temperature after the completed 2048 batch matrix was `40.9 °C`; throttle flags remained `0x0`.

## CPU reference after enabling V3D

The same static RustFFT benchmark and hash were rerun with the GPU driver idle:

| NFFT | Full pipeline p50 | Full pipeline p99 | FFT-only p50 |
| ---: | ---: | ---: | ---: |
| 2048 | 47.500 µs | 52.741 µs | 33.944 µs |
| 4096 | 106.351 µs | 111.685 µs | 83.944 µs |
| 8192 | 215.852 µs | 222.167 µs | 176.370 µs |

This is close to the pre-GPU 2048 baseline of `46.352/51.408 µs` full p50/p99. Enabling V3D did not produce a major CPU regression while the GPU was idle.

## Interpretation

- For 2048 points, V3D needs batch 32–64 merely to match the CPU FFT kernel. CPU remains the production default because its full pipeline is already about 47.5 µs and has much lower batching latency.
- For 4096 points, batch 8–32 GPU kernel throughput is faster than the CPU FFT kernel, so a fused GPU pipeline may release ARM cores for classification. It still needs an end-to-end implementation and correctness test.
- The current VkFFT 8192 path is slower than CPU at batch 1/8 and the batch32/N500 job caused a severe responsiveness failure. It is not a candidate on this Pi.
- The upstream benchmark places many FFT/iFFT pairs into one command buffer. Large `N` values create long non-preemptible or poorly responsive workloads on this platform. Future tests must use small `N`, an external timeout, bounded command buffers and a hardware/system watchdog.
- Pi GPU does not reduce SDR-to-Pi traffic. When bandwidth is the problem, preprocessing must move into the SDR FPGA/ARM path.

## Stability incident

During `NFFT=8192`, `batch=32`, `N=500`, the active SSH session timed out. The Pi continued answering ICMP and TCP port 22 accepted a connection, but SSH did not send its protocol banner. Tailscale SSH also failed. This is sufficient to reject the workload even without a recovered kernel log.

Do not repeat the combination.

## Manual recovery result

The Pi required a physical power cycle; the SDR remained powered and was not modified. After restart:

- the Pi management address and persistent Dropbear SSH service recovered;
- `/dev/dri/renderD128`, `v3d`, `vc4`, DRM and V3DV all recovered;
- `vulkaninfo` again selected hardware `V3D 4.2.14.0` and Mesa `26.2.0`;
- the direct SDR interface recovered as `192.168.1.20/24` and the SDR replied to three pings with zero loss;
- temperature was `35.5 °C`, throttle flags were `0x0`, and 3.5 GiB memory was available;
- no old VkFFT or RustFFT process survived the restart;
- the temporary target-side benchmark binaries and Vulkan runtime directory were removed.

This DietPi installation had neither a persistent journal nor pstore crash data, so the pre-restart V3D/OOM state could not be recovered. Current-boot `dmesg` contains only normal V3D/VC4 initialization and the Mesa transparent-hugepage performance recommendation; it contains no GPU reset, timeout, OOM or lockup report.

The enabled GPU configuration is therefore retained, but CPU RustFFT remains the production default. Any future GPU test must first add bounded command buffers, an external timeout and an independent watchdog; it must not use the rejected 8192/batch32 workload.
