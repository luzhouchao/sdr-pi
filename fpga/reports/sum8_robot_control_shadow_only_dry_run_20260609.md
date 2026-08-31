# SUM8 Robot Control Shadow-Only Dry-Run

Date: 2026-06-09

## Result

PASS as an active-package dry-run. The active NX `robot_control` package was not
modified, and no ROS, SDR runtime, mapping, navigation, `cmd_vel`, or robot
motion process was started.

## Context Reviewed

Independent experiment modules reviewed before preparing the safer active
candidate:

```text
nx_experiments/sdr_fpga_offload_test/sdr_fpga_offload_test/feature_flag_assist.py
nx_experiments/sdr_fpga_offload_test/sdr_fpga_offload_test/sdr_kernel_client.py
nx_experiments/sdr_fpga_offload_test/sdr_fpga_offload_test/fpga_assisted_metrics.py
```

Findings:

- `feature_flag_assist.py` already provides off/shadow/assist decision logic
  around explicit arm/read SUM8/AGG8 access, with CPU fallback and quality-gate
  visibility.
- `sdr_kernel_client.py` is the reusable SUM8/QUA8/AGG8 register client. It
  accepts the current V8D0/V8L1/V8L2 AGG8 build IDs and uses explicit arm/read
  aggregate access.
- `fpga_assisted_metrics.py` keeps the correct split: FPGA returns primitive
  corrected power/cross/quality summaries, while NX does RSSI/coherence/phase
  and AoA composition.

Because the current active-package step should be conservative, a new
shadow-only patch was prepared instead of applying the older shadow/assist
patch.

## New Staged Candidate

Patch:

```text
nx_experiments/sdr_fpga_offload_test/staged_robot_control_integration/robot_control_sum8_shadow_only.patch
```

Candidate backend syntax file:

```text
nx_experiments/sdr_fpga_offload_test/staged_robot_control_integration/robot_control_shadow_only_candidate/sdr_aoa_backend.py
```

Patch behavior:

```text
aoa_backend=auto/cpu/numpy       unchanged CPU path
aoa_backend=fpga_sum8_shadow     CPU publication; FPGA AGG8 sidecar read/status only
```

The patch does not add `fpga_sum8_assist`, and it never returns an FPGA result
as the published AoA estimate.

## Verification

Local syntax check:

```text
python -m py_compile \
  nx_experiments/sdr_fpga_offload_test/staged_robot_control_integration/robot_control_shadow_only_candidate/sdr_aoa_backend.py \
  nx_experiments/sdr_fpga_offload_test/staged_robot_control_integration/robot_control_candidate/sdr_dual_aoa_localizer.py
```

Result: PASS.

The staged files were copied only to the NX independent experiment directory:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/staged_robot_control_integration
```

Active-package dry-run command:

```bash
cd /home/wheeltec/ros2_ws/src/robot_control
patch -p0 --dry-run < sdr_fpga_offload_test/staged_robot_control_integration/robot_control_sum8_shadow_only.patch
```

Result:

```text
checking file robot_control/sdr_aoa_backend.py
checking file robot_control/sdr_dual_aoa_localizer.py
```

NX candidate syntax check:

```text
python3 -m py_compile \
  sdr_fpga_offload_test/staged_robot_control_integration/robot_control_shadow_only_candidate/sdr_aoa_backend.py \
  sdr_fpga_offload_test/staged_robot_control_integration/robot_control_candidate/sdr_dual_aoa_localizer.py
```

Result: PASS.

## Safety Notes

- No active `robot_control` file was modified.
- No patch was applied.
- No runtime process was started.
- The shadow-only candidate still uses the independent Python batch read helper,
  so it is suitable for first shadow logging only. It is not the final runtime
  hot-path transport and must not be used as active assist.

## Next Controlled Step

Only after explicit user approval:

```text
1. Apply robot_control_sum8_shadow_only.patch to active robot_control.
2. Run py_compile on the two touched active files.
3. Stop again before starting any SDR/ROS runtime.
```

First runtime collection, if later approved, must keep:

```text
default CPU publication
FPGA sidecar logging only
immediate CPU fallback on read/error/quality failure
no assist selection
```
