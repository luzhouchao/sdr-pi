# P201Pro Summary V1 Hardware Validation

Date: 2026-06-07

## Scope

Validated the experiment-only Summary V1 BOOT after the user physically
power-cycled the SDR. No ROS, SDR streaming runtime, mapping, robot controller,
or motion path was started.

## SD Boot Hashes After Power-Cycle

```text
5f550533c3441b309e62488bd5d3ffeaafec222825305a90bb9973fa4e614b6e  /sd/BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  /sd/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  /sd/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  /sd/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  /sd/uramdisk.image.gz
```

## AD9361/IIO Health

IIO devices:

```text
/sys/bus/iio/devices/iio:device0 ad9361-phy
/sys/bus/iio/devices/iio:device1 xadc
/sys/bus/iio/devices/iio:device2 cf-ad9361-dds-core-lpc
/sys/bus/iio/devices/iio:device3 cf-ad9361-lpc
```

Relevant dmesg:

```text
ad9361 spi1.0: ad9361_probe : AD936x Rev 0 successfully initialized
cf_axi_dds 79024000.cf-ad9361-dds-core-lpc: probed DDS AD9361
cf_axi_adc 79020000.cf-ad9361-lpc: probed ADC AD9361 as MASTER
```

## Summary V1 Version Check

```text
devmem 0x43C00040 32 -> 0x53554D31
```

This confirms the Summary V1 bitstream is running on hardware.

## Minimal Register Frame Capture

Commands:

```text
devmem 0x43C00004 32 0x00000040
devmem 0x43C00000 32 0x00000002
devmem 0x43C00000 32 0x00000001
```

Result:

```text
0x43C00008 STATUS              0x00000007
0x43C00030 DEBUG_FLAGS         0x00000037
0x43C00034 DEBUG_CLK           0x00000022
0x43C00038 DEBUG_VALID         0x008F1F6F
0x43C0003c DEBUG_ACCEPT        0x00000040
0x43C00040 SUMMARY_VERSION     0x53554D31
0x43C00044 SUMMARY_FLAGS       0x00000037
0x43C00048 FRAME_COUNTER       0x00000001
0x43C0004c SAMPLE_COUNT        0x00000040
0x43C00050 SUM_POWER_LO        0x00006900
0x43C00054 SUM_POWER_HI        0x00000000
0x43C00058 PEAK_POWER          0x00000B54
0x43C0005c PEAK_INDEX          0x00000035
```

Interpretation:

- The Summary V1 register mirror is reachable.
- The tap accepted exactly 64 samples after clear/enable.
- Frame counter incremented to 1.
- Sum power and peak power are non-zero.
- This proves first-stage FPGA time-domain frame summary is working in hardware.

## Repeated Register-Only Frame Series

Command:

```text
python3 scripts/capture_summary_v1_series.py --frames 20 --frame-len 64 --out logs/summary_v1_register_frame_series.json
```

Result summary:

```text
requested_frames: 20
all_versions_ok: true
all_sample_counts_match: true
frame_counter: 2..21
debug_accept: 64 for every captured frame
rssi_dbfs_min: -53.1308
rssi_dbfs_median: -46.0134
rssi_dbfs_max: -22.8250
sum_power_min: 334197
sum_power_max: 358577684
```

Interpretation:

- The Summary V1 frame engine repeatedly captures frames after software clear/enable.
- `SUMMARY_VERSION` remains stable at `0x53554D31`.
- Every requested frame reports exactly 64 samples.
- The observed power variation is expected for live RF samples; the register path itself is stable.

## NX Logs

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/logs/summary_v1_after_power_cycle_validation.json
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/logs/summary_v1_register_frame_capture.json
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/logs/summary_v1_register_frame_series.json
```

## Remaining Work

This validates FPGA register summary generation, but not yet numerical equivalence
to NX raw-buffer reference math on the exact same capture. Next step is to create
a controlled side-by-side capture path in the independent NX experiment directory,
then compare `sum_power_raw`, `peak_power_raw`, `peak_index`, and derived RSSI.

## One-Shot Raw IIO Reference Sanity Check

Independent one-shot capture was run from:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/scripts/capture_raw_i16_once.py
```

It performs one IIO buffer refill, computes the same time-domain raw power
reference, and closes the buffer. It does not start ROS or any long-running SDR
worker.

Result:

```text
raw_i16_length: 128
sample_count: 64
sum_power_raw: 509235
peak_power_raw: 43802
peak_index: 30
rssi_dbfs: -51.3016
```

Statistical comparison against the prior 20 FPGA summary frames:

```text
FPGA RSSI range:   -53.1308 .. -22.8250 dBFS
FPGA RSSI median:  -46.0134 dBFS
raw RSSI:          -51.3016 dBFS
delta to median:   -5.2882 dB
```

This is a scale sanity check only. It is not a pass/fail equivalence test because
the raw IIO buffer and FPGA register frame are not triggered from the exact same
sample window.
