# P201Pro Summary V8L2 Auto-Roll Fix Candidate

Status: PC build, post-route physopt, Bootgen, and SD payload generation PASS.
NOT HARDWARE VALIDATED until SDR `/sd` staging, physical SDR power-cycle,
AD9361/IIO health, V8L2 identity registers, and continuous AGG auto-roll
validation pass.

V8L2 is a V8L1-derived continuity fix. It keeps the validated SUM8/QUA8/AGG8
surface and fixes the V8L1 auto-roll stall where `AGG_SEQUENCE` advanced once
and then stopped. It does not add SPEC, FFT, BRAM, DMA, ROS, streaming runtime,
or robot-control integration.

## Source

```text
experiments/v8_derived_low_nx_load/hdl/p201pro_ad9361_power_tap_axi_regs.v
```

Boot experiment HDL snapshot:

```text
boot_experiments/sd_boot_rebuild_p201_summary_v8l2_auto_roll_fix/hdl/p201pro_ad9361_power_tap_axi_regs.v
```

## Expected Registers

```text
0x43C00040 SUMMARY_VERSION  0x53554D38 ("SUM8")
0x43C000EC ABI_VERSION      0x00010002
0x43C000F0 CAPABILITY       0x000003ff
0x43C000FC BUILD_ID         0x56384C32 ("V8L2")
0x43C00100 QUALITY_VERSION  0x51554138 ("QUA8")
0x43C00138 QUALITY_CAP      0x0000000f
0x43C0013C QUALITY_BUILD_ID 0x51384C32 ("Q8L2")
0x43C00180 AGG_VERSION      0x41474738 ("AGG8")
0x43C001F4 AGG_CAP          0x0000003f
0x43C001F8 AGG_BUILD_ID     0x41384C32 ("A8L2")
0x43C00200 SPEC_VERSION     0x00000000
0x43C002F0 SPEC_BIN_COUNT   0x00000000
0x43C002F4 SPEC_CAP         0x00000000
0x43C002F8 SPEC_BUILD_ID    0x00000000
0x43C002FC SPEC_ABI_VERSION 0x00000000
```

## PC Artifact Gate

Vivado reports:

```text
reports/stage4_ad9361_tap_ip_v8l2_auto_roll_fix/stage4_ad9361_tap_ip_report.md
reports/stage4_ad9361_tap_integration_v8l2_auto_roll_fix/ad9361_tap_integration_report.md
reports/stage4_ad9361_tap_integrated_synth_v8l2_auto_roll_fix/integrated_synth_report.md
reports/stage4_ad9361_tap_bitstream_physopt_v8l2_auto_roll_fix/bitstream_physopt_report.md
```

Final post-route physopt result:

```text
IP packaging: PASS
BD validation: PASS
integrated synthesis: PASS
phys_opt_design: PASS
route_design: PASS
write_bitstream: PASS
WNS +0.015 ns
WHS +0.053 ns
route fully routed
routing errors 0
DRC errors 0; DRC critical warnings 0; warning/advisory classes remain
```

## Bootgen And SD Payload

Bootgen:

```text
E:\Xilinx\SDK\2019.1\bin\bootgen.bat -arch zynq -image p201_summary_v8l2_auto_roll_fix_sd.bif -w -o BOOT_p201_summary_v8l2_auto_roll_fix.bin
```

BOOT hash:

```text
1f7935fb9153966eb9eb9cec9f4f1fa2364ac54e45badced0848fac4b43e5248  BOOT_p201_summary_v8l2_auto_roll_fix.bin
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

## Validation Script

Use after SDR `/sd` staging and physical SDR power-cycle:

```text
nx_experiments/sdr_fpga_offload_test/scripts/benchmark_v8l1_auto_roll_batch_ssh.py
```

The script already accepts V8L2 build IDs and checks that `AGG_SEQUENCE`
continues advancing without re-clearing/re-arming every window.

## Safety

Rollback:

```text
V8L1 first
V8 second
```

V8L2 is burnable only after the local artifact gate is current. It is still NOT
HARDWARE VALIDATED until the user physically power-cycles the SDR and validation
passes.
