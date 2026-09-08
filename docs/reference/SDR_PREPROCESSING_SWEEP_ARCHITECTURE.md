# AGX software sweep and aggregation architecture

Last reviewed: 2026-09-07

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
radio:    fixed RX1/A_BALANCED identity, sample_rate_hz, rf_bandwidth_hz, gain
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
- the Adapter probes and correlates the verified RX1/RX0/A_BALANCED identity
  returned by current SDRD/1; missing, changed or incompatible identity fails closed.

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
[`CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](../CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md).

The current one-point inline frame is limited by the SDRD/1 response bound;
there is no project-wide fixed total-scan byte ceiling. Total bytes are derived
from the validated plan and remain finite.

## Result contract

Each point or aggregate record should include:

```text
sweep_id, point_index, timestamp
requested_center_hz, actual_center_hz, rx_port_identity
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

## Validation status and next work

- The fixed `RX1 / A_BALANCED` SDRD/1 capability, profile/capture audit field
  and end-of-session unchanged check are live-validated and remain outside
  Planner parameters.
- Bounded AGX software-acquisition overload testing is complete: the current
  path processed 128 maximum inline frames (32 MiB) without loss, rejected an
  oversized point before backend work and restored after deadline and client-
  disconnect failures; see
  [`P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md`](../validation/P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md).
  The separate sustained 5/10-MS/s aggregate acceptance gate remains retired
  by the explicit 2026-09-03 operator decision; this is not a new continuous-
  streaming claim.
- Keep the completed 1,800-second reconnect, cancellation and fault-recovery
  evidence covered by regression testing.
- Preserve the now-validated selected-window path to the experimental
  CUDA/Mamba Worker, and do not promote it until the RF preprocessing,
  retraining, label and rejection gates pass.
- Keep all processing on AGX; the retired FPGA path must not return.

## Web first-survey parameter suggestions (2026-09-08)

The Web settings page can independently fix step, settling time and gain, or ask
its saved upstream Planner to fill any subset. `POST /api/survey/parameters`
accepts integer `start_hz`, `stop_hz`, and nullable `step_hz`, `dwell_ms`, `gain_db`.
Null means model-selected; non-null values are immutable. The endpoint never
creates a session, saves settings, starts RX or sends an execution command.

Web uses `SDR_WEB_PLANNER_SOCKET` (default `/run/sdr-agent/planner.sock`). The
existing bounded one-shot socket accepts a separate `operation=survey_parameters`
frame with `protocol_version=1`, a correlated `request_id` and those five fields.
It shares the existing inference lease and provider selection with normal
Planner requests. Its only tool uses a three-integer suggestion schema; no web
search, hardware tools, observations or IQ are provided. Existing action/session
protocols and Controller execution rules are unchanged.

Both Worker and Rust reject changes to fixed fields, malformed/extra output,
step outside 1 kHz–8 MHz, dwell outside 0–1000 ms, gain outside 0–60 dB, more than
768 points or a conservative duration over 300 seconds. Rust preserves the exact
requested endpoints. Sample rate/bandwidth remain 10 MHz and frame size remains
4096 complex int16 samples per point. These are the existing first-survey
execution settings, not additional model-selected fields.

The response contains a validated concrete `initial_survey` and Planner identity.
The page discards suggestions received after settings edits, invalidates an old
suggestion when its input changes, and requires successful generation before
saving AI-selected fields. Saving stores concrete values in the existing config;
AI/manual selector state is intentionally not persisted or re-run at startup.
The normal new-session confirmation and once-only initial-survey claim still
control RX. Requests are bounded by the Planner's existing timeout (at most
120 s), a 125 s Web exchange and a 130 s browser request. Failure has no default
parameter fallback and no execution side effects.

Frequency display selects Hz/kHz/MHz/GHz and retains integer-Hz precision without
trailing zeroes. Only rendered sweep text is reformatted; original session events
and protocol Hz integers remain unchanged (for example 2400000000–2483500000 Hz
renders as 2.4–2.4835 GHz).
