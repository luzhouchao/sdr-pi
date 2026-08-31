# P201Pro Summary V9B0 Minimal Isolation PC Artifacts

Date: 2026-06-08 Asia/Shanghai

Status: PC artifact gate PASS. Bootgen PASS. SD payload ready for SDR `/sd` staging.
Not hardware validated.

## Purpose

V9B0 is the minimal isolation experiment after V9A/SPEC9 failed AD9361/IIO health.
It removes active SPEC9 behavior from the ADC hot path and keeps the build close
to the V8 SUM/QUA/AGG footprint while using explicit V9B0 identity registers.

The diagnostic question is:

```text
Does a SUM/QUA/AGG-only rebuild allow AD9361 TX tuning and cf-ad9361-lpc registration?
```

## Artifact

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9b0_minimal_isolation
```

Candidate HDL:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9b0_minimal_isolation\hdl\p201pro_ad9361_power_tap_axi_regs.v
```

The main HDL under `E:\vivado\fpga_p201pro_accel\hdl` was not overwritten by this
candidate.

## Vivado Gate

OOC/IP package:

```text
reports\stage4_ad9361_tap_ip_v9b0\stage4_ad9361_tap_ip_report.md
synth_design Complete!
WNS +1.292 ns
WHS +0.037 ns
4761 LUT / 6358 FF / 52 DSP
```

BD integration:

```text
reports\stage4_ad9361_tap_integration_v9b0\ad9361_tap_integration_report.md
validate_bd_design PASS
AXI-Lite offset 0x43C00000
AXI-Lite range 0x00010000
```

Post-route physopt:

```text
reports\stage4_ad9361_tap_bitstream_physopt_v9b0\bitstream_physopt_report.md
phys_opt_design PASS
route_design PASS
write_bitstream PASS
WNS +0.015 ns
WHS +0.053 ns
route fully routed
routing errors 0
17933 LUT / 26187 FF / 80 DSP / 6 BRAM
```

DRC:

```text
0 errors
known warnings/advisories only: DPIP/DPOP, REQP-1577, REQP-1839, AVAL-4
```

## Bootgen And Payload

Bootgen command:

```text
E:\Xilinx\SDK\2019.1\bin\bootgen.bat -arch zynq -image p201_summary_v9b0_minimal_isolation_sd.bif -w -o BOOT_p201_summary_v9b0_minimal_isolation.bin
```

BOOT hash:

```text
0051864c24513248e78fde9bb6ced7d465b4a0c5df6cee804bbafb50d55d35e2  BOOT_p201_summary_v9b0_minimal_isolation.bin
```

Payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9b0_minimal_isolation\sd_payload
```

Files:

```text
BOOT.bin
devicetree.dtb
uEnv.txt
uImage
uramdisk.image.gz
```

Hash manifest:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9b0_minimal_isolation\HASHES.sha256
```

## Expected Registers After SDR Power-Cycle

```text
devmem 0x43C00040 32 -> 0x53394230
devmem 0x43C000EC 32 -> 0x00010002
devmem 0x43C000F0 32 -> 0x000003ff
devmem 0x43C000FC 32 -> 0x56394230
devmem 0x43C00100 32 -> 0x51394230
devmem 0x43C00138 32 -> 0x0000000f
devmem 0x43C0013C 32 -> 0x51394230
devmem 0x43C00180 32 -> 0x41394230
devmem 0x43C001F4 32 -> 0x0000001f
devmem 0x43C001F8 32 -> 0x41394230
devmem 0x43C00200 32 -> 0x00000000
devmem 0x43C002F0 32 -> 0x00000000
devmem 0x43C002F4 32 -> 0x00000000
devmem 0x43C002F8 32 -> 0x00000000
devmem 0x43C002FC 32 -> 0x00000000
```

## Safety State

V9B0 is burnable for the authorized SDR `/sd` experiment target only after route
documents are current. It must not be promoted to hardware-validated until:

```text
/sd BOOT hash matches V9B0
the SDR is physically power-cycled
cf-ad9361-lpc registers
expected V9B0 registers match
SUM/QUA/AGG validation passes
```

After-powercycle validation script:

```text
E:\vivado\fpga_p201pro_accel\scripts\validate_v9b0_minimal_isolation_after_powercycle_via_nx.py
```

V8 remains the current highest hardware-validated rollback.
