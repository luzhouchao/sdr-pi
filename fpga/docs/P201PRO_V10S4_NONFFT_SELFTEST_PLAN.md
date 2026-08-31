# P201Pro V10S4 Non-FFT Self-Test Plan And Artifact

Date: 2026-06-09 artifact snapshot

## Purpose

V10S4 is the combined self-test image for reusable non-FFT SDR FPGA helpers.
It was built after the V10S1, V10S2, and V10S3 RTL modules passed
deterministic PC testbenches.

V10S4 is not a live AD9361 integration. It should use deterministic internal
samples and an isolated AXI-Lite page, following the V10S0 pattern.

## Included Tracks

```text
V10S1 quality stats:
  count, sums, energy ingredients, cross term, peaks, clipping/drop counters

V10S2 frame/window:
  decimation gate, frame counter, valid/last generation, optional windowing

V10S3 energy/peak:
  total, min/noise proxy, peak, second peak, prominence, threshold count
```

## Why This Is Separate From V10S0

V10S0 already proves a mixed reusable module self-test flow, but it includes
FFT-adjacent blocks. V10S4 is intentionally non-FFT so the board test can
separate three questions:

```text
1. Does a fresh V8L1-like implementation still keep AD9361/IIO healthy?  -> V8D0
2. Does an isolated mixed submodule page disturb AD9361/IIO?              -> V10S0
3. Does an isolated non-FFT helper page disturb AD9361/IIO?              -> V10S4
```

## AXI-Lite Contract

Base address:

```text
0x43C20000
```

Identity registers:

```text
0x00 VERSION      0x53345430  "S4T0"
0x18 CAPABILITY   0x00000007  quality, frame/window, energy/peak
0x1c BUILD_ID     0x56313034  "V104"
0x20 ABI_VERSION  0x000a4000
```

Control/status:

```text
0x04 CONTROL      bit0 enable, bit1 start, bit2 clear
0x08 STATUS       bit0 busy, bit1 irq_pending, bit2 done, bit3 fail
0x0c DONE_MASK    bit0 quality, bit1 frame/window, bit2 energy/peak
0x10 ERROR_MASK   same bit positions
0x14 RUN_ID
```

Result pages:

```text
0x30..0x6f quality stats
0x70..0x9f frame/window stats
0xa0..0xdf energy/peak stats
0xe0..0xef expected/done debug
0xf4..0xfc capability/build/ABI mirror
```

The exact deterministic result values are documented in:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s4_nonfft_selftest\README_SUMMARY_V10S4_NONFFT_SELFTEST.md
```

## Current Artifact

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_v10s4_nonfft_selftest
```

Status:

```text
V10S1/V10S2/V10S3 XSIM PASS
combined V10S1/S2/S3 OOC PASS
V10S4 XSIM PASS
V10S4 OOC synth PASS
IP package PASS
BD integration PASS
full bitstream PASS
Bootgen PASS
SD payload generated
STAGED TO SDR /sd ON 2026-06-09 10:36 Asia/Shanghai
POST-POWER-CYCLE SELF-TEST REGISTERS PASS
POST-POWER-CYCLE AD9361/IIO FAIL
NOT HARDWARE VALIDATED
```

BOOT hash:

```text
df773e5b8b01f301634ff838f462464289213cfb4bba6c11855d022e08a377ce
```

## Artifact Gate

Before any SDR `/sd` staging:

```text
standalone RTL testbench PASS
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
```

## Hardware Validation Gate

After SDR `/sd` staging and `sync`, stop and wait for user physical SDR
power-cycle. After power-cycle:

```text
/sd BOOT hash PASS
cf-ad9361-lpc registered
no Tuning TX FAILED
no cf_axi_adc probe error -5
V8D0/V8L1-style base registers PASS
V10S4 identity registers PASS
V10S4 deterministic self-test PASS
```

Only then may V10S4 be described as hardware-validated, and only for isolated
non-FFT submodule self-test.

## Integration Rule

Do not merge V10S4 into the main V8L1 tap path or connect it to live AD9361
sample/valid/clock/reset nets until V8D0 and V10S0 hardware results show that
the board tolerates this style of isolated implementation change.
