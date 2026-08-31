# P201Pro Summary V1 FPGA Build

Date: 2026-06-07 17:50 Asia/Shanghai

## Scope

This build adds a versioned frame-level summary register mirror to the existing
P201Pro AD9361 tap. It does not change NX runtime code and was not copied to SD.

## HDL Change

File:

```text
E:\vivado\fpga_p201pro_accel\hdl\p201pro_ad9361_power_tap_axi_regs.v
```

Changes:

- `AXIL_ADDR_WIDTH` changed from 6 to 8.
- Existing legacy registers at `0x00..0x3c` remain compatible.
- New summary mirror registers added at `0x40..0x5c`.

New summary map:

```text
0x43C00040 SUMMARY_VERSION  0x53554d31 ("SUM1")
0x43C00044 SUMMARY_FLAGS    same bit layout as DEBUG_FLAGS
0x43C00048 FRAME_COUNTER
0x43C0004c SAMPLE_COUNT
0x43C00050 SUM_POWER_LO
0x43C00054 SUM_POWER_HI
0x43C00058 PEAK_POWER
0x43C0005c PEAK_INDEX
```

The current frame engine still captures one frame after clear/enable and then
holds `pending` until software clears control bit 1. With default frame length
64, this is useful for deterministic side-by-side validation.

## Vivado Validation

IP package/synthesis:

```text
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_ip\stage4_ad9361_tap_ip_report.md
```

Result:

```text
ipx::check_integrity PASS
synth_design Complete!
```

BD integration:

```text
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_integration\ad9361_tap_integration_report.md
```

Result:

```text
validate_bd_design PASS
AXI-Lite offset 0x43C00000
AXI-Lite range 0x00010000
```

Bitstream:

```text
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream\system_top_with_p201_tap.bit
```

Result:

```text
write_bitstream Complete!
WNS +0.015 ns
WHS +0.059 ns
Route status fully routed
Routing errors 0
```

Hashes:

```text
f51c8d88cd59de7ab0ef48ab7e627ef52945989cfc919e4aa7cac4278ee01f6a  system_top_with_p201_tap.bit
4964e48d233f096c3f49e68f1d1f7595316c29508f3bc548be4f8ee36c663541  system_top_with_p201_tap.hwdef
```

## Boot Experiment

Experiment directory:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v1
```

BIF:

```text
image : {
  [bootloader] fsbl_from_pzsdr_fw.elf
  system_top_with_p201_summary_v1.bit
  u-boot_from_pzsdr_fw.elf
}
```

Bootgen command:

```text
E:\Xilinx\SDK\2019.1\bin\bootgen.bat -arch zynq -image p201_summary_v1_sd.bif -w -o BOOT_p201_summary_v1.bin
```

Result:

```text
bootgen exit code 0
BOOT_p201_summary_v1.bin exists
BOOT_p201_summary_v1.bin size 4,565,732 bytes
```

Hashes:

```text
5f550533c3441b309e62488bd5d3ffeaafec222825305a90bb9973fa4e614b6e  BOOT_p201_summary_v1.bin
f51c8d88cd59de7ab0ef48ab7e627ef52945989cfc919e4aa7cac4278ee01f6a  system_top_with_p201_summary_v1.bit
5115c0e1872c61fe64b9b7ff1c0b448b5afaea2f3f538776368e815f0f393a24  fsbl_from_pzsdr_fw.elf
69b9b060dd7a3525806e98e6c93e77b2b47795993dc9069279b7beca1a4c943d  u-boot_from_pzsdr_fw.elf
```

## Status

This is an experiment build only. It has not been promoted to:

```text
E:\vivado\fpga_p201pro_accel\deliverables\p201pro_2t2r_sd_ready
```

It has not been copied to SD and has not been hardware boot validated.

## Next Hardware Validation

If the user chooses to test this experiment on a copied/new SD card, copy only
the boot experiment `BOOT_p201_summary_v1.bin` as `BOOT.bin` together with the
already validated final boot companions:

```text
devicetree.dtb
uEnv.txt
uImage
uramdisk.image.gz
```

After physical power-cycle, read:

```text
devmem 0x43C00040 32
devmem 0x43C00044 32
devmem 0x43C00048 32
devmem 0x43C0004c 32
devmem 0x43C00050 32
devmem 0x43C00054 32
devmem 0x43C00058 32
devmem 0x43C0005c 32
```

Expected first check:

```text
0x43C00040 == 0x53554d31
```
