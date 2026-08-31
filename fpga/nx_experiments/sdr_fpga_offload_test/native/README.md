# P201 Native mmap/UIO Transport

This directory contains the Phase 1.1 local register backend for the independent
P201Pro SDR FPGA offload experiment.

It is intentionally separate from active `robot_control` code. It does not start
ROS, SDR streaming runtime, mapping, RTAB-Map, navigation, `robot_controller`,
`cmd_vel`, or any robot motion path.

## Scope

The backend provides:

- one-time open and mmap of `/dev/mem`, `/dev/uioX`, or a fake register file;
- 32-bit register reads and writes;
- explicit SUM8/AGG8 arm/read helper;
- fixed SUM8/AGG8 snapshot struct;
- elapsed register snapshot timing;
- invalid identity, not-done, overflow, stale-frame, sample-mismatch, and
  target-mismatch flags.
- standalone `p201_sum8_native_probe` for SDR images that do not have Python.

It does not implement FFT/PSD. It is a transport milestone used before adding
`fpga_fft_shadow` ABI work.

## Build And Test

On a Linux/POSIX target:

```bash
cd /home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/native
make clean test lib
```

From this Windows workspace via WSL:

```bash
wsl --cd /mnt/e/vivado/fpga_p201pro_accel_mainline \
  sh -lc "make -C nx_experiments/sdr_fpga_offload_test/native clean test lib"
```

The test uses a fake mmap register file. It does not access SDR hardware.

Build only the standalone probe with a cross compiler:

```bash
make CC=arm-linux-gnueabihf-gcc probe
```

## Local Probe

Read-only snapshot on a local SDR Linux shell:

```bash
cd /home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
python3 scripts/probe_sum8_native_transport.py \
  --mode devmem \
  --device /dev/mem
```

Explicit SUM8/AGG8 arm/read probe:

```bash
python3 scripts/probe_sum8_native_transport.py \
  --mode devmem \
  --device /dev/mem \
  --arm \
  --frame-len 64 \
  --agg-frames 64 \
  --out-json logs/sum8_native_transport_CURRENT.json
```

For UIO, use `--mode uio --device /dev/uioX` after confirming the UIO device
maps the P201 tap aperture at mmap offset 0.

If SDR local Linux lacks Python, run the standalone C probe instead:

```bash
/tmp/p201_p1_1_native_transport_test/p201_sum8_native_probe --device /dev/mem
/tmp/p201_p1_1_native_transport_test/p201_sum8_native_probe \
  --device /dev/mem \
  --arm \
  --frame-len 64 \
  --agg-frames 64
```

## Safety Notes

- No SSH, `devmem`, subprocess, or fork is used in the hot path.
- The default probe mode is read-only. Register writes only happen when `--arm`
  is supplied.
- This backend is not active runtime integration and is not hardware validation.
