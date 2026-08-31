# P201Pro V8L2 Auto-Roll Fix SDR SD Staging

Date: 2026-06-08

Status: SDR `/sd` staging PASS. Sync was run on the SDR. NOT HARDWARE
VALIDATED until physical SDR power-cycle and validation pass.

## Artifact

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8l2_auto_roll_fix
```

Staging evidence:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8l2_auto_roll_fix\stage_v8l2_auto_roll_fix_to_sdr_sd_20260608.json
```

## Result

```text
operation: stage_v8l2_auto_roll_fix_payload_via_nx
upload_method: ssh_exec_cat
remote_sd: /sd
passed: true
sync: run twice on SDR
```

Remote before:

```text
BOOT.bin bdd7e27c4cd02259cb891e06bc25cdf70f0763de55dda77d2853da660a8f24aa
```

Remote after:

```text
BOOT.bin 1f7935fb9153966eb9eb9cec9f4f1fa2364ac54e45badced0848fac4b43e5248
devicetree.dtb 960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a
uEnv.txt 2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f
uImage e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5
uramdisk.image.gz 0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55
```

## Safety

No ROS, SDR streaming runtime, robot_control, cmd_vel, mapping, RTAB-Map, or
robot motion path was started. The original Windows SD backup and vendor package
were not touched.

## Required Next Step

Stop and wait for user physical SDR power-cycle. After that, validate:

```text
/sd BOOT hash
cf-ad9361-lpc registered
AD9361/IIO health PASS
V8L2 identity registers PASS
SPEC page disabled/read-zero PASS
AGG_SEQUENCE advances continuously without re-clear/re-arm
```
