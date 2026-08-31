# SDR preprocessing and configurable sweep architecture

Date: 2026-08-31

## Outcome

Use one validated `SweepPlan` interface for all backends. The caller chooses the frequency range and desired result, while the module hides LO retuning, settle timing, buffer reuse, FFT backend selection, FPGA capabilities, overload handling, state restore, and result normalization.

```text
SweepPlan
   |
   v
SweepEngine.run(plan) -> SweepReport
   |                         ^
   +-- IIO tuning/capture ---+
   +-- CPU/GPU processor ----+
   +-- SDR summary adapter --+
```

This is a deep module: callers learn one plan and one report instead of separately controlling AD9361 attributes, libiio buffers, CPU/GPU FFT, FPGA registers, timing, and rollback.

## Adjustable sweep interface

The external interface should accept either:

- a continuous range: `start_hz`, `stop_hz`, and `step_hz`; or
- an explicit list of center frequencies for channel plans such as Wi-Fi 1/6/11.

Required controls:

```text
frequency: start / stop / step or centers[]
radio:     sample_rate, RF bandwidth, gain mode
timing:    settle time, captures per point, optional dwell limit
DSP:       NFFT, overlap, window, averages, coarse bins, top-k
backend:   cpu / gpu / sdr_summary / auto
output:    summary, coarse PSD, or trigger-only raw IQ
```

The example configuration is [`sweep.example.yaml`](../raspberry-pi/config/sweep.example.yaml). A later Rust CLI should expose the same fields:

```text
p201pro scan --start-freq 2400000000 --stop-freq 2500000000 \
  --step-freq 8000000 --sample-rate 10000000 --rf-bandwidth 8000000 \
  --settle-ms 5 --captures-per-step 4 --fft-size 2048 --overlap 50
```

The first software aggregation slice is now available through
`p201pro-test capture --analysis aggregate`. It provides the streaming
Hann/RustFFT, linear-power averaging, median noise estimation, coarse PSD and
adjacent-candidate merge needed to validate this result shape before the fixed
work is moved into the SDR. It deliberately leaves raw-IQ trigger capture and
FPGA activation for later verified slices.

## Validation before touching the radio

The plan is rejected before the first LO write unless all rules pass:

- every center frequency is inside the verified AD9361/P201 range, currently `70 MHz..6 GHz`;
- `start <= stop`, `step > 0`, and generated point count is no more than `max_points`;
- sample rate is inside `2.083333..30.72 MS/s` and is not below RF bandwidth;
- RF bandwidth is inside `0.2..56 MHz`;
- FFT size is supported by the selected backend and overlap is `0..75%`;
- estimated duration and output volume are calculated and printed before execution;
- continuous coverage rejects a step larger than the configured usable bandwidth;
- the original LO, sample rate, bandwidth, gain mode, and enabled channels can be read back for restoration.

The engine restores the original tuning in a finally/RAII guard on success, error, timeout, or user cancellation, then performs an IIO health readback.

## Choosing step and bandwidth

One tuning point observes approximately the configured RF bandwidth, but filter edges should not be treated as equally reliable. For gap-free coverage, start with:

```text
step_hz <= 0.8 * rf_bandwidth_hz
```

This is a conservative project default, not an AD9361 hardware law. Measure the actual passband and calibration before changing it. A smaller step improves edge coverage but increases retunes, duplicate observations, FFT work, and total scan time.

For known channel systems, an explicit center list is usually better than a dense range. For unknown emitters, use a coarse-to-fine scan:

1. coarse range scan with low averages and compact PSD;
2. detect peaks/occupied sub-bands;
3. revisit only candidates with smaller step, longer dwell, or raw capture;
4. send candidate IQ to modulation recognition or direction finding.

## Where preprocessing belongs

### AD9361 and existing receive chain

Keep RF tuning, analog/digital filtering, gain control, and supported calibration in the AD9361 driver path. Do not add a second correction stage unless measurement proves it is needed.

### SDR Zynq programmable logic

This is the best place for fixed, high-rate work that can reduce data before Ethernet:

- framing, overlap bookkeeping, clipping/quality counters;
- optional DDC/channelization, FIR/CIC decimation;
- Hann/window multiply and fixed-size FFT;
- magnitude/power, time/frequency accumulation and coarse PSD;
- noise/threshold, top-k peaks, band powers and event trigger;
- dual-RX power/cross-power/phase/correlation summaries;
- trigger-controlled short raw-IQ ring capture.

The useful output is a small versioned result page or DMA ring with sequence, source frequency, sample count, scale exponent, valid/stale/overflow flags, timestamp, dropped-frame counter, and payload length. Full FFT vectors must use DMA/ring transport; repeated AXI-Lite or `devmem` reads are not a runtime path.

The current loaded FPGA image is not the documented V8L1/V10 baseline, so this path cannot be enabled until boot identity, golden rollback, timing, and hardware health are re-established.

### SDR Zynq ARM cores

Use the dual Cortex-A9 for persistent local control and light aggregation:

- own one local IIO context/buffer across the whole scan;
- execute the frequency plan without per-point SSH/process setup;
- configure FPGA kernels and package compact results;
- expose a small framed TCP protocol to the Pi;
- monitor overflow, sequence gaps, temperature and health.

Do not make the SDR ARM perform every high-rate floating-point FFT unless a local benchmark proves it beats moving that work to PL or Pi. It has only two much slower cores and already hosts IIOD/network work.

### Raspberry Pi CPU and GPU

- CPU RustFFT: default for one RX, low latency, flexible algorithms and fallback.
- V3D/VkFFT: optional for batched FFT/PSD when releasing ARM cores is worth the batch latency.
- Rust control layer: sweep scheduling, calibration, confidence, classification, storage and result publication.

Pi GPU cannot reduce SDR-to-Pi traffic because raw IQ has already crossed Ethernet. If the link is the bottleneck, preprocessing must occur inside the SDR.

## Sweep result contract

Each point should produce a stable record such as:

```text
sweep_id, point_index, timestamp
requested_center_hz, actual_center_hz
sample_rate_hz, rf_bandwidth_hz, gain_mode
settle_ms, captured_samples, dropped_samples
noise_floor_dbfs, band_power_dbfs
peak_frequency_hz, peak_power_dbfs, peak_width_hz
occupancy, confidence, clipped_count
backend, backend_version, flags
coarse_psd[] (optional)
raw_iq_ref (triggered only)
```

Do not return an unlabelled float array. Frequency mapping, FFT/window normalization, calibration, backend identity, sequence continuity, and quality flags are part of the interface.

## What sweep results can do

- spectrum waterfall and heatmap over time/frequency;
- channel occupancy, noise/interference ranking and automatic channel selection;
- unknown-signal discovery with center frequency, bandwidth and persistence;
- trigger high-resolution raw capture only around interesting events;
- provide candidate windows for modulation recognition/classification;
- generate RF fingerprints and anomaly/change detection;
- compare locations or antennas for coverage/interference surveys;
- feed dual-RX AoA/correlation only for selected signals;
- enforce spectrum masks or alert on unexpected emitters where legally permitted.

PSD alone cannot identify a transmitter, decode content, or reliably determine modulation. Those require suitable bandwidth, raw or richer features, calibration, observation time, and often supervised models.

## Performance strategy

Use three scan profiles rather than one expensive universal sweep:

| Profile | Purpose | Processing | Output |
| --- | --- | --- | --- |
| survey | find activity quickly | coarse PSD, low averages | peaks/bands only |
| inspect | characterize candidates | smaller step, more averages | PSD + features |
| capture | feed recognition/debug | fixed candidate frequency | bounded raw IQ |

The main performance metric is time to useful result, not FFT kernel speed. Record per point:

```text
retune + settle + capture + preprocess + transfer + DSP + classify + output
```

FPGA or GPU is promoted only if it reduces this end-to-end total under the same frequency plan and result contract.
