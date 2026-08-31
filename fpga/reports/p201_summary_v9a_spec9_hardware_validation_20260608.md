# P201Pro Summary V9A SPEC9 Hardware Validation Attempt

Date: 2026-06-08

Status: PARTIAL PASS / IIO HEALTH FAIL. NOT HARDWARE VALIDATED.

## Scope

V9A was staged to SDR `/sd`, the user physically power-cycled the SDR, and the validation script ran through the NX jump host.

Evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9a_spec9_hardware_validation_20260608.json
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9a_spec9_iio_failure_diagnostics_20260608.json
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9\stage_v9a_to_sdr_sd_20260608.json
```

## Passed

SDR `/sd` hashes matched the V9A payload:

```text
BOOT.bin          58de598eea686e857a5cbb82135fea6fca2c0c79904b65af5f1b4b5f5f259447
devicetree.dtb    960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a
uEnv.txt          2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f
uImage            e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5
uramdisk.image.gz 0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55
```

Physical power-cycle was plausible from SDR uptime:

```text
SDR uptime at validation: 464.15 seconds
```

All V9A identity registers matched:

```text
SUMMARY_VERSION  0x53554D39 ("SUM9")
ABI_VERSION      0x00010003
CAPABILITY       0x000007FF
BUILD_ID         0x56390001
QUALITY_VERSION  0x51554139 ("QUA9")
QUALITY_CAP      0x0000000F
QUALITY_BUILD_ID 0x51390001
AGG_VERSION      0x41474739 ("AGG9")
AGG_CAP          0x0000001F
AGG_BUILD_ID     0x41390001
SPEC_VERSION     0x53504339 ("SPC9")
SPEC_BIN_COUNT   0x00000004
SPEC_CAP         0x0000000F
SPEC_BUILD_ID    0x53390001
SPEC_ABI_VERSION 0x00010003
```

SPEC9 register validation passed:

```text
SPEC9 captures: 6 / 6 PASS
frame IDs: monotonic 1..6
frame length: 64 samples
SPEC9 valid flag set and busy flag clear in every capture
peak/bin/total internal consistency checks passed
```

Tap debug evidence showed the tap was alive:

```text
SUMMARY_VERSION 0x53554D39
SPEC_VERSION    0x53504339
DEBUG_VALID     increasing
DEBUG_ACCEPT    0x00000042
SPEC_SAMPLES    0x00000040
```

## Failed

AD9361/IIO health did not pass. `cf-ad9361-lpc` was missing from IIO devices:

```text
iio:device0=ad9361-phy
iio:device1=xadc
iio:device2=cf-ad9361-dds-core-lpc
```

`iio_info -s` also did not show `cf-ad9361-lpc` in the local context.

dmesg showed:

```text
SAMPL CLK: 61440000 tuning: TX
ad9361 spi1.0: ad9361_dig_tune_delay: Tuning TX FAILED!
cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
```

## Decision

Do not promote V9A to highest hardware-validated candidate.

Treat this as:

```text
V9A BOOT/hash: PASS
V9A SUM9/QUA9/AGG9/SPEC9 registers: PASS
V9A SPEC9 capture consistency: PASS
AD9361/IIO health: FAIL
Overall hardware validation: FAIL / incomplete
```

V8 remains the current highest hardware-validated bypass candidate.

## Next Safe Step

Keep V9A staged only if continuing IIO/tuning diagnosis. If a known-good operational state is needed, restore V8 and physically power-cycle the SDR.

Do not start ROS, SDR streaming runtime, mapping, RTAB-Map, robot_controller, cmd_vel, or robot motion paths.
