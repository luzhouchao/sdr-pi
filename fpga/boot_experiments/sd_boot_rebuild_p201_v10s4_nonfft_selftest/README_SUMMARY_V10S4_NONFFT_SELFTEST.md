# P201Pro V10S4 Non-FFT Self-Test

Date: 2026-06-09

Status: PC build, XSIM, OOC synth, IP package, BD integration, full bitstream,
Bootgen, SD payload generation, and SDR `/sd` staging PASS. Physical SDR
power-cycle validation attempted on 2026-06-09. V10S4 self-test registers PASS,
but AD9361/IIO health FAIL. NOT HARDWARE VALIDATED.

## Purpose

V10S4 is a V8D0-based isolated reusable non-FFT submodule self-test image. It
keeps the V8D0/V8L1-style SUM8/QUA8/AGG8 tap at `0x43C00000` and adds an
independent AXI-Lite self-test page at `0x43C20000`.

Covered reusable RTL:

```text
p201_sdr_quality_stats.v
p201_v10s2_frame_window.v
p201_v10s2_hann8_coeff.v
p201_v10s3_energy_peak_reducer.v
p201_v10s4_nonfft_selftest_axi_regs.v
```

This is not live AD9361 integration, not FFT, not PSD, and not active NX
`robot_control` integration. The self-test IP uses deterministic internal
samples in the AXI clock domain. No AD9361 sample, valid, clock, or reset net
is connected to the V10S4 self-test IP.

## Artifact

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s4_nonfft_selftest
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s4_nonfft_selftest\BOOT_p201_v10s4_nonfft_selftest.bin
```

SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s4_nonfft_selftest\sd_payload
```

NX validation script:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\validate_v10s4_nonfft_selftest_after_powercycle_via_nx.py
```

## Gate Evidence

```text
V10S1 XSIM: PASS
V10S2 XSIM: PASS
V10S3 XSIM: PASS
V10S1/S2/S3 combined OOC: PASS
V10S4 AXI wrapper XSIM: PASS
V10S4 OOC synthesis: PASS
IP packaging: PASS
BD validation: PASS
integrated synthesis: PASS
write_bitstream: PASS
WNS +0.015 ns
WHS +0.009 ns
route fully routed
routing errors 0
DRC errors 0
DRC critical warnings 0
DRC advisories: AVAL-4 24, REQP-181 1
Bootgen: PASS
SD payload hashes: PASS
```

Resource snapshot after implementation:

```text
LUT: 19505
FF: 27154
DSP: 83
BRAM tile: 6
```

## Bootgen

BIF:

```text
image : {
  [bootloader] fsbl_from_pzsdr_fw.elf
  system_top_with_p201_v10s4_nonfft_selftest.bit
  u-boot_from_pzsdr_fw.elf
}
```

Command:

```powershell
& 'E:\Xilinx\SDK\2019.1\bin\bootgen.bat' -arch zynq -image 'p201_v10s4_nonfft_selftest_sd.bif' -w -o 'BOOT_p201_v10s4_nonfft_selftest.bin'
```

## Hashes

```text
5115c0e1872c61fe64b9b7ff1c0b448b5afaea2f3f538776368e815f0f393a24  fsbl_from_pzsdr_fw.elf
69b9b060dd7a3525806e98e6c93e77b2b47795993dc9069279b7beca1a4c943d  u-boot_from_pzsdr_fw.elf
e17a05818dddd4d777f63ab63fbe5167259a6f62e7393101ef0df9b6c67d7fa6  system_top_with_p201_v10s4_nonfft_selftest.bit
df773e5b8b01f301634ff838f462464289213cfb4bba6c11855d022e08a377ce  BOOT_p201_v10s4_nonfft_selftest.bin
8e2934cf6f6d2d5742760d21e262ca2b2fb048c09559f5bb7f82568df57a7ab3  p201_v10s4_nonfft_selftest_sd.bif
df773e5b8b01f301634ff838f462464289213cfb4bba6c11855d022e08a377ce  sd_payload\BOOT.bin
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
devmem 0x43C00200 32 -> 0x00000000
devmem 0x43C002F0 32 -> 0x00000000
devmem 0x43C002F4 32 -> 0x00000000
devmem 0x43C002F8 32 -> 0x00000000
devmem 0x43C002FC 32 -> 0x00000000
```

V10S4 self-test page before start:

```text
devmem 0x43C20000 32 -> 0x53345430
devmem 0x43C20018 32 -> 0x00000007
devmem 0x43C2001C 32 -> 0x56313034
devmem 0x43C20020 32 -> 0x000A4000
devmem 0x43C200E0 32 -> 0x00000007
devmem 0x43C200E4 32 -> 0x00000000
devmem 0x43C200F4 32 -> 0x00000007
devmem 0x43C200F8 32 -> 0x56313034
devmem 0x43C200FC 32 -> 0x000A4000
```

Start:

```text
devmem 0x43C20004 32 0x00000004
devmem 0x43C20004 32 0x00000003
```

Expected after done:

```text
devmem 0x43C20008 32 -> bit2 done set, bit3 fail clear
devmem 0x43C2000C 32 -> 0x00000007
devmem 0x43C20010 32 -> 0x00000000
devmem 0x43C20014 32 -> run_id increments by 1
devmem 0x43C20034 32 -> 0x00000008
devmem 0x43C20038 32 -> 0x00008374
devmem 0x43C2003C 32 -> 0xFFFF7B9C
devmem 0x43C20040 32 -> 0x400E6D8C
devmem 0x43C20044 32 -> 0x400FE730
devmem 0x43C20048 32 -> 0xBFF187E8
devmem 0x43C2004C 32 -> 0x00008000
devmem 0x43C20050 32 -> 0x00010001
devmem 0x43C20054 32 -> 0x00010001
devmem 0x43C20058 32 -> 0x00000008
devmem 0x43C2005C 32 -> 0x00000000
devmem 0x43C20074 32 -> 0x00000008
devmem 0x43C20078 32 -> 0x00000008
devmem 0x43C2007C 32 -> 0x00000000
devmem 0x43C20080 32 -> 0x00000000
devmem 0x43C20084 32 -> 0x00000001
devmem 0x43C200A0 32 -> bits masked by 0x00000117 equal 0x00000111
devmem 0x43C200A4 32 -> 0x00000001
devmem 0x43C200A8 32 -> 0x00000008
devmem 0x43C200AC 32 -> 0x00000135
devmem 0x43C200B0 32 -> 0x00000002
devmem 0x43C200B4 32 -> 0x00000064
devmem 0x43C200B8 32 -> 0x00000004
devmem 0x43C200BC 32 -> 0x0000005A
devmem 0x43C200C0 32 -> 0x00000006
devmem 0x43C200C4 32 -> 0x00000062
devmem 0x43C200C8 32 -> 0x00000003
```

Expected registers are planned post-boot checks only; they have not been read
from SDR hardware yet.

## SDR Staging Status

```text
STAGED TO SDR /sd ON 2026-06-09 10:36 Asia/Shanghai
SYNC COMPLETED BY STAGING SCRIPT
PHYSICAL SDR POWER-CYCLE COMPLETED BY USER
POST-POWER-CYCLE VALIDATION FAIL ON 2026-06-09 10:43 Asia/Shanghai
NOT HARDWARE VALIDATED
```

Earlier staging attempt on 2026-06-09 05:45 Asia/Shanghai:

```text
TCP port 22 on NX 192.168.2.193 was reachable, but SSH returned:
Connection closed by 192.168.2.193 port 22
No SDR connection was opened.
No SDR /sd files were written.
No sync was run because no write occurred.
```

Successful staging JSON:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s4_nonfft_selftest\stage_v10s4_nonfft_selftest_to_sdr_sd_20260609.json
```

Staging report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_v10s4_nonfft_selftest_sd_staging_20260609.md
```

Hardware validation JSON:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_v10s4_nonfft_selftest_after_powercycle_20260609.json
```

Hardware failure report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_v10s4_nonfft_selftest_hardware_failure_20260609.md
```

Remote before staging:

```text
BOOT.bin 3e2c59a32a6ba8b6a80fc9cfe4c4a0ec94a43051cbb1d383f99cbd596417f883
```

Remote after staging:

```text
BOOT.bin df773e5b8b01f301634ff838f462464289213cfb4bba6c11855d022e08a377ce
```

## Hardware Validation Required

After SDR `/sd` staging and `sync`, stop and wait for a physical SDR
power-cycle. The 2026-06-09 post-power-cycle validation was run:

```powershell
python nx_experiments\sdr_fpga_offload_test\scripts\validate_v10s4_nonfft_selftest_after_powercycle_via_nx.py --out-json reports\p201_v10s4_nonfft_selftest_after_powercycle_20260609.json
```

The V10S4 self-test register checks passed, but AD9361/IIO failed:

```text
/sd BOOT hash == df773e5b8b01f301634ff838f462464289213cfb4bba6c11855d022e08a377ce
V8D0 base identity registers PASS
V10S4 identity registers PASS
V10S4 deterministic self-test registers PASS
AD9361/IIO health FAIL
cf-ad9361-lpc missing
Tuning TX FAILED
cf_axi_adc probe error -5
```

Rollback order remains V8L1 first, then V8.
