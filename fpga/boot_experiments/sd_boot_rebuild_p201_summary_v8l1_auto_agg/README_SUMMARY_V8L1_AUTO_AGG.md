# P201Pro Summary V8L1 Auto Aggregate Candidate

Status: PC build, post-route physopt, Bootgen, SD payload generation, SDR `/sd`
staging, physical SDR power-cycle, AD9361/IIO health, V8L1 identity registers,
and no-motion AGG auto-roll captures PASS. Hardware validated.

V8L1 is a V8-derived low-NX-load candidate. It keeps the validated SUM8/QUA8/AGG8
identity surface and adds AGG auto-roll so NX can read fewer registers across a
capture window. It does not add SPEC/FFT/BRAM/DMA.

## Source

```text
experiments/v8_derived_low_nx_load/hdl/p201pro_ad9361_power_tap_axi_regs.v
```

Boot experiment HDL snapshot:

```text
boot_experiments/sd_boot_rebuild_p201_summary_v8l1_auto_agg/hdl/p201pro_ad9361_power_tap_axi_regs.v
```

## Expected Registers

```text
0x43C00040 SUMMARY_VERSION  0x53554D38 ("SUM8")
0x43C000EC ABI_VERSION      0x00010002
0x43C000F0 CAPABILITY       0x000003ff
0x43C000FC BUILD_ID         0x56384C31 ("V8L1")
0x43C00100 QUALITY_VERSION  0x51554138 ("QUA8")
0x43C00138 QUALITY_CAP      0x0000000f
0x43C0013C QUALITY_BUILD_ID 0x51384C31 ("Q8L1")
0x43C00180 AGG_VERSION      0x41474738 ("AGG8")
0x43C001F4 AGG_CAP          0x0000003f
0x43C001F8 AGG_BUILD_ID     0x41384C31 ("A8L1")
0x43C00200 SPEC_VERSION     0x00000000
0x43C002F0 SPEC_BIN_COUNT   0x00000000
0x43C002F4 SPEC_CAP         0x00000000
0x43C002F8 SPEC_BUILD_ID    0x00000000
0x43C002FC SPEC_ABI_VERSION 0x00000000
```

## PC Artifact Gate

Summary report:

```text
reports/p201_v8l1_auto_agg_bitstream_gate_20260608.md
```

Post-route physopt:

```text
reports/stage4_ad9361_tap_bitstream_physopt_v8l1_auto_agg/bitstream_physopt_report.md
phys_opt_design: PASS
route_design: PASS
write_bitstream: PASS
WNS +0.004 ns
WHS +0.052 ns
route fully routed
routing errors 0
DRC errors 0
```

## Bootgen And SD Payload

Bootgen:

```text
E:\Xilinx\SDK\2019.1\bin\bootgen.bat -arch zynq -image p201_summary_v8l1_auto_agg_sd.bif -w -o BOOT_p201_summary_v8l1_auto_agg.bin
```

BOOT hash:

```text
bdd7e27c4cd02259cb891e06bc25cdf70f0763de55dda77d2853da660a8f24aa  BOOT_p201_summary_v8l1_auto_agg.bin
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

## Hardware Validation

```text
reports/p201_summary_v8l1_auto_agg_hardware_validation_20260608.md
reports/p201_summary_v8l1_auto_agg_after_powercycle_20260608.json
```

Result:

```text
/sd hashes: PASS
AD9361/IIO health: PASS
cf-ad9361-lpc registered
V8L1 identity registers: PASS
SPEC page disabled/read-zero: PASS
AGG auto-roll capture: 3 / 3 PASS
```

## Safety

V8L1 is the current highest hardware-validated bypass offload candidate. V8
remains the first validated rollback.
