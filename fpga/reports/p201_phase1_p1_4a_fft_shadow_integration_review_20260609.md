# P201 Phase 1 P1.4a FFT Shadow Integration Review

Generated: 2026-06-09 18:16 Asia/Shanghai

## Scope

P1.4a is a PC-only integration review for the low-resolution
`fpga_fft_shadow` mainline:

```text
AD9361 -> FPGA summary/top/coarse -> C mmap/UIO -> NX
```

This review does not add RTL, does not run Vivado implementation, does not
generate a bitstream, does not generate or overwrite `BOOT.bin`, does not stage
an SD payload, does not touch active `robot_control`, and does not change the
hardware version route.

## Current Usable Blocks

Phase 1 has these usable, bounded blocks:

| Block | Evidence | Integration Meaning |
| --- | --- | --- |
| Native C mmap/UIO transport | P1.1 fake-register and SDR-local V10S0/V8D0 SUM8/AGG8 probes PASS | Suitable transport shape for future local register snapshots; no SSH/devmem hot loop. |
| FFT shadow ABI/client | ABI draft and fake-register gate PASS | Stable `0x400..0x6fc` software contract for summary, four top peaks, and 64..128 coarse PSD bins. |
| FFT/PSD reference gate | P1.2 Windows/NX PASS | Defines current NX Hann/fftshift/coherent-gain PSD math, exact 96-bin coarse PSD, and tolerance fixtures. |
| ABI fixture RTL | P1.3 XSIM/OOC PASS | Proves deterministic AXI-Lite register shape only. |
| Top-4 PSD reducer | P1.3b XSIM/OOC PASS | Timing-clean post-PSD helper with guard-bin suppression. |
| Coarse96 reducer | P1.3c XSIM/OOC PASS | Exact 2048-to-96 max-hold helper matching P1.2 grouping. |
| FFT4 smoke core | P1.3d XSIM/OOC PASS | Minimal true FFT butterfly datapath smoke test with power/peak summary. |

The current highest hardware-validated forward baseline remains:

```text
V8L1 / SUM8 + QUA8 + AGG8 auto-aggregate
```

V10S0 remains hardware-validated only as an isolated self-test page on a V8D0
live tap base. It is not live FFT/PSD integration.

## Explicit Gaps

The A-route shadow path is not ready for board staging because these pieces do
not exist yet:

- no 2048-point FFT core in the Phase 1 shadow path
- no Hann/window application in RTL
- no PSD scale/calibration path matching the P1.2 reference
- no integrated pipeline connecting FFT/window/PSD to top-4 and coarse96
- no live AD9361 sample/valid/clock/reset coupling for the FFT shadow page
- no IP/BD integration, implementation, route, bitstream, Bootgen, or payload
- no board readback or physical-power-cycle hardware validation
- no active NX runtime integration

Do not present the P1.3d FFT4 smoke core as a 2048-point FFT. It is valuable
because it proves a timing-clean fixed butterfly/power/peak datapath in
isolation, but it is not a production FFT/window/PSD generator.

## Integration Decision

P1.4 should not jump directly from the FFT4 smoke core to a board-staged live
tap image.

Recommended next technical step:

```text
Build a PC-only Xilinx FFT IP or vendor-equivalent OOC probe for the target
2048-point fixed-shape spectral kernel, then compose it in isolation with the
existing post-PSD top-4 reducer and coarse96 reducer before any V8-derived live
tap integration.
```

The probe should stay isolated from the live AD9361 tap until it shows:

- fixed 2048-point configuration, or a documented smaller first step that is
  not called the 2048 runtime path
- deterministic valid/ready framing and backpressure behavior
- explicit window policy: Hann first if matching the P1.2 reference, or a
  documented rectangular-mode fallback with changed capability bits
- PSD square-sum scaling and signed dBFS conversion strategy, or an explicit
  split where NX applies final log/dB calibration from fixed-point powers
- top-4 reducer and coarse96 reducer composition with known latency
- no full 2048-bin AXI-Lite readback in the runtime path

## Coarse PSD Register Review

P1.3c proved exact 96-bin coarse PSD reduction in isolation, but the direct
register cost remains a design risk:

```text
96 coarse bins = useful for NX spectrum/fingerprint continuity
128 reserved ABI bins = convenient for compatibility
full 2048 bins = not Phase 1 runtime scope
```

Keep 96 coarse bins as the first functional target only if timing and register
decode remain clean after FFT/window/PSD integration. If timing/resource pressure
appears, the safe fallback is a documented 64-bin runtime page plus a debug-only
path for wider vectors. If a debug vector path is added later, keep it outside
the hot runtime path and do not promote it without a separate performance review.

## FPGA/NX Split

Keep the Phase 1 split:

```text
FPGA:
  fixed-shape FFT/window/PSD primitive
  scalar summary
  top peaks
  limited coarse PSD bins
  valid/stale/overflow/low_confidence/sample_mismatch flags

NX:
  center-frequency composition
  calibration
  dB/log policy if not finalized in FPGA
  feature flags
  fallback
  logging
  publication only after explicit approval
```

Native C mmap/UIO remains the right transport direction for the future hot path.
Python remains appropriate for validation, reference comparison, and shadow
logging, but not for runtime-influencing high-frequency polling.

## Pre-Board Gates

Before any board staging for FFT shadow, require:

```text
P1.2 reference gate still PASS
FFT shadow fake-register ABI gate still PASS
XSIM PASS for the integrated FFT/window/PSD/top4/coarse path
OOC timing PASS for each risky primitive
IP/BD integration PASS if applicable
implementation PASS
write_bitstream Complete
WNS >= 0
WHS >= 0
route fully routed
routing errors 0
no critical clock/reset/CDC blocker
Bootgen PASS if an SD payload is made
unique artifact directory and README
payload hashes if staging is intended
VERSION_ROUTE.md updated without overstating validation
rollback version remains V8L1 unless VERSION_ROUTE.md changes
```

Board staging still requires the normal SDR `/sd` workflow and a later physical
power-cycle validation. A software reboot is not final validation.

## Non-Claims

P1.4a does not claim:

- hardware validation
- runtime integration
- active `robot_control` safety
- FFT/PSD complete
- 2048-point FFT implemented
- board staging readiness
- hardware version promotion

## Checks Run

Lightweight checks for this PC-only documentation milestone:

```text
python scripts/test_fft_shadow_contract.py -> PASS
python scripts/test_fft_psd_reference.py -> PASS
git diff --check -> PASS
```

No ROS, SDR streaming runtime, mapping, RTAB-Map, navigation,
`robot_controller`, `cmd_vel`, or robot motion commands are part of this
milestone.

## Next Safe Step

Create a PC-only P1.4b isolated 2048 spectral-method probe, preferably using
Xilinx FFT IP/OOC evidence first. Only after that probe composes cleanly with
the top-4 and coarse96 reducers should the mainline consider a V8-derived live
tap integration candidate.
