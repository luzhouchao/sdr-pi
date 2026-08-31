# P201Pro V10S4 Non-FFT Self-Test SDR SD Staging

Date: 2026-06-09 10:36 Asia/Shanghai

## Result

V10S4 non-FFT self-test payload was staged to the SDR `/sd` experiment target
through NX and SDR SSH. The staging script reported `passed: true`; all five
remote hashes matched the local payload hashes after copy, and `sync` was run
on the SDR.

This is not hardware validation. V10S4 still requires a physical SDR
power-cycle and the matching post-power-cycle validation script before it can
be described as hardware-validated.

## Artifact

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s4_nonfft_selftest
```

Payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s4_nonfft_selftest\sd_payload
```

Staging JSON:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s4_nonfft_selftest\stage_v10s4_nonfft_selftest_to_sdr_sd_20260609.json
```

## Hash Evidence

Remote before staging:

```text
BOOT.bin          3e2c59a32a6ba8b6a80fc9cfe4c4a0ec94a43051cbb1d383f99cbd596417f883
devicetree.dtb    960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a
uEnv.txt          2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f
uImage            e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5
uramdisk.image.gz 0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55
```

Remote after staging:

```text
BOOT.bin          df773e5b8b01f301634ff838f462464289213cfb4bba6c11855d022e08a377ce
devicetree.dtb    960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a
uEnv.txt          2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f
uImage            e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5
uramdisk.image.gz 0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55
```

The companion file hashes stayed on the known-good values. Only `BOOT.bin`
changed from the V8D0 layout-probe image to the V10S4 non-FFT self-test image.

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

V10S4 remains an isolated AXI-Lite deterministic self-test page at
`0x43C20000`; it does not connect AD9361 sample, valid, clock, or reset nets.

## Expected V10S4 Identity After Power-Cycle

```text
devmem 0x43C20000 32 -> 0x53345430
devmem 0x43C20018 32 -> 0x00000007
devmem 0x43C2001C 32 -> 0x56313034
devmem 0x43C20020 32 -> 0x000A4000
```

## Validation Script

After the user physically power-cycles the SDR, run:

```powershell
python E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\validate_v10s4_nonfft_selftest_after_powercycle_via_nx.py `
  --out-json E:\vivado\fpga_p201pro_accel\reports\p201_v10s4_nonfft_selftest_after_powercycle_20260609.json
```

Pass requires `/sd` hashes, AD9361/IIO health, V8D0 base registers, V10S4
identity registers, and V10S4 deterministic self-test registers to pass.

## Rollback

Rollback version remains:

```text
V8L1 first, then V8
```

Do not stage another candidate until the V10S4 post-power-cycle result is
recorded.
