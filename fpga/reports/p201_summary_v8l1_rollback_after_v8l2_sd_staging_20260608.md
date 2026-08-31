# P201Pro V8L1 Rollback After V8L2 SDR SD Staging

Date: 2026-06-08

Status: V8L1 rollback payload staged to SDR `/sd` and synced. Physical SDR
power-cycle is still required before rollback validation.

## Reason

V8L2 loaded and passed identity registers after physical SDR power-cycle, but
AD9361/IIO health failed with missing `cf-ad9361-lpc`, TX tuning failure, and
`cf_axi_adc` probe error `-5`. V8L2 is not hardware-validated.

## Artifact

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8l1_auto_agg
```

Staging evidence:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8l1_auto_agg\stage_v8l1_rollback_after_v8l2_to_sdr_sd_20260608.json
```

## Result

```text
operation: stage_v8l1_rollback_after_v8l2_payload_via_nx
upload_method: ssh_exec_cat
remote_sd: /sd
passed: true
sync: run twice on SDR
```

Remote before:

```text
BOOT.bin 1f7935fb9153966eb9eb9cec9f4f1fa2364ac54e45badced0848fac4b43e5248
```

Remote after:

```text
BOOT.bin bdd7e27c4cd02259cb891e06bc25cdf70f0763de55dda77d2853da660a8f24aa
devicetree.dtb 960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a
uEnv.txt 2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f
uImage e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5
uramdisk.image.gz 0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55
```

## Required Next Step

Stop and wait for user physical SDR power-cycle. Then validate V8L1:

```text
/sd BOOT hash == bdd7e27c4cd02259cb891e06bc25cdf70f0763de55dda77d2853da660a8f24aa
cf-ad9361-lpc registered
AD9361/IIO health PASS
V8L1 identity registers PASS
```
