# P201Pro Summary V9A SPEC9 Performance Review

Date: 2026-06-08

## Decision

```text
V9A SPEC9 summary-only coarse spectral proxy: GO for PC build.
V9A FFT/window/PSD/DMA/BRAM vector transport: NO-GO.
V10/V11/V12 work: defer until V9A build and hardware validation gates pass.
```

## FPGA/NX Split

FPGA remains limited to fixed-shape, reusable primitives:

```text
SUM9/QUA9/AGG9 compatibility
4-bin SPEC9 coarse spectral proxy
dominant coarse bin
total coarse spectral power
noise floor proxy
prominence proxy
limit flags
summary registers only
```

NX remains responsible for:

```text
register reads
division/sqrt/atan2
calibration
algorithm composition
fallback
logging
publication
active robot_control decisions
```

## Constraints

- Do not implement FFT IP, full PSD, DMA, BRAM spectrum vectors, or wide spectrum readback in V9A.
- Do not modify active NX `robot_control`.
- Do not start ROS, SDR streaming runtime, mapping, RTAB-Map, robot_controller, cmd_vel, or motion paths.
- Do not overwrite original `BOOT.bin`, original SD backup, or vendor package files.
- Preserve V8 as rollback.

## Performance Rationale

V8 is hardware-validated but has thin timing margin (`WNS +0.011 ns`). V9A can still be justified because the new spectral path is add/sub/sign-rotation only and exposes a small summary page. The design must keep work out of the ADC sample-accept hot path where possible and use post-frame handling for absolute value, peak, noise, prominence, and saturation decisions.

If Vivado reports negative WNS/WHS, route errors, SUM/QUA/AGG regression, or unexplained SPEC9 mismatch, stop V9A and recommend rollback to V8.
