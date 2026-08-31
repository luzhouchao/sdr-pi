# P201Pro V10S0 Submodule Self-Test Hardware Validation

Date: 2026-06-09 10:52 Asia/Shanghai

## Result

V10S0 passed post-power-cycle hardware validation after the user physically
power-cycled the SDR.

This validates V10S0 as an isolated deterministic reusable submodule self-test
only. It is not live AD9361 FFT/PSD integration, not SDR streaming runtime,
not ROS integration, and not active `robot_control` integration.

V8L1 remains the current forward hardware-validated bypass baseline.

## Evidence

Validation JSON:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_v10s0_submodule_selftest_after_powercycle_20260609.json
```

Staging report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_v10s0_submodule_selftest_sd_staging_20260609.md
```

Artifact:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s0_submodule_selftest
```

## Checks

Pass summary:

```text
overall passed: true
SDR uptime after physical power-cycle: 32.75 sec
/sd hashes: PASS
AD9361/IIO health: PASS
V8D0 base registers: PASS
V10S0 identity registers: PASS
V10S0 done bit set: PASS
V10S0 fail bit clear: PASS
V10S0 deterministic result registers: PASS
```

The `/sd/BOOT.bin` hash matched the V10S0 payload:

```text
83ff655ff8cba879b2c37568cc99399ad3c3deecadaf56f5961c664aed61be1b
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

V10S0 identity registers matched:

```text
devmem 0x43C10000 32 -> 0x53305430
devmem 0x43C10018 32 -> 0x0000000F
devmem 0x43C1001C 32 -> 0x56313053
devmem 0x43C10020 32 -> 0x000A2000
```

V10S0 run result checks matched:

```text
done_mask -> 0x0000000F
error_mask -> 0x00000000
run_id -> 0x00000001
packer accepted/observed -> 256 / 256
packer dropped -> 0
FFT-family summary nfft -> 256
FFT-family peak bin/power -> 5 / 4096
bandpower total -> 56622
multi-lag correlation samples -> 0x003D0040
```

V8D0 base registers also matched, including the base build IDs:

```text
devmem 0x43C000FC 32 -> 0x56384430
devmem 0x43C0013C 32 -> 0x51384430
devmem 0x43C001F8 32 -> 0x41384430
```

## Three-Test Interpretation

Recent hardware results now form a useful three-point comparison:

```text
V8D0  PASS: V8L1-like fresh implementation/layout did not break AD9361/IIO.
V10S4 FAIL: isolated non-FFT AXI self-test page passed registers but broke AD9361/IIO.
V10S0 PASS: isolated mixed/FFT-adjacent AXI self-test page passed registers and kept AD9361/IIO healthy.
```

The V10S0 pass means the V10S4 failure is not explained by "any extra isolated
AXI-Lite self-test page always breaks AD9361." It is more likely tied to the
specific V10S4 implementation/layout/routing/resource interaction.

The V10S4 failure also remains real: it passed its own registers but reproduced
the `Tuning TX FAILED` / `cf_axi_adc` error `-5` pattern. So the next safe
engineering step is to compare V10S0 and V10S4 implementation deltas, placement
effects, and reset/AXI decode fanout before merging any reusable self-test work
into a live AD9361 path.

## Status

```text
HARDWARE VALIDATED AS ISOLATED SELF-TEST ONLY
NOT LIVE AD9361 FFT
NOT PSD
NOT SDR STREAMING RUNTIME
NOT ACTIVE NX robot_control INTEGRATION
```

Rollback remains:

```text
V8L1 first, then V8
```
