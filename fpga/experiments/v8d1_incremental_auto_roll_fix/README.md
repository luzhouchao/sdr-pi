# V8D1 Incremental Auto-Roll Fix

Purpose: keep the V8L2 continuous auto-roll fix while trying to preserve V8L1
implementation placement/routing through incremental implementation.

HDL source:

```text
experiments\v8d1_incremental_auto_roll_fix\hdl\p201pro_ad9361_power_tap_axi_regs.v
```

Expected identity registers:

```text
SUMMARY_BUILD_ID = 0x56384431
QUALITY_BUILD_ID = 0x51384431
AGG_BUILD_ID     = 0x41384431
```

Incremental reference:

```text
reports\stage4_ad9361_tap_bitstream_physopt_v8l1_auto_agg\system_top_with_p201_tap_v8l1_auto_agg_physopt_impl.dcp
```

Behavior:

- Uses the V8L2 `pending_adc` auto-mode continuity fix.
- Keeps SUM8/QUA8/AGG8 ABI shape.
- No SPEC, FFT, BRAM, DMA, ROS, streaming runtime, or robot-control integration.

Interpretation after hardware test:

- If V8D1 passes AD9361/IIO while V8L2 failed, implementation churn was likely
  the dominant issue.
- If V8D1 also fails, add physical isolation constraints or a more conservative
  tap partition before moving toward FFT.
