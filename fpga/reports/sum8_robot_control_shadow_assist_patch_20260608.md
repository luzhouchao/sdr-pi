# SUM8 Robot Control Shadow/Assist Patch Staging

Date: 2026-06-08

## Result

PASS as a staged, off-by-default integration patch. The active NX `robot_control`
package was not modified.

The patch is prepared for the existing AoA backend abstraction:

```text
robot_control/sdr_aoa_backend.py
robot_control/sdr_dual_aoa_localizer.py
```

Patch file:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\staged_robot_control_integration\robot_control_sum8_shadow_assist.patch
```

NX staged location:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/staged_robot_control_integration/robot_control_sum8_shadow_assist.patch
```

## Behavior

Existing behavior remains unchanged for:

```text
aoa_backend=auto
aoa_backend=cpu
aoa_backend=numpy
```

New backend modes in the staged patch:

```text
aoa_backend=fpga_sum8_shadow
```

Returns the original CPU/GPU AoA result, but also reads SUM8/AGG8 and exposes
`fpga_last` in the backend status for shadow logging.

```text
aoa_backend=fpga_sum8_assist
```

Returns the FPGA AGG8 primitive result only when the FPGA read succeeds and
quality gates pass. Otherwise it falls back to the original CPU/GPU AoA result.

## Performance Review

Decision: GO for staged patch and dry-run; do not apply to active package until
the user explicitly approves.

Reason:

- The patch uses the existing `AoaBackend` abstraction instead of spreading FPGA
  logic through the localizer.
- Default behavior is unchanged.
- `shadow` mode can collect FPGA evidence beside the current result.
- `assist` mode has CPU/GPU fallback and rejects clipped/failed FPGA estimates.
- It still uses the batch AGG8 script, so it is suitable for first runtime
  shadow collection but not the final low-latency transport.

## Verification

Candidate files compiled locally and on NX:

```text
sdr_aoa_backend.py
sdr_dual_aoa_localizer.py
```

Patch dry-run against the active NX package:

```text
cd /home/wheeltec/ros2_ws/src/robot_control
patch -p0 --dry-run < sdr_fpga_offload_test/staged_robot_control_integration/robot_control_sum8_shadow_assist.patch
```

Result:

```text
checking file robot_control/sdr_aoa_backend.py
checking file robot_control/sdr_dual_aoa_localizer.py
```

No active package file was changed.

## Next Step

When approved, apply the patch and compile only:

```bash
cd /home/wheeltec/ros2_ws/src/robot_control
patch -p0 < sdr_fpga_offload_test/staged_robot_control_integration/robot_control_sum8_shadow_assist.patch
python3 -m py_compile robot_control/sdr_aoa_backend.py robot_control/sdr_dual_aoa_localizer.py
```

Do not start runtime automatically. After that, the first runtime test should use:

```text
aoa_backend=fpga_sum8_shadow
```

Only after shadow logs are stable should `fpga_sum8_assist` be tested.
