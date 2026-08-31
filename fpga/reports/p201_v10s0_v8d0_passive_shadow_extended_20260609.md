# P201Pro V10S0/V8D0 Passive Shadow Extension

Date: 2026-06-09 12:08 Asia/Shanghai

Scope:

```text
Current SDR image: V10S0 isolated reusable submodule self-test
Live tap base used: V8D0 SUM8/QUA8/AGG8 at 0x43C00000
NX path: /home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
Windows mirror path: E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test
```

Safety:

```text
No ROS.
No SDR streaming runtime.
No robot_control modification.
No mapping, RTAB-Map, navigation, cmd_vel, or robot motion.
No SDR /sd staging or BOOT.bin change in this step.
```

Results:

```text
sum8_v8d0_passive_read_20260609_extended_mainline.json
  PASS 20 / 20
  frame_len=64
  agg_frames=16/64/256/1024
  sample_counts=1024/4096/16384/65536

sum8_v8d0_shadow_compare_20260609_extended64_mainline.json
  PASS 10 / 10
  frame_len=64
  agg_frames=64
  sample_count=4096
  overflows=0

sum8_v8d0_shadow_compare_20260609_extended256_mainline.json
  PASS 5 / 5
  frame_len=64
  agg_frames=256
  sample_count=16384
  overflows=0

v8d0_auto_roll_batch_ssh_20260609_mainline.json
  FAIL for continuous latest-window semantics
  pass_count=1 / 8
  post-first sequence_deltas=0,0,0,0,0,0,0
  control=0x00000015

feature_flag_assist_shadow_v8d0_20260609_mainline.json
  PASS 5 / 5
  selected_cpu=5
  fpga_read_ok=5
  gate_failures=aoa_phase_clipped

feature_flag_assist_assist_v8d0_20260609_mainline.json
  PASS 5 / 5
  selected_cpu=5
  fallback=5
  fpga_read_ok=5
  gate_failures=aoa_phase_clipped

feature_flag_assist_primitive_allow_clip_v8d0_20260609_mainline.json
  PASS 5 / 5
  selected_fpga=5
  fpga_read_ok=5
  clipped_estimates=5

feature_flag_assist_assist_v8d0_20260609_stress20_mainline.json
  PASS 20 / 20
  fpga_read_ok=20
  selected_fpga=1
  selected_cpu=19
  fallback=19
  gate_failures=aoa_phase_clipped for 19 decisions

feature_flag_assist_primitive_allow_clip_v8d0_20260609_stress20_mainline.json
  PASS 20 / 20
  fpga_read_ok=20
  selected_fpga=20

feature_flag_assist_assist_v8d0_20260609_stress100_mainline.json
  PASS 100 / 100
  fpga_read_ok=100
  selected_fpga=4
  selected_cpu=96
  fallback=96
  gate_failures=aoa_phase_clipped for 94 decisions, coherence_below_gate for 7 decisions

feature_flag_assist_primitive_allow_clip_v8d0_20260609_stress100_mainline.json
  PASS 100 / 100
  fpga_read_ok=100
  selected_fpga=97
  selected_cpu=3
  fallback=3
  gate_failures=coherence_below_gate for 3 decisions
```

Interpretation:

```text
Current-loaded FPGA identity was rechecked read-only before interpreting the
stress20 probes. V8D0 base IDs and the V10S0 self-test page were present:
BASE_BUILD=0x56384430, BASE_QUALITY_BUILD=0x51384430,
BASE_AGG_BUILD=0x41384430, V10S0_MAGIC=0x53305430,
V10S0_DONE=0x0000000F, V10S0_BUILD=0x56313053. V10S4 and V10S5 pages were
absent.

No new SDR /sd staging or physical power-cycle happened for the feature-flag
probe step, so the feature-flag results are current-loaded-image board tests
only. They are not a new SD payload validation event.

After stress100, read-only health remained good: V8D0/V10S0 identity registers
still matched and the IIO context still exposed ad9361-phy plus cf-ad9361-lpc.

The current V10S0 image's V8D0 base is stable for explicit arm/read passive
aggregate captures and shadow compare from the independent NX experiment
directory. It should not be treated as an auto-roll latest-window backend until
a later candidate shows an advancing agg_sequence.

The feature-flag assist prototype confirms the immediate mainline shape:
default assist remains conservative and falls back to CPU when AoA policy gates
fire, while primitive-assist can select FPGA SUM8/AGG8 primitives and leave the
clipped AoA flag visible to NX policy.

These results are passive shadow workflow evidence only. CPU raw-IQ and FPGA
AGG8 windows are adjacent/nearby, not hardware-synchronized. This is not active
NX runtime integration, not feature-flag assist in robot_control, and not a new
hardware-validation promotion beyond the existing V10S0 isolated self-test
scope recorded in VERSION_ROUTE.md.
```
