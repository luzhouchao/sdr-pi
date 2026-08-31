# P201Pro Summary V4 Hardware Validation

Date: 2026-06-08

Status: PASS after physical SDR power-cycle.

## Artifact

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v4
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v4\BOOT_p201_summary_v4.bin
```

Expected version:

```text
SUMMARY_VERSION = 0x53554D34 ("SUM4")
```

## Validation Script

The validation ran only inside the independent NX experiment directory:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
```

Script:

```text
scripts/capture_summary_v4_mean_corrected.py
```

Remote evidence:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/logs/summary_v4_mean_corrected_after_reboot.json
```

Local evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\summary_v4_mean_corrected_after_reboot_20260608.json
```

## Result

V4 passed the same-frame snapshot comparison and mean-corrected dual-RX checks.

Passing checks:

```text
version_is_sum4
sample_count_match
dual_samples_match
rx0_power_match
rx1_power_match
rx0_peak_power_match
rx1_peak_power_match
rx0_peak_index_match
rx1_peak_index_match
cross_re_match
cross_im_match
i0_sum_match
q0_sum_match
i1_sum_match
q1_sum_match
mean_corrected_phase_match
mean_corrected_coherence_match
```

Representative capture:

```text
sample_count = 64
snapshot_count = 64
rx0_power_raw = 4640356
rx1_power_raw = 13904934
cross_re_raw = -3591560
cross_im_raw = -4125513
i0_sum = 457
q0_sum = 867
i1_sum = -444
q1_sum = -104
phase_mean_corrected_deg = -131.04203166141005
coherence_mean_corrected = 0.6812617194623656
```

## Interpretation

V4 is now a validated debug fallback for same-frame snapshot and NX-side mean-corrected AoA comparison. It is not the best production offload candidate because it keeps snapshot readback and does not include the V6/V7/V8 production ABI pages.

Keep V4 out of the normal active burn order unless snapshot-level debugging is needed.
