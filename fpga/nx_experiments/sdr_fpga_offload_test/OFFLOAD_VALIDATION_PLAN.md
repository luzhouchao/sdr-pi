# SDR FPGA Offload Validation Plan

Last updated: 2026-06-09 19:20 Asia/Shanghai

This plan describes the current safe validation ladder for the independent NX
experiment directory. `VERSION_ROUTE.md` remains the source of truth for version
status and hardware-validation claims.

## Phase 0: Identity And Health

Before interpreting any board result, confirm the current-loaded image:

```text
0x43C00040 BASE_SUMMARY       expected 0x53554D38
0x43C000FC BASE_BUILD         expected 0x56384430 for V8D0 current-loaded base
0x43C00100 BASE_QUALITY       expected 0x51554138
0x43C0013C BASE_QUALITY_BUILD expected 0x51384430
0x43C00180 BASE_AGG           expected 0x41474738
0x43C001F8 BASE_AGG_BUILD     expected 0x41384430

0x43C10000 V10S0_MAGIC        expected 0x53305430 when V10S0 page is loaded
0x43C10018 V10S0_DONE         expected 0x0000000F
0x43C1001C V10S0_BUILD        expected 0x56313053
```

Also confirm IIO still sees:

```text
ad9361-phy
cf-ad9361-lpc
```

## Phase 1: Passive Aggregate Read

Use explicit arm/read AGG8 access:

```bash
python3 scripts/read_sum8_aggregate_batch_ssh.py \
  --frame-len 64 \
  --agg-frames 16 64 256 1024 \
  --repeat 5 \
  --out-json logs/sum8_v8d0_passive_read_CURRENT.json
```

Pass conditions:

```text
metadata/version/build IDs match expected route
done set
overflow clear
sample_count == frame_len * agg_frames
all captures pass
```

## Phase 1.1: Native Local Register Transport

Use the local C mmap/UIO backend to remove SSH/devmem subprocess overhead before
making runtime-latency claims.

Software gate:

```bash
cd /home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/native
make clean test lib
python3 -m py_compile ../sdr_fpga_offload_test/native_transport.py ../scripts/probe_sum8_native_transport.py
```

Read-only board probe, after confirming the expected loaded image:

```bash
cd /home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
python3 scripts/probe_sum8_native_transport.py --mode devmem --device /dev/mem
```

Explicit arm/read probe:

```bash
python3 scripts/probe_sum8_native_transport.py \
  --mode devmem \
  --device /dev/mem \
  --arm \
  --frame-len 64 \
  --agg-frames 64 \
  --out-json logs/sum8_native_transport_CURRENT.json
```

Pass conditions:

```text
native identity fields match the current route
done set after explicit arm/read
overflow clear
sample_count == frame_len * agg_frames
snapshot elapsed time is reported
no SSH/devmem/fork in the hot path
fallback Python/devmem validation path remains available
```

Current result:

```text
2026-06-09 PASS on current-loaded V10S0/V8D0.
Read-only identity PASS.
Explicit arm/read 64x64 PASS with agg_samples 4096 and status_flags 0.
Repeat20 with poll-us=50 PASS 20/20.
Post-test V8D0/V10S0 identity and AD9361/IIO health PASS.
```

## Phase 2: Passive Shadow Compare

Use raw-IIO CPU primitives beside FPGA AGG8 primitives:

```bash
python3 scripts/compare_sum8_fpga_assisted_metrics.py \
  --frame-len 64 \
  --agg-frames 64 \
  --repeat 10 \
  --out-json logs/sum8_v8d0_shadow_compare_CURRENT.json
```

This is trend/cost evidence, not strict equivalence, because CPU raw-IQ and FPGA
AGG8 windows are adjacent/nearby rather than hardware-synchronized.

## Phase 2.1: FFT Shadow ABI Software Gate

Before RTL or board work, keep the `fpga_fft_shadow` ABI fake-register tests
passing:

```bash
cd /home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
python3 scripts/test_fft_shadow_contract.py
python3 scripts/test_fft_psd_reference.py --out-json logs/p1_2_fft_psd_reference_tolerances_CURRENT.json
python3 scripts/dump_sdr_kernel_contract.py --out SDR_KERNEL_CONTRACT.json
```

Pass conditions:

```text
identity/status fields decode
four top peaks decode
coarse_bin_count accepts 64..128
preferred 96-bin fixture decodes exactly
proxy_not_fft status remains available so a proxy cannot be called FFT/PSD
offline reference/tolerance gate passes for exact 96-bin coarse PSD and top peaks
```

Current result:

```text
2026-06-09 PASS.
test_fft_shadow_contract.py PASS.
test_fft_psd_reference.py PASS on Windows and NX.
Reference keeps exact 96-bin coarse PSD for the FPGA ABI and records the active
UI 2048 -> 98 bin max-hold compression behavior when max_bins=96.
P1.3 isolated RTL self-test PASS on PC:
experiments/phase1_fft_shadow_selftest XSIM/OOC passed for the same ABI page.
P1.3b isolated signed top-4 PSD peak reducer PASS on PC with XSIM/OOC timing.
It is a post-PSD helper primitive only, not a live FFT/PSD hardware path.
P1.3c isolated exact 2048-to-96 coarse PSD reducer PASS on PC with XSIM/OOC
timing. It is a coarse-bin helper primitive only, not a live FFT/PSD hardware
path.
P1.3d isolated FFT4 smoke core PASS on PC with XSIM/OOC timing. It is a minimal
true FFT butterfly datapath gate only, not a 2048-point FFT/window/PSD hardware
path.
P1.4a integration review COMPLETE on PC. It records the usable shadow blocks and
the missing 2048-point FFT/window/PSD generator plus live AD9361 coupling. The
next safe step is an isolated Xilinx FFT IP or equivalent OOC probe before any
bitstream/BOOT/SD payload, board staging, runtime integration, or version
promotion.
No board staging or hardware validation exists.
```

## Phase 3: Feature-Flag Assist Probe

Default conservative assist:

```bash
python3 scripts/probe_feature_flag_assist.py \
  --mode assist \
  --frame-len 64 \
  --agg-frames 64 \
  --repeat 100 \
  --out-json logs/feature_flag_assist_assist_CURRENT.json
```

Primitive-assist experiment:

```bash
python3 scripts/probe_feature_flag_assist.py \
  --mode assist \
  --allow-aoa-phase-clipped \
  --frame-len 64 \
  --agg-frames 64 \
  --repeat 100 \
  --out-json logs/feature_flag_assist_primitive_CURRENT.json
```

Pass conditions:

```text
FPGA read OK for every capture
default assist falls back when quality gates fail
primitive assist selects FPGA only when non-AoA quality gates pass
no clip-count gate failures unless intentionally testing clipping behavior
post-stress identity and IIO health remain good
```

## Phase 4: Active-Package Dry-Run

Allowed next step after independent stress evidence:

```text
patch --dry-run only
py_compile only
no ROS
no runtime process
no active robot_control launch
no motion
```

This step may verify that an off-by-default/shadow candidate patch would apply
cleanly, but it must not start the SDR runtime or publish FPGA-selected values.

Current result:

```text
2026-06-09 PASS. The shadow-only patch
staged_robot_control_integration/robot_control_sum8_shadow_only.patch applied
cleanly in active-package dry-run, and staged candidate py_compile checks
passed. No active robot_control file was modified.
```

## Phase 5: User-Approved Shadow Integration

Only after explicit user approval:

```text
apply an off-by-default feature flag
default mode remains off or shadow
publish CPU result while logging FPGA sidecar
keep immediate CPU fallback
keep clipped-AoA and coherence gates visible
do not start motion-related nodes
```

## Runtime Requirements Before Assist Can Matter

The current Python/SSH/devmem probes are validation tools, not runtime hot-path
implementation. Any runtime-influencing backend must move to C/C++ or another
non-blocking local register access path with:

```text
mmap/UIO access
latency measurement
stale-frame detection
overflow and low-confidence detection
immediate CPU fallback
no fork/devmem/SSH polling in the hot loop
```
