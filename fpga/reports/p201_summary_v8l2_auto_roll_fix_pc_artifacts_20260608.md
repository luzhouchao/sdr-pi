# P201Pro V8L2 Auto-Roll Fix PC Artifact Summary

Date: 2026-06-08

Status: PC build, post-route physopt, Bootgen, and SD payload generation PASS.
NOT HARDWARE VALIDATED.

## Purpose

V8L2 fixes the V8L1 continuous auto-roll stall. V8L1 hardware validation showed
AD9361/IIO health and initial auto aggregate capture were healthy, but the
latest-window benchmark found `AGG_SEQUENCE` stopped at `1`. V8L2 changes the
ADC-domain pending condition so auto mode keeps accepting samples after each
target window.

## Artifact

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8l2_auto_roll_fix
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8l2_auto_roll_fix\BOOT_p201_summary_v8l2_auto_roll_fix.bin
```

SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8l2_auto_roll_fix\sd_payload
```

## Gate Evidence

```text
IP packaging: PASS
BD validation: PASS
integrated synthesis: PASS
post-route phys_opt_design: PASS
route_design: PASS
write_bitstream: PASS
WNS +0.015 ns
WHS +0.053 ns
route fully routed
routing errors 0
DRC errors 0
DRC critical warnings 0
Bootgen: PASS
```

## Hashes

```text
5115c0e1872c61fe64b9b7ff1c0b448b5afaea2f3f538776368e815f0f393a24  fsbl_from_pzsdr_fw.elf
69b9b060dd7a3525806e98e6c93e77b2b47795993dc9069279b7beca1a4c943d  u-boot_from_pzsdr_fw.elf
87805373c852e0a2932045c6180d8bb3595d95970054a39395f79ca24a97027a  system_top_with_p201_v8l2_auto_roll_fix.bit
1f7935fb9153966eb9eb9cec9f4f1fa2364ac54e45badced0848fac4b43e5248  BOOT_p201_summary_v8l2_auto_roll_fix.bin
1f7935fb9153966eb9eb9cec9f4f1fa2364ac54e45badced0848fac4b43e5248  sd_payload\BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  sd_payload\devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  sd_payload\uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  sd_payload\uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  sd_payload\uramdisk.image.gz
```

## Expected Hardware Registers

```text
devmem 0x43C00040 32 -> 0x53554D38
devmem 0x43C000FC 32 -> 0x56384C32
devmem 0x43C00100 32 -> 0x51554138
devmem 0x43C0013C 32 -> 0x51384C32
devmem 0x43C00180 32 -> 0x41474738
devmem 0x43C001F4 32 -> 0x0000003F
devmem 0x43C001F8 32 -> 0x41384C32
```

## Next Step

After gated SDR `/sd` staging and `sync`, stop and wait for a physical SDR
power-cycle. Then validate `/sd/BOOT.bin` hash, AD9361/IIO health, V8L2 identity
registers, SPEC page read-zero, and continuous `AGG_SEQUENCE` advancement.
