# P201Pro Project-Level Band Scan Optimization Plan

Last updated: 2026-06-09 Asia/Shanghai

Status: current unified optimization direction

This plan replaces the split A/B framing as the primary optimization lens. The
goal is not to prove that FPGA, CPU, GPU, or IIO wins in isolation. The goal is
to make the project demo visibly faster by optimizing the whole SDR scan
workflow.

The target improvement is project-level:

```text
Good target: reduce a multi-band or 2.4 GHz scan from about 1 minute toward
             about 10 seconds.
Low-value target: reduce a 500 ms inner step to 10 ms if the full scan still
                  takes tens of seconds.
```

No ROS, SDR streaming runtime, active `robot_control`, mapping, navigation,
`cmd_vel`, robot motion, BOOT/SD staging, device-tree, kernel, driver, or
vendor-package change is part of this plan.

## Current Functional Surface

Read-only project analysis shows these SDR features and data dependencies:

| Feature | Current shape | Optimization meaning |
| --- | --- | --- |
| Channel scan | Tune, settle, capture raw buffers, FFT/PSD, aggregate RSSI/noise/peaks/prominence | Main target. Optimize as a session, not as isolated refills. |
| Clean channel recommendation | Occupancy, RSSI, prominence gates | Can often use coarse or staged scan before high-resolution confirmation. |
| Spectrum snapshot | PSD plus compressed UI payload | Can share the same session and output schema. |
| Heatmap/fingerprint | Occupancy and compressed PSD history | Needs stable per-channel schema more than full raw IQ every time. |
| Dominant user estimate | Peak count/frequency/power | Can start with coarse/top peaks and refine only suspicious channels. |
| Dual-RX AoA | Phase/coherence/peak-bin phase from raw dual-RX IQ | Future backend; keep separate from first band-scan service. |

The important local measurements are:

```text
SDR-local real IIO context open/setup: about 28-30 ms
buffer create: about 3-5 ms
8192-sample refill median: about 0.025 ms
8192-sample copy median: about 0.28-0.32 ms
SSH wrapper around a validation run: about 150 ms
```

Conclusion:

```text
Refill/copy is not the project bottleneck. Repeated setup, scan/session
structure, retune/settle policy, per-channel process/wrapper overhead, FFT/PSD
plan reuse, aggregation, and UI/log payload construction are the meaningful
optimization targets.
```

## External Reference Facts

These facts inform the plan, but they do not authorize live retune or runtime
integration by themselves.

- Analog Devices libiio documents the intended lifecycle: create a context,
  enable scan channels, create an input buffer, refill it, and read samples from
  that buffer. A buffer can fail to create if no channels are enabled. This
  supports a session-owned context/buffer design rather than repeated one-shot
  capture setup:
  <https://analogdevicesinc.github.io/libiio/v0.21/libiio/index.html>
- NVIDIA cuFFT separates plan creation from execution and supports batched 1D
  transforms. This supports owning FFT plan setup at the scan-session level
  instead of per-channel/per-capture:
  <https://docs.nvidia.com/cuda/cufft/index.html>
- The AD9361 supports Fast Lock profiles for faster frequency changes by
  storing synthesizer configuration information for later recall. This is a
  future live-scan lever, but using it requires a separate controlled retune
  gate:
  <https://www.analog.com/media/en/technical-documentation/user-guides/AD9361_Reference_Manual_UG-570.pdf>
- 2.4 GHz Wi-Fi channel plans are overlapping; common non-overlapping channels
  in the U.S. are 1, 6, and 11. This supports a staged scan policy: coarse pass
  on key channels first, then refine the neighborhood only when useful:
  <https://www.cisco.com/c/en/us/td/docs/wireless/controller/9800/technical-reference/wireless-rf-reference-guide.html>
  and <https://www.mathworks.com/help/wlan/gs/wlan-radio-frequency-channels.html>

## Unified Architecture

Use one top-level service/session abstraction:

```text
BandScanSession
  ChannelPlan
  BackendProvider
  TimingRecorder
  ResultNormalizer
  OccupancyScorer
  PayloadEmitter
```

Backends are implementation choices under the same session contract:

| Backend | Role | When useful |
| --- | --- | --- |
| `highres_iio_cpu_gpu` | High-resolution raw or near-raw path using IIO plus CPU/GPU FFT/PSD | Detail, calibration, debug, final confirmation, full PSD. |
| `fpga_lowres_shadow` | Summary/top/coarse register provider | Default fast summary only if it removes a whole scan-stage cost, not just inner FFT cost. |
| `mock_replay` | Offline development using saved logs and synthetic channels | Safe session/schema/UI iteration with no SDR contact. |

The service owns:

```text
context/process/session lifetime
channel list and scan order
retune/settle policy, when explicitly approved
buffer and FFT/PSD plan reuse
per-channel capture batching
coarse/high-res result normalization
confidence/status/fallback
single session log and UI/fingerprint payload
```

## Optimization Strategy

### 1. Optimize Scan Policy Before Kernels

Do not scan every channel at full resolution by default. For 2.4 GHz:

```text
Fast coarse pass:
  channels 1, 6, 11

Refinement pass:
  neighboring or all channels only when occupancy/peak/confidence requires it

Detail pass:
  high-resolution PSD only for selected channels or user-requested snapshots
```

The first demo target should make time-to-first-useful-result low, even if a
background detail pass continues afterward.

### 2. Make Setup Session-Owned

One scan session should open/setup once:

```text
open IIO/local helper context once
enable/restore scan channels in a controlled gate
create/reuse buffers where possible
create/reuse CPU/GPU FFT plans
reuse window/coarse-bin/top-peak work buffers
emit one session JSON payload
```

Avoid:

```text
per-channel SSH exec
per-channel process launch
per-channel IIO context open
per-capture FFT plan creation
per-channel schema/log object churn
```

### 3. Use GPU/CPU Where They Win

CPU/GPU should remain the default high-resolution compute path when samples are
already on NX. The key rules:

```text
create FFT/CUDA plans once per session
batch same-size FFTs when possible
keep arrays reusable
avoid unnecessary host/device synchronization
compress PSD only once for UI payloads
```

The GPU is not a reason to keep an inefficient session loop. It is a backend
under the session.

### 4. Use FPGA Only For Whole-Stage Removal

FPGA is useful only when it removes an entire high-cost stage:

```text
AD9361/PL -> summary/top/coarse registers -> NX small read
```

FPGA is not worth pushing if the path still needs:

```text
raw IIO capture
per-channel IIO context open
full PSD vector readback over AXI-Lite
NX-side one-shot wrapper for every channel
```

Current FPGA evidence remains valuable as reusable primitive knowledge, but it
should not drive the project unless it improves the session-level scan time.

## Proposed Phases

### S0: Freeze And Reframe

Goal: stop A/B split momentum and define one project-level route.

Deliverables:

```text
docs/P201PRO_PROJECT_LEVEL_BAND_SCAN_OPTIMIZATION_PLAN.md
```

Rules:

```text
No new bitstream/BOOT/SD.
No live retune.
No active runtime modification.
Existing A/B uncommitted drafts remain inputs, not route truth.
```

### S1: Offline Session Model And Demo Target

Goal: prove the new software shape without touching SDR state.

Deliverables:

```text
channel plan for 2.4 GHz
unified session result schema
mock/replay scan session prototype
timing model for 1-minute -> 10-second path
```

Measurements to model:

```text
channels scanned
captures per channel
retune/settle placeholder
context/process setup
buffer/refill/copy
FFT/PSD and plan creation
aggregation/scoring
payload/log generation
```

Exit gate:

```text
Dry-run session can show where seconds are saved.
No live SDR action.
```

### S2: Read-Only Active-Code Timing Audit

Goal: find the real seconds-level costs in the existing scan code without
starting it.

Allowed:

```text
read active Python files
static instrumentation patch draft only
patch --dry-run only
py_compile staged candidates only
```

Not allowed:

```text
apply active robot_control changes
start ROS or SDR runtime
```

Exit gate:

```text
A timing-instrumentation candidate exists and is off-by-default.
```

### S3: Independent Live Session Test

Goal: run a safe, non-ROS, isolated scan session from the independent experiment
directory.

Requires explicit approval because it may retune or configure the SDR.

Minimum live safety:

```text
pre-test IIO health
state snapshot
limited channel plan
controlled retune/settle
post-test restore
post-test IIO health
single JSON result log
```

Initial live test should be small:

```text
2.4 GHz channels 1, 6, 11 only
one or two captures per channel
no ROS
no active runtime
no motion
```

Exit gate:

```text
End-to-end session timing is measured and compared with the old scan shape.
```

### S4: CPU/GPU Session Backend

Goal: make high-resolution CPU/GPU scans session-owned.

Work items:

```text
reuse IIO context/buffer where possible
reuse Hann/window arrays
reuse NumPy/cuFFT plans or equivalent backend state
batch per-channel PSD work
emit normalized scan payload
```

Exit gate:

```text
The same channel plan and schema can run mock/replay and isolated live.
```

### S5: FPGA Low-Resolution Backend Review

Goal: decide whether FPGA still earns a place in the session.

FPGA backend GO only if it removes a whole cost block:

```text
default summary scan avoids raw IIO transfer and CPU/GPU PSD for most channels
```

FPGA backend NO-GO if:

```text
it only moves a few milliseconds of FFT work
it still requires full raw capture
it requires full vector readback
it adds AD9361/IIO risk without session-level time savings
```

If GO, the first candidate is a sidecar/shadow backend for the unified session,
not an active replacement.

## Demo Metrics

Use metrics that a demo can feel:

```text
total scan time
time to first useful result
channels per second
number of full-resolution captures avoided
CPU/GPU utilization during scan
IIO/AD9361 health before/after
payload size to UI/fingerprint
fallback reasons and confidence flags
```

Secondary metrics:

```text
context open time
buffer create time
refill/copy time
FFT/PSD compute time
JSON/log time
```

Do not optimize a secondary metric unless it moves a primary metric.

## Immediate Next Step

The next useful work item is not FPGA bitstream work. It is:

```text
Create a unified offline band-scan session prototype and timing model that
compares:
  old one-shot/per-channel shape
  session-reuse highres CPU/GPU shape
  optional FPGA lowres summary backend shape
```

Only after that model identifies a live test worth running should the project
enter an isolated SDR retune/session test gate.

## Current Uncommitted Inputs

At the time this plan was written, the following local drafts existed and should
be reviewed before committing or deleting:

```text
docs/P201PRO_HIGHRES_IIO_HELPER_PHASE1_PLAN.md
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/WIFI_BAND_SCAN_SESSION_PLAN.md
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/configs/
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/schemas/
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/scripts/wifi_band_scan_session.py
nx_experiments/sdr_fpga_offload_test/logs/highres_iio_wifi_session_dryrun_20260609.json
reports/stage_v10f0_xfft2048_bd_probe/
scripts/vivado_probe_xfft2048_bd_cell.tcl
```

The band-scan drafts are useful input. The V10F0/XFFT BD probe residue should
not become the main route unless the unified session model shows that FPGA
removes a seconds-level cost block.
