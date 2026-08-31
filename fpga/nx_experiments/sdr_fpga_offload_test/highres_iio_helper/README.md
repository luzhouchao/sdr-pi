# P201Pro High-Resolution IIO Helper

Status: H1.1/H1.2 profiling scaffold only

This directory is a side path for explaining the current raw or near-raw IQ
capture cost. It does not replace the low-resolution FPGA FFT/PSD shadow plan
and it does not modify active `robot_control`.

Windows mirror / B lane root:

```text
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/
```

NX-side B lane root:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/highres_iio_helper/
```

SDR temporary runtime directory:

```text
/tmp/p201_highres_iio_helper_phase1/
```

B logs:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/logs/highres_iio_*.json
```

## Safety Scope

Allowed:

- Run a standalone SDR-local helper from a temporary directory.
- Open the local IIO context.
- Discover the current RX buffer device, normally `cf-ad9361-lpc`.
- Create a short-lived receive buffer, refill it, optionally copy the bytes,
  and print JSON timing.
- Use the Python launcher as SSH validation scaffolding and log collection.

Forbidden:

- No ROS, SDR streaming runtime, mapping, RTAB-Map, navigation,
  `robot_controller`, `/cmd_vel`, or robot motion.
- No active `robot_control` edits.
- No BOOT.bin, SD image, device tree, kernel, driver, FPGA bitstream, clocking,
  AD9361 retune, LO/gain/sample-rate writes, or PHY attribute writes.
- No production runtime claim from Phase 1 timing.
- No low-resolution A-lane FFT shadow files, reports, or ABI artifacts.

## Build

Default build is a fake/no-IIO binary for Windows/WSL CLI and JSON checks:

```bash
cd nx_experiments/sdr_fpga_offload_test/highres_iio_helper
make smoke
```

On SDR Linux with libiio development headers installed:

```bash
cd /tmp/p201_highres_iio_helper_phase1/
make WITH_LIBIIO=1
./build/p201_highres_iio_bench --sample-count 8192 --repeat 20
```

If the SDR has the libiio runtime but lacks `iio.h`, use the Phase 1 dynamic
loader build. This is a profiling fallback only; it calls the same local libiio
context/buffer/refill APIs through `dlopen` and does not write PHY attributes:

```bash
make WITH_LIBIIO=1 IIO_DLOPEN=1 LDLIBS=-ldl
```

If the fresh local IIO context has no RX voltage scan channels enabled and an
isolated benchmark has been approved, use:

```bash
./build/p201_highres_iio_bench --allow-scan-enable --sample-count 8192 --repeat 20
```

If `pkg-config` is not available on the SDR, try:

```bash
make WITH_LIBIIO=1 IIO_LIBS=-liio
```

## Helper Output

The C helper prints one JSON object to stdout with these fields:

```text
operation
passed
sample_count
bytes_per_refill
repeat
context_open_ms
buffer_create_ms
refill_min_ms
refill_median_ms
refill_max_ms
copy_min_ms
copy_median_ms
copy_max_ms
notes
```

`context_open_ms`, `buffer_create_ms`, `refill_*_ms`, and `copy_*_ms` are kept
separate so Phase 1 can distinguish IIO setup, buffer setup, refill cost, and
userspace copy cost.

## NX Launcher

Local fake smoke:

```bash
python3 scripts/run_highres_iio_bench.py \
  --local \
  --helper build/p201_highres_iio_bench \
  --fake \
  --sample-count 128 \
  --repeat 3
```

NX-to-SDR validation scaffold:

```bash
python3 scripts/run_highres_iio_bench.py \
  --ssh-target root@192.168.1.10 \
  --helper /tmp/p201_highres_iio_helper_phase1/p201_highres_iio_bench \
  --sample-count 8192 \
  --repeat 20 \
  --out-json logs/highres_iio_phase1_CURRENT.json
```

Add `--allow-scan-enable` only when the SDR-local benchmark is explicitly
allowed to choose temporary RX voltage scan channels for its short-lived buffer.

The Python launcher records SSH wrapper wall time and helper stdout. That SSH
wall time is validation overhead only and must not be treated as the helper hot
path.

## Notes

- The real helper path calls libiio buffer APIs only. It does not write AD9361
  PHY attributes or retune RF state.
- The default real helper path preserves current RX scan-channel state. If no
  RX voltage scan channel is already enabled, it fails with JSON notes instead
  of changing the device. `--allow-scan-enable` is available only for an
  approved isolated benchmark where temporary scan-channel enable/disable is
  acceptable.
- Phase 1 answers timing bottlenecks only: it does not define a production
  binary protocol or runtime integration.

## Latest Real-IIO Phase 1 Result

2026-06-09 H1.1/H1.2 ran on the SDR from:

```text
/tmp/p201_highres_iio_helper_phase1/build/p201_highres_iio_bench
```

The SDR image had libiio runtime `0.21` but no gcc/python/pkg-config or
`/usr/include/iio.h`, so the committed ARMv7 helper used `IIO_DLOPEN=1`.

Default scan-preserving real-IIO probe:

```text
logs/highres_iio_phase1_real_default_1024x3_20260609.json
passed false, because no RX voltage scan channels were already enabled.
```

Approved isolated `--allow-scan-enable` real-IIO probes:

```text
logs/highres_iio_phase1_real_allow_scan_1024x3_20260609.json
PASS, bytes_per_refill 8192, refill_median_ms 0.024507, copy_median_ms 0.039903.

logs/highres_iio_phase1_real_allow_scan_8192x20_retry_20260609.json
PASS, bytes_per_refill 65536, refill_median_ms 0.027464, copy_median_ms 0.281906,
context_open_ms 27.903177, buffer_create_ms 3.132843, wrapper_wall_ms 153.203975.
```

Post-test health still found `ad9361-phy` and `cf-ad9361-lpc`; all RX scan
enable files read back `0`.

Successful real-IIO runs also emitted libiio's cleanup warning:

```text
ERROR: Error during buffer disable: Unknown error -161
```

This did not prevent valid JSON, a zero helper return code, or post-test IIO
health PASS, but it is an observed cleanup risk. Keep it visible for any H2
persistent-helper or buffer-lifetime review.
