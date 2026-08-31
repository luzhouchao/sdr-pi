# P201Pro Summary V8 Hardware Validation

Date: 2026-06-08

## Result

PASS. V8 is now the highest hardware-validated SDR FPGA offload candidate.

The SDR was physically power-cycled after staging the V8 SD payload. SUM8, QUA8,
and AGG8 metadata matched the expected register values, and the aggregate page
completed without overflow.

## Evidence

Primary hardware log copied from NX:

```text
E:\vivado\fpga_p201pro_accel\reports\summary_v8_aggregate_after_power_cycle_20260608.json
```

Reusable client validation log:

```text
E:\vivado\fpga_p201pro_accel\reports\sum8_aggregate_client_20260608.json
```

Report file hashes:

```text
ffb06f71639fc01e13cea8f5c09da83ed60534396b85dbec826634f4567542e1  summary_v8_aggregate_after_power_cycle_20260608.json
9d22d506b58582626ad144dcbdb6222e73221054d70556ed9495c342686a3251  sum8_aggregate_client_20260608.json
```

## Boot And Register Checks

The SDR `/sd/BOOT.bin` hash matched V8:

```text
6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb  /sd/BOOT.bin
```

Expected metadata was observed:

```text
SUMMARY_VERSION = 0x53554D38
ABI_VERSION     = 0x00010002
CAPABILITY      = 0x000003FF
BUILD_ID        = 0x56380001
QUALITY_VERSION = 0x51554138
QUALITY_BUILD_ID= 0x51380001
AGG_VERSION     = 0x41474738
AGG_CAP         = 0x0000001F
AGG_BUILD_ID    = 0x41380001
```

IIO devices were present after the physical power-cycle:

```text
ad9361-phy
xadc
cf-ad9361-dds-core-lpc
cf-ad9361-lpc
```

Tap diagnostics before aggregate validation:

```text
DEBUG_FLAGS = 0x00000060
DEBUG_CLK   = 0x00002534
DEBUG_VALID = 0x94296DC2
```

## Aggregate Validation

Primary V8 validation:

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
control = 0x00000011
done = true
overflow = false
frame_count = 16
sample_count = 1024
```

Reusable client validation using the new independent NX API:

```text
frame_len = 64
agg_frames = 4, 16, 64
repeat = 2
captures = 6
pass_count = 6
passed = true
```

Observed sample counts matched `frame_len * agg_frames`:

```text
4 frames  -> 256 samples
16 frames -> 1024 samples
64 frames -> 4096 samples
```

## Performance Interpretation

V8 moves a useful load-reduction step into FPGA without replacing the active NX
SDR chain. The FPGA now aggregates fixed-shape multi-frame primitives:

- corrected RX0/RX1 power numerators
- corrected cross real/imag numerators
- raw RX0/RX1 power
- clip, zero-cross, and same-sign quality counts

NX still owns division, square root, `atan2`, calibration, AoA composition,
CPU/GPU backend choice, and later frontend/ROS publication. This is the desired
bypass split: low-rate primitive pages from FPGA, flexible algorithm composition
on NX.

## Safety Notes

Validation stayed inside:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
```

No ROS launch, SDR streaming runtime, mapping, RTAB-Map, `robot_controller`,
`cmd_vel`, or active robot-control path was started or modified.

## Next Step

Use V8 as the current highest validated bypass candidate. Next FPGA/NX iteration
should perform the authorized performance review first, then decide between:

- improving the AGG8 client path and low-rate CPU/GPU coordination, or
- adding the next fixed-shape FPGA primitive such as rolling aggregate, peak/noise
  summary, or a carefully scoped spectral primitive.
