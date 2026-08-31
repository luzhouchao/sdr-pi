# P201Pro V8 Rollback Validation After V9A IIO Failure

Date: 2026-06-08

Status: PASS. V8 rollback is active after physical SDR power-cycle.

After V9A failed AD9361/IIO health, the V8 payload was staged back to SDR `/sd`.
The user physically power-cycled the SDR, then this validation checked boot
identity, AD9361/IIO health, V8 registers, and the independent AGG8 validation
script.

Evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\summary_v8_after_v9a_rollback_powercycle_20260608.json
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9a_spec9_iio_diagnosis_and_v8_rollback_20260608.md
```

## Boot And IIO Health

SDR uptime after the physical power-cycle was about 105 seconds when checked.

SDR `/sd` hashes matched V8 and known-good companion files:

```text
BOOT.bin          6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
devicetree.dtb    960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a
uEnv.txt          2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f
uImage            e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5
uramdisk.image.gz 0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55
```

IIO devices included the ADC buffer again:

```text
ad9361-phy
xadc
cf-ad9361-dds-core-lpc
cf-ad9361-lpc
```

dmesg showed successful AD9361 and ADC probe:

```text
ad9361 spi1.0: AD936x Rev 0 successfully initialized
cf_axi_dds 79024000.cf-ad9361-dds-core-lpc: probed DDS AD9361
cf_axi_adc 79020000.cf-ad9361-lpc: probed ADC AD9361 as MASTER
```

Runtime DTB properties remained the validated LVDS-bias configuration:

```text
adi,digital-interface-tune-skip-mode = <0>
adi,lvds-mode-enable present
adi,lvds-bias-mV = <150>
adi,lvds-rx-onchip-termination-enable present
adi,rx-data-clock-delay = <4>
adi,rx-data-delay = <4>
adi,tx-fb-clock-delay = <7>
```

## V8 Register Checks

Expected V8 identities matched:

```text
SUMMARY_VERSION  0x53554D38
ABI_VERSION      0x00010002
CAPABILITY       0x000003FF
BUILD_ID         0x56380001
QUALITY_VERSION  0x51554138
AGG_VERSION      0x41474738
AGG_CAP          0x0000001F
AGG_BUILD_ID     0x41380001
```

Tap diagnostics showed RX activity:

```text
DEBUG_FLAGS  0x00000020
DEBUG_CLK    0x00003062
DEBUG_VALID  0xC0D9CF2D
```

## AGG8 Validation

Independent script:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/scripts/capture_summary_v8_aggregate.py
```

Result:

```text
frame_len = 64
agg_frames = 16
captures = 5
pass_count = 5
passed = true
```

Each capture reported:

```text
AGG_VERSION = 0x41474738
AGG_BUILD_ID = 0x41380001
done = true
overflow = false
frame_count = 16
sample_count = 1024
```

Median total capture time was about 1.024 seconds over SSH/devmem.

## Decision

V8 rollback is active and healthy after physical SDR power-cycle.

V8 remains the current highest hardware-validated bypass candidate. V9A remains
NOT HARDWARE VALIDATED and should only be used for isolated AD9361/IIO or
bitstream-layout diagnosis.

Safety boundary observed: no ROS, SDR streaming runtime, mapping, RTAB-Map,
`robot_controller`, `cmd_vel`, robot motion path, active `robot_control`
modification, vendor package modification, or original SD backup modification.
