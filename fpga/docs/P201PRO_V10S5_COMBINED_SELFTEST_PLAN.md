# P201Pro V10S5 Combined Self-Test Plan

Date: 2026-06-09 source-candidate snapshot

## Purpose

V10S5 is the planned isolated combined self-test candidate for the reusable SDR
FPGA helper modules. It should keep the V8D0/V8L1-style base tap at
`0x43C00000` and add a separate deterministic AXI-Lite self-test page at
`0x43C30000`.

`VERSION_ROUTE.md` remains the source of truth for whether this candidate is
built, staged, or hardware-validated.

V10S5 is not live AD9361 integration, not active NX `robot_control`
integration, not ROS integration, and not a motion-capable runtime path. The
self-test page must use deterministic internal stimuli and must not connect to
live AD9361 sample, valid, clock, or reset nets.

## Intended Tracks

V10S5 is expected to combine the V10S0 mixed reusable self-test lane and the
V10S4 non-FFT helper lane into one isolated candidate.

Planned capability bits:

```text
0x0000003F  six deterministic self-test tracks complete
bit0        FFT-family frame/packer lane
bit1        FFT-family summary lane
bit2        FFT-family auxiliary reducer lane
bit3        non-FFT quality stats lane
bit4        non-FFT frame/window lane
bit5        non-FFT energy/peak lane
```

Until a V10S5 artifact README is generated from a passed build, the NX validator
checks identity, base health, done mask, error mask, and run completion only.

## AXI-Lite Contract

Base address:

```text
0x43C30000
```

Identity registers:

```text
0x00 VERSION      0x53355430  "S5T0"
0x18 CAPABILITY   0x0000003F
0x1c BUILD_ID     0x56313035  "V105"
0x20 ABI_VERSION  0x000A5000
```

Control/status:

```text
0x04 CONTROL      bit0 enable, bit1 start, bit2 clear
0x08 STATUS       bit0 busy, bit1 irq_pending, bit2 done, bit3 fail
0x0c DONE_MASK    expected 0x0000003F after run
0x10 ERROR_MASK   expected 0x00000000 after run
0x14 RUN_ID       increments once per accepted start
```

Debug mirrors:

```text
0xe0 EXPECT_DONE_MASK  0x0000003F
0xe4 EXPECT_ERROR      0x00000000
0xf4 TEST_CAPABILITY   0x0000003F
0xf8 TEST_BUILD_ID     0x56313035
0xfc TEST_ABI_VERSION  0x000A5000
```

## Current Artifact State

Expected artifact directory after build:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s5_combined_selftest
```

Status:

```text
SOURCE AND SCRIPT CANDIDATE ONLY
SIDECORE TESTS REPORTED BY SUBAGENTS
COMBINED WRAPPER XSIM PASS
COMBINED WRAPPER OOC SYNTH PASS
OOC WNS +4.021 ns
OOC WHS +0.129 ns
NO IP PACKAGE YET
NO BD INTEGRATION YET
NO BITSTREAM YET
NO BOOT HASH YET
NO SD PAYLOAD YET
NOT STAGED
NOT HARDWARE VALIDATED
NOT BURNABLE UNTIL THE ARTIFACT GATE PASSES
```

Current source paths:

```text
E:\vivado\fpga_p201pro_accel\experiments\v10s5_combined_selftest\README.md
E:\vivado\fpga_p201pro_accel\experiments\v10s5_combined_selftest\rtl\p201_v10s5_fft_family_selftest_core.v
E:\vivado\fpga_p201pro_accel\experiments\v10s5_combined_selftest\rtl\p201_v10s5_nonfft_selftest_core.v
E:\vivado\fpga_p201pro_accel\experiments\v10s5_combined_selftest\rtl\p201_v10s5_combined_selftest_axi_regs.v
E:\vivado\fpga_p201pro_accel\experiments\v10s5_combined_selftest\test\tb_p201_v10s5_fft_family_selftest_core.v
E:\vivado\fpga_p201pro_accel\experiments\v10s5_combined_selftest\test\tb_p201_v10s5_nonfft_selftest_core.v
E:\vivado\fpga_p201pro_accel\experiments\v10s5_combined_selftest\test\tb_p201_v10s5_combined_selftest_axi_regs.v
```

Current script paths:

```text
E:\vivado\fpga_p201pro_accel\scripts\xsim_v10s5_combined_selftest.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_ooc_v10s5_combined_selftest.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_package_v10s5_combined_selftest_ip.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_integrate_v10s5_combined_selftest_v8d0_base.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_impl_bitstream_v10s5_combined_selftest_v8d0_base.tcl
E:\vivado\fpga_p201pro_accel\scripts\vivado_postroute_physopt_v10s5_combined_selftest_v8d0_base.tcl
```

Important wrapper note:

```text
The combined AXI wrapper currently defaults to deterministic internal mirrors.
The external FFT-family and non-FFT sidecar cores are not the default combined
wrapper path unless their interface is explicitly reviewed and enabled.
```

## Artifact Gate

Before any SDR `/sd` staging:

```text
deterministic RTL testbench PASS
AXI self-test wrapper XSIM PASS
OOC synth PASS
IP package PASS
BD integration PASS
full implementation PASS
WNS >= 0
WHS >= 0
route fully routed
routing errors 0
DRC errors 0
DRC critical warnings 0
Bootgen PASS
HASHES.sha256 PASS
SD payload generated
artifact README current
VERSION_ROUTE.md current
```

## Hardware Validation Gate

After SDR `/sd` staging and `sync`, stop and wait for user physical SDR
power-cycle. Do not treat a software reboot as final hardware validation.

Run:

```powershell
python E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\validate_v10s5_combined_selftest_after_powercycle_via_nx.py `
  --out-json E:\vivado\fpga_p201pro_accel\reports\p201_v10s5_combined_selftest_after_powercycle_20260610.json `
  --boot-sha256 <V10S5_BOOT_SHA256>
```

If `--boot-sha256` is omitted, the script records the placeholder BOOT hash and
must fail `sd_hashes_ok`. This prevents an un-hashed image from being reported
as validated.

Pass conditions:

```text
/sd BOOT hash PASS
/sd companion hashes PASS
AD9361/IIO health PASS
cf-ad9361-lpc present
ad9361-phy present
no Tuning TX FAILED
no cf_axi_adc probe error -5
V8D0 base registers PASS
V10S5 base 0x43C30000 responds
V10S5 version 0x53355430 PASS
V10S5 capability 0x0000003F PASS
V10S5 build 0x56313035 PASS
V10S5 ABI 0x000A5000 PASS
V10S5 done mask 0x0000003F PASS
V10S5 error mask 0x00000000 PASS
V10S5 status done bit set
V10S5 status fail bit clear
V10S5 run_id increments by 1
```

Only then may V10S5 be described as hardware-validated, and only for isolated
combined self-test.

## Safety And Rollback

Do not touch the original SD backup, vendor package, active NX runtime, ROS,
SDR streaming, `robot_control`, `cmd_vel`, or motion.

Rollback order remains:

```text
V8L1 first, then V8
```

Do not merge V10S5 into the main V8L1 tap path or connect it to live AD9361
nets until the AD9361/IIO sensitivity route in `VERSION_ROUTE.md` says it is
safe to continue.
