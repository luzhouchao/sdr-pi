# P201Pro V8L1 Auto Aggregate Hardware Validation

Date: 2026-06-08

Status: PASS. V8L1 is hardware-validated after SDR `/sd` staging and physical
SDR power-cycle.

## Gates

- SDR power-cycle evidence: PASS, uptime 93.57 seconds at validation.
- `/sd` hashes: PASS.
- AD9361/IIO health: PASS.
- `cf-ad9361-lpc`: registered.
- Known V9A/V9B0 failure strings: absent.
- SUM8/QUA8/AGG8/V8L1 identity registers: PASS.
- SPEC page remains disabled/read-zero: PASS.
- Minimal no-motion AGG auto-roll capture: 3 / 3 PASS.

## Key Evidence

```text
/sd/BOOT.bin bdd7e27c4cd02259cb891e06bc25cdf70f0763de55dda77d2853da660a8f24aa
iio:device0=ad9361-phy
iio:device2=cf-ad9361-dds-core-lpc
iio:device3=cf-ad9361-lpc
dmesg: cf_axi_adc 79020000.cf-ad9361-lpc ... probed ADC AD9361 as MASTER
```

Expected V8L1 identity registers matched:

```text
0x43C00040 SUMMARY_VERSION  0x53554D38
0x43C000EC ABI_VERSION      0x00010002
0x43C000F0 CAPABILITY       0x000003FF
0x43C000FC BUILD_ID         0x56384C31
0x43C00100 QUALITY_VERSION  0x51554138
0x43C00138 QUALITY_CAP      0x0000000F
0x43C0013C QUALITY_BUILD_ID 0x51384C31
0x43C00180 AGG_VERSION      0x41474738
0x43C001F4 AGG_CAP          0x0000003F
0x43C001F8 AGG_BUILD_ID     0x41384C31
0x43C00200 SPEC_VERSION     0x00000000
0x43C002F0 SPEC_BIN_COUNT   0x00000000
0x43C002F4 SPEC_CAP         0x00000000
0x43C002F8 SPEC_BUILD_ID    0x00000000
0x43C002FC SPEC_ABI_VERSION 0x00000000
```

Capture settings:

```text
frame_len = 64
agg_frames = 16
sample_count = 1024 per capture
captures = 3
```

All captures reported:

```text
AGG done = true
overflow = false
frame_count = 16
sample_count = 1024
AGG capability = 0x0000003F
AGG build ID = 0x41384C31
```

Machine-readable validation result:

```text
reports/p201_summary_v8l1_auto_agg_after_powercycle_20260608.json
```

## Version Route Decision

V8L1 replaces V8 as the current highest hardware-validated bypass offload
candidate. V8 remains the first rollback target.

V8L1 is not FFT/PSD/DMA and does not integrate with active NX robot_control. It
is the new validated baseline for lowering NX register polling and CPU load
before adding heavier kernels.
