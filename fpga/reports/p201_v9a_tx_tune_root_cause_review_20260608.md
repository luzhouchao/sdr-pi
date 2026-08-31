# P201Pro V9A TX Tune Root-Cause Review

Date: 2026-06-08 18:29 Asia/Shanghai

Status: offline diagnosis only. No SDR `/sd` staging, no reboot, no ROS/runtime/motion
commands, and no active NX runtime changes were performed in this review.

## Current Safe Baseline

V8 remains the current highest hardware-validated candidate and is active after
the post-V9A rollback power-cycle.

Evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8_after_v9a_rollback_powercycle_20260608.md
E:\vivado\fpga_p201pro_accel\reports\summary_v8_after_v9a_rollback_powercycle_20260608.json
```

V9A remains not hardware-validated.

## V9A Failure Shape

V9A passed the bypass-specific checks:

- `/sd` hashes matched the V9A payload.
- SUM9/QUA9/AGG9/SPEC9 identity registers passed.
- SPEC9 capture consistency passed 6 / 6.

The failing subsystem was AD9361/IIO ADC registration:

```text
ad9361 spi1.0: ad9361_probe : AD936x Rev 0 successfully initialized
cf_axi_dds 79024000.cf-ad9361-dds-core-lpc: ... probed DDS AD9361
SAMPL CLK: 61440000 tuning: TX
ad9361 spi1.0: ad9361_dig_tune_delay: Tuning TX FAILED!
cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
```

This narrows the fault: SPI/DTB/basic AD9361 probe and DDS registration are not
the first failing point. The failure happens during TX digital tuning before
`cf-ad9361-lpc` registers.

## What Was Checked Offline

Generated read-only Vivado DCP diagnostics:

```text
E:\vivado\fpga_p201pro_accel\scripts\vivado_report_v9a_ad9361_interface_diagnostics.tcl
E:\vivado\fpga_p201pro_accel\reports\v9a_ad9361_interface_diagnostics_20260608
```

The script opened only:

```text
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream_physopt\system_top_with_p201_tap_physopt_impl.dcp
```

It did not synthesize, implement, write bitstream, or touch hardware.

## Findings

1. The BD integration does not explicitly drive AD9361 TX/DAC data/control.

The tap connects to:

```text
/axi_ad9361/l_clk       -> p201_tap0 adc_clk
/axi_ad9361/rst         -> p201_tap0 adc_rst
/axi_ad9361/adc_data_*  -> p201_tap0 sample inputs
/axi_ad9361/adc_valid_* -> p201_tap0 valid inputs
/axi_cpu_interconnect/M10_AXI -> p201_tap0 s_axi
p201_tap0 irq -> /sys_concat_intc/In0
```

There is no deliberate TX/DAC data-path replacement in the V9A integration.

2. The companion boot files are unlikely to be the root cause.

Live diagnosis showed V9A used the expected companion DTB/uEnv/uImage/uramdisk
hashes and the final LVDS-bias DTB settings. Rolling only BOOT back to V8 with
the same companion files restored `cf-ad9361-lpc` after physical power-cycle.

3. V9A is timing-clean globally, but AD9361 board-level interface timing remains
not fully constrained.

V9A implemented timing:

```text
WNS +0.015 ns
WHS +0.061 ns
rx_clk WNS +0.170 ns
clk_fpga_0 WNS +0.488 ns
route fully routed
routing errors 0
```

The same timing report still shows:

```text
7 input ports with no input delay specified
10 ports with no output delay specified
1 register/latch pin with multiple clocks
```

This means Vivado closure does not prove external AD9361 LVDS setup/hold margin.
V8 working under the same broad constraint style means this is not sufficient by
itself, but it makes implementation perturbation a credible failure mechanism.

4. V9A added a large side-band IP footprint.

V9A DCP diagnostic summary:

```text
p201_tap0 cells: 16983
p201_tap0 utilization: 6784 LUT, 7817 FF, 52 DSP48
axi_ad9361 utilization: 7460 LUT, 11740 FF, 28 DSP48
```

V8 total resource snapshot:

```text
Slice LUTs       17877
Slice Registers  26120
DSPs                80
```

V9A total resource snapshot:

```text
Slice LUTs       19935
Slice Registers  27646
DSPs                80
```

V9A increased total design logic by about 2058 LUT and 1526 FF versus V8, while
the tap itself is now roughly comparable in LUT count to the ADI `axi_ad9361`
core. Even without explicit TX connections, this can alter placement/routing and
clock/reset/data fanout around the AD9361 interface.

5. V9A has several high-fanout tap nets.

Top tap-related examples:

```text
summary_same_i_sign_count_axi[15]_i_1_n_0 fanout 2359
summary_sample_count_axi0                 fanout 2049
spec_peak_bin_stage_adc                   fanout 1352
agg_latched_last_frame_adc                fanout 864
agg_latched_frame_count_adc[31]_i_2_n_0   fanout 834
```

These are not direct TX nets, but they are evidence that the V9A register/readback
and post-frame logic are wide enough to disturb implementation quality.

6. The `clk_fpga_0` critical path is inside the p201 tap AXI readback mux.

Worst `clk_fpga_0` path:

```text
Source:      axi_cpu_interconnect ... m_amesg_i_reg[10]
Destination: p201_tap0/inst/s_axi_rdata_reg[5]
Slack:       +0.488 ns
Data delay:  9.337 ns, route 7.306 ns
```

The route-heavy AXI read mux is not the AD9361 TX tune path, but it confirms the
tap page is now big enough to create long routed paths and consume placement
freedom.

7. There is no global routing congestion or DRC blocker.

The new diagnostics show:

```text
route fully routed
routing errors 0
congestion report: no congested windows listed
DRC: 0 errors, 0 critical warnings, 121 warnings/advisories
```

DRC warnings are still relevant to future cleanup:

```text
p201_tap0 DSP input/output/multiplier pipelining warnings
ADI dac/adc FIFO RAMB36 async-control warnings
```

They are not a direct proof of the TX tuning failure.

## Assessment

The strongest current hypothesis is implementation-side AD9361 interface
sensitivity caused by the V9A tap footprint and routing/fanout growth, not a
wrong companion DTB or an explicit TX-path wiring mistake.

Evidence strength:

- Strong: V8 with the same companion files restores `cf-ad9361-lpc`.
- Strong: V9A fails at TX digital tuning while AD9361 base probe and DDS still
  register.
- Strong: V9A integrates the tap as a passive ADC-side monitor plus AXI/IRQ; it
  does not intentionally replace TX/DAC logic.
- Medium: V9A adds enough tap logic and fanout to perturb placement/routing.
- Medium: AD9361 external I/O timing is not proven by board-level input/output
  delay constraints.
- Not proven: the exact physical net or placement region that breaks TX tuning.

## Recommended Next Step

Do not restage V9A as-is.

Use V8 as the operational hardware-validated baseline, then create an isolation
candidate before any V10/V11 spectral expansion:

```text
V9B0: V8-compatible rebuild / minimal tap-change isolation
```

Purpose:

```text
Prove whether a fresh PC rebuild and current integration flow still lets AD9361/IIO register
before adding SPEC9-sized logic again.
```

Design constraints for V9B0:

- Preserve V8-style SUM/QUA/AGG behavior.
- Disable/remove the SPEC9 page.
- Keep the artifact uniquely named; do not call it hardware-validated until the
  normal copy, physical power-cycle, register, IIO, and validation gates pass.
- Keep V8 rollback first.
- Add targeted Vivado reports from this review to the artifact README.

If V9B0 passes IIO health, then build a second isolation candidate:

```text
V9B1: SPEC9 reintroduced with reduced register mux fanout and stronger pipelining/floorplan hygiene
```

Potential V9B1 cleanup:

- Split or pipeline the AXI read mux for the `0x200..0x2fc` page.
- Register high-fanout SPEC/AGG status signals before AXI-domain readback.
- Keep SPEC post-frame compare/abs logic out of the sample-accept path.
- Consider a conservative pblock or placement constraint to keep `p201_tap0`
  away from AD9361 LVDS/TX interface-critical resources.
- Add an explicit AD9361 I/O timing review rather than relying only on global WNS/WHS.

If V9B0 fails, the problem is likely the rebuild/integration/placement flow rather
than SPEC9 specifically; stop and compare against the hardware-validated V8
artifact before adding features.
