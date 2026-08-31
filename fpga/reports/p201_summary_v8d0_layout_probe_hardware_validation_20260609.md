# P201Pro V8D0 Layout Probe Hardware Validation

Date: 2026-06-09 10:32 Asia/Shanghai

## Result

V8D0 layout probe passed post-power-cycle hardware validation after the user
physically power-cycled the SDR.

This validates V8D0 as a diagnostic layout probe only. It does not replace
V8L1 as the current forward baseline, and it is not FFT, PSD, live AD9361
integration beyond the existing tap path, ROS integration, or active
`robot_control` integration.

## Evidence

Validation JSON:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8d0_layout_probe_after_powercycle_20260609.json
```

Staging report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8d0_layout_probe_sd_staging_20260609.md
```

Artifact:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8d0_layout_probe
```

## Checks

Pass summary:

```text
overall passed: true
SDR uptime after physical power-cycle: 133.61 sec
/sd hashes: PASS
AD9361/IIO health: PASS
known V9A-style IIO failure absent: PASS
V8D0 identity registers: PASS
SPEC page read-zero: PASS
AGG8 no-motion captures: 3 / 3 PASS
```

The `/sd/BOOT.bin` hash matched the V8D0 payload:

```text
3e2c59a32a6ba8b6a80fc9cfe4c4a0ec94a43051cbb1d383f99cbd596417f883
```

IIO devices included:

```text
iio:device0=ad9361-phy
iio:device1=xadc
iio:device2=cf-ad9361-dds-core-lpc
iio:device3=cf-ad9361-lpc
```

dmesg showed AD9361 and `cf-ad9361-lpc` initialized successfully, with no
`Tuning TX FAILED` and no `cf_axi_adc` probe error `-5`.

## Register Evidence

V8D0 identity and AGG registers matched:

```text
devmem 0x43C00040 32 -> 0x53554D38
devmem 0x43C000EC 32 -> 0x00010002
devmem 0x43C000F0 32 -> 0x000003FF
devmem 0x43C000FC 32 -> 0x56384430
devmem 0x43C00100 32 -> 0x51554138
devmem 0x43C00138 32 -> 0x0000000F
devmem 0x43C0013C 32 -> 0x51384430
devmem 0x43C00180 32 -> 0x41474738
devmem 0x43C001F4 32 -> 0x0000003F
devmem 0x43C001F8 32 -> 0x41384430
```

SPEC page remained disabled/read-zero:

```text
devmem 0x43C00200 32 -> 0x00000000
devmem 0x43C002F0 32 -> 0x00000000
devmem 0x43C002F4 32 -> 0x00000000
devmem 0x43C002F8 32 -> 0x00000000
devmem 0x43C002FC 32 -> 0x00000000
```

## AGG8 Captures

Three AGG8 no-motion captures passed at:

```text
frame_len=64
agg_frames=16
sample_count=1024
```

Each capture reported:

```text
agg_done: true
agg_no_overflow: true
agg_frames_ok: true
agg_samples_ok: true
agg_capability_ok: true
agg_build_id_ok: true
agg_limit_ok: true
```

## Analysis

The V8D0 result is useful root-cause evidence. A fresh Vivado implementation of
V8L1-like logic with build-ID-only HDL changes did not reproduce the AD9361/IIO
failure seen on V8L2, V9A, and V9B0.

This suggests the previous AD9361/IIO failures are less likely to be caused by
implementation/layout churn alone. The remaining suspects are the specific RTL
changes, routing/fanout effects introduced by those changes, or interactions
from added pages/logic such as V8L2 auto-roll or V9 SPEC-style logic.

Next safe step:

```text
Either test V8D1 incremental auto-roll fix, or test isolated V10S0/V10S4
self-test pages. Do not stage another candidate until this V8D0 result is
committed and the route docs are current.
```

Rollback remains:

```text
V8L1 first, then V8
```
