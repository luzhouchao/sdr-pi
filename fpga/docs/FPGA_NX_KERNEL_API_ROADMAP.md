# FPGA/NX SDR Kernel API Roadmap

Last updated: 2026-06-09 19:20 Asia/Shanghai

## Principle

Make FPGA a general SDR math coprocessor, not a rigid single-purpose algorithm box.

FPGA should do high-rate fixed-shape kernels. NX should drive those kernels and compose algorithms in Python, C++, CUDA, or CPU/GPU libraries.

## Current Stable Ladder

```text
SUM3: debug snapshot baseline, hardware validated
SUM4: snapshot plus I/Q sums, hardware-validated debug fallback
SUM5: production no-snapshot corrected summary, hardware booted but failed consistency
SUM6: SUM5-compatible ABI/capability metadata, hardware-validated fallback
SUM7: SUM6-compatible quality page with clip/zero-cross/sign counters, hardware-validated rollback
SUM8: SUM7-compatible AGG8 multi-frame aggregate page; V8L1 is the current highest hardware-validated forward baseline
```

SUM8/QUA8/AGG8 is now the active primitive layer for reducing NX polling and
Python aggregation load. The current-loaded V10S0 image includes a V8D0 SUM8
base that passed passive shadow and feature-flag primitive-assist stress100 in
the independent NX experiment directory. V7 and V6 remain older rollback
candidates.

## Python Package Direction

Target package layers inside the independent experiment directory:

```text
transport/   devmem, mmap, nested SSH, Paramiko
contracts/   offsets, magic values, signedness, ABI versions
drivers/     SummaryV3Driver, SummaryV4Driver, SummaryV5Driver, future V6/V7/V8 drivers
kernels/     DualRxSummary, CorrectedCross, PsdSummary dataclasses
algorithms/  AoA, coherence, RSSI, calibration, aggregation, fallback routing
cli/         validation scripts only
```

Current first files:

```text
sdr_fpga_offload_test\sdr_kernel_contract.py
sdr_fpga_offload_test\sdr_kernel_client.py
sdr_fpga_offload_test\feature_flag_assist.py
scripts\read_sum8_aggregate_client.py
scripts\probe_feature_flag_assist.py
```

Do not move these into active `robot_control` until the user explicitly approves
active integration. The current approved next step is active-package dry-run
only: patch dry-run and py_compile, no ROS/runtime start.

## C++ Direction

Current first header:

```text
include\p201_sdr_kernel_contract.hpp
```

Use it for future C++/CUDA orchestration, but do not bind it to ROS, CUDA, or robot runtime yet.

## Planned Versions

### V6 Block Summary ABI

Goal: turn SUM5 into a stable reusable register ABI.

Candidate additions:

```text
ABI major/minor
kernel capability bitmap
latched result sequence ID
frame-valid flag
overflow flags
last frame length
block-ready/status/error counters
widened corrected numerator post path
```

Still register-only. No FFT, no DMA.

### V7 Quality Page ABI

Goal: expose cheap signal-quality primitives without forcing a full algorithm into FPGA.

Current timing-clean SUM7A outputs:

```text
clip counts
zero-cross counts
same-sign counts
quality page version/capability/build metadata
```

Abs-sum registers are reserved and read zero in SUM7A. A fuller abs-sum version failed timing and was not packaged as burnable.

### V8 Aggregate ABI

Goal: move repeated multi-frame primitive aggregation out of NX Python while
keeping the existing SDR runtime untouched.

Validated outputs:

```text
corrected RX0/RX1 power numerators
corrected cross real/imag numerators
raw RX0/RX1 power
clip counts
zero-cross counts
same-sign counts
```

NX still performs:

```text
divide
sqrt
atan2
calibration
AoA composition
CPU/GPU backend choice
frontend/ROS publication later
```

### V9 FFT/PSD Summary ABI

Goal: add a general spectral kernel without forcing full raw spectrum transfer.

Current Phase 1 software ABI draft uses a new `fpga_fft_shadow` page at
`0x400..0x6fc`, leaving the historical SPEC9 four-bin proxy page at `0x200`
unchanged. It returns scalar summary, four top peaks, and 64..128 coarse PSD
bins with 96 preferred for the first implementation. This is not hardware yet.
The P1.2 reference/tolerance gate now passes on Windows and NX with the current
NX Hann/fftshift/coherent-gain PSD math, exact 96-bin coarse PSD for the FPGA
ABI, and a documented active-UI max-hold compression difference where 2048 PSD
bins become 98 UI bins when `max_bins=96`.
P1.3 now has a PC-only isolated RTL fixture for the same ABI, with XSIM/OOC
PASS and 96 coarse bins visible through AXI-Lite. It is deterministic register
shape evidence only, not live AD9361 FFT/PSD hardware.
P1.3b adds a PC-only timing-clean signed top-4 PSD reducer primitive for the
same shadow path. XSIM PASS and OOC timing PASS at 8.138 ns; it is a post-PSD
helper only, not FFT/PSD generation or live AD9361 integration.
P1.3c adds a PC-only exact 2048-to-96 coarse PSD max-hold reducer primitive for
the same shadow path. XSIM PASS and OOC timing PASS at 8.138 ns; it is a
coarse-bin helper only, and its 96-direct-register cost must be reviewed before
live integration.
P1.3d adds a PC-only 4-point complex FFT smoke core for the same shadow path.
XSIM PASS and OOC timing PASS at 8.138 ns; it proves a minimal true FFT
butterfly datapath with power/peak summary, but it is not a 2048-point
FFT/window/PSD generator or live AD9361 integration.
P1.4a records the PC-only integration review. The usable blocks are the native
mmap/UIO transport, FFT shadow ABI/client, P1.2 reference gate, ABI fixture,
top-4 reducer, coarse96 reducer, and FFT4 smoke core. The missing block is a
real 2048-point FFT/window/PSD generator plus live AD9361 coupling. The next
recommended A-route step is an isolated Xilinx FFT IP or equivalent OOC probe,
composed with top-4 and coarse96 before any bitstream/BOOT/SD work.

Candidate controls:

```text
nfft
window ID
scale exponent
average count
bin range
```

Candidate outputs:

```text
top peaks
band power
noise floor
peak prominence
optional limited PSD bins
```

### V10 DMA Stream ABI

Goal: move larger vectors only after the register kernel path proves useful.

Candidate features:

```text
ring buffer metadata
ownership flags
sequence IDs
timestamps
dropped-frame counters
DMA for raw IQ, FFT bins, or batch summaries
```

## What Not To Build Yet

Before the next FPGA/NX iteration, run the authorized performance review. The
review should explicitly check whether the next step reduces NX load as a
reusable primitive, whether widths/pipelines are timing-safe, and whether debug
paths stay isolated from production timing.

Do not add:

```text
ROS integration
active robot_control replacement
SDR streaming runtime
robot motion hooks
CUDA/GPU kernels
full DMA
FFT HDL
plugin framework
generated bindings
general SDR framework
```

Keep the work boring, versioned, and easy for the next human or AI to resume.
