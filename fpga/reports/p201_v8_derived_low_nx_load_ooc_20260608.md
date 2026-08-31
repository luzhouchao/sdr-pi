# P201 V8-Derived Low-NX-Load OOC Result

Generated: 2026-06-08

## Scope

PC-side OOC synthesis/timing only for the V8-derived AGG8 auto-roll experiment.

This is not a burnable artifact, not a BOOT/SD payload, and not hardware validated. No SDR `/sd`, ROS, SDR streaming runtime, active NX runtime, or robot-motion path was touched.

## Input

RTL:

```text
E:\vivado\fpga_p201pro_accel\experiments\v8_derived_low_nx_load\hdl\p201pro_ad9361_power_tap_axi_regs.v
```

Tcl:

```text
E:\vivado\fpga_p201pro_accel\scripts\vivado_ooc_v8_derived_low_nx_load.tcl
```

## Result

OOC synthesis:

```text
PASS
0 errors
0 critical warnings
```

Timing at 8.138 ns clocks:

```text
Overall WNS +0.908 ns
Overall WHS +0.157 ns
TNS 0.000 ns
THS 0.000 ns
Failing setup endpoints 0
Failing hold endpoints 0
```

Per clock:

```text
adc_clk    WNS +0.908 ns, WHS +0.157 ns
s_axi_aclk WNS +4.123 ns, WHS +0.157 ns
```

Utilization:

```text
Slice LUTs      5340
Slice Registers 6313
DSP48E1         52
Block RAM Tile  0
```

CDC:

```text
s_axi_aclk -> adc_clk: 37 endpoints, 37 safe, 0 unsafe, 0 unknown
adc_clk -> s_axi_aclk: 1884 endpoints, 1884 safe, 0 unsafe, 0 unknown
```

## Evidence

```text
E:\vivado\fpga_p201pro_accel\reports\stage_v8_derived_low_nx_load\ooc_synth\ooc_summary.md
E:\vivado\fpga_p201pro_accel\reports\stage_v8_derived_low_nx_load\ooc_synth\ooc_timing_summary.txt
E:\vivado\fpga_p201pro_accel\reports\stage_v8_derived_low_nx_load\ooc_synth\ooc_utilization.txt
E:\vivado\fpga_p201pro_accel\reports\stage_v8_derived_low_nx_load\ooc_synth\ooc_cdc.txt
E:\vivado\fpga_p201pro_accel\reports\stage_v8_derived_low_nx_load\ooc_synth\ooc_check_timing.txt
```

## Decision

The V8-derived AGG8 auto-roll experiment passes the first OOC gate and remains the recommended next hardware-changing candidate.

Do not write SDR `/sd` yet. The next gate should be integrated Vivado packaging/synthesis/implementation using this experiment RTL in a versioned artifact path. Only after integrated timing, route status, bitstream, Bootgen, and SD payload evidence pass should SDR staging be considered.

## Risks

- V8 integrated timing margin is historically thin, so OOC margin does not guarantee routed timing.
- The OOC CDC report is useful but does not replace full integrated CDC/timing in the real block design.
- Auto mode overwrites the latest aggregate page; NX must use `AGG_SEQUENCE` to detect skipped windows.
