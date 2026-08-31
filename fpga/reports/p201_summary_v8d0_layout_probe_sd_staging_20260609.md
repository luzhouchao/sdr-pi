# P201Pro V8D0 Layout Probe SDR SD Staging

Date: 2026-06-09 10:28 Asia/Shanghai

## Result

V8D0 layout probe payload was staged to the SDR `/sd` experiment target through
NX and SDR SSH. The staging script reported `passed: true`; all five remote
hashes matched the local payload hashes after copy, and `sync` was run on the
SDR.

This is not hardware validation. V8D0 still requires a physical SDR power-cycle
and the matching post-power-cycle validation script before it can be described
as hardware-tested.

## Artifact

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8d0_layout_probe
```

Payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8d0_layout_probe\sd_payload
```

Staging JSON:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8d0_layout_probe\stage_v8d0_layout_probe_to_sdr_sd_20260609.json
```

## Hash Evidence

Remote before staging:

```text
BOOT.bin          bdd7e27c4cd02259cb891e06bc25cdf70f0763de55dda77d2853da660a8f24aa
devicetree.dtb    960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a
uEnv.txt          2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f
uImage            e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5
uramdisk.image.gz 0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55
```

Remote after staging:

```text
BOOT.bin          3e2c59a32a6ba8b6a80fc9cfe4c4a0ec94a43051cbb1d383f99cbd596417f883
devicetree.dtb    960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a
uEnv.txt          2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f
uImage            e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5
uramdisk.image.gz 0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55
```

The companion file hashes stayed on the known-good values. Only `BOOT.bin`
changed from the V8L1 rollback image to the V8D0 layout-probe image.

## Safety

The staging script recorded:

```text
no ROS
no SDR streaming runtime
no robot_control
no cmd_vel or motion
no original Windows SD backup touch
no vendor package touch
requires physical power-cycle after staging
```

## Expected V8D0 Registers After Power-Cycle

```text
devmem 0x43C00040 32 -> 0x53554D38
devmem 0x43C000FC 32 -> 0x56384430
devmem 0x43C00100 32 -> 0x51554138
devmem 0x43C0013C 32 -> 0x51384430
devmem 0x43C00180 32 -> 0x41474738
devmem 0x43C001F4 32 -> 0x0000003F
devmem 0x43C001F8 32 -> 0x41384430
```

SPEC page should remain disabled/read-zero:

```text
devmem 0x43C00200 32 -> 0x00000000
devmem 0x43C002F0 32 -> 0x00000000
devmem 0x43C002F4 32 -> 0x00000000
devmem 0x43C002F8 32 -> 0x00000000
devmem 0x43C002FC 32 -> 0x00000000
```

## Validation Script

After the user physically power-cycles the SDR, run:

```powershell
python E:\vivado\fpga_p201pro_accel\scripts\validate_v8d0_layout_probe_after_powercycle_via_nx.py `
  --out-json E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8d0_layout_probe_after_powercycle_20260609.json
```

Pass requires `/sd` hashes, AD9361/IIO health, V8D0 identity registers, SPEC
read-zero checks, and AGG8 no-motion validation to pass.

## Rollback

Rollback version remains:

```text
V8L1 first, then V8
```

Do not stage another candidate until the V8D0 post-power-cycle result is
recorded.
