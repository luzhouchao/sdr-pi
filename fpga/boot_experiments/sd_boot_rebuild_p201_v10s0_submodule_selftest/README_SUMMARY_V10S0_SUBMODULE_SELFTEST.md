# P201Pro V10S0 Submodule Self-Test

Date: 2026-06-09

Status: PC build, XSIM, OOC synth, IP package, BD integration, full bitstream,
Bootgen, SD payload generation, SDR `/sd` staging, physical SDR power-cycle,
AD9361/IIO health, V8D0 base registers, V10S0 identity registers, and V10S0
deterministic self-test registers PASS. Hardware-validated as an isolated
self-test only on 2026-06-09.

## Purpose

V10S0 is a V8D0-based isolated reusable submodule self-test image. It keeps the
V8D0/V8L1-style SUM8/QUA8/AGG8 tap at `0x43C00000` and adds an independent
AXI-Lite self-test page at `0x43C10000`.

Covered reusable RTL:

```text
p201_fft_frame_packer.v
p201_v10_fft_bin_power.v
p201_v10_fft_summary_reducer.v
p201_v10_fft_stream_summary_top.v
p201_bandpower_reducer.v
p201_v10_multilag_corr_module.v
p201_v10s0_submodule_selftest_axi_regs.v
```

This is not live AD9361 FFT/PSD integration. The self-test IP uses deterministic
internal samples in the AXI clock domain. No AD9361 sample, valid, clock, or
reset net is connected to the V10S0 self-test IP.

## Artifact

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s0_submodule_selftest
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s0_submodule_selftest\BOOT_p201_v10s0_submodule_selftest.bin
```

SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s0_submodule_selftest\sd_payload
```

## Gate Evidence

```text
XSIM: PASS
OOC synthesis: PASS
IP packaging: PASS
BD validation: PASS
integrated synthesis: PASS
write_bitstream: PASS
WNS +0.015 ns
WHS +0.033 ns
route fully routed
routing errors 0
DRC errors 0
DRC critical warnings 0
DRC warnings/advisories 189
Bootgen: PASS
SD payload hashes: PASS
```

DRC warning/advisory classes:

```text
DPIP-1 48
DPOP-1 30
DPOP-2 60
DPREG-4 6
REQP-1577 1
REQP-1839 19
AVAL-4 24
REQP-181 1
```

These are not accepted as hardware evidence. They are a sign that future
production FFT/correlation integration should pipeline DSP-heavy logic before
being merged into the AD9361 hot path.

## Hashes

```text
5115c0e1872c61fe64b9b7ff1c0b448b5afaea2f3f538776368e815f0f393a24  fsbl_from_pzsdr_fw.elf
69b9b060dd7a3525806e98e6c93e77b2b47795993dc9069279b7beca1a4c943d  u-boot_from_pzsdr_fw.elf
cc05059f050bb8563c90fb2f460c9ad1df3718ec38d38099a0e206780aa3e189  system_top_with_p201_v10s0_submodule_selftest.bit
83ff655ff8cba879b2c37568cc99399ad3c3deecadaf56f5961c664aed61be1b  BOOT_p201_v10s0_submodule_selftest.bin
d1cdd7a1160b5bee0964f98d1afc266224365b6b3af2b368fb289366f32bd13f  p201_v10s0_submodule_selftest_sd.bif
83ff655ff8cba879b2c37568cc99399ad3c3deecadaf56f5961c664aed61be1b  sd_payload\BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  sd_payload\devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  sd_payload\uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  sd_payload\uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  sd_payload\uramdisk.image.gz
```

## Expected Registers

V8D0 base page:

```text
devmem 0x43C00040 32 -> 0x53554D38
devmem 0x43C000FC 32 -> 0x56384430
devmem 0x43C00100 32 -> 0x51554138
devmem 0x43C0013C 32 -> 0x51384430
devmem 0x43C00180 32 -> 0x41474738
devmem 0x43C001F4 32 -> 0x0000003F
devmem 0x43C001F8 32 -> 0x41384430
```

V10S0 self-test page before start:

```text
devmem 0x43C10000 32 -> 0x53305430
devmem 0x43C10018 32 -> 0x0000000F
devmem 0x43C1001C 32 -> 0x56313053
devmem 0x43C10020 32 -> 0x000A2000
```

Start:

```text
devmem 0x43C10004 32 0x00000004
devmem 0x43C10004 32 0x00000003
```

Expected after done:

```text
devmem 0x43C10008 32 -> done bit set, fail bit clear
devmem 0x43C1000C 32 -> 0x0000000F
devmem 0x43C10010 32 -> 0x00000000
devmem 0x43C10014 32 -> 0x00000001
devmem 0x43C10034 32 -> 256
devmem 0x43C10054 32 -> 256
devmem 0x43C10058 32 -> 5
devmem 0x43C1005C 32 -> 4096
devmem 0x43C10060 32 -> 6385
devmem 0x43C10064 32 -> 0x00211105
devmem 0x43C10074 32 -> 256
devmem 0x43C10078 32 -> 0x002AC864
devmem 0x43C1007C 32 -> 56622
devmem 0x43C10080 32 -> 12062
devmem 0x43C10084 32 -> 12126
devmem 0x43C10088 32 -> 13186
devmem 0x43C1008C 32 -> 19248
devmem 0x43C100A4 32 -> 0x003D0040
devmem 0x43C100A8 32 -> 155328
devmem 0x43C100AC 32 -> 552128
devmem 0x43C100C4 32 -> 513681
```

## SDR Staging Status

Successful staging on 2026-06-09 10:48 Asia/Shanghai:

```text
STAGED TO SDR /sd
SYNC COMPLETED BY STAGING SCRIPT
PHYSICAL SDR POWER-CYCLE COMPLETED BY USER
POST-POWER-CYCLE VALIDATION PASS ON 2026-06-09 10:52 Asia/Shanghai
HARDWARE-VALIDATED AS ISOLATED SELF-TEST ONLY
```

Staging JSON:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s0_submodule_selftest\stage_v10s0_submodule_selftest_to_sdr_sd_20260609.json
```

Staging report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_v10s0_submodule_selftest_sd_staging_20260609.md
```

Hardware validation JSON:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_v10s0_submodule_selftest_after_powercycle_20260609.json
```

Hardware validation report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_v10s0_submodule_selftest_hardware_validation_20260609.md
```

Remote before staging:

```text
BOOT.bin df773e5b8b01f301634ff838f462464289213cfb4bba6c11855d022e08a377ce
```

Remote after staging:

```text
BOOT.bin 83ff655ff8cba879b2c37568cc99399ad3c3deecadaf56f5961c664aed61be1b
```

## Hardware Validation Required

After SDR `/sd` staging and `sync`, stop and wait for a physical SDR
power-cycle. The 2026-06-09 post-power-cycle validation passed:

```text
python nx_experiments\sdr_fpga_offload_test\scripts\validate_v10s0_submodule_selftest_after_powercycle_via_nx.py --boot-sha256 83ff655ff8cba879b2c37568cc99399ad3c3deecadaf56f5961c664aed61be1b --out-json reports\p201_v10s0_submodule_selftest_after_powercycle_20260609.json
```

V10S0 passed all of these checks:

```text
/sd BOOT hash == 83ff655ff8cba879b2c37568cc99399ad3c3deecadaf56f5961c664aed61be1b
cf-ad9361-lpc registered
AD9361/IIO health PASS
V8D0 base identity registers PASS
V10S0 self-test registers PASS
```

Rollback order remains V8L1 first, then V8.
