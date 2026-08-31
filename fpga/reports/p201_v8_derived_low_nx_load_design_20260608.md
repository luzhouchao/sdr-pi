# P201Pro V8-Derived Low-NX-Load Auto Aggregate Design

Status: PC-side RTL experiment only. NOT BURNABLE. NOT HARDWARE VALIDATED.

Source copied from:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\v9a_spec9_work_snapshots\p201pro_ad9361_power_tap_axi_regs.pre_v9a_continue_20260608.v
```

Experiment RTL:

```text
E:\vivado\fpga_p201pro_accel\experiments\v8_derived_low_nx_load\hdl\p201pro_ad9361_power_tap_axi_regs.v
```

No SD card, SDR `/sd`, vendor package, mainline HDL, scripts, ROS, SDR streaming runtime, mapping, RTAB-Map, robot_controller, cmd_vel, or robot motion path was touched.

## Design Goal

V8 AGG8 already reduces NX CPU work by accumulating multiple frames in FPGA, but NX still has to repeat a clear/arm/wait/read cycle for every aggregate. This experiment keeps the V8 fixed-shape summary primitive and adds a tiny rolling aggregate mode:

1. NX configures `AGG_TARGET` once.
2. NX writes `AGG_CONTROL` with enable + clear + auto mode.
3. FPGA repeatedly accumulates `AGG_TARGET` valid frames, latches the latest aggregate page, increments a sequence counter, clears the working accumulator, and continues.
4. NX can read the latest aggregate at a low rate. It no longer needs to clear/arm/poll for every aggregate window.

This is still a bypass/shadow primitive. NX still owns divide, sqrt, atan2, calibration, policy, fallback, logging, and any later publication.

## Register ABI

Retained identity and summary behavior:

```text
0x040 SUMMARY_VERSION    0x53554d38 ("SUM8")
0x0ec ABI_VERSION        0x00010002
0x0f0 CAPABILITY         0x000003ff
0x100 QUALITY_VERSION    0x51554138 ("QUA8")
0x138 QUALITY_CAP        0x0000000f
0x180 AGG_VERSION        0x41474738 ("AGG8")
```

Experimental build IDs:

```text
0x0fc BUILD_ID           0x56384c31 ("V8L1")
0x13c QUALITY_BUILD_ID   0x51384c31 ("Q8L1")
0x1f8 AGG_BUILD_ID       0x41384c31 ("A8L1")
```

New aggregate register:

```text
0x17c AGG_SEQUENCE       Read-only. Increments on each newly latched aggregate event.
                         Cleared by AGG_CONTROL bit1 or global CONTROL clear.
```

Extended aggregate control:

```text
0x184 AGG_CONTROL
  bit0  enable          Existing V8 meaning.
  bit1  clear/arm       Existing V8 write-one pulse, reads as 0.
  bit2  auto_roll       New. 0 = V8 manual done-stop mode. 1 = rolling latest-aggregate mode.
  bit3  reserved        Reads 0.
  bit4  done            Existing ready indication; in auto mode it stays high after first latched event.
  bit5  overflow        Existing overflow/bad-frame indication for the latched page.
```

Extended aggregate capability:

```text
0x1f4 AGG_CAP            0x0000003f
  bits0..4              Existing V8 AGG capabilities.
  bit5                  AGG auto-roll + AGG_SEQUENCE supported.
```

All existing AGG8 data offsets from `0x188..0x1fc` are retained. `REG_AGG_SEQUENCE` uses the previously unused gap before `AGG_VERSION`, so it does not move the existing AGG8 page.

The copied source contained SPEC9 residue and unresolved SUM8 identity references. The experiment RTL explicitly restores SUM8/QUA8/AGG8 identity constants and removes SPEC/SUM9/QUA9/AGG9 references from the experimental copy.

## NX Read Pattern

Recommended low-rate read pattern in auto mode:

```text
write 0x188 = target_frames
write 0x184 = 0x00000007   # enable + clear/arm + auto_roll

periodically:
  seq_a = read 0x17c
  read aggregate data page
  seq_b = read 0x17c
  accept if seq_a == seq_b and seq_a != previous_seq
```

If `seq_b != seq_a`, NX caught an update while reading and should reread once. If `seq_a - previous_seq > 1`, NX missed one or more aggregate windows; this is acceptable for latest-summary mode but should be counted by the client.

Manual mode remains:

```text
write 0x184 = 0x00000003   # enable + clear/arm, auto_roll=0
poll/read done, then read AGG8 page
```

## Why This Is V8-Like

This candidate does not add FFT, SPEC, BRAM, DMA, vector buffers, or a new streaming path. The existing V8 AGG8 wide accumulators and corrected numerator math are reused.

The added hardware is small:

- one AXI-visible `agg_auto` bit;
- two CDC synchronizer flops for auto mode;
- one ADC-domain 32-bit sequence counter;
- one ADC-to-AXI aggregate-update toggle and AXI synchronizer;
- one AXI-domain 32-bit sequence register;
- mux/control logic to clear the existing working accumulators after each target window in auto mode.

No new multipliers, DSP blocks, BRAMs, or per-sample spectral comparisons are added. Removing the SPEC residue from the copied file keeps this experiment closer to V8 than V9A/V9B0.

## Checks Run

Lightweight syntax check only:

```text
E:\Xilinx\Vivado\2019.1\bin\xvlog.bat E:\vivado\fpga_p201pro_accel\experiments\v8_derived_low_nx_load\hdl\p201pro_ad9361_power_tap_axi_regs.v
```

Result:

```text
PASS
INFO: [VRFC 10-2263] Analyzing Verilog file ...
INFO: [VRFC 10-311] analyzing module p201pro_ad9361_power_tap_axi_regs
```

Log directory:

```text
E:\vivado\fpga_p201pro_accel\reports\stage_v8_derived_low_nx_load\xvlog_syntax
```

Static text checks:

```text
No SPEC/spec_ references remain in the experiment RTL.
No SUM9/QUA9/AGG9 identity references remain in the experiment RTL.
```

## Suggested OOC Checks

Do not run full vendor implementation until this PC-side experiment is reviewed. Suggested next checks:

```tcl
read_verilog E:/vivado/fpga_p201pro_accel/experiments/v8_derived_low_nx_load/hdl/p201pro_ad9361_power_tap_axi_regs.v
synth_design -mode out_of_context -top p201pro_ad9361_power_tap_axi_regs -part xc7z020clg400-2
report_utilization -file E:/vivado/fpga_p201pro_accel/reports/stage_v8_derived_low_nx_load/ooc_util.rpt
report_timing_summary -file E:/vivado/fpga_p201pro_accel/reports/stage_v8_derived_low_nx_load/ooc_timing.rpt
report_cdc -file E:/vivado/fpga_p201pro_accel/reports/stage_v8_derived_low_nx_load/ooc_cdc.rpt
```

Acceptance for moving beyond OOC:

```text
no syntax errors
no critical reset/CDC blocker
WNS >= 0
WHS >= 0
resource delta plausibly near V8
AGG8 manual mode preserved by inspection or simulation
auto mode sequence increments on every target completion, including AGG_TARGET=1
```

## Risks

- V8 integrated timing margin is thin. Even a small control addition still needs OOC and later integrated timing before any burnable artifact discussion.
- The aggregate data bus still follows the V8-style latched multi-bit CDC pattern. The new update toggle improves event capture but is not a full handshake FIFO.
- Auto mode overwrites the latest aggregate page if NX reads slower than the aggregate period. `AGG_SEQUENCE` lets NX detect missed windows.
- Bad-frame/overflow events latch a page and increment `AGG_SEQUENCE`. NX should reject pages with `AGG_CONTROL[5] = 1`.
- This is not hardware validated and not active NX integration.
