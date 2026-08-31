# P201Pro Summary V9B0 Minimal Isolation Hardware Failure

Date: 2026-06-08 Asia/Shanghai

Status: hardware validation FAIL. V9B0 is not hardware validated.

## Result

After user-confirmed physical SDR power-cycle, V9B0 booted and all expected
identity registers matched, but AD9361/IIO health failed.

Evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9b0_minimal_isolation_after_powercycle_20260608.json
```

Passing checks:

```text
/sd BOOT hash matched V9B0:
0051864c24513248e78fde9bb6ced7d465b4a0c5df6cee804bbafb50d55d35e2

SDR uptime after power-cycle: 133.16 seconds
SUMMARY_VERSION  -> 0x53394230
ABI_VERSION      -> 0x00010002
CAPABILITY       -> 0x000003FF
BUILD_ID         -> 0x56394230
QUALITY_VERSION  -> 0x51394230
QUALITY_CAP      -> 0x0000000F
QUALITY_BUILD_ID -> 0x51394230
AGG_VERSION      -> 0x41394230
AGG_CAP          -> 0x0000001F
AGG_BUILD_ID     -> 0x41394230
SPEC_VERSION/CAP/BUILD/ABI/BIN_COUNT -> 0
```

Failing checks:

```text
cf-ad9361-lpc missing
dmesg: ad9361_dig_tune_delay: Tuning TX FAILED!
dmesg: cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
```

IIO devices observed:

```text
ad9361-phy
xadc
cf-ad9361-dds-core-lpc
```

`cf-ad9361-lpc` was absent.

## Interpretation

V9B0 disabled SPEC readback/identity behavior and removed active SPEC accumulation
from the hot path, but the AD9361 TX tuning failure still reproduced. Therefore,
the failure is not explained by SPEC9 output registers alone.

The next hardware-changing work should treat V8 as the validated footprint
baseline and avoid rebuilding from the V9A/V9B0 source line unless the exact V8
source/placement relationship is preserved or intentionally isolated.

## Rollback Staging

After the V9B0 failure, V8 rollback payload was staged back to SDR `/sd` and
synced:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8\stage_v8_rollback_after_v9b0_to_sdr_sd_20260608.json
```

Result:

```text
remote_before_hashes: V9B0 BOOT 0051864c24513248e78fde9bb6ced7d465b4a0c5df6cee804bbafb50d55d35e2
remote_after_hashes:  V8 BOOT   6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
sync was run on SDR
```

The user later clarified that the forward direction remains reducing NX load
from the V8 baseline, not repeatedly writing V8. Do not keep re-staging V8 unless
rollback safety or a new hardware test explicitly requires it.
