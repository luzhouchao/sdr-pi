# P201 Summary V6 Hardware Validation

Date: 2026-06-08 Asia/Shanghai

## Result

V6 hardware validation passed after physical SDR power-cycle.

V6 is now the highest hardware-validated production-summary candidate.

## Safe Test Scope

- Ran only through `/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test`.
- Did not start ROS, SDR streaming runtime, mapping, RTAB-Map, `robot_controller`, `/cmd_vel`, or robot motion code.
- Wrote only the staged V6 five-file SD payload to SDR `/sd`.

## SD Payload Hashes After SDR Physical Power-Cycle

```text
e47c012ad5f8f14bc769620f00add18ef75be74bd09dbaaddaa91aaf62ade60b  /sd/BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  /sd/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  /sd/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  /sd/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  /sd/uramdisk.image.gz
```

## Register Evidence

Across all 15 captures:

```text
SUMMARY_VERSION = 0x53554D36
SNAPSHOT_COUNT = 0
ABI_VERSION     = 0x00010000
CAPABILITY      = 0x000000FF
MAX_CORR_FRAME  = 0x0000FFFF
BUILD_ID        = 0x56360001
LIMIT_FLAGS     = 0x0000000C
```

`LIMIT_FLAGS = 0x0000000C` means:

```text
corrected_valid = true
snapshot_disabled = true
arithmetic_overflow = false
frame_len_limited = false
```

## Production Sweep

NX command:

```bash
python3 scripts/capture_summary_v6_block_abi.py --frame-lens 64,128,256 --repeat 5 --out-json logs/summary_v6_block_abi_sweep.json
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
version_is_sum6
snapshot_disabled
sample_count_matches_frame_len
dual_samples_match
summary_sum_matches_rx0_power
rx0_corr_power_num_match
rx1_corr_power_num_match
corr_cross_re_num_match
corr_cross_im_num_match
abi_version_ok
capability_ok
max_corr_frame_ok
build_id_ok
corrected_valid_without_overflow
```

## Evidence Files

```text
E:\vivado\fpga_p201pro_accel\reports\summary_v6_block_abi_sweep_20260608.json
```

NX original:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/logs/summary_v6_block_abi_sweep.json
```

## Decision

V6 passes hardware bypass validation and resolves the V5 production consistency failure pattern in this test set.

Continue active route with V7 if testing the quality page is desired. Keep V6 as the current validated fallback.
