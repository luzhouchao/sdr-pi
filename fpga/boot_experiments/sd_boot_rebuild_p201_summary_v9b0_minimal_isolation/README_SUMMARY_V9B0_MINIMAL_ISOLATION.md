# P201Pro Summary V9B0 Minimal Isolation Candidate

Status: PC build, post-route physopt, Bootgen, SD payload generation, and SDR
`/sd` staging PASS. Physical SDR power-cycle validation is pending. Not hardware
validated.

V9B0 is a diagnostic branch after V9A SPEC9 failed AD9361/IIO health. It is meant
to answer one question: can a SUM/QUA/AGG-only rebuild, with SPEC9 disabled, boot
and allow `cf-ad9361-lpc` to register?

## Source

Candidate HDL:

```text
boot_experiments/sd_boot_rebuild_p201_summary_v9b0_minimal_isolation/hdl/p201pro_ad9361_power_tap_axi_regs.v
```

The top-level production HDL in `hdl/` is not overwritten by this candidate.

## Expected Registers

```text
0x43C00040 SUMMARY_VERSION  0x53394230 ("S9B0")
0x43C000EC ABI_VERSION      0x00010002
0x43C000F0 CAPABILITY       0x000003ff
0x43C000FC BUILD_ID         0x56394230
0x43C00100 QUALITY_VERSION  0x51394230 ("Q9B0")
0x43C00138 QUALITY_CAP      0x0000000f
0x43C0013C QUALITY_BUILD_ID 0x51394230
0x43C00180 AGG_VERSION      0x41394230 ("A9B0")
0x43C001F4 AGG_CAP          0x0000001f
0x43C001F8 AGG_BUILD_ID     0x41394230
0x43C00200 SPEC_VERSION     0x00000000
0x43C002F0 SPEC_BIN_COUNT   0x00000000
0x43C002F4 SPEC_CAP         0x00000000
0x43C002F8 SPEC_BUILD_ID    0x00000000
0x43C002FC SPEC_ABI_VERSION 0x00000000
```

## Build Scripts

```text
scripts/vivado_package_ad9361_power_tap_ip_v9b0.tcl
scripts/vivado_integrate_ad9361_power_tap_v9b0.tcl
scripts/vivado_synth_integrated_ad9361_tap_project_v9b0.tcl
scripts/vivado_impl_bitstream_integrated_ad9361_tap_project_v9b0.tcl
scripts/vivado_postroute_physopt_integrated_ad9361_tap_project_v9b0.tcl
```

V9B0 report directories use `_v9b0` suffixes.

## PC Artifact Gate

OOC/IP synth:

```text
reports/stage4_ad9361_tap_ip_v9b0/stage4_ad9361_tap_ip_report.md
Synthesis status: synth_design Complete!
WNS +1.292 ns
WHS +0.037 ns
IP utilization: 4761 LUT / 6358 FF / 52 DSP
```

Post-route physopt:

```text
reports/stage4_ad9361_tap_bitstream_physopt_v9b0/bitstream_physopt_report.md
phys_opt_design: PASS
route_design: PASS
write_bitstream: PASS
WNS +0.015 ns
WHS +0.053 ns
route fully routed
routing errors 0
implemented utilization: 17933 LUT / 26187 FF / 80 DSP
```

DRC has 0 errors and only known vendor/tap pipelining warnings/advisories:
DPIP/DPOP, REQP-1577, REQP-1839, and AVAL-4.

## Bootgen And SD Payload

Bootgen:

```text
E:\Xilinx\SDK\2019.1\bin\bootgen.bat -arch zynq -image p201_summary_v9b0_minimal_isolation_sd.bif -w -o BOOT_p201_summary_v9b0_minimal_isolation.bin
```

BOOT hash:

```text
0051864c24513248e78fde9bb6ced7d465b4a0c5df6cee804bbafb50d55d35e2  BOOT_p201_summary_v9b0_minimal_isolation.bin
```

SD payload:

```text
sd_payload/BOOT.bin
sd_payload/devicetree.dtb
sd_payload/uEnv.txt
sd_payload/uImage
sd_payload/uramdisk.image.gz
```

Hash list:

```text
HASHES.sha256
```

SDR `/sd` staging log:

```text
stage_v9b0_to_sdr_sd_20260608.json
```

Staging result:

```text
remote_before BOOT.bin: 6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
remote_after  BOOT.bin: 0051864c24513248e78fde9bb6ced7d465b4a0c5df6cee804bbafb50d55d35e2
sync was run on SDR
```

## After-Powercycle Validation Script

```text
scripts/validate_v9b0_minimal_isolation_after_powercycle_via_nx.py
```

This script checks SDR `/sd` hashes, Linux uptime, AD9361/IIO registration,
known V9A TX tuning failure strings, and the V9B0 identity/read-zero registers.
It does not start ROS, SDR streaming runtime, robot_control, mapping, RTAB-Map,
`cmd_vel`, or robot motion.

## Safety

Historical note: V8 remained the highest hardware-validated candidate and active
rollback at this artifact stage. Current state is in `VERSION_ROUTE.md`.
Do not restage V9A as-is. V9B0 must not be promoted to hardware validated until
it is staged to SDR `/sd`, the SDR is physically power-cycled, expected registers
are read, AD9361/IIO health passes, and the validation scripts pass.
