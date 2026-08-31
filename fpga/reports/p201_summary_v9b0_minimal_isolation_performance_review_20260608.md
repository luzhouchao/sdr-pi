# P201Pro V9B0 Minimal Isolation Performance Review

Date: 2026-06-08

Status: PC-side candidate preparation. Not built, not staged, not hardware validated yet.

## Baseline

V8 / SUM8 + QUA8 + AGG8 remains the highest hardware-validated candidate.
V9A / SUM9 + QUA9 + AGG9 + SPEC9 passed register/SPEC capture checks but failed
AD9361/IIO health after power-cycle: `cf-ad9361-lpc` did not register and dmesg
reported TX digital tune failure plus `cf_axi_adc probe error -5`.

## V9B0 Goal

V9B0 is an isolation build, not a feature expansion. It keeps the same AD9361 RX
monitoring boundary and SUM/QUA/AGG-style register workflow, but disables the
V9A SPEC page and its per-sample bin accumulation.

Expected identity registers:

```text
0x040 SUMMARY_VERSION  0x53394230 ("S9B0")
0x0ec ABI_VERSION      0x00010002
0x0f0 CAPABILITY       0x000003ff
0x100 QUALITY_VERSION  0x51394230 ("Q9B0")
0x180 AGG_VERSION      0x41394230 ("A9B0")
0x200 SPEC_VERSION     0x00000000
```

## FPGA/NX Split

FPGA keeps fixed-shape summary primitives: per-frame power/cross/quality and
multi-frame AGG accumulation. NX remains responsible for policy, calibration,
division/sqrt/atan2, fallback, logging, and validation.

No ROS, streaming runtime, mapping, RTAB-Map, `robot_controller`, `/cmd_vel`, or
robot motion is involved.

## Arithmetic And Timing Decisions

- Disable SPEC9 readback advertisement by returning zero for `0x200..0x2fc`.
- Disconnect SPEC bin accumulation from the ADC sample-accept path.
- Skip SPEC post-processing by jumping from corrected-numerator stage 3 to the
  existing final AGG/pending stage.
- Preserve SUM/QUA/AGG arithmetic and register offsets for diagnostic continuity.
- Use separate V9B0 Vivado reports so V9A evidence remains intact.

## Gate Before Hardware

Do not stage V9B0 to SDR unless PC artifact gate passes:

```text
OOC/IP synth complete
integrated synth complete
implementation complete
post-route physopt bitstream write complete
WNS >= 0
WHS >= 0
route fully routed
routing errors 0
no critical DRC/CDC blocker
```

If V9B0 still fails AD9361 TX tuning after a clean PC gate and physical
power-cycle, the root cause is more likely tied to generic tap integration,
placement/routing disturbance, or BD/IP integration side effects rather than the
SPEC9 datapath specifically.
