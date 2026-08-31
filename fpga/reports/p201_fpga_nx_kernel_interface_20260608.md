# P201 FPGA/NX Kernel Interface Preparation

Generated: 2026-06-08

## Goal

Prepare the project for the architecture where FPGA exposes general SDR kernels/results and NX composes algorithms in Python/C++/CPU/GPU.

No active NX runtime code was changed. No ROS, SDR streaming runtime, robot control, mapping, RTAB-Map, `/cmd_vel`, or motion path was started.

## Added Interface Files

Python contract:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\sdr_kernel_contract.py
```

Python typed client:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\sdr_kernel_client.py
```

C++ header:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\include\p201_sdr_kernel_contract.hpp
```

Contract dump CLI:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\dump_sdr_kernel_contract.py
```

Generated machine-readable contract in tomorrow bundle:

```text
E:\vivado\fpga_p201pro_accel\tomorrow_validation_bundle_20260608\SDR_KERNEL_CONTRACT.json
```

## Added Docs

Canonical register/kernel contract:

```text
E:\vivado\fpga_p201pro_accel\docs\P201_SDR_FPGA_KERNEL_CONTRACT.md
```

FPGA/NX API roadmap:

```text
E:\vivado\fpga_p201pro_accel\docs\FPGA_NX_KERNEL_API_ROADMAP.md
```

## Current SUM5 Contract

SUM5 is the current production-shaped register kernel:

```text
SUMMARY_VERSION = 0x53554D35
SNAPSHOT_COUNT  = 0
```

FPGA role:

```text
dual-RX power
dual-RX peaks
cross real/imag
signed I/Q sums
corrected numerator registers
```

NX role:

```text
read versioned registers
compute coherence/phase/aoa/calibration
aggregate frames
choose CPU/GPU/Python/C++ higher-level algorithms
publish later only after validation
```

## Future Version Route

V6 should stabilize the block-summary ABI before adding new math:

```text
ABI major/minor
capability bitmap
sequence ID
frame-valid flag
overflow flags
widened corrected path
status/error counters
```

V7 should add FFT/PSD summary as a fixed-shape optional kernel:

```text
nfft
window ID
scale exponent
top peaks
band power
noise floor
limited PSD bins
```

V8 should add DMA only after register kernels prove value:

```text
ring metadata
ownership
sequence/timestamp
dropped-frame counters
raw IQ, FFT bins, or batch summaries
```

## Verification

Local compile check passed for:

```text
sdr_kernel_contract.py
sdr_kernel_client.py
dump_sdr_kernel_contract.py
```

Contract dump command succeeded:

```powershell
python nx_experiments\sdr_fpga_offload_test\scripts\dump_sdr_kernel_contract.py --out tomorrow_validation_bundle_20260608\SDR_KERNEL_CONTRACT.json
```

## Important Limits

Do not advertise SUM5 corrected numerator validation above frame length 256 until HDL widens the post-frame I/Q sum path.

Do not move these interfaces into active `robot_control` until V5 passes hardware validation and side-by-side comparison.
