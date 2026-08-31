# P201Pro V8L2 Auto-Roll Fix Hardware Failure

Date: 2026-06-08

Status: hardware validation FAIL. V8L2 is NOT hardware-validated.

## Summary

After SDR `/sd` staging, sync, and physical SDR power-cycle, V8L2 loaded and its
SUM8/QUA8/AGG8 identity registers matched the expected V8L2 build IDs. However,
AD9361/IIO health failed: `cf-ad9361-lpc` did not register and dmesg showed the
same TX tuning failure pattern previously seen on V9A/V9B0.

Because AD9361/IIO health failed, validation stopped before running the V8L2
continuous auto-roll benchmark.

## Evidence

JSON:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8l2_auto_roll_fix_after_powercycle_20260608.json
```

SD `/sd` hash:

```text
BOOT.bin 1f7935fb9153966eb9eb9cec9f4f1fa2364ac54e45badced0848fac4b43e5248 PASS
```

V8L2 identity registers:

```text
SUMMARY_VERSION  0x53554D38 PASS
BUILD_ID         0x56384C32 PASS
QUALITY_VERSION  0x51554138 PASS
QUALITY_BUILD_ID 0x51384C32 PASS
AGG_VERSION      0x41474738 PASS
AGG_CAP          0x0000003F PASS
AGG_BUILD_ID     0x41384C32 PASS
SPEC page        read-zero PASS
```

AD9361/IIO:

```text
cf-ad9361-lpc registered: false
AD9361/IIO health: FAIL
dmesg: ad9361_dig_tune_delay: Tuning TX FAILED!
dmesg: cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
```

## Safety

No ROS, SDR streaming runtime, robot_control, cmd_vel, mapping, RTAB-Map, or
robot motion path was started. Validation used NX-to-SDR SSH and read-only
checks except `devmem` register reads.

## Decision

Stop V8L2 as a hardware candidate. Do not promote V8L2 above V8L1. The current
highest hardware-validated version remains V8L1.

Recommended next safe step:

```text
stage V8L1 rollback payload to SDR /sd
sync
ask user for physical SDR power-cycle
validate V8L1 AD9361/IIO health and identity registers after power-cycle
```
