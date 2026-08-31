# P201Pro Phase 1.1 Native mmap/UIO Transport

Date: 2026-06-09

## Result

P1.1 software milestone PASS for local fake-register validation.

This does not promote any FPGA version and does not claim board readback,
hardware validation, FFT, PSD, active NX runtime integration, or safety for
active `robot_control`.

Later same-day SDR-local board probe evidence is recorded separately in:

```text
reports/p201_phase1_p1_1_native_mmap_board_probe_20260609.md
```

## What Changed

- Added `nx_experiments/sdr_fpga_offload_test/native/p201_native_mmio.[ch]`.
- Added a strict C fake-register test:
  `nx_experiments/sdr_fpga_offload_test/native/test_p201_native_mmio.c`.
- Added `nx_experiments/sdr_fpga_offload_test/native/Makefile`.
- Added ctypes adapter:
  `nx_experiments/sdr_fpga_offload_test/sdr_fpga_offload_test/native_transport.py`.
- Added local probe script:
  `nx_experiments/sdr_fpga_offload_test/scripts/probe_sum8_native_transport.py`.

## Backend Shape

The C backend opens once and mmaps once, then provides:

- 32-bit register read/write;
- SUM8/AGG8 explicit arm/read helper;
- SUM8/AGG8 fixed snapshot struct;
- snapshot elapsed time in nanoseconds;
- invalid identity, not-done, overflow, stale-frame, sample-mismatch, and
  target-mismatch status flags.

Supported mapping modes:

- `/dev/mem` with page-aligned physical base mapping;
- `/dev/uioX` at mmap offset 0;
- fake register file for unit tests.

## Verification

Commands run from the mainline worktree:

```text
wsl --cd /mnt/e/vivado/fpga_p201pro_accel_mainline sh -lc "make -C nx_experiments/sdr_fpga_offload_test/native clean test"
```

Result:

```text
p201_native_mmio fake-register tests PASS
```

Shared library build:

```text
wsl --cd /mnt/e/vivado/fpga_p201pro_accel_mainline sh -lc "make -C nx_experiments/sdr_fpga_offload_test/native lib"
```

Python checks:

```text
python -m py_compile nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\native_transport.py nx_experiments\sdr_fpga_offload_test\scripts\probe_sum8_native_transport.py
wsl --cd /mnt/e/vivado/fpga_p201pro_accel_mainline sh -lc "python3 -m py_compile nx_experiments/sdr_fpga_offload_test/sdr_fpga_offload_test/native_transport.py nx_experiments/sdr_fpga_offload_test/scripts/probe_sum8_native_transport.py"
```

ctypes fake mmap smoke test:

```text
python native_transport fake mmap PASS
```

## Not Run

- No SDR board mmap readback was run for this initial software milestone.
- No SSH/devmem equivalence check was run for this initial P1.1 commit.
- No ROS, SDR streaming runtime, mapping, RTAB-Map, navigation,
  `robot_controller`, `cmd_vel`, or robot motion process was started.
- No active `robot_control` file was modified.

## Next Safe Step

Copy/build this independent experiment code on the SDR-local Linux side or a
confirmed UIO-capable target, then run `probe_sum8_native_transport.py` first in
read-only mode and then with explicit `--arm` if the loaded image exposes the
expected SUM8/AGG8 registers.
