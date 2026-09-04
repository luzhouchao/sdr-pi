# AGX software sweep and aggregation architecture

Last reviewed: 2026-09-04

## Data path

```text
SweepPlan
   -> Rust validation and finite byte/duration calculation
   -> one P201 SDRD/1 ownership session
   -> bounded CAPTURE_IQ_INLINE windows
   -> AGX power/noise/PSD/candidate aggregation
   -> SQLite summary + optional per-scan SigMF
   -> Planner observation and Web result view
   -> selected fresh candidate only
   -> RecognitionTarget + admitted RecognitionInputProfile
   -> AGX model-ready windows for Chapter 6
```

P201 performs receive-only Linux/IIO acquisition and transport. AGX owns all
software aggregation, persistence and model-facing summaries.

## Sweep plan

The caller supplies either a continuous `start_hz`/`stop_hz`/`step_hz` range or
an explicit center-frequency list. Each plan also includes:

```text
radio:    sample_rate_hz, rf_bandwidth_hz, fixed gain
timing:   settle_ms, frame_samples, aggregate_frames, point timeout
DSP:      window, FFT size, overlap, averages and candidate threshold
storage:  summary-only or explicitly enabled per-scan SigMF
limits:   max points, duration and exact finite byte count
```

The plan is rejected before the first radio write unless:

- every center is inside `70 MHz..6 GHz`;
- sample rate is inside `2.083333..30.72 MS/s`;
- RF bandwidth is inside `0.2..56 MHz` and no greater than sample rate;
- point count, dwell, samples and total bytes fit the Rust policy limits;
- continuous coverage does not leave a gap larger than usable bandwidth;
- AGX free space is sufficient when IQ retention is enabled;
- the original radio state can be read for restoration.

For gap-free unknown-band surveys, begin with
`step_hz <= 0.8 * rf_bandwidth_hz`. Known channel plans should normally use an
explicit center list.

## AGX aggregation

For every point the software Adapter validates the returned request and session
generation, sample shape and exact byte count, decodes complex-int16 IQ, checks
clipping, computes normalized power and records Adapter sequence,
drop/overflow, measured timeout/elapsed and health metadata.  It fails closed
on a stale result, timeout, drop, overflow or unhealthy Adapter result instead
of synthesizing a healthy zero status on AGX. The engine derives a noise
baseline, merges adjacent active points and produces bounded candidates for the
next Planner turn.

Use a coarse-to-fine workflow:

1. Survey a bounded band with short windows.
2. Detect and merge occupied regions on AGX.
3. Let the Planner choose a bounded candidate inspection profile.
4. Save or forward IQ only for explicitly selected candidates.

The production recognition handoff is not an arbitrary raw-IQ forward. A
selected candidate must first pass a bounded fine inspection, source/age and
quality checks. Rust then derives capture and preprocessing from an admitted
`RecognitionInputProfile`; Planner continues to choose only the candidate ID.
The handoff separates `rx_gain_db`, raw RMS, measured SNR and any dataset SNR
label, and carries the preprocessing ID/hash into the recognition result. The
full joint plan is in
[`CHAPTER_4_6_INTEGRATION_PLAN.md`](CHAPTER_4_6_INTEGRATION_PLAN.md).

The current one-point inline frame is limited by the SDRD/1 response bound;
there is no project-wide fixed total-scan byte ceiling. Total bytes are derived
from the validated plan and remain finite.

## Result contract

Each point or aggregate record should include:

```text
sweep_id, point_index, timestamp
requested_center_hz, actual_center_hz
sample_rate_hz, rf_bandwidth_hz, gain_db
settle_ms, captured_samples, dropped_samples
noise_floor_dbfs, band_power_dbfs
peak_frequency_hz, peak_power_dbfs, peak_width_hz
occupancy, confidence, clipped_count
backend, backend_version, sequence, timeout and health flags
raw_iq_ref (only when explicitly retained)
```

The Web aggregate-results page renders the real power trace, noise baseline,
candidate markers, scan metrics and optional IQ state. SQLite stores bounded
summary/index rows; one scan may optionally own one `ci16_le` SigMF pair. Manual
deletion removes only the selected indexed result and its managed files.

## Next validation

- Complete bounded AGX software-acquisition overload testing. The separate
  sustained 5/10-MS/s aggregate acceptance gate was retired by explicit
  operator decision on 2026-09-03; this is not a new measured throughput claim.
- Keep the completed 1,800-second reconnect, cancellation and fault-recovery
  evidence covered by regression testing.
- Preserve the now-validated selected-window path to the experimental
  CUDA/Mamba Worker, and do not promote it until the RF preprocessing,
  retraining, label and rejection gates pass.
- Keep all processing on AGX; the retired FPGA path must not return.
