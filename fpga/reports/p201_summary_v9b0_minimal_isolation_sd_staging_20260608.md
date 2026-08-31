# P201Pro Summary V9B0 Minimal Isolation SDR SD Staging

Date: 2026-06-08 Asia/Shanghai

Status: SDR `/sd` staging PASS. Physical SDR power-cycle still required.
Not hardware validated.

## Source Payload

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9b0_minimal_isolation\sd_payload
```

Staging log:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9b0_minimal_isolation\stage_v9b0_to_sdr_sd_20260608.json
```

## Result

Staging was performed from Windows through the NX SSH jump to the SDR and copied
only the five boot files to SDR `/sd`.

```text
operation: stage_v9b0_minimal_isolation_payload_via_nx
passed: true
remote_before BOOT.bin: 6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
remote_after  BOOT.bin: 0051864c24513248e78fde9bb6ced7d465b4a0c5df6cee804bbafb50d55d35e2
devicetree/uEnv/uImage/uramdisk hashes: matched expected known-good companion files
sync: run on SDR after copy
```

Upload method:

```text
ssh_exec_cat
```

SFTP negotiation returned EOF, so the staging script used the safe SSH `cat`
fallback into a temporary SDR directory, verified temporary hashes, copied into
`/sd`, and ran `sync`.

## Safety

No ROS, SDR streaming runtime, robot_control, mapping, RTAB-Map, `cmd_vel`, or
robot motion was started. The original Windows SD backup and vendor package were
not touched.

## Next Required Step

The user must physically power-cycle the SDR before validation:

```text
1. Remove SDR power.
2. Wait a few seconds.
3. Reapply SDR power.
4. Tell the agent that physical power-cycle is complete.
```

Do not use Linux `reboot` as final proof on this board.

After power-cycle, run:

```text
E:\vivado\fpga_p201pro_accel\scripts\validate_v9b0_minimal_isolation_after_powercycle_via_nx.py
```

V8 remains the current highest hardware-validated rollback until V9B0 passes
post-power-cycle validation.
