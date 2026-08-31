# P201Pro V10S4 Non-FFT Self-Test Hardware Failure

Date: 2026-06-09 10:43 Asia/Shanghai

## Result

V10S4 booted and its isolated AXI-Lite deterministic self-test page responded
correctly, but the candidate failed hardware validation because AD9361/IIO
health failed after the user physically power-cycled the SDR.

V10S4 is not hardware-validated.

## Evidence

Validation JSON:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_v10s4_nonfft_selftest_after_powercycle_20260609.json
```

Staging report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_v10s4_nonfft_selftest_sd_staging_20260609.md
```

Artifact:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s4_nonfft_selftest
```

## Passes

The safe checks that passed:

```text
/sd hashes: PASS
V8D0 base registers: PASS
V10S4 identity registers: PASS
V10S4 run_id increment: PASS
V10S4 done bit: PASS
V10S4 fail bit clear: PASS
V10S4 done_mask: 0x00000007 PASS
V10S4 error_mask: 0x00000000 PASS
V10S4 quality result registers: PASS
V10S4 frame/window result registers: PASS
V10S4 energy/peak result registers: PASS
```

The `/sd/BOOT.bin` hash matched the V10S4 payload:

```text
df773e5b8b01f301634ff838f462464289213cfb4bba6c11855d022e08a377ce
```

The V10S4 identity registers matched:

```text
devmem 0x43C20000 32 -> 0x53345430
devmem 0x43C20018 32 -> 0x00000007
devmem 0x43C2001C 32 -> 0x56313034
devmem 0x43C20020 32 -> 0x000A4000
```

## Failure

AD9361/IIO health failed:

```text
ad9361-phy present: true
cf-ad9361-lpc present: false
no Tuning TX FAILED: false
no cf_axi_adc probe error -5: false
```

IIO devices found:

```text
iio:device0=ad9361-phy
iio:device1=xadc
iio:device2=cf-ad9361-dds-core-lpc
```

`cf-ad9361-lpc` was missing.

dmesg tail included:

```text
ad9361 spi1.0: ad9361_dig_tune_delay: Tuning TX FAILED!
cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
```

## Analysis

V8D0 passed immediately before this test, so a V8L1-like fresh implementation
alone did not reproduce the AD9361/IIO failure. V10S4 adds an isolated
non-FFT AXI-Lite self-test page at `0x43C20000` and does not connect AD9361
sample, valid, clock, or reset nets to the self-test IP.

Because V10S4 self-test registers passed while AD9361/IIO failed, the failure
is most likely caused by implementation/layout/resource/routing perturbation
from adding the isolated self-test IP and AXI decode, not by the deterministic
self-test logic producing wrong register values.

This resembles the V8L2, V9A, and V9B0 failure pattern:

```text
Tuning TX FAILED
cf_axi_adc probe error -5
cf-ad9361-lpc missing
```

## Status

```text
NOT HARDWARE VALIDATED
DO NOT PROMOTE
DO NOT USE AS BASELINE
DO NOT CALL LIVE AD9361 INTEGRATION
DO NOT CALL FFT OR PSD RUNTIME
```

Rollback recommendation:

```text
Stage V8L1 first, then physically power-cycle and validate V8L1 if continuing
hardware tests.
```
