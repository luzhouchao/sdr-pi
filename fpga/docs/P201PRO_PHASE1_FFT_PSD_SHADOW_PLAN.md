# P201Pro Phase 1 FFT/PSD Shadow Plan

Last updated: 2026-06-09 19:20 Asia/Shanghai

This plan describes the next fast mainline push after SUM8/QUA8/AGG8 primitive
evidence. It is a working plan, not a hardware-validation claim. `VERSION_ROUTE.md`
remains the source of truth for version status, hardware-validation state, and
rollback order.

## Intent

Move the high-rate FFT/PSD-shaped SDR work away from NX CPU/GPU while preserving
the current NX SDR feature surface. The first phase should be useful quickly,
but it must stay reversible:

```text
FPGA: fixed-shape spectral summaries and limited coarse PSD bins.
NX: configuration, policy, fallback, logging, JSON/ROS publication, and AoA strategy.
```

The target is not full FFT vector readback, DMA, or active runtime replacement.
The target is an off-by-default `fpga_fft_shadow` path that can prove the
transport, ABI, and functional coverage before any active publication change.

## Current Baseline

Use these facts unless `VERSION_ROUTE.md` is updated:

```text
V8L1 remains the highest hardware-validated forward baseline.
V10S0 is hardware-validated only as an isolated V8D0-base self-test page.
The current-loaded V10S0/V8D0 image provides SUM8/QUA8/AGG8 primitive evidence.
V10S4 failed AD9361/IIO despite self-test register pass.
V10S5 remains side-path/source work until its artifact gate is complete.
No active robot_control runtime integration has happened.
```

Current SUM8 load-reduction evidence is strong at the data-movement and primitive
level, but the current Python plus SSH plus devmem validation transport is too
slow for runtime conclusions. Phase 1 therefore starts by removing that transport
cost with a local mmap/UIO register backend.

## NX Feature Coverage Target

The active NX SDR code currently uses these feature shapes:

| NX feature | Current dependency | Phase 1 target |
| --- | --- | --- |
| Channel scan | RSSI, peak, noise floor, prominence, averaged PSD | Cover with FPGA summary plus coarse PSD |
| Recommended clean channel | RSSI, occupancy, prominence gates | Cover with FPGA summary |
| `/sdr/channel_scan` payload | Per-channel summary and optional spectrum | Cover, CPU remains fallback |
| `/sdr/spectrum_snapshot` payload | Compressed spectrum, currently capped near 96 bins | Cover with coarse PSD bins |
| Heatmap | Occupancy and RSSI/prominence scoring | Cover primary behavior |
| RF fingerprint | Long-term occupancy plus compressed PSD peaks | Mostly cover with coarse PSD bins |
| Dominant user estimate | PSD peak count and peak frequencies | Cover at coarse resolution |
| Full high-resolution PSD debug | Full 2048-bin PSD array | Not covered in Phase 1 except CPU fallback |
| Dual AoA localization | Dual-RX raw IQ, cross phase, coherence, peak-bin phase | Leave for Phase 2 aperture only |

The key design choice is to return both scalar conclusions and a small spectral
shape:

```text
summary + top peaks + limited coarse PSD bins
```

Only scalar conclusions would keep simple channel recommendations alive, but it
would weaken spectrum display and fingerprint behavior. Full 2048-bin readback
would preserve everything but expands protocol, buffering, timing, and likely DMA
scope too early.

## Phase 1 ABI Shape

Use a new FFT/PSD summary page or isolated kernel page. Do not silently change
SUM8/QUA8/AGG8 register meanings.

Preferred first ABI, subject to small adjustments after resource and timing
review:

```text
identity:
  magic
  build_id
  abi_version
  capability_bitmap

frame/status:
  sequence
  valid
  stale
  overflow
  low_confidence
  sample_count
  nfft
  sample_rate_hz
  window_id
  scale_exponent
  coarse_bin_count
  coarse_bin_step_q16

summary:
  rssi_dbfs_x100
  peak_bin
  peak_offset_hz
  peak_power_dbfs_x100
  noise_floor_dbfs_x100
  peak_prominence_db_x100
  band_power_dbfs_x100

top peaks:
  top0_bin, top0_power_dbfs_x100
  top1_bin, top1_power_dbfs_x100
  top2_bin, top2_power_dbfs_x100
  top3_bin, top3_power_dbfs_x100

coarse PSD:
  coarse_psd_dbfs_x100[64..128], prefer 96 if practical
```

NX should compute absolute `peak_freq_hz` from the current LO and the returned
offset or bin metadata. FPGA should not need to know the absolute center
frequency for Phase 1.

If 96 coarse bins costs too much routing or register space, it is acceptable to
try 64 bins first. If the implementation changes from real FFT/PSD to a spectral
proxy, rename the capability and do not call it FFT/PSD.

Current ABI draft:

```text
Page: 0x400..0x6fc, identity magic 0x46465431 ("FFT1")
0x400..0x43c identity, sequence, status, sample_count, nfft, sample_rate,
              window_id, scale exponent, coarse count/step_q16, RX mask
0x440..0x45c scalar summary: RSSI, peak, offset Hz, power, noise floor,
              prominence, band power
0x460..0x484 four top-peak bin/power entries
0x500..0x6fc coarse_psd_dbfs_x100[0..127]
Preferred first coarse_bin_count: 96
Allowed coarse_bin_count: 64..128
```

This draft is represented in:

```text
nx_experiments/sdr_fpga_offload_test/sdr_fpga_offload_test/sdr_kernel_contract.py
nx_experiments/sdr_fpga_offload_test/sdr_fpga_offload_test/fft_shadow_client.py
nx_experiments/sdr_fpga_offload_test/SDR_KERNEL_CONTRACT.json
reports/p201_phase1_fft_shadow_abi_draft_20260609.md
```

## Mainline Work Stages

The stages below are intentionally bounded. The coordinator can adjust small
details when measurements or Vivado evidence point to a better shape, as long as
the safety boundary and version truth are preserved.

### P1.0 NX Functional Fit

Goal: keep the ABI matched to the current NX SDR feature surface.

Deliverables:

```text
nx_experiments/sdr_fpga_offload_test/NX_SDR_READONLY_ANALYSIS.md
docs/P201PRO_PHASE1_FFT_PSD_SHADOW_PLAN.md
```

Checks:

```text
Read-only scan only.
No ROS.
No SDR runtime start.
No active robot_control modification.
```

Decision rule:

```text
Phase 1 must include limited coarse PSD bins unless the user explicitly accepts
loss of spectrum/fingerprint fidelity.
```

### P1.1 Minimal Local Register Transport

Goal: replace SSH/devmem validation transport with a local C mmap/UIO backend.

Preferred shape:

```text
C shared library:
  open once
  mmap once
  read/write 32-bit registers
  snapshot into a fixed struct
  expose elapsed time and stale/overflow/invalid status

Python adapter:
  ctypes or cffi wrapper
  no fork/exec in the hot path
  no SSH/devmem in the hot path
```

First target can be the already validated SUM8/AGG8 page. This proves transport
speed without waiting for new FFT RTL.

Allowed tests:

```text
local compile
unit tests with fake memory/register fixtures
read-only or explicit arm/read SUM8 board probes from the NX experiment directory
```

Not allowed:

```text
active robot_control modification
ROS launch
SDR streaming runtime
mapping/navigation/robot motion
```

Gate to advance:

```text
mmap/UIO readback agrees with existing devmem client on identity and SUM8/AGG8 fields
latency is reported separately from FPGA compute time
fallback path remains available
```

Current software milestone:

```text
2026-06-09:
P1.1 native C mmap/UIO backend, ctypes adapter, default-read-only probe script,
and fake-register tests were added under the independent NX experiment
directory. Local fake-register tests pass. SDR-local standalone native probe
board readback also passes on the current-loaded V10S0/V8D0 image: read-only
identity, explicit arm/read 64x64, repeat20 poll-us=50, and post-test IIO health
all pass. This is not hardware validation and does not change the current FPGA
version route.
```

### P1.2 FFT/PSD Reference Model And Tolerances

Goal: define what "matching CPU FFT/PSD" means before RTL is judged.

Reference inputs:

```text
current NX sdr_iio_driver.py CPU path
optional CUDA path as comparison only
known synthetic tones
quiet/noise-like captures
multi-peak captures
```

Comparison metrics:

```text
peak_bin tolerance
peak_power tolerance
noise_floor tolerance
prominence tolerance
band_power tolerance
top-N peak stability
coarse PSD shape error after identical grouping rule
valid/stale/overflow flag behavior
```

Gate to advance:

```text
Tolerances are documented in the experiment directory.
The same vectors can be used by RTL simulation, Python shadow compare, and later board tests.
```

Current software milestone:

```text
2026-06-09:
P1.2 offline FFT/PSD reference and tolerance gate PASS on Windows and NX. The
reference matches the current NX Hann/fftshift/coherent-gain PSD shape, defines
exact 96-bin coarse PSD max-hold grouping for the FPGA ABI, records
`coarse_bin_step_q16=1398101` for 2048/96, and documents that the current active
UI max-hold compressor produces 98 bins for 2048-point PSD when max_bins is 96.
This is software-only and does not implement FPGA FFT/PSD hardware.
```

### P1.3 Isolated FPGA FFT/PSD Summary Self-Test

Goal: prove the register ABI and deterministic math without live AD9361 coupling.

Implementation preference:

```text
isolated self-test page
deterministic internal sample source or loaded fixture
fixed nfft first
small number of window/scale modes
summary and coarse bins visible through AXI-Lite
```

Keep this isolated from active runtime and do not promote it as live AD9361
integration. If FFT IP, custom FFT, Goertzel, or another spectral method is
chosen, name the capability exactly.

Minimum PC gates:

```text
XSIM or equivalent RTL simulation PASS
OOC synth PASS
register map/readback model PASS
timing review for new critical paths
resource review on Zynq-7020
```

Gate to advance:

```text
no critical clock/reset/CDC blocker
no route/timing claim without reading reports
ABI values match the plan or the plan is updated before testing
```

Current PC-only milestone:

```text
2026-06-09:
P1.3 isolated `fpga_fft_shadow` RTL self-test PASS. The new
experiments/phase1_fft_shadow_selftest page is a deterministic ABI fixture
derived from the P1.2 synthetic multi-tone reference. It exposes the draft
0x400..0x6fc page with identity/status, summary, four top peaks, 96 populated
coarse PSD bins, and bins 96..127 reserved/read-zero.

XSIM PASS.
OOC synth PASS at 8.138 ns target.
WNS +6.476 ns, WHS +0.129 ns.
Utilization: 103 LUT, 30 FF, 0 BRAM, 0 DSP.

This does not implement live AD9361 FFT/PSD hardware, does not generate a
bitstream/BOOT/SD payload, and does not promote any FPGA version.
```

P1.3b adds a PC-only signed top-4 PSD peak reducer primitive for the same
shadow path. The first one-cycle guard/replace/sort shape showed why timing
reports must be read: it synthesized but violated setup. The committed reducer
uses a small ready/valid multi-cycle state machine with guard-bin suppression.
XSIM PASS covers both the ABI fixture and reducer testbench. OOC timing PASS at
8.138 ns with WNS +1.102 ns, WHS +0.129 ns, and utilization of 340 LUT,
509 FF, 0 BRAM, 0 DSP. This is a post-PSD helper only; it is not a complete
FFT, PSD, coarse-bin generator, live AD9361 integration, or hardware version.

Evidence:

```text
reports/p201_phase1_p1_3b_fft_shadow_top4_reducer_20260609.md
reports/stage_phase1_fft_shadow_top4_reducer/ooc_report.md
```

P1.3c adds a PC-only exact 2048-to-96 coarse PSD max-hold reducer primitive for
the same shadow path. It matches the P1.2 exact-count grouping rule and keeps
`coarse_bin_step_q16=1398101`. XSIM PASS covers the ABI fixture, top-4 reducer,
and coarse96 reducer. OOC timing PASS at 8.138 ns with WNS +2.264 ns,
WHS +0.185 ns, and utilization of 2138 LUT, 3275 FF, 0 BRAM, 0 DSP. This is a
coarse-bin helper only; it is not a complete FFT/window/PSD generator, live
AD9361 integration, or hardware version. The resource cost is high enough that
P1.4 should explicitly review whether 96 direct AXI-Lite bins remain a runtime
path or become a debug/BRAM/vector path.

Evidence:

```text
reports/p201_phase1_p1_3c_fft_shadow_coarse96_reducer_20260609.md
reports/stage_phase1_fft_shadow_coarse96_reducer/ooc_report.md
```

P1.3d adds a PC-only 4-point complex FFT smoke core for the same shadow path.
It drives a deterministic bin-1 complex tone through a real FFT butterfly,
computes per-bin power, total power, and peak summary, and keeps the XSIM gate
tied to the existing ABI/top4/coarse96 tests. The first one-stage power path
functionally passed but failed setup timing, so the committed core pipelines
the multiplier, square-sum, and peak-summary stages. XSIM PASS covers the ABI
fixture, top-4 reducer, coarse96 reducer, and FFT4 smoke core. OOC timing PASS
at 8.138 ns with WNS +1.424 ns, WHS +0.132 ns, and utilization of 1299 LUT,
856 FF, 0 BRAM, 8 DSP. This is a minimal FFT datapath smoke test only; it is
not a 2048-point FFT/window/PSD generator, live AD9361 integration, or hardware
version.

Evidence:

```text
reports/p201_phase1_p1_3d_fft_shadow_fft4_smoke_core_20260609.md
reports/stage_phase1_fft_shadow_fft4_smoke_core/ooc_report.md
```

P1.4a records the PC-only integration review for the low-resolution default hot
path:

```text
AD9361 -> FPGA summary/top/coarse -> C mmap/UIO -> NX
```

The review keeps P1.1/P1.2/P1.3/P1.3b/P1.3c/P1.3d as useful blocks, but
identifies the missing 2048-point FFT/window/PSD generator and live AD9361
coupling as hard blockers before board staging. The recommended next step is a
PC-only Xilinx FFT IP or equivalent OOC probe for the target fixed-shape
2048-point spectral kernel, composed in isolation with the existing top-4 and
coarse96 reducers before any V8-derived live tap integration. This is not a
bitstream, BOOT/SD payload, hardware validation, or version promotion.

Evidence:

```text
reports/p201_phase1_p1_4a_fft_shadow_integration_review_20260609.md
```

### P1.4 AD9361-Safe Build Gate

Goal: integrate the isolated spectral kernel only after layout and AD9361/IIO
risk is controlled.

Build discipline:

```text
derive from V8L1/V8D0-safe knowledge
avoid monolithic edits to the live tap path
keep reset/clock changes minimal
prefer post-route evidence over exit codes
```

Minimum artifact gates before any board staging:

```text
IP/BD integration PASS if applicable
implementation PASS
write_bitstream Complete
WNS >= 0
WHS >= 0
route fully routed
routing errors 0
no critical clock/reset/CDC blocker
Bootgen PASS if an SD payload is being made
payload hashes and README written
```

Board staging and hardware validation still require the user-approved physical
SDR workflow. A software reboot is not final validation.

Current PC-only integration decision:

```text
Do not board-stage from FFT4 smoke evidence.
Do not describe FFT4 as a 2048-point FFT.
Run an isolated 2048 FFT/window/PSD OOC probe before live tap integration.
Keep 96 coarse bins only if timing/register decode remain clean after
integration; otherwise document a 64-bin runtime fallback or debug-only vector
path before testing.
```

### P1.5 Passive Live Shadow

Goal: run FPGA spectral summary beside CPU FFT/PSD without influencing NX
publication.

Mode:

```text
fpga_fft_shadow
CPU remains selected source
FPGA sidecar logs only
immediate CPU fallback on invalid/stale/overflow/low_confidence/mismatch
```

Allowed live tests, after matching artifact gate and user-approved board state:

```text
read-only identity and IIO health
passive register readback
passive shadow compare from the independent NX experiment directory
no ROS
no SDR runtime process
no active robot_control launch
no robot motion
```

Compare against:

```text
current NX CPU FFT/PSD snapshot
coarse PSD compressed with the same grouping rule used by sdr_channel_monitor.py
channel scan fields used by sdr_band_scanner.py
fingerprint fields consumed by sdr_rf_survey.py
```

Gate to advance:

```text
shadow pass rate and mismatch reasons are logged
identity and IIO health remain good after stress
transport latency is measured with mmap/UIO, not SSH/devmem
```

### P1.6 Active-Package Dry-Run Only

Goal: prepare, but not apply, an off-by-default active package candidate.

Allowed:

```text
patch --dry-run
py_compile
static import checks if they do not launch runtime
```

Required default:

```text
FPGA_FFT_MODE=off or shadow
CPU publication remains default
FPGA output is sidecar logging only
CPU fallback is immediate
```

Not allowed without explicit user approval:

```text
applying active robot_control changes
starting ROS
starting SDR streaming runtime
publishing FPGA-selected values
mapping, navigation, robot_controller, cmd_vel, robot motion
```

## Fast Change Rules

The plan should move quickly, but changes need a clear rule:

```text
Small ABI width/count changes are allowed when documented before tests.
Dropping coarse PSD below 64 bins requires documenting feature loss.
Moving from FFT/PSD to a proxy requires renaming the capability.
Any AD9361/IIO failure stops promotion and routes back to isolation analysis.
Any active robot_control change waits for explicit user approval.
```

Avoid spending time perfecting every future feature. Phase 1 should prove:

```text
local transport is fast enough
summary/coarse PSD covers current NX scan/spectrum/heatmap/fingerprint behavior
shadow compare is stable
fallback remains boring and immediate
```

## Subagent Collaboration Map

Use subagents as bounded work packages. The coordinator owns merge order, final
claims, and live-test decisions.

| Lane | Scope | Can run in parallel | Must not do |
| --- | --- | --- | --- |
| A1 NX feature audit | Keep `NX_SDR_READONLY_ANALYSIS.md` current; map fields to ABI | Yes, after P1.0 target is known | Modify active robot_control |
| A2 C mmap/UIO backend | C shared library, fake-register tests, SUM8 readback client | Yes, independent of FFT RTL | Start runtime or use fork/devmem hot path |
| A3 Python adapter | ctypes/cffi wrapper, dataclass conversion, shadow logging | Yes, after draft C ABI | Apply active package patch |
| A4 Reference vectors | CPU FFT/PSD fixtures, tolerances, grouping rule | Yes | Claim hardware equivalence |
| A5 RTL kernel | isolated self-test RTL, XSIM/OOC, register map | Yes, after ABI draft | Touch active runtime or claim live AD9361 |
| A6 Vivado/artifact gate | logs, timing, route, Bootgen, hashes, README | After A5 outputs | Trust exit code alone |
| A7 NX board probe | independent experiment readback/shadow scripts | After artifact gate and approved board state | Start ROS/SDR runtime or motion |
| A8 Documentation audit | keep `VERSION_ROUTE.md`, handoff, reports indexes consistent | Yes | Promote unvalidated version claims |

Recommended coordination:

```text
Freeze a minimal ABI draft before A2/A3/A5 branch too far.
Let A2 prove transport on existing SUM8 while A5 works on isolated spectral RTL.
Let A4 define tolerances before P1.5 board shadow.
Use A8 after each milestone so route facts do not drift.
Close subagents promptly after their scoped task finishes.
```

NX-side Codex may help only inside the approved independent experiment scope:

```text
/home/wheeltec
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
```

It must not modify active `robot_control` or start forbidden runtime processes.

## Live Test Policy

Live tests are useful, but they are gates, not background activity. Start them
only when the matching software/RTL/artifact preconditions are met.

Read-only checks can be used to confirm board state:

```text
FPGA identity registers
expected build IDs
AD9361/IIO device presence
post-test identity and IIO health
```

Power-cycle-dependent hardware validation requires the user to physically
power-cycle the SDR and then run the expected post-boot validation. Do not call a
candidate hardware-validated before that chain passes.

If the live board is not in the expected state, adapt the plan by moving back to:

```text
offline reference tests
mmap/UIO transport tests against current safe registers
isolated self-test RTL
artifact gate review
```

## Phase 2 Aperture Only

Do not plan Phase 2 in detail until Phase 1 shadow evidence is good.

Leave this interface direction open:

```text
fpga_aoa_shadow
rssi0_dbfs
rssi1_dbfs
coherence
phase_cross_deg
phase_used_deg
phase_corrected_deg
peak_freq_hz
peak_power_dbfs
clipped
ambiguity_risk
```

Phase 2 should target dual-RX phase/coherence primitives for AoA. It should not
be mixed into Phase 1 FFT/PSD summary work except for preserving compatible
status/fallback conventions.

Do not claim Phase 2 coverage for:

```text
dual AoA localization
dual RX raw debug
triangulation
robot motion decisions
```

Those remain NX-owned or future-shadow-only until Phase 1 is complete and a new
user-approved Phase 2 plan is written.

## Completion Definition

Phase 1 is complete enough to plan Phase 2 only when:

```text
C mmap/UIO transport is validated against existing safe registers.
FFT/PSD summary ABI is documented and self-tested.
Coarse PSD bins preserve scan/spectrum/heatmap/fingerprint behavior in shadow.
Passive live shadow logs show stable comparisons and post-test IIO health.
An active-package dry-run candidate passes patch --dry-run and py_compile.
No active runtime change has been made without explicit user approval.
```

Until then, keep CPU as the publication authority and treat FPGA output as
sidecar evidence.
