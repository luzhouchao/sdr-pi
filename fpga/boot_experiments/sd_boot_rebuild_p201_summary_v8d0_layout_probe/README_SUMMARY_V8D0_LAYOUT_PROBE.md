# P201Pro V8D0 Layout Probe

Date: 2026-06-09

Status: PC build, post-route physopt, Bootgen, SD payload generation, SDR
`/sd` staging, physical SDR power-cycle, AD9361/IIO health, V8D0 identity
registers, SPEC read-zero checks, and AGG8 no-motion validation PASS.
Hardware-validated as a diagnostic layout probe on 2026-06-09.

## Purpose

V8D0 is a V8L1-derived diagnostic image. It keeps V8L1 SUM8/QUA8/AGG8 behavior
and changes only the build IDs. The goal is to test whether a fresh
implementation/layout of V8L1-like logic is enough to reproduce the AD9361 TX
tuning / `cf-ad9361-lpc` failure seen on V9A, V9B0, and V8L2.

## Artifact

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8d0_layout_probe
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8d0_layout_probe\BOOT_p201_summary_v8d0_layout_probe.bin
```

SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8d0_layout_probe\sd_payload
```

## Gate Evidence

```text
IP packaging: PASS
BD validation: PASS
integrated synthesis: PASS
initial write_bitstream: PASS but WNS -0.092 ns, not accepted
post-route phys_opt_design: PASS
route_design: PASS
post-physopt write_bitstream: PASS
post-physopt WNS +0.012 ns
post-physopt WHS +0.053 ns
route fully routed
routing errors 0
DRC errors 0
DRC critical warnings 0
Bootgen: PASS
```

Resource snapshot after post-route physopt:

```text
LUT: 18367
FF: 26142
DSP: 80
BRAM: 6
```

## Hashes

```text
5115c0e1872c61fe64b9b7ff1c0b448b5afaea2f3f538776368e815f0f393a24  fsbl_from_pzsdr_fw.elf
69b9b060dd7a3525806e98e6c93e77b2b47795993dc9069279b7beca1a4c943d  u-boot_from_pzsdr_fw.elf
34d43221e3b02393bce22125ccd81c726581f1b945c723b176c605e7470a3580  system_top_with_p201_v8d0_layout_probe.bit
3e2c59a32a6ba8b6a80fc9cfe4c4a0ec94a43051cbb1d383f99cbd596417f883  BOOT_p201_summary_v8d0_layout_probe.bin
04b18b70eb3b4fe80248439fce79346dbbe3d9fc2094b465dad17b4f6cc276cb  p201_summary_v8d0_layout_probe_sd.bif
3e2c59a32a6ba8b6a80fc9cfe4c4a0ec94a43051cbb1d383f99cbd596417f883  sd_payload\BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  sd_payload\devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  sd_payload\uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  sd_payload\uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  sd_payload\uramdisk.image.gz
```

## Expected Hardware Registers

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

## SDR `/sd` Staging

Status:

```text
STAGED TO SDR /sd ON 2026-06-09 10:27 Asia/Shanghai
SYNC COMPLETED BY STAGING SCRIPT
PHYSICAL SDR POWER-CYCLE COMPLETED BY USER
POST-POWER-CYCLE VALIDATION PASS ON 2026-06-09 10:32 Asia/Shanghai
HARDWARE-VALIDATED AS DIAGNOSTIC LAYOUT PROBE ONLY
```

Staging JSON:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8d0_layout_probe\stage_v8d0_layout_probe_to_sdr_sd_20260609.json
```

Staging report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8d0_layout_probe_sd_staging_20260609.md
```

Hardware validation JSON:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8d0_layout_probe_after_powercycle_20260609.json
```

Hardware validation report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8d0_layout_probe_hardware_validation_20260609.md
```

Remote before staging:

```text
BOOT.bin bdd7e27c4cd02259cb891e06bc25cdf70f0763de55dda77d2853da660a8f24aa
```

Remote after staging:

```text
BOOT.bin 3e2c59a32a6ba8b6a80fc9cfe4c4a0ec94a43051cbb1d383f99cbd596417f883
```

## Hardware Validation Required

After gated SDR `/sd` staging and `sync`, stop and wait for a physical SDR
power-cycle. The 2026-06-09 post-power-cycle validation passed:

```text
/sd BOOT hash == 3e2c59a32a6ba8b6a80fc9cfe4c4a0ec94a43051cbb1d383f99cbd596417f883
cf-ad9361-lpc registered
AD9361/IIO health PASS
V8D0 identity registers PASS
SPEC page read-zero PASS
AGG8 no-motion validation PASS
```

Validation script:

```powershell
python E:\vivado\fpga_p201pro_accel\scripts\validate_v8d0_layout_probe_after_powercycle_via_nx.py `
  --out-json E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8d0_layout_probe_after_powercycle_20260609.json
```

Interpretation:

```text
If V8D0 fails AD9361/IIO, fresh implementation/layout churn alone is likely enough to break the AD9361 path.
If V8D0 passes AD9361/IIO, proceed to V8D1 incremental auto-roll fix or a carefully isolated FFT integration plan.
```
