# V9A SPEC9 Execution Log

Date: 2026-06-08

## Inputs

Roadmap copied into workspace:

```text
E:\vivado\fpga_p201pro_accel\docs\P201Pro_NX_FFT_Roadmap_V9A_to_V12_Codex.md
```

Copied roadmap SHA256:

```text
5671AF3B26E73C20A1DFF78DC443A603E27131A5C5AFA394A80427F8273BDFD4
```

Base candidate:

```text
V8 / SUM8 + QUA8 + AGG8
```

V8 BOOT hash:

```text
6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
```

V8 timing:

```text
WNS +0.011 ns
WHS +0.053 ns
```

Target:

```text
V9A / SPEC9 coarse spectral proxy, not full FFT
```

Rollback:

```text
V8 -> V7 -> V6 -> V4
```

## Snapshot Note

The workspace is not a git repository, so the roadmap's `git status`, `git diff`, and `git branch` snapshot commands cannot run here.

Manual WIP HDL snapshot was created instead:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\v9a_spec9_work_snapshots\p201pro_ad9361_power_tap_axi_regs.pre_v9a_continue_20260608.v
```

Snapshot SHA256:

```text
CCBF9056FB237870CEA419748500928F70C6DF0B02AEAF30FA8B56BAF8953DC9
```

## Execution Boundary

Current execution scope:

```text
Do V9A now.
Do not implement V10 until V9A passes.
Do not modify active NX robot_control.
Do not start ROS, SDR streaming runtime, mapping, RTAB-Map, robot_controller, cmd_vel, or motion-related paths.
```

## Bounded Performance Review

Decision:

```text
V9A SPEC9 summary-only coarse spectral proxy: GO for PC build.
V9A FFT/window/PSD/DMA/BRAM vector transport: NO-GO.
V10/V11/V12 work: defer until V9A build and hardware validation gates pass.
```

Reasoning:

- The FPGA/NX split remains correct: FPGA adds fixed-shape, low-rate spectral summary primitives; NX keeps division, sqrt, atan2, calibration, policy, fallback, logging, and later publication.
- SPEC9 is a reusable kernel page, not a rigid end-to-end AoA replacement. It is suitable for gating and quality classification only.
- The V8 timing margin is thin, so V9A must avoid multipliers in the new spectral path and must not add FFT IP, DMA, full-vector BRAM readback, or wide AXI-Lite spectrum windows.
- The 4-bin proxy uses add/sub/rotation signs on RX0 I/Q only, then exposes saturated 32-bit summary registers at `0x200..0x2fc`.
- Wide compare/abs/prominence logic should stay out of the ADC sample-accept hot path and should be evaluated during post-frame handling.
- Existing SUM/QUA/AGG register behavior must remain compatible except for documented SUM9/QUA9/AGG9 identity registers.
- V8 remains the first rollback candidate if V9A timing, Bootgen, register identity, or SPEC9 reference comparison fails.

Risk notes:

- The current monolithic tap already has little slack. If V9A timing fails, stop and preserve V8 rather than expanding to V10.
- SPEC9 is not FFT or calibrated PSD; all reports and validation scripts must keep that wording precise.

## PC Build Result After Post-Route PhysOpt

Updated: 2026-06-08 17:18 Asia/Shanghai

Result:

```text
V9A SPEC9 PC build: PASS
Timing: PASS
Route: PASS
Bootgen: PASS
SD payload: staged to SDR /sd and synced
Hardware validation: PARTIAL PASS / IIO HEALTH FAIL
```

Key Vivado evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream_physopt\timing_summary_impl.txt
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream_physopt\route_status_impl.txt
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream_physopt\drc_impl.txt
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream_physopt\bitstream_physopt_report.md
```

Timing:

```text
WNS +0.015 ns
TNS 0.000 ns
failing setup endpoints 0
WHS +0.061 ns
THS 0.000 ns
failing hold endpoints 0
clk_fpga_0 WNS +0.488 ns
rx_clk WNS +0.170 ns
```

Route/DRC:

```text
route fully routed
routing errors 0
DRC 0 Errors
DRC 0 Critical Warnings
DRC warnings/advisories remain: 121
```

Artifact:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9\BOOT_p201_summary_v9a_spec9.bin
```

SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9\sd_payload
```

Hashes:

```text
58de598eea686e857a5cbb82135fea6fca2c0c79904b65af5f1b4b5f5f259447  BOOT_p201_summary_v9a_spec9.bin
1929b3d70ffacb40dd5c6489f1c5db83e6d0ef2e071a47d03eb9da7accc19542  system_top_with_p201_summary_v9a_spec9.bit
```

Reference selftest:

```text
python nx_experiments\sdr_fpga_offload_test\scripts\compare_spec9_reference.py
SPEC9 reference selftest: 6 / 6 PASS
```

Evidence:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9\spec9_reference_selftest_20260608.json
```

Stop point:

```text
Do not claim V9A hardware validation yet.
Do not copy V9A to the original SD backup.
Do not overwrite any original BOOT.bin.
Do not start ROS, SDR streaming runtime, mapping, RTAB-Map, robot_controller, cmd_vel, or motion paths.
Next hardware validation requires physical SDR power-cycle by the user.
```

## SDR `/sd` Staging

Updated: 2026-06-08 17:34 Asia/Shanghai

Staging script:

```text
E:\vivado\fpga_p201pro_accel\scripts\stage_v9a_spec9_payload_via_nx.py
```

Evidence:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9\stage_v9a_to_sdr_sd_20260608.json
```

Result:

```text
passed: true
upload_method: ssh_exec_cat
SFTP unavailable on SDR: SSHException('EOF during negotiation')
remote_before_hashes: V8 BOOT 6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
remote_after_hashes:  V9A BOOT 58de598eea686e857a5cbb82135fea6fca2c0c79904b65af5f1b4b5f5f259447
devicetree/uEnv/uImage/uramdisk hashes matched local payload
sync was run on SDR after copy
```

Current stop point:

```text
V9A is staged on SDR /sd.
User physically power-cycled SDR.
After power-cycle, /sd hash and SUM9/QUA9/AGG9/SPEC9 register validation passed.
SPEC9 capture validation passed.
AD9361/IIO health failed, so V9A is not hardware-validated.
```

## Hardware Validation Attempt After Physical Power-Cycle

Updated: 2026-06-08 17:47 Asia/Shanghai

Evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9a_spec9_hardware_validation_20260608.md
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9a_spec9_hardware_validation_20260608.json
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9a_spec9_iio_failure_diagnostics_20260608.json
```

Result:

```text
/sd hashes: PASS
physical power-cycle evidence: PASS, SDR uptime 464.15 seconds at validation
SUM9/QUA9/AGG9/SPEC9 identity registers: PASS
SPEC9 capture consistency: 6 / 6 PASS
tap debug: DEBUG_VALID increasing, DEBUG_ACCEPT 0x00000042
AD9361/IIO health: FAIL
cf-ad9361-lpc missing
dmesg: SAMPL CLK: 61440000 tuning: TX
dmesg: ad9361_dig_tune_delay: Tuning TX FAILED!
dmesg: cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
overall V9A hardware validation: FAIL / incomplete
```

Decision:

```text
Do not promote V9A.
At this point in the historical log, V8 remained the highest hardware-validated
candidate. Use VERSION_ROUTE.md for the current highest validated baseline.
Continue only with AD9361/IIO diagnosis or restore V8 if a known-good validated state is needed.
```

## Live IIO Diagnosis And V8 Rollback Staging

Updated: 2026-06-08 18:04 Asia/Shanghai

Evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9a_spec9_iio_diagnosis_and_v8_rollback_20260608.md
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v9a_spec9_iio_diagnosis_and_v8_rollback_20260608.json
```

Read-only live diagnosis while V9A was still staged/running reconfirmed:

```text
/sd/BOOT.bin = V9A hash 58de598eea686e857a5cbb82135fea6fca2c0c79904b65af5f1b4b5f5f259447
runtime DTB = validated LVDS-bias DTB hash 960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a
SUM9/QUA9/AGG9/SPEC9 registers alive
cf-ad9361-lpc missing
dmesg still shows Tuning TX FAILED and cf_axi_adc probe error -5
```

The V8 rollback payload was then staged to SDR `/sd` and `sync` was run:

```text
remote_before_hashes: V9A BOOT 58de598eea686e857a5cbb82135fea6fca2c0c79904b65af5f1b4b5f5f259447
remote_after_hashes:  V8 BOOT 6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
devicetree/uEnv/uImage/uramdisk hashes remained the known-good companion hashes
copy: PASS
remote hash check: PASS
sync: PASS
```

Current stop point:

```text
V8 was staged on SDR /sd for the next boot.
The user physically power-cycled SDR.
V8 rollback validation passed: /sd BOOT hash matched V8, cf-ad9361-lpc registered, SUM8/QUA8/AGG8 registers matched, and AGG8 validation passed 5 / 5 captures.
```

## Offline TX Tune Root-Cause Review

Updated: 2026-06-08 18:29 Asia/Shanghai

Evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_v9a_tx_tune_root_cause_review_20260608.md
E:\vivado\fpga_p201pro_accel\reports\p201_v9a_tx_tune_root_cause_review_20260608.json
E:\vivado\fpga_p201pro_accel\scripts\vivado_report_v9a_ad9361_interface_diagnostics.tcl
E:\vivado\fpga_p201pro_accel\reports\v9a_ad9361_interface_diagnostics_20260608
```

Result:

```text
No hardware was touched.
The V9A DCP was opened read-only for IO, timing, clock, DRC, utilization, high-fanout, and congestion reports.
The tap does not explicitly drive AD9361 TX/DAC data/control.
The same companion boot files work again after V8 rollback, so companion DTB/uEnv/uImage/uramdisk are unlikely as root cause.
V9A is timing-clean globally, but AD9361 LVDS board-level IO delay coverage remains incomplete.
p201_tap0 footprint is large: 16983 cells, 6784 LUT, 7817 FF, 52 DSP48.
High-fanout tap nets include summary_same_i_sign_count_axi fanout 2359, summary_sample_count_axi0 fanout 2049, and spec_peak_bin_stage_adc fanout 1352.
Strongest current hypothesis: implementation-side AD9361 interface sensitivity from V9A tap footprint/routing/fanout growth.
```

Decision:

```text
Do not restage V9A as-is.
Keep V8 as active hardware-validated baseline.
Recommended next hardware-changing diagnosis is V9B0: a V8-compatible minimal isolation candidate before SPEC9-sized logic is reintroduced.
```
