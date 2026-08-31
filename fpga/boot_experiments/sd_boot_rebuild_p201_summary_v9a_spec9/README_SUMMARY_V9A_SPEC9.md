# P201Pro Summary V9A SPEC9 Candidate

Status: PC-built, timing-clean, Bootgen PASS, SD payload staged to SDR `/sd`.

Hardware validation: PARTIAL PASS / IIO HEALTH FAIL. NOT HARDWARE VALIDATED.

Burn policy: already staged to SDR `/sd` experiment target. Do not copy to the original SD backup.

Historical note: at this artifact stage, V8 remained the highest
hardware-validated candidate. Current rollback order is in `VERSION_ROUTE.md`.
Rollback order at that point:

```text
V8 -> V7 -> V6 -> V4
```

## Purpose

V9A adds `SPEC9`, a four-bin fixed coarse spectral proxy page, while preserving the existing SUM/QUA/AGG summary flow.

SPEC9 is not FFT, not PSD, not calibrated spectrum, and not a replacement for active NX SDR/robot_control. It is a summary-only primitive for later bypass/shadow quality classification and gating experiments.

## Performance Decision

V9A SPEC9 summary-only coarse spectral proxy: GO for PC build.

V9A FFT/window/PSD/DMA/BRAM vector transport: NO-GO.

The FPGA/NX split remains:

```text
FPGA: fixed-shape SUM9/QUA9/AGG9/SPEC9 primitives and low-rate summary registers.
NX: register orchestration, divide/sqrt/atan2, calibration, fallback, logging, algorithm composition, and publication.
```

The final timing-clean build used post-route `phys_opt_design -directive AggressiveExplore` plus `route_design -directive Explore`. This fixed the remaining `clk_fpga_0` reset/AXI-side negative slack without adding Bootgen or SD side effects during the optimization step.

## Artifact Paths

Artifact directory:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9
```

BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9\BOOT_p201_summary_v9a_spec9.bin
```

Ready-to-copy SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9\sd_payload
```

SDR `/sd` staging evidence:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9\stage_v9a_to_sdr_sd_20260608.json
```

Staging result:

```text
remote_before_hashes: V8 BOOT 6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
remote_after_hashes:  V9A BOOT 58de598eea686e857a5cbb82135fea6fca2c0c79904b65af5f1b4b5f5f259447
all five /sd files matched local V9A payload hashes
sync was run on SDR
```

Bitstream:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9\system_top_with_p201_summary_v9a_spec9.bit
```

PhysOpt evidence:

```text
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream_physopt\timing_summary_impl.txt
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream_physopt\route_status_impl.txt
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream_physopt\drc_impl.txt
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream_physopt\bitstream_physopt_report.md
```

## Register Contract

Existing summary identities move to V9A-compatible metadata:

```text
0x040 SUMMARY_VERSION    0x53554D39 ("SUM9")
0x0ec ABI_VERSION        0x00010003
0x0f0 CAPABILITY_BITMAP  0x000007FF
0x0fc BUILD_ID           0x56390001
0x100 QUALITY_VERSION    0x51554139 ("QUA9")
0x180 AGG_VERSION        0x41474739 ("AGG9")
```

New SPEC9 page:

```text
0x200 SPEC_VERSION       0x53504339 ("SPC9")
0x204 SPEC_FLAGS
0x208 SPEC_FRAME_ID
0x20c SPEC_SAMPLES
0x210 SPEC_PEAK_BIN
0x214 SPEC_PEAK_POWER
0x218 SPEC_TOTAL_POWER
0x21c SPEC_NOISE_FLOOR
0x220 SPEC_PROMINENCE
0x224 SPEC_BIN0_POWER
0x228 SPEC_BIN1_POWER
0x22c SPEC_BIN2_POWER
0x230 SPEC_BIN3_POWER
0x234 SPEC_LIMIT_FLAGS
0x238 SPEC_RX_MASK
0x23c SPEC_RESERVED0
0x2f0 SPEC_BIN_COUNT     4
0x2f4 SPEC_CAP           0x0000000F
0x2f8 SPEC_BUILD_ID      0x53390001
0x2fc SPEC_ABI_VERSION   0x00010003
```

## Vivado Status

```text
IP packaging: PASS
BD validation: PASS
write_bitstream Complete!
phys_opt_design: PASS
route_design: PASS
WNS +0.015 ns
TNS 0.000 ns
failing setup endpoints 0
WHS +0.061 ns
THS 0.000 ns
failing hold endpoints 0
route fully routed
routing errors 0
```

Clock group highlights:

```text
clk_fpga_0 WNS +0.488 ns, WHS +0.069 ns
rx_clk     WNS +0.170 ns, WHS +0.061 ns
```

DRC:

```text
Design State: Fully Routed
Violations found: 121
Error count: 0
Critical warning count: 0
```

Known DRC warning classes:

```text
DPIP-1 input pipelining warnings
DPOP-1/DPOP-2 DSP output pipelining warnings
REQP-1577 clock output buffering warning
REQP-1839 RAMB36 async control warnings in ADI/vendor FIFO paths
AVAL-4 and REQP-181 advisories
```

These are not treated as V9A acceptance blockers because the final bitstream has positive setup/hold timing, route errors are zero, and Vivado bitgen reported 0 Critical Warnings and 0 Errors. Keep them on the risk list for future V10 isolation work.

## Bootgen

BIF:

```text
image : {
  [bootloader] fsbl_from_pzsdr_fw.elf
  system_top_with_p201_summary_v9a_spec9.bit
  u-boot_from_pzsdr_fw.elf
}
```

Command:

```powershell
& 'E:\Xilinx\SDK\2019.1\bin\bootgen.bat' -arch zynq -image 'p201_summary_v9a_spec9_sd.bif' -w -o 'BOOT_p201_summary_v9a_spec9.bin'
```

Bootgen status: PASS.

## Hashes

```text
58de598eea686e857a5cbb82135fea6fca2c0c79904b65af5f1b4b5f5f259447  BOOT_p201_summary_v9a_spec9.bin
1929b3d70ffacb40dd5c6489f1c5db83e6d0ef2e071a47d03eb9da7accc19542  system_top_with_p201_summary_v9a_spec9.bit
5115c0e1872c61fe64b9b7ff1c0b448b5afaea2f3f538776368e815f0f393a24  fsbl_from_pzsdr_fw.elf
69b9b060dd7a3525806e98e6c93e77b2b47795993dc9069279b7beca1a4c943d  u-boot_from_pzsdr_fw.elf
803e775dc73eb6e445c8da3bb31671bac3755016779af47b889148073c0ab9ed  p201_summary_v9a_spec9_sd.bif
ab257beeac6bd8ea922a47e41f5f5f162eeab23380ecf135d5db449d7067858d  spec9_reference_selftest_20260608.json
58de598eea686e857a5cbb82135fea6fca2c0c79904b65af5f1b4b5f5f259447  sd_payload/BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  sd_payload/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  sd_payload/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  sd_payload/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  sd_payload/uramdisk.image.gz
```

## Reference Selftest

Evidence:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v9a_spec9\spec9_reference_selftest_20260608.json
```

Result:

```text
SPEC9 reference selftest: 6 / 6 PASS
```

The reference model intentionally does not call `numpy.fft`, because SPEC9 is a four-bin coarse proxy rather than a full FFT or PSD.

## Hardware Validation Attempt

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
SPEC9 hardware capture consistency: 6 / 6 PASS
AD9361/IIO health: FAIL
cf-ad9361-lpc missing
dmesg: ad9361_dig_tune_delay: Tuning TX FAILED!
dmesg: cf_axi_adc: probe of 79020000.cf-ad9361-lpc failed with error -5
overall V9A hardware validation: FAIL / incomplete
```

Do not promote V9A to hardware-validated status. It failed AD9361/IIO health.
Use `VERSION_ROUTE.md` for the current validated baseline and rollback target.

## Safe SD Copy

The five `sd_payload` files have already been copied to SDR `/sd` and synced. If copying again is required later, copy only these five files from `sd_payload` to a copied/new SDR SD boot partition or SDR `/sd` experiment target after the local artifact gate passes:

```text
BOOT.bin
devicetree.dtb
uEnv.txt
uImage
uramdisk.image.gz
```

Do not copy anything into:

```text
C:\Users\20642\Desktop\开发\SDR\2r2t
G:\ROS开发\SDR P201P
```

Do not overwrite any original `BOOT.bin`.

## NX Validation

NX validation must stay inside:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
```

Windows mirror:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test
```

Prepared validation scripts:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\read_spec9_once.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\compare_spec9_reference.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\compare_spec9_batch_ssh.py
```

Suggested first validation after staging and physical SDR power-cycle:

```bash
python3 scripts/read_spec9_once.py --json
python3 scripts/compare_spec9_batch_ssh.py --frame-len 64 --repeat 6 --out-json logs/spec9_batch_after_reboot.json
```

Expected key registers:

```text
devmem 0x43C00040 32 -> 0x53554D39
devmem 0x43C000EC 32 -> 0x00010003
devmem 0x43C000F0 32 -> 0x000007FF
devmem 0x43C000FC 32 -> 0x56390001
devmem 0x43C00100 32 -> 0x51554139
devmem 0x43C00180 32 -> 0x41474739
devmem 0x43C00200 32 -> 0x53504339
devmem 0x43C002F0 32 -> 0x00000004
devmem 0x43C002F8 32 -> 0x53390001
devmem 0x43C002FC 32 -> 0x00010003
```

Minimum hardware validation pattern:

```text
1. Confirm /sd/BOOT.bin hash is 58de598eea686e857a5cbb82135fea6fca2c0c79904b65af5f1b4b5f5f259447.
2. Physically power-cycle SDR.
3. Confirm AD9361/IIO health.
4. Read expected SUM9/QUA9/AGG9/SPEC9 registers.
5. Run the independent SPEC9 validation script.
6. Record a hardware validation report and update VERSION_ROUTE.md.
```

## Known Risks

- V9A is not hardware-validated.
- AD9361/IIO health failed in the first post-power-cycle V9A validation attempt.
- Timing is clean but thin at global WNS +0.015 ns.
- SPEC9 is a coarse proxy only; do not present it as FFT, PSD, or calibrated spectral output.
- Existing DRC warnings remain, including DSP pipeline suggestions and ADI/vendor FIFO async-control warnings.
- Do not start ROS, SDR streaming runtime, robot_control, mapping, RTAB-Map, cmd_vel, or motion paths during validation.
- Do not modify active NX `robot_control`; V9A remains bypass/shadow-only.
