# P201Pro Reusable SDR FPGA Submodule Matrix

Date: 2026-06-10 current-state snapshot

## Purpose

This document separates reusable FPGA submodules from version-route handoff
state. `VERSION_ROUTE.md` remains the source of truth for hardware validation.

The goal is not to make everything an FFT. The goal is to move repeated,
fixed-shape SDR preprocessing from NX to FPGA while keeping NX responsible for
configuration, division, sqrt, atan2, calibration, policy, fallback, logging,
and publication.

## SDR-Tested Artifacts

### V8D0 Layout Probe

Meaning:

```text
V8L1-like SUM8/QUA8/AGG8 logic with build-ID-only HDL changes.
```

Why it matters:

```text
Tests whether fresh Vivado implementation/layout churn alone can reproduce the
AD9361 TX tuning / cf-ad9361-lpc failure seen on V9A, V9B0, and V8L2.
```

Status:

```text
PC build PASS
post-route physopt PASS
Bootgen PASS
SD payload generated
staged to SDR /sd on 2026-06-09 10:27 Asia/Shanghai
hardware-validated as diagnostic layout probe after physical SDR power-cycle
on 2026-06-09 10:32 Asia/Shanghai
```

Artifact:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8d0_layout_probe
```

### V10S0 Mixed Reusable Submodule Self-Test

Meaning:

```text
V8D0 base plus isolated AXI-Lite self-test page at 0x43C10000.
```

Included reusable modules:

```text
frame packer
post-FFT bin power
FFT summary reducer
bandpower reducer
multi-lag correlation module
AXI-Lite deterministic self-test wrapper
```

Why it is not "all FFT":

```text
Only three blocks are FFT-adjacent: frame packer, bin power, and summary.
Bandpower and correlation are separate reducers that can be reused with or
without a future FFT front end.
```

Status:

```text
XSIM PASS
OOC synth PASS
IP package PASS
BD integration PASS
full bitstream PASS
Bootgen PASS
SD payload generated
staged to SDR /sd on 2026-06-09 10:48 Asia/Shanghai
hardware-validated as isolated self-test after physical SDR power-cycle
on 2026-06-09 10:52 Asia/Shanghai
```

Artifact:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s0_submodule_selftest
```

## PC-Only Submodule Tracks

These tracks are meant to produce reusable RTL and testbenches first. They
should not be merged into the live V8L1/V8D0 tap path until AD9361/IIO
sensitivity is understood.

### V10S1 Quality Stats

Not FFT.

Target FPGA work:

```text
sample count
sum_i and sum_q
sum_i2 and sum_q2
sum_iq / cross term
absolute peak
clipping/saturation count
valid/drop counters
```

PC status:

```text
XSIM PASS
included in combined V10S1/S2/S3 OOC synth PASS
no IP package
no bitstream
no SD payload
not hardware validated
```

NX load reduced:

```text
per-frame mean, RMS/power ingredients, clipping checks, low-quality rejection,
and quality logging inputs.
```

### V10S2 Frame Window

Not FFT.

Target FPGA work:

```text
decimation-by-N gate
frame sample counter
valid/last generation
optional lightweight fixed window multiply
drop/overflow counters
```

PC status:

```text
XSIM PASS
included in combined V10S1/S2/S3 OOC synth PASS
no IP package
no bitstream
no SD payload
not hardware validated
```

NX load reduced:

```text
sample selection, frame boundary bookkeeping, and repeated pre-windowing for
future FFT or non-FFT reducers.
```

### V10S3 Energy Peak

Not necessarily FFT.

Target FPGA work:

```text
total energy
minimum/noise-floor proxy
max peak value and index
second peak
prominence proxy
threshold crossing count
```

PC status:

```text
XSIM PASS
included in combined V10S1/S2/S3 OOC synth PASS
no IP package
no bitstream
no SD payload
not hardware validated
```

NX load reduced:

```text
peak/noise/prominence scans over power streams. The input can be FFT bin power
or ordinary scalar power windows.
```

## Non-FFT Combined Self-Test Candidate

### V10S4 Non-FFT Self-Test Page

Meaning:

```text
An isolated AXI-Lite self-test page that combines V10S1, V10S2, and V10S3
deterministic tests into one SDR-testable image.
```

Current status:

```text
V10S1/S2/S3 XSIM PASS
combined V10S1/S2/S3 OOC synth PASS
V10S4 AXI-Lite wrapper XSIM PASS
OOC synth PASS
IP package PASS
BD integration PASS
full bitstream PASS
Bootgen PASS
SD payload generated
staged to SDR /sd on 2026-06-09 10:36 Asia/Shanghai
post-power-cycle: self-test registers PASS
post-power-cycle: AD9361/IIO FAIL
NOT hardware validated
```

Artifact:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s4_nonfft_selftest
```

BOOT hash:

```text
df773e5b8b01f301634ff838f462464289213cfb4bba6c11855d022e08a377ce
```

Acceptance before any SDR staging:

```text
RTL review PASS
deterministic XSIM PASS
OOC synth PASS
IP package PASS
BD integration PASS
full bitstream PASS
Bootgen PASS
SD payload hash PASS
```

Integration rule:

```text
Do not connect V10S4 to AD9361 sample/valid/clock/reset nets. Keep it as an
isolated AXI-Lite self-test page until V8D0/V10S0 hardware evidence says layout
perturbation is safe enough to continue.
```

## Combined FFT-Family Plus Non-FFT Candidate

### V10S5 Combined Self-Test Page

Meaning:

```text
A planned isolated AXI-Lite self-test page at 0x43C30000 combining the
FFT-family lane and the non-FFT helper lane into one future SDR-testable image.
```

Current status:

```text
source and scripts prepared
sidecar module checks reported by subagents
combined AXI wrapper XSIM PASS
combined AXI wrapper OOC synth PASS
OOC WNS +4.021 ns
OOC WHS +0.129 ns
no IP package
no BD integration
no bitstream
no Bootgen
no SD payload
not staged
not hardware validated
```

Important implementation note:

```text
The combined AXI wrapper currently defaults to deterministic internal mirrors.
The external V10S5 FFT-family and non-FFT sidecar core interface needs review
before the wrapper can be called a true combined-module hardware test.
```

Source:

```text
E:\vivado\fpga_p201pro_accel\experiments\v10s5_combined_selftest
```

Plan:

```text
E:\vivado\fpga_p201pro_accel\docs\P201PRO_V10S5_COMBINED_SELFTEST_PLAN.md
```

## Hardware Validation Rule

No module or version is hardware-validated until all of these pass after user
physical SDR power-cycle:

```text
/sd hash check
AD9361/IIO health check
expected base registers
candidate self-test registers
candidate validation script
```
