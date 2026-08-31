# P201Pro High-Resolution IIO Helper Phase 1 Report

Date: 2026-06-09 Asia/Shanghai

## Scope

B side path only:

```text
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/
```

Purpose:

```text
Explain or reduce the current 29-31 ms raw/near-raw IQ capture cost by splitting
SDR-local IIO timing into setup, refill, copy, and launcher wrapper overhead.
```

This is not low-resolution FPGA FFT/PSD shadow work and not production runtime
integration.

## Added Files

```text
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/.gitignore
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/Makefile
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/README.md
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/HANDOFF.md
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/VALIDATION_PLAN.md
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/src/p201_highres_iio_bench.c
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/scripts/run_highres_iio_bench.py
```

## Helper Behavior

The helper prints JSON with:

```text
operation
passed
sample_count
bytes_per_refill
repeat
context_open_ms
buffer_create_ms
refill_min_ms/refill_median_ms/refill_max_ms
copy_min_ms/copy_median_ms/copy_max_ms
notes
```

Default no-libiio build supports `--fake` for CLI/JSON validation. Real-IIO
build uses `WITH_LIBIIO=1` and opens a local IIO context on SDR Linux.

The real-IIO default preserves current RX scan-channel state. If no RX voltage
scan channel is already enabled, it fails safely with JSON notes instead of
changing AD9361 or RX device state.

For the P201Pro SDR image used on 2026-06-09, libiio runtime existed but
development headers did not. The helper therefore now supports an
`IIO_DLOPEN=1` build that calls the local libiio context/device/buffer/refill
APIs through `dlopen("libiio.so.0")`. This fallback is Phase 1 profiling-only
and still does not write PHY attributes, LO, gain, sample-rate, clocking,
driver, or FPGA state.

## NX Launcher

`scripts/run_highres_iio_bench.py` can run the helper locally or over SSH. It
records:

```text
wrapper_wall_ms
helper_stdout
helper_stderr
helper_json
helper_json_errors
upload_events
```

The wrapper wall time is validation scaffolding only and must not be treated as
the helper hot path.

## Checks

Completed on the Windows host:

```text
python -m py_compile scripts/run_highres_iio_bench.py
gcc -std=c11 -Wall -Wextra -Wpedantic -Werror -O2 -DP201_HIGHRES_WITH_LIBIIO=0
build/p201_highres_iio_bench.exe --fake --sample-count 128 --repeat 3
python scripts/run_highres_iio_bench.py --smoke-json build/highres_iio_fake.json
python scripts/run_highres_iio_bench.py --local --helper build/p201_highres_iio_bench.exe --fake --sample-count 128 --repeat 3
WSL make clean smoke, no-libiio
git diff --check -- nx_experiments/sdr_fpga_offload_test/highres_iio_helper
```

No real libiio timing was run on this host. WSL had gcc, python3, and make, but
libiio was not detected; PATH also exposed a Windows `pkg-config` that could not
execute inside WSL. If WSL or SDR lacks libiio headers, use the no-libiio/fake
build to keep CLI/JSON validation passing and record the missing dependency.

Additional checks completed in this continuation:

```text
Xilinx SDK arm-linux-gnueabihf-gcc 8.2.0 located on Windows.
ARMHF dlopen helper built as ELF32 ARM EABI hard-float.
NX B-lane helper directory synchronized under:
  /home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/highres_iio_helper/
SDR helper deployed under:
  /tmp/p201_highres_iio_helper_phase1/build/p201_highres_iio_bench
SDR fake smoke PASS from the deployed binary.
```

## Real H1.1/H1.2 Result

Read-only health and toolchain facts:

```text
NX: Linux aarch64, gcc/make/python3/pkg-config present, Paramiko 2.9.3 present.
SDR: Linux armv7l, iio_info present, libiio 0.21 runtime present.
SDR missing: gcc, cc, make, python3, pkg-config, and /usr/include/iio.h.
IIO devices before profiling: ad9361-phy, xadc, cf-ad9361-dds-core-lpc,
cf-ad9361-lpc.
```

Default real-IIO run without `--allow-scan-enable`:

```text
Log: logs/highres_iio_phase1_real_default_1024x3_20260609.json
Result: expected safe FAIL.
Reason: libiio loaded successfully, but no RX voltage scan channels were
already enabled. The helper did not change scan-channel state in default mode.
```

Approved isolated real-IIO run with temporary scan-channel enable, small probe:

```text
Log: logs/highres_iio_phase1_real_allow_scan_1024x3_20260609.json
passed true
sample_count 1024
repeat 3
bytes_per_refill 8192
context_open_ms 30.829683
buffer_create_ms 2.331981
refill_median_ms 0.024507
copy_median_ms 0.039903
wrapper_wall_ms 163.181895
```

Approved isolated real-IIO run with temporary scan-channel enable, target probe:

```text
Log: logs/highres_iio_phase1_real_allow_scan_8192x20_retry_20260609.json
passed true
sample_count 8192
repeat 20
bytes_per_refill 65536
context_open_ms 27.903177
buffer_create_ms 3.132843
refill_median_ms 0.027464
copy_median_ms 0.281906
wrapper_wall_ms 153.203975
```

The helper stderr for successful `--allow-scan-enable` runs included:

```text
ERROR: Error during buffer disable: Unknown error -161
```

The process still returned 0 and produced valid helper JSON. Post-test read-only
health passed:

```text
Log: logs/highres_iio_phase1_post_health_after_real_20260609.json
iio_info -s still lists ad9361-phy and cf-ad9361-lpc.
sysfs device names still include cf-ad9361-lpc.
RX scan enable files under iio:device3 read back 0.
```

Do not ignore the `-161` cleanup warning. It did not invalidate H1.1/H1.2
because the helper completed, scan enables returned to `0`, and IIO health
passed, but it should be reviewed before any H2 persistent helper or reusable
high-resolution service is proposed.

One 8192 x 20 run launched concurrently with other IIO probes failed buffer
creation:

```text
logs/highres_iio_phase1_real_allow_scan_8192x20_20260609.json
```

Treat it as a concurrency diagnostic, not the final timing result. The serial
retry above is the accepted H1.1/H1.2 measurement.

## Interpretation

Compared with the known 29-31 ms raw-IQ NX path, the SDR-local timing separates
the likely cost centers:

```text
context open: about 28-31 ms
buffer create: about 2-3 ms
refill: about 0.025-0.027 ms median
copy: about 0.04 ms for 1024 samples, about 0.28 ms for 8192 samples
NX SSH wrapper: about 153-163 ms, validation overhead only
```

This suggests the expensive part of one-shot high-resolution capture is not the
SDR-local refill/copy loop itself. Future B-lane work should focus on persistent
context/buffer reuse and a non-SSH transfer/receiver path if high-resolution
data is needed on demand.

## Not Touched

```text
active robot_control
ROS or SDR streaming runtime
low-resolution A-lane FFT shadow files
HDL/Vivado/Bootgen/SD payloads
BOOT.bin/original SD backup/vendor package
AD9361 tuning, clocking, kernel, driver, device tree, or FPGA bitstream
```

## Next Safe Step

H1.1/H1.2 are complete enough for Phase 1 profiling. The next safe B-lane step,
if requested, is H1.3 optional preprocessing/no-copy/packed-output probes. Keep
those probes isolated under `highres_iio_helper/` and do not define or apply a
production protocol yet.
