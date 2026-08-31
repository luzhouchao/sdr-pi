# P201 Summary V5 Hardware Validation

Date: 2026-06-08 Asia/Shanghai

## Result

V5 boot/register validation passed, but production consistency validation did not fully pass.

Treat V5 as hardware-booted but not production-validated.

## Safe Test Scope

- Ran only through `/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test`.
- Did not start ROS, SDR streaming runtime, mapping, RTAB-Map, `robot_controller`, `/cmd_vel`, or robot motion code.
- Wrote only the staged V5 five-file SD payload to SDR `/sd`.

## SD Payload Hashes After SDR Physical Power-Cycle

```text
a9849d26185671c9fb276cdab032913864b379b3c8fcca9286d472be964f0544  /sd/BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  /sd/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  /sd/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  /sd/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  /sd/uramdisk.image.gz
```

## Register Evidence

The V5 validation script confirmed every capture reported:

```text
SUMMARY_VERSION = 0x53554D35
SNAPSHOT_COUNT = 0
```

This proves the SDR booted the V5 BOOT payload and the V5 no-snapshot behavior is active.

## Production Sweep

NX command:

```bash
python3 scripts/capture_summary_v5_production.py --frame-lens 64,128,256 --repeat 5 --out-json logs/summary_v5_production_sweep.json
```

Summary:

```text
capture_count: 15
pass_count: 9
overall_passed: false
```

Per frame length:

```text
64 samples:  4 / 5 passed
128 samples: 3 / 5 passed
256 samples: 2 / 5 passed
```

Failed checks:

```text
rx1_corr_power_num_match: 6
corr_cross_re_num_match: 6
corr_cross_im_num_match: 6
```

The failure pattern is tied to RX1/Q1 sum values that sometimes decode near `+/-2^47`, for example:

```text
frame_len 64  iteration 3  q1_sum -70368744177786
frame_len 128 iteration 2  q1_sum  140737488354989
frame_len 256 iteration 4  q1_sum -140737488353031
```

## Narrow Q1 Probe

Additional probe:

```bash
python3 scripts/probe_v5_q1_sum_registers.py --repeat 20 --frame-len 64 --out-json logs/probe_v5_q1_sum_registers.json
```

It repeatedly observed the previous failed frame state:

```text
Q1_SUM_HI raw word: 0xffff8000
Q1_SUM_HI low16:    0x8000
Q1_SUM_LO:          2297
decoded Q1_SUM:     -140737488353031
```

This confirms the anomalous shape of the readback. The probe did not advance to a new frame, so it is supporting evidence, not an independent pass/fail sweep.

## Evidence Files

```text
E:\vivado\fpga_p201pro_accel\reports\summary_v5_production_sweep_20260608.json
E:\vivado\fpga_p201pro_accel\reports\probe_v5_q1_sum_registers_20260608.json
```

NX originals:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/logs/summary_v5_production_sweep.json
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/logs/probe_v5_q1_sum_registers.json
```

## Decision

Do not mark V5 as production-validated.

Continue active hardware validation with V6, because V6 is the block ABI / widened metadata candidate and may clarify whether this is a V5-specific corrected-path issue.
