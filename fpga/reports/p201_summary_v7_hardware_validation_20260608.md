# P201 Summary V7 Hardware Validation

Date: 2026-06-08 Asia/Shanghai

## Result

V7 / SUM7A hardware validation passed after physical SDR power-cycle.

V7 is now the highest hardware-validated FPGA SDR offload candidate. V6 remains the validated fallback.

## Safe Test Scope

- Ran only through `/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test`.
- Did not start ROS, SDR streaming runtime, mapping, RTAB-Map, `robot_controller`, `/cmd_vel`, or robot motion code.
- Wrote only the staged V7 five-file SD payload to SDR `/sd`.

## SD Payload Hashes After SDR Physical Power-Cycle

```text
ca7af9cfa33ddb26a5817b9a0117e550e295f3b1a992cf5236d040dabfe405d1  /sd/BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  /sd/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  /sd/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  /sd/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  /sd/uramdisk.image.gz
```

## Summary Register Evidence

Across all 15 captures:

```text
SUMMARY_VERSION = 0x53554D37
ABI_VERSION     = 0x00010001
CAPABILITY      = 0x000001FF
MAX_CORR_FRAME  = 0x0000FFFF
BUILD_ID        = 0x56370001
SNAPSHOT_COUNT  = 0
```

## Quality Page Evidence

Across all 15 captures:

```text
QUALITY_VERSION  = 0x51554137
QUALITY_CAP      = 0x0000000F
QUALITY_BUILD_ID = 0x51370001
```

Quality capability bits validated:

```text
clip_counts = true
zero_cross_counts = true
sign_same_counts = true
reserved_abs_sum_regs_read_zero = true
```

All reserved abs-sum registers read zero in every capture:

```text
0x43C00128 RX0_I_ABS_SUM_RESERVED = 0
0x43C0012C RX0_Q_ABS_SUM_RESERVED = 0
0x43C00130 RX1_I_ABS_SUM_RESERVED = 0
0x43C00134 RX1_Q_ABS_SUM_RESERVED = 0
```

## Quality Sweep

NX command:

```bash
python3 scripts/capture_summary_v7_quality_page.py --frame-lens 64,128,256 --repeat 5 --out-json logs/summary_v7_quality_page_sweep.json
```

Summary:

```text
capture_count: 15
pass_count: 15
overall_passed: true
```

Per frame length:

```text
64 samples:  5 / 5 passed
128 samples: 5 / 5 passed
256 samples: 5 / 5 passed
```

All captures passed:

```text
version_is_sum7
snapshot_disabled
sample_count_matches_frame_len
dual_samples_match
abi_version_ok
capability_ok
max_corr_frame_ok
build_id_ok
quality_version_ok
quality_capability_ok
quality_build_id_ok
quality_frame_matches_summary
quality_samples_match_summary
reserved_abs_regs_read_zero
```

## Evidence Files

```text
E:\vivado\fpga_p201pro_accel\reports\summary_v7_quality_page_sweep_20260608.json
```

NX original:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/logs/summary_v7_quality_page_sweep.json
```

## Decision

V7 / SUM7A passes hardware bypass validation for the quality page candidate.

Keep V6 as the validated fallback because V7 has a thin PC timing hold margin (`WHS +0.003 ns`) even though hardware validation passed in this test.
