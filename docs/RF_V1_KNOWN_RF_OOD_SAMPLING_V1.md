# RF-v1 independent known-RF/OOD sampling protocol v1

Registered 2026-09-06, before collecting/fitting the new independent evidence.
This is V1a's collection and review specification, not a claim that V1b data
exists or that any production classifier is admitted. Changes require a new
version before inspecting the affected acceptance predictions; retain the prior
version and rationale. The epoch-10 checkpoint, FP16 autocast/FP32 resident
weights, RF-v1 four-window/shared-RMS transform and numeric class space stay
fixed. No locked-test access, training or precision re-selection is authorized.

## Scope and sampling unit

Only P201 Linux/IIO RX1/RX0/A_BALANCED acquisition and AGX processing are in
scope. No TX, USRP/B210/N210, FPGA/BOOT or NX offload is a data dependency or
permitted collection action. Each acquisition needs its own finite repository-
validated plan, byte/free-space check, direct stop, restoration and cleanup.
This document does not authorize a continuous collector or preapprove a batch
of future captures. User corpus results are persistent application data with a
visible manual-delete path, not development temporary data.

One RF-v1 observation is one original 4,096-complex-sample capture at 2.1 MS/s,
1.5 MHz bandwidth, fixed 50-dB gain, interpreted as four ordered 1,024-sample
windows with shared RMS and DC preserved. Four windows, multiple label revisions,
repeated inference, crops or derived profiles are not four independent samples.
The raw content SHA-256, source sample, capture session and UTC date remain
attached to every derivation. A copied capture is counted once.

The existing store admits complete healthy captures with zero drop/overflow/
clipping and verified restoration. Low-quality signal conditions below refer to
low SNR, fading, interference, poor spectral containment or ambiguous occupancy
within such intact captures. Incomplete hardware captures and transport faults
must be recorded separately as acquisition failures; do not relabel their bytes
as valid known/OOD corpus. Extending the acquisition safety contract is outside
V1a. Silence or unusable RF-v1 numerical RMS is retained as signal-quality
context where the raw intake allows it; it is not forced through the classifier.

## Evidence and annotation review

Use `unknown` until an independent reviewer has a source-correlated basis.
A model top-1, softmax, agreement, recognizer report, or an unknown reason is
never that basis. `independent_of_model=true` is a reviewer's declaration checked
by the tool, not automatic proof of honesty or scientific correctness.

Every independent annotation needs:

- an immutable report and its SHA-256, reviewer ID, method and UTC review time;
- the original IQ hash, source sample/session/day, request/generation/sequence,
  frozen profile/preprocess and numeric-label-space hashes;
- a concrete explanation of how the external decoder, independent instrument
  measurement or documented human review establishes this capture's class or
  nonclass condition, including time/frequency correlation;
- an explicit category, numeric ID only for known classes, and any ambiguity.

The report should state instrument/decoder/version, observation interval,
frequency/bandwidth, clock uncertainty, signal isolation and competing sources.
Human review requires an external factual basis; visual resemblance to a model
prediction is insufficient. The reviewer must explain the numeric-ID mapping
without treating the disputed display-name table as verified. If this cannot be
established, retain an ambiguous receive-domain record and resolve it in V1b/V3a.
Independent reviewers should work without seeing model predictions. Disagreement
must be retained and adjudicated independently before evaluation eligibility.

The corpus continues to distinguish `dataset_ground_truth` for original offline
rows, `independent_annotation` for correlated received evidence, and `unknown`.
The P201 import API rejects dataset-ground-truth labels. This protocol neither
loads nor imports dataset test rows. Text names remain provisional; a numeric ID
identifies the model class slot, not an independently proved signal by itself.

Old seven-file packages lack an original request report. Their immutable metadata
can be rebound to RF-v1 as unknown only. A reconstructed report must be identified
as such; matching an IQ hash or waveform is insufficient to invent a missing
request receipt. Newly ingested root packages retain the original report hash.

## Coverage matrix and selection

Select captures by a predeclared time/frequency sampling schedule or independently
identified signal availability, never by confidence or a desired predicted class.
Log attempted, rejected, unavailable, unlabeled and ambiguous captures alongside
successes so coverage is not inflated by cherry-picking. No unknown record enters
known-class accuracy, calibration fitting or acceptance metrics.

| Category | Independent target | Required variation and accounting |
| --- | --- | --- |
| `known_class` | Each numeric ID 0–23 with independently justified mapping | Measured receive SNR bins `<10`, `10–20`, `>20` dB; at least two center-frequency regions and two occupied-bandwidth ranges where independently available; source/session/day variation. Unavailable combinations are explicit gaps, never synthesized labels. |
| `noise_idle` | Correlated absence of the target signal / independently characterized noise | Quiet and raised-noise periods, different frequency regions and days; a small peak alone does not establish idle. |
| `out_of_label_space` | Independently established modulation outside the 24-class space | At least three independently documented families and two spectral regions; no numeric ID forced into the known space. |
| `mixed` | Independently confirmed multiple components/interference | Dominant-component ratios, overlapping/separated spectra and varying SNR; no single correct class without a separately reviewed isolation rule. |
| `low_quality` | Independently established impairment affecting interpretation | Low SNR, fading/interference and off-center or broad occupancy, with quality severity recorded independently of confidence. |
| `ambiguous` | Incomplete or conflicting evidence | Preserve the dispute/basis; receive_domain only, excluded from fitting and acceptance. |

Calibration and acceptance must each include every claimed class/category and
its declared operating conditions. Do not generalize a narrowband/SNR-limited
sample to unmeasured conditions. If coverage is infeasible, revise the claimed
operating domain before acceptance prediction access and record the exclusion.
Record gain, ADC RMS/dBFS, measured receive SNR and dataset nominal SNR separately;
these are different quantities. No field SNR is inferred from gain alone.

## Sample-size rationale

These are planning targets for statistical resolution, not acceptance thresholds
and not values for temperature/confidence/agreement/SNR rejection policy.

For independent Bernoulli observations, the worst-case approximate two-sided
95% half-width is `1.96 * sqrt(0.25 / n)`: 385 effective observations support
about ±5 percentage points for one aggregate proportion. For simultaneous
per-class reporting across 24 classes, a Bonferroni-adjusted normal quantile is
about 3.08, requiring about 950 effective observations per class for the same
precision. Set the acceptance planning target to **1,000 effective independent
observations per claimed known class**, with at least 100 per measured-SNR bin.
Report Wilson intervals and the actual multiple-comparison correction; the
normal formula is only the advance planning approximation.

For an OOD stratum with zero false accepts, a one-sided exact bound is
`1 - alpha^(1/n)`. Using `alpha=0.05/4` across the four nonclass categories,
**437 effective observations per category** resolve an upper bound of about 1%.
This is a measurement-resolution example, not a frozen permissible false-accept
rate. Nonzero counts need exact intervals and may require additional independently
planned data. No performance-dependent collection may repeatedly peek and stop
when a passing bound first appears without a separately registered sequential
procedure. Collect the fixed target before opening acceptance predictions.

Calibration planning starts at **400 effective observations per known class**
and **200 per nonclass category**, with the same declared coverage axes. Freeze
the fitting/selection procedure using calibration only, including uncertainty
and sensitivity analysis. If this cannot constrain the selected scalar/policy
parameters, register a larger calibration-only campaign; do not consume the
acceptance group to fix the deficit.

Correlation reduces information. A burst of adjacent captures does not meet
these effective sample targets. Before counting samples, the reviewer must
justify independent source/session blocks and estimate or conservatively bound
within-session/day dependence. Use block/cluster intervals by source session
and day, and report both raw counts and effective counts. The planning relation
`n_eff = n / (1 + (m-1)*rho)` illustrates cluster inflation; unknown dependence
must not be treated as zero. Require at least 10 distinct calibration days and
30 distinct acceptance days for clustered reporting, plus multiple source/
session blocks in each coverage cell. Those day minima alone do not establish
1,000 effective trials. If effective independence cannot be supported, V1b
coverage remains incomplete irrespective of raw capture count.

## Split assignment and acceptance isolation

1. Register calibration vs acceptance campaigns before model-output inspection.
   Source sample, capture session, UTC day and identical raw IQ must not cross
   train/validation/test/calibration/acceptance evaluation partitions.
2. Every derived record inherits the original source/session/day. The parent
   may remain unknown in receive_domain; an independently reviewed child may
   enter its assigned evaluation partition. Do not rewrite the parent.
3. The application commits group assignments transactionally. Hash-only group
   constraints survive manual record deletion so deletion/re-import cannot
   migrate previously assigned data into a different evaluation partition.
   This is not retention of IQ or the annotation report.
4. Freeze the independently reviewed acceptance manifest/hashes before opening
   its model predictions. Annotators may inspect evidence to determine labels;
   the fitting workflow may not inspect acceptance predictions or use them to
   select temperature/policy. Keep selection logs and role separation in V1b.
5. The current tool's coverage output reports raw records, distinct IQ hashes,
   sessions and days. These are not effective sample sizes, reviewed coverage,
   or proof of labels. It always reports `v1b_complete=false` and
   `recognizer_available=false`.

V1b requires actual reviewed evidence and coverage meeting this preregistration
(or a prospectively documented revision). V2 still must freeze calibration and
rejection, report known accuracy/coverage/rejection, OOD false acceptance and
ECE/NLL on independent acceptance data. V3 still owns the one-time locked-test
admission and name-space questions. V1a tools/specification cannot complete any
of those gates.
