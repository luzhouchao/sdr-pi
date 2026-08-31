# P201Pro V8L1 Auto Aggregate SDR SD Staging

Date: 2026-06-08

Status: PASS. V8L1 SD payload was written to SDR `/sd` through NX SSH jump and
`sync` was run. Physical SDR power-cycle is now required before hardware
validation.

## Hashes

Remote before staging:

```text
BOOT.bin  6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
```

Remote after staging:

```text
BOOT.bin          bdd7e27c4cd02259cb891e06bc25cdf70f0763de55dda77d2853da660a8f24aa
devicetree.dtb   960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a
uEnv.txt         2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f
uImage           e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5
uramdisk.image.gz 0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55
```

Staging JSON:

```text
boot_experiments/sd_boot_rebuild_p201_summary_v8l1_auto_agg/stage_v8l1_auto_agg_to_sdr_sd_20260608.json
```

## Safety

The staging script did not reboot the SDR and did not start ROS, SDR streaming
runtime, mapping, RTAB-Map, robot_controller, cmd_vel, or any robot motion chain.
