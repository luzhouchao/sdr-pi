# P201Pro Phase 1.1 Native mmap Board Probe

Date: 2026-06-09

## Result

P1.1 native local register transport board probe PASS on the current-loaded
V10S0/V8D0 image.

This is a current-loaded-image transport milestone only. It does not promote any
FPGA version, does not claim FFT/PSD hardware, does not modify active
`robot_control`, and does not start ROS, SDR streaming runtime, mapping,
RTAB-Map, navigation, `robot_controller`, `cmd_vel`, or robot motion.

## Safety Scope

- SDR writes were limited to the existing SUM8/AGG8 explicit arm/read control
  sequence.
- No AD9361 configuration was changed.
- No BOOT file, SD payload, original SD backup, or vendor package was modified.
- The standalone probe was copied only to SDR `/tmp`:
  `/tmp/p201_p1_1_native_transport_test/p201_sum8_native_probe`.
- NX files stayed under the independent experiment directory.

## Toolchain And Upload

The SDR root filesystem did not provide `gcc`, `python3`, `tar`, or SFTP, so the
probe was built on Windows with the Xilinx ARMHF cross compiler and uploaded via
NX using Paramiko SSH exec plus `cat`.

Static probe artifact:

```text
nx_experiments/sdr_fpga_offload_test/native/build/p201_sum8_native_probe_armhf_static
```

ELF check:

```text
ELF 32-bit LSB executable, ARM, EABI5, statically linked, for GNU/Linux 3.2.0
```

SHA256:

```text
0ddd6ff0dabe9394015f79a7864750079003979cdd773034256dc8a7762a042b
```

Local and NX fake-register gate:

```text
p201_native_mmio fake-register tests PASS
```

## Board Precheck

Log:

```text
nx_experiments/sdr_fpga_offload_test/logs/p1_1_native_phase0_before_probe_20260609.json
```

Checks:

```text
BASE_SUMMARY       0x53554D38 PASS
BASE_BUILD         0x56384430 PASS
BASE_QUALITY       0x51554138 PASS
BASE_QUALITY_BUILD 0x51384430 PASS
BASE_AGG           0x41474738 PASS
BASE_AGG_BUILD     0x41384430 PASS
V10S0_MAGIC        0x53305430 PASS
V10S0_DONE         0x0000000F PASS
V10S0_BUILD        0x56313053 PASS
ad9361-phy         present PASS
cf-ad9361-lpc      present PASS
V10S4/V10S5 pages  absent from current-loaded image PASS
```

## Read-Only Native Probe

Command on SDR:

```text
/tmp/p201_p1_1_native_transport_test/p201_sum8_native_probe --device /dev/mem
```

Log:

```text
nx_experiments/sdr_fpga_offload_test/logs/p1_1_native_probe_readonly_20260609.json
```

Result:

```text
passed true
identity_ok true
summary_version 0x53554D38
build_id 0x56384430
agg_build_id 0x41384430
snapshot_elapsed_ns 10107
```

The read-only mode opens `/dev/mem` read-only and performs no register writes.

## Explicit Arm/Read Native Probe

Command on SDR:

```text
/tmp/p201_p1_1_native_transport_test/p201_sum8_native_probe --device /dev/mem --arm --frame-len 64 --agg-frames 64
```

Log:

```text
nx_experiments/sdr_fpga_offload_test/logs/p1_1_native_probe_arm64_20260609.json
```

Result:

```text
passed true
identity_ok true
aggregate_ok true
agg_samples 4096
agg_control 0x00000011
status_flags 0x00000000
poll_elapsed_ns 1092276
snapshot_elapsed_ns 8526
```

The default probe uses `poll-us=1000`, so the single-run poll time is dominated
by the coarse sleep interval rather than AXI-Lite register access.

## Repeat Timing Probe

Command shape:

```text
/tmp/p201_p1_1_native_transport_test/p201_sum8_native_probe --device /dev/mem --arm --frame-len 64 --agg-frames 64 --poll-us 50
```

Log:

```text
nx_experiments/sdr_fpga_offload_test/logs/p1_1_native_probe_arm64_repeat20_poll50_20260609.json
```

Result:

```text
passed_count 20 / 20
snapshot_elapsed_ns min/median/max 8520 / 8560 / 8700
poll_elapsed_ns     min/median/max 133290 / 141771 / 145071
NX exec wall median 15120466
```

Interpretation:

- Native mmap register snapshot readback is in the single-digit to low tens of
  microseconds on the SDR.
- Aggregate completion wait is separate from snapshot readback and was about
  142 microseconds median with 50 us polling in this 64x64 probe.
- The NX-triggered SSH exec wrapper remains millisecond-scale. It is validation
  scaffolding, not the runtime hot path.

## Post-Test Health

Log:

```text
nx_experiments/sdr_fpga_offload_test/logs/p1_1_native_phase0_after_probe_20260609.json
```

Post-test read-only health still passed:

```text
V8D0 base identity PASS
V10S0 self-test page identity PASS
ad9361-phy present PASS
cf-ad9361-lpc present PASS
V10S4/V10S5 pages absent from current-loaded image PASS
```

## Gate Status

P1.1 gate satisfied:

- mmap readback agrees with the expected current-loaded SUM8/QUA8/AGG8 identity.
- Explicit arm/read reports done, no overflow, no sample mismatch, and no target
  mismatch.
- Latency is reported separately as snapshot readback, aggregate poll wait, and
  remote validation wrapper wall time.
- Existing Python/SSH/devmem validation paths remain available as fallback.

## Next Safe Step

Continue Phase 1 without active runtime changes:

```text
P1.2 FFT/PSD reference model and tolerances
P1.3 isolated fpga_fft_shadow register/self-test implementation
```

Keep Phase 2 AoA phase/coherence as aperture only until Phase 1 shadow evidence
is complete.
