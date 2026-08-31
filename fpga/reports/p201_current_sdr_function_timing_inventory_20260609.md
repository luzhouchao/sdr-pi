# Current SDR Function Timing Inventory

Date: 2026-06-09 Asia/Shanghai

## Scope

This report measures and inventories the current implemented SDR software functions, not FPGA primitive performance in isolation. It uses existing independent logs, read-only inspection of the active NX `robot_control` SDR source files, and one NX offline synthetic CPU benchmark that imported active modules without connecting IIO, retuning SDR, starting ROS, or starting any SDR runtime.

No active `robot_control` file was modified. No ROS, SDR streaming runtime, mapping, navigation, `cmd_vel`, robot motion, BOOT/SD staging, or power-cycle action was started by this report step.

## Current Implemented Function Surface

| Function | Active implementation shape | Current timing status |
| --- | --- | --- |
| IIO driver connect/capture/PSD | `sdr_iio_driver.py`: connect, enable channels, create buffer, refill/read, CPU/CUDA PSD, batch PSD | Partially measured by helper and offline CPU benchmark; full active connect path still needs instrumented live run. |
| Band scan | `sdr_band_scanner.py`: for each point, retune, settle, read `rounds_per_channel`, analyze batch, aggregate RSSI/PSD | Source-derived lower bound known; full live scan not yet timed. |
| Channel monitor | `sdr_channel_monitor.py`: periodic scan, occupancy scoring, recommendations, spectrum compression, JSON publish | Source shape known; payload build/publish not yet separately timed. |
| Spectrum snapshot / UI payload | PSD array plus max-hold compression to `SPECTRUM_MAX_BINS_PER_CHANNEL=96` | Compression shape known; payload timing still missing. |
| Dual-RX AoA | `sdr_dual_aoa_core.py` plus `sdr_dual_aoa_localizer.py`: raw read, lane unpack, AoA FFT/cross phase, smoothing, ray/fix publish | CPU algorithm measured offline; full timer loop not yet live-timed. |
| CUDA FFT backend | `sdr_cuda_fft_backend.py`: optional ctypes wrapper, single/batch PSD | Implementation present; current report measured CPU path only. |
| FPGA AoA sidecar backend | `sdr_aoa_backend.py` staged/active candidate shape uses helper script and SSH/devmem for SUM8/AGG8 | Measured as validation transport; not a fast project runtime path. |

## Measured Baseline

| Function block | Median timing | What it means |
| --- | ---: | --- |
| SDR-local IIO context open | 28.293 ms | One-shot setup dominates local helper setup. |
| SDR-local IIO buffer create | 3.133 ms | Smaller than context open, still setup-owned. |
| SDR-local IIO refill | 0.025 ms | Refill itself is not the seconds-level bottleneck. |
| SDR-local IIO copy, 8192 sample run included | 0.317 ms | Copy is sub-ms in the helper evidence. |
| NX wrapper around helper | 154.326 ms | Validation wrapper overhead, not hot-path refill cost. |
| Active CPU PSD, 4096 IQ, NFFT 2048 | 0.271 ms | Algorithm-only synthetic benchmark on NX. |
| Active CPU PSD batch, 3 x 4096 IQ | 0.800 ms | Matches heatmap rounds-per-channel shape without live IIO. |
| Active AoA lane unpack + estimate, 8192 x 4 | 0.523 ms | AoA math itself is sub-ms on synthetic data. |
| Raw IIO capture in shadow compare, 4096 dual-RX | 29.269 ms | Existing live independent log; includes live raw IIO capture path used by compare script. |
| CPU dual-RX primitive compute, 4096 samples | 0.950 ms | Existing live independent log; math is not the slow step. |
| AGG8 one-window read over current SSH/devmem validation path | 286.774 ms | Validation transport only; too slow for runtime. |
| FPGA sidecar read in primitive-assist validation path | 806.739 ms | Confirms current sidecar helper is not project-level fast path. |
| SDR-local native mmap register snapshot | 0.009 ms | Fast local transport evidence, but not integrated into active SDR functions. |

## Default Scan-Time Lower Bounds From Active Source

| Profile | Channels | Rounds/channel | Settle policy from code | Settle-only lower bound |
| --- | ---: | ---: | --- | ---: |
| `fast_survey_24g` / heatmap | 13 | 3 | retune settle + between-read delays | 1.170 s batch path, 1.560 s fallback path |
| `full_band_fingerprint` | 38 | 2 | retune settle + between-read delays | 2.660 s batch path, 3.990 s fallback path |

These lower bounds exclude IIO LO write time, buffer reads, FFT/PSD, AoA hooks, scoring, compression, JSON serialization, ROS publish, and reconnect failures. They show why the next optimization should measure and reshape the scan session rather than optimize sub-ms math first.

## Important Interpretation

- The active CPU PSD and AoA math are sub-ms in the offline synthetic benchmark. This does not prove live scans are fast; it says the seconds-level cost is unlikely to be the NumPy FFT/AoA arithmetic alone.
- Existing live independent raw-IIO capture in compare scripts is about 29 ms median for the 4096 dual-RX capture shape, while the local helper shows refill/copy itself is far below that. The missing breakdown is active `IioSdrDriver.read_raw_i16()` plus Python IIO wrapper behavior during real scans.
- The current FPGA sidecar evidence is dominated by SSH/devmem validation transport: around 0.8 s per sidecar read. That is useful validation evidence, not a project-level optimization path unless replaced by local mmap/UIO or a session-owned backend.
- The default heatmap/full-fingerprint profiles already contain seconds-scale repeated settle time. Scan policy, session lifetime, batching, and payload cadence are the likely high-leverage targets.

## Missing Timing Points

| Missing point | Why it matters | Safe next measurement shape |
| --- | --- | --- |
| Active `IioSdrDriver.connect_with_channels()` breakdown | Separates context open, LO/sample-rate/RF-bandwidth writes, channel enable, and buffer creation in the real active code | Off-by-default timing wrapper in independent copy first; active patch only after approval. |
| Active `scan_scan_points()` per-channel timing | This is the real WiFi scan loop: retune, settle, capture, analyze, aggregate | Isolated non-ROS live scan from independent directory after explicit approval, starting with channels 1/6/11. |
| `sdr_channel_monitor._build_payload()` and `_build_spectrum_payload()` | UI/status payload can matter when repeated across many channels | Offline replay using saved/synthetic `ChannelScanResult` objects, no SDR. |
| CUDA backend live availability and batch timing | GPU path may already be useful if sessions batch work correctly | Offline synthetic CUDA benchmark if `libsdr_cuda_fft.so` is present; no SDR. |
| Full ROS timer-cycle time | Needed for demo-visible latency | Only after explicit runtime approval; no mapping/navigation/motion. |

## Next Work Item

Build a read-only/offline timing harness under the independent experiment directory that can replay or synthesize `ChannelScanResult` objects and can, after a separate approval gate, run one isolated non-ROS 1/6/11 scan. The harness should emit per-function timings for connect, retune, settle, read_raw_i16, analyze_spectrum_batch, result aggregation, occupancy scoring, spectrum compression, JSON payload, and optional AoA hook.

This is the correct next step before deciding whether FPGA, CPU, GPU, or pure scan-policy optimization is worth pursuing.
