# P201Pro Summary V2 Hardware Validation

Generated: 2026-06-07 22:00 Asia/Shanghai

## Scope

Summary V2 was validated as a bypass/offload experiment only. Existing NX SDR
runtime code and the existing `robot_control` launch/runtime chain were not
modified. No ROS, SDR streaming runtime, mapping, RTAB-Map, `robot_controller`,
`cmd_vel`, or robot motion path was started.

## Boot Verification After Physical Power-Cycle

The user physically power-cycled the SDR after V2 was staged on `/sd/BOOT.bin`.

SDR `/sd` hashes after boot:

```text
0abd8a02e8798fb56c3ac6d38aa9b1e261e71e9e444a82ccd8d9b37615393a43  /sd/BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  /sd/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  /sd/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  /sd/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  /sd/uramdisk.image.gz
```

Summary version:

```text
devmem 0x43C00040 32 -> 0x53554D32
```

IIO devices:

```text
ad9361-phy
xadc
cf-ad9361-dds-core-lpc
cf-ad9361-lpc
```

## Same-Frame Snapshot Equivalence

NX independent script:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/scripts/capture_summary_v2_snapshot.py
```

The script reads the FPGA summary registers and the 64-sample raw IQ snapshot
latched from the same frame, recomputes the reference math on NX, and compares
integer fields exactly.

First run:

```text
SUMMARY_VERSION     0x53554D32
FRAME_COUNTER       1
SAMPLE_COUNT        64
SUM_POWER_RAW       186737892
PEAK_POWER_RAW      6769445
PEAK_INDEX          58
RSSI_DBFS           -25.658474
passed              true
```

Checks:

```text
version_is_sum2      true
sample_count_match   true
sum_power_match      true
peak_power_match     true
peak_index_match     true
```

## Repeated Snapshot Equivalence

Five repeat captures were saved under:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/logs/summary_v2_snapshot_compare_repeat_*.json
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/samples/summary_v2_snapshot_raw_i16_repeat_*.npz
```

Summary:

```text
all_passed: true
```

Rows:

```text
run  frame  samples  sum_power_raw  peak_power_raw  peak_index  rssi_dbfs
1    7      64       315609         20609           9           -53.379304
2    8      64       1006029        52577           54          -48.344693
3    9      64       1101108        88180           61          -47.952499
4    10     64       423343         31329           50          -52.103874
5    11     64       392843268      8384513         25          -22.428605
```

All repeat checks were true:

```text
version_is_sum2
sample_count_match
sum_power_match
peak_power_match
peak_index_match
```

## Conclusion

Summary V2 proves exact same-frame equivalence for the current single-RX FPGA
power-summary offload primitive:

```text
sample_count
sum_power_raw
peak_power_raw
peak_index
```

This is the first real bypass validation milestone toward reducing NX SDR
compute load. It is still not a replacement for the existing NX calculation
chain. The next appropriate offload extension is dual-RX power and cross
real/imag accumulation for AoA phase/coherence support.
