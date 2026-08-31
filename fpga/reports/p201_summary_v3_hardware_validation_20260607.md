# P201Pro Summary V3 Hardware Validation

Generated: 2026-06-07 22:40 Asia/Shanghai

## Scope

Summary V3 was validated as a bypass/offload experiment only. Existing NX SDR
runtime code and the existing `robot_control` launch/runtime chain were not
modified. No ROS, SDR streaming runtime, mapping, RTAB-Map, `robot_controller`,
`cmd_vel`, or robot motion path was started.

## Boot Verification After Physical Power-Cycle

The user physically power-cycled the SDR after V3 was staged on `/sd/BOOT.bin`.

SDR `/sd` hashes after boot:

```text
c6c727bc4ac16a6e21565d5074a18404b01a6c43a160809ab1178224d3bce7f1  /sd/BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  /sd/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  /sd/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  /sd/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  /sd/uramdisk.image.gz
```

Summary version:

```text
devmem 0x43C00040 32 -> 0x53554D33
```

IIO devices:

```text
ad9361-phy
xadc
cf-ad9361-dds-core-lpc
cf-ad9361-lpc
```

## Same-Frame Dual-RX Snapshot Equivalence

NX independent script:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/scripts/capture_summary_v3_dual_snapshot.py
```

The script reads the FPGA dual-RX summary registers and the 64-sample RX0/RX1 raw
IQ snapshots latched from the same frame, recomputes the reference math on NX,
and compares integer fields exactly.

First run:

```text
SUMMARY_VERSION     0x53554D33
FRAME_COUNTER       1
SAMPLE_COUNT        64
RX0_POWER_RAW       518456
RX1_POWER_RAW       231110
CROSS_RE_RAW        -162588
CROSS_IM_RAW        -124303
RX0_PEAK_POWER_RAW  45810
RX0_PEAK_INDEX      62
RX1_PEAK_POWER_RAW  15161
RX1_PEAK_INDEX      12
COHERENCE           0.591248
PHASE_DEG           -142.601093
passed              true
```

Checks:

```text
version_is_sum3          true
sample_count_match       true
dual_samples_match       true
rx0_power_match          true
rx0_v2_sum_match         true
rx1_power_match          true
cross_re_match           true
cross_im_match           true
rx0_peak_power_match     true
rx0_peak_index_match     true
rx1_peak_power_match     true
rx1_peak_index_match     true
```

## Repeated Dual-RX Snapshot Equivalence

Five repeat captures were saved under:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/logs/summary_v3_dual_snapshot_compare_repeat_*.json
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/samples/summary_v3_dual_snapshot_iq_repeat_*.npz
```

Summary:

```text
all_passed: true
```

Rows:

```text
run  frame  samples  rx0_power   rx1_power   cross_re    cross_im    coherence  phase_deg
1    2      64       235209      48253696    1524668     1957345     0.736462   52.083299
2    3      64       748351      474372      -249992     -154059     0.492853   -148.356311
3    4      64       2725274     1659610     -151844     -1168817    0.554208   -97.401985
4    5      64       550180      153426      -151979     -61219      0.563940   -158.059821
5    6      64       24823797    25409785    -1453089    24851364    0.991190   93.346343
```

Every repeat check was true:

```text
version_is_sum3
sample_count_match
dual_samples_match
rx0_power_match
rx0_v2_sum_match
rx1_power_match
cross_re_match
cross_im_match
rx0_peak_power_match
rx0_peak_index_match
rx1_peak_power_match
rx1_peak_index_match
```

## Conclusion

Summary V3 proves exact same-frame equivalence for the current dual-RX FPGA
offload primitive:

```text
RX0 power
RX1 power
cross real = sum(I0*I1 + Q0*Q1)
cross imag = sum(Q0*I1 - I0*Q1)
RX0/RX1 peak power and index
```

This is a hardware-validated basis for AoA phase/coherence bypass validation on
NX. It is still not a replacement for the existing NX calculation chain.
