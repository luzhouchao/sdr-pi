# P201 V8L1 Auto Aggregate PC Gate Progress

Generated: 2026-06-08

## Scope

V8L1 is the V8-derived AGG8 auto-roll low-NX-load candidate. These gates are PC-side only.

No BOOT.bin, SD payload, SDR `/sd` write, ROS, SDR streaming runtime, active NX runtime, or robot-motion path was used.

## Gate Results So Far

### OOC RTL Gate

```text
PASS
WNS +0.908 ns
WHS +0.157 ns
LUT 5340
FF 6313
DSP 52
BRAM 0
```

Evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_v8_derived_low_nx_load_ooc_20260608.md
```

### IP Packaging Gate

```text
PASS
IP packaging PASS
synth_design Complete!
WNS +0.810 ns
WHS +0.037 ns
LUT 5340
FF 6313
DSP 52
BRAM 0
```

Evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_ip_v8l1_auto_agg\stage4_ad9361_tap_ip_report.md
```

### BD Integration Gate

```text
PASS
validate_bd_design PASS
AXI-Lite offset 0x43C00000
AXI-Lite range  0x00010000
```

Evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_integration_v8l1_auto_agg\ad9361_tap_integration_report.md
```

### Integrated Synthesis Gate

```text
SYNTHESIS PASS
synth_design Complete!
WNS +0.069 ns
WHS -0.101 ns
LUT 21289
FF 28014
DSP 89
BRAM 6
```

Evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_integrated_synth_v8l1_auto_agg\integrated_synth_report.md
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_integrated_synth_v8l1_auto_agg\timing_summary.txt
```

## Decision

Continue to implementation/route/bitstream gate because synthesis completes and setup remains positive, but do not treat V8L1 as artifact-gated yet. The integrated synthesis hold result is negative and must be resolved by implementation, route, or post-route phys_opt before any Bootgen or SD staging discussion.

## Next Gate

Run implementation through bitstream and check:

```text
write_bitstream Complete!
WNS >= 0
WHS >= 0
route fully routed
routing errors 0
DRC has no blocking errors
```
