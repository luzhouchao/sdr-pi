# V8D0 Layout Probe

Purpose: isolate whether a V8L1-like fresh implementation can reproduce the
AD9361/IIO TX tuning failure.

HDL source:

```text
experiments\v8d0_layout_probe\hdl\p201pro_ad9361_power_tap_axi_regs.v
```

Expected identity registers:

```text
SUMMARY_BUILD_ID = 0x56384430
QUALITY_BUILD_ID = 0x51384430
AGG_BUILD_ID     = 0x41384430
```

Behavior:

- Same intended SUM8/QUA8/AGG8 behavior as V8L1.
- Build-ID-only diagnostic change.
- No SPEC, FFT, BRAM, DMA, ROS, streaming runtime, or robot-control integration.

Interpretation after hardware test:

- AD9361/IIO fail means fresh implementation/layout churn is likely enough to
  break the AD9361 path.
- AD9361/IIO pass means the V8L2 auto-roll fix or its induced optimization
  remains suspect.
