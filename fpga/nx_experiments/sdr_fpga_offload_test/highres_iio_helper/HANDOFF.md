# P201Pro High-Resolution IIO Helper Handoff

Last updated: 2026-06-09 Asia/Shanghai

## Scope

B lane root:

```text
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/
```

NX-side root:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/highres_iio_helper/
```

SDR temporary runtime directory:

```text
/tmp/p201_highres_iio_helper_phase1/
```

Logs:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/logs/highres_iio_*.json
```

This lane profiles the high-resolution path:

```text
AD9361 -> SDR-local C IIO helper -> raw/preprocessed data -> NX CPU/GPU
```

It is side-path profiling only. It does not replace the low-resolution FPGA
FFT/PSD shadow mainline and makes no production runtime claim.

## Safety Boundary

Do not start ROS, SDR streaming runtime, mapping, RTAB-Map, navigation,
`robot_controller`, `/cmd_vel`, or robot motion.

Do not modify active `robot_control`.

Do not modify BOOT.bin, SD payloads, original SD backups, vendor packages,
device tree, kernel, drivers, clocking, AD9361 tuning, or FPGA bitstream.

Do not touch A-lane FFT shadow files:

```text
sdr_fpga_offload_test/fft_shadow_client.py
SDR_KERNEL_CONTRACT.json
scripts/test_fft_shadow_contract.py
scripts/test_fft_psd_reference.py
reports/p201_phase1_p1_4a_fft_shadow_integration_review_20260609.md
```

## What Changed

- Added a B-lane work folder with `README.md`, `HANDOFF.md`,
  `VALIDATION_PLAN.md`, `Makefile`, `src/`, and `scripts/`.
- Added `src/p201_highres_iio_bench.c`.
  - Default build is no-libiio/fake-capable for Windows/WSL smoke checks.
  - `WITH_LIBIIO=1` enables SDR-local libiio timing.
  - Real-IIO default preserves current RX scan-channel state.
  - It reports separate context-open, buffer-create, refill, and copy timing.
  - Added `IIO_DLOPEN=1` support for SDR images with libiio runtime but no
    development headers. This is Phase 1 profiling-only dynamic loading of
    local libiio buffer APIs.
- Added `scripts/run_highres_iio_bench.py`.
  - Runs the helper locally or over SSH.
  - Added optional Paramiko password SSH mode for NX-to-SDR validation where
    interactive `ssh root@192.168.1.10` would require a locally managed password.
  - Records wrapper wall time separately from helper JSON.
  - Validates helper JSON shape.
- Added report:

```text
reports/p201_highres_iio_helper_phase1_20260609.md
```

## What Was Not Touched

- No active NX `robot_control` files.
- No ROS launch/runtime files.
- No low-resolution FFT shadow ABI/client/test files.
- No HDL, Vivado scripts, bitstreams, Bootgen artifacts, or SD payloads.
- No AD9361 retune, clocking, device tree, kernel, driver, or FPGA state.

## Build And Run

Windows/WSL fake smoke:

```bash
cd nx_experiments/sdr_fpga_offload_test/highres_iio_helper
make smoke
```

Equivalent direct build if `make` is unavailable:

```bash
gcc -std=c11 -Wall -Wextra -Wpedantic -Werror -O2 \
  -DP201_HIGHRES_WITH_LIBIIO=0 \
  -o build/p201_highres_iio_bench src/p201_highres_iio_bench.c
./build/p201_highres_iio_bench --fake --sample-count 128 --repeat 3
python3 scripts/run_highres_iio_bench.py --smoke-json build/highres_iio_fake.json
```

SDR-local real-IIO build:

```bash
cd /tmp/p201_highres_iio_helper_phase1/
make WITH_LIBIIO=1
./build/p201_highres_iio_bench --sample-count 8192 --repeat 20
```

NX launcher scaffold:

```bash
cd /home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/highres_iio_helper
python3 scripts/run_highres_iio_bench.py \
  --ssh-target root@192.168.1.10 \
  --helper /tmp/p201_highres_iio_helper_phase1/build/p201_highres_iio_bench \
  --sample-count 8192 \
  --repeat 20 \
  --out-json logs/highres_iio_phase1_CURRENT.json
```

The SSH wrapper wall time is validation scaffolding only.

## Checks

PC checks completed:

```text
python -m py_compile scripts/run_highres_iio_bench.py
gcc no-libiio build with -Wall -Wextra -Wpedantic -Werror
fake helper JSON smoke
launcher local fake smoke
WSL make clean smoke, no-libiio
git diff --check for highres_iio_helper
```

Real libiio build was not run on this Windows/WSL host. WSL had gcc, python3,
and make, but libiio was not detected; the PATH also exposed a Windows
`pkg-config` that could not execute inside WSL. If WSL or SDR lacks libiio
headers, keep using the no-libiio fake build for CLI/JSON validation and record
the missing dependency.

## H1.1/H1.2 Real SDR Result

2026-06-09:

```text
SDR: armv7l, libiio runtime 0.21 at /usr/lib/libiio.so.0.21
SDR missing: gcc, cc, make, python3, pkg-config, /usr/include/iio.h
NX: aarch64, gcc/make/python3/pkg-config present, no armhf cross compiler
Windows host: Xilinx SDK arm-linux-gnueabihf-gcc 8.2.0 present
```

The helper was cross-compiled on Windows as ARM EABI hard-float with
`P201_HIGHRES_WITH_LIBIIO=1` and `P201_HIGHRES_IIO_DLOPEN=1`, copied through NX,
and run from:

```text
/tmp/p201_highres_iio_helper_phase1/build/p201_highres_iio_bench
```

Default real-IIO run without `--allow-scan-enable` loaded libiio successfully
but failed safely because no RX voltage scan channels were already enabled:

```text
logs/highres_iio_phase1_real_default_1024x3_20260609.json
```

Approved isolated real-IIO runs with `--allow-scan-enable` passed:

```text
logs/highres_iio_phase1_real_allow_scan_1024x3_20260609.json
  PASS, sample_count 1024, repeat 3, bytes_per_refill 8192
  refill_median_ms 0.024507, copy_median_ms 0.039903

logs/highres_iio_phase1_real_allow_scan_8192x20_retry_20260609.json
  PASS, sample_count 8192, repeat 20, bytes_per_refill 65536
  context_open_ms 27.903177, buffer_create_ms 3.132843
  refill_median_ms 0.027464, copy_median_ms 0.281906
  wrapper_wall_ms 153.203975
```

The helper stderr included libiio's buffer-disable warning:

```text
ERROR: Error during buffer disable: Unknown error -161
```

The process still returned 0 and post-test read-only health passed. After the
run, `iio_info -s` still listed `ad9361-phy` and `cf-ad9361-lpc`, and RX scan
enable sysfs files read back `0`. Treat the `-161` buffer-disable message as an
observed cleanup warning for H2 persistent-helper or buffer-lifetime review; do
not hide it in future work even though H1.1/H1.2 health passed.

One earlier 8192/20 run failed buffer creation while multiple real-IIO probes
were launched in parallel. Treat
`logs/highres_iio_phase1_real_allow_scan_8192x20_20260609.json` as concurrency
diagnostic evidence only; the final serial retry above is the H1.1/H1.2 timing
result.

## Known Blockers

- Real IIO refill timing still needs SDR-local libiio headers/runtime.
- The default real-IIO helper requires current RX scan channels to already be
  enabled. If none are enabled, it fails safely with JSON notes.
- SSH launcher timing cannot be used as the hot-path latency number.
- No hardware timing claim exists until the helper runs locally on the SDR and
  post-test IIO health is checked.

## Next Safe Step

Phase 1 H1.1/H1.2 has enough real profiling evidence. The next safe B-lane step
is H1.3 only if requested: add optional preprocessing probes such as no-copy,
decimate-by-N, packed binary output, or RSSI/power timing. Keep this separate
from A-lane FPGA FFT shadow work and do not define a production protocol yet.
