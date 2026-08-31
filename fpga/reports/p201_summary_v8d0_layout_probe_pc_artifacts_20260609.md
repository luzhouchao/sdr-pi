# P201Pro V8D0 Layout Probe PC Artifact Summary

Date: 2026-06-09

Status: PC build, post-route physopt, Bootgen, and SD payload generation PASS.
NOT HARDWARE VALIDATED.

## Purpose

V8D0 is the first V8-derived AD9361-sensitivity probe after V8L2 failed IIO
health. It is intentionally boring: V8L1 behavior with build-ID-only HDL
changes.

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
initial integrated write_bitstream: PASS, but WNS -0.092 ns, rejected
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

## Expected Registers

```text
devmem 0x43C00040 32 -> 0x53554D38
devmem 0x43C000FC 32 -> 0x56384430
devmem 0x43C00100 32 -> 0x51554138
devmem 0x43C0013C 32 -> 0x51384430
devmem 0x43C00180 32 -> 0x41474738
devmem 0x43C001F4 32 -> 0x0000003F
devmem 0x43C001F8 32 -> 0x41384430
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

## Next Step

V8D0 can be staged to SDR `/sd` only after the local artifact gate is rechecked.
It is not hardware validated until the SDR is physically power-cycled and
AD9361/IIO plus V8D0 identity-register checks pass.
