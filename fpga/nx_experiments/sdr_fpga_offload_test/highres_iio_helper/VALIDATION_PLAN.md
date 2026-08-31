# P201Pro High-Resolution IIO Helper Validation Plan

Last updated: 2026-06-09 Asia/Shanghai

This plan is for B-lane H1.1/H1.2 profiling only.

## Fixed Paths

Windows mirror:

```text
nx_experiments/sdr_fpga_offload_test/highres_iio_helper/
```

NX work folder:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/highres_iio_helper/
```

SDR temporary runtime folder:

```text
/tmp/p201_highres_iio_helper_phase1/
```

Log pattern:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/logs/highres_iio_*.json
```

## H1.1 PC/WSL Software Gate

Goal: prove CLI, JSON shape, fake/no-IIO mode, and launcher parsing without SDR.

Commands:

```bash
cd nx_experiments/sdr_fpga_offload_test/highres_iio_helper
python3 -m py_compile scripts/run_highres_iio_bench.py
make smoke
```

If `make` is unavailable:

```bash
mkdir -p build
gcc -std=c11 -Wall -Wextra -Wpedantic -Werror -O2 \
  -DP201_HIGHRES_WITH_LIBIIO=0 \
  -o build/p201_highres_iio_bench src/p201_highres_iio_bench.c
./build/p201_highres_iio_bench --fake --sample-count 128 --repeat 3 \
  > build/highres_iio_fake.json
python3 scripts/run_highres_iio_bench.py --smoke-json build/highres_iio_fake.json
```

Pass conditions:

```text
helper fake JSON has required timing fields
launcher validates helper JSON
no libiio dependency is required for fake mode
no ROS/SDR runtime/active robot_control action occurs
```

## H1.1 SDR-Local Real-IIO Gate

Goal: separate context-open, buffer-create, refill, and userspace copy timing.

Commands on SDR:

```bash
cd /tmp/p201_highres_iio_helper_phase1/
make WITH_LIBIIO=1
./build/p201_highres_iio_bench --sample-count 8192 --repeat 20
```

If the SDR has libiio runtime but lacks headers, build elsewhere with:

```bash
make WITH_LIBIIO=1 IIO_DLOPEN=1 LDLIBS=-ldl
```

Default behavior:

```text
open local IIO context
find current RX buffer device
use currently enabled RX scan channels
create one buffer
run repeat refills
measure optional copy timing
print JSON
destroy buffer/context
```

The default real-IIO path must not write PHY attributes or retune AD9361. It
also does not enable scan channels unless `--allow-scan-enable` is explicitly
used for an approved isolated benchmark.

Pass conditions:

```text
passed true
bytes_per_refill > 0
refill timing reported
copy timing reported unless --no-copy was used
post-test IIO health still sees ad9361-phy and cf-ad9361-lpc
```

Current result:

```text
2026-06-09 real-IIO PASS with explicit isolated --allow-scan-enable.
Default scan-preserving run loaded libiio but failed safely because no RX scan
channels were already enabled.

1024 x 3:
  bytes_per_refill 8192
  refill_median_ms 0.024507
  copy_median_ms 0.039903

8192 x 20 serial retry:
  bytes_per_refill 65536
  context_open_ms 27.903177
  buffer_create_ms 3.132843
  refill_median_ms 0.027464
  copy_median_ms 0.281906

Post-test health PASS: ad9361-phy and cf-ad9361-lpc still present; RX scan
enable sysfs files read back 0.

Observed cleanup warning on successful allow-scan runs:

  ERROR: Error during buffer disable: Unknown error -161

This did not fail H1.1/H1.2 because helper JSON passed, the process returned 0,
and post-test IIO health passed. It remains an H2 cleanup/buffer-lifetime review
item and must not be hidden in future persistent-helper work.
```

## H1.2 NX Launcher Gate

Goal: collect the SDR-local helper JSON and record wrapper overhead separately.

Command on NX:

```bash
cd /home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/highres_iio_helper
python3 scripts/run_highres_iio_bench.py \
  --ssh-target root@192.168.1.10 \
  --helper /tmp/p201_highres_iio_helper_phase1/build/p201_highres_iio_bench \
  --sample-count 8192 \
  --repeat 20 \
  --out-json logs/highres_iio_phase1_CURRENT.json
```

Use launcher `--allow-scan-enable` only when the corresponding helper-side
option has been approved for an isolated benchmark.

Pass conditions:

```text
launcher passed true
helper_json passed true
wrapper_wall_ms recorded separately
helper stdout preserved
log saved under logs/highres_iio_*.json
no active runtime touched
```

Current result:

```text
2026-06-09 H1.2 PASS.
NX launcher used Paramiko password SSH to avoid an interactive SDR password
prompt, preserved helper stdout/stderr, saved logs under logs/highres_iio_*.json,
and recorded wrapper_wall_ms separately. The 8192 x 20 serial retry wrapper wall
time was 153.203975 ms; this is validation scaffolding overhead, not the helper
hot path.
```

## Stop Conditions

Stop and document if:

```text
any command would start ROS, SDR streaming runtime, mapping, RTAB-Map,
navigation, robot_controller, cmd_vel, or motion
any command would modify active robot_control
any command would retune AD9361 or write PHY/clock/gain/sample-rate attrs
any command would modify BOOT.bin, SD payload, kernel, driver, device tree, or FPGA bitstream
helper cannot find current RX buffer device
real-IIO default finds no currently enabled RX scan channels
post-test IIO health regresses
```

## Result Interpretation

If refill median is near 29-31 ms:

```text
focus next on IIO buffer/cadence constraints
```

If refill is fast but wrapper or transfer is slow:

```text
do not optimize SSH; design a future binary protocol or NX C/C++ receiver after Phase 1
```

If copy dominates:

```text
evaluate buffer reuse, packing, and optional preprocessing modes
```

No production runtime claim is made in Phase 1.
