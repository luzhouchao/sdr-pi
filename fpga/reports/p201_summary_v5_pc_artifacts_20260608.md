# P201 Summary V5 PC Artifacts

Generated: 2026-06-08 01:30 Asia/Shanghai

## Scope

Summary V5 is a PC-prepared FPGA offload candidate for tomorrow's SDR burn-in. It was not copied to SDR and was not hardware-tested in this run because the user powered off NX and SDR.

Hard boundaries were preserved:

- Original SD backup was not modified.
- Existing NX SDR runtime code was not modified.
- `robot_control` runtime/launch chain was not modified.
- ROS, SDR streaming runtime, mapping, RTAB-Map, robot_controller, cmd_vel, and motion paths were not started.

## Design Decision

A short sub-agent performance review recommended stopping at V5 tonight and not building V6 FFT/window/PSD HDL before tomorrow's burn-in.

Reason:

- V5 is already a large burnable step toward FPGA offload.
- FFT/window/PSD needs a separate buffering, scaling, coefficient, FFT IP or pipeline, DMA/register, validation, and timing-closure contract.
- Adding FFT tonight would risk the burnable V5 path before V5 has hardware validation.

Next-stage plan after V5 hardware validation:

```text
FPGA: optional Python-callable kernels such as FFT/window/PSD/noise/peak blocks.
NX: version routing, register/DMA reads, divide/sqrt/atan2/calibration, aggregation, fallback, frontend/ROS publication.
```

## V5 FPGA Function

V5 production no-snapshot FPGA summary computes:

- Dual-RX sample count.
- RX0/RX1 raw power sums.
- RX0/RX1 peak power and peak index.
- Cross real: `sum(I0*I1 + Q0*Q1)`.
- Cross imag: `sum(Q0*I1 - I0*Q1)`.
- Signed I/Q sums for RX0/RX1.
- Corrected numerator registers:
  - `N*rx0_power - i0_sum^2 - q0_sum^2`
  - `N*rx1_power - i1_sum^2 - q1_sum^2`
  - `N*cross_re - i0_sum*i1_sum - q0_sum*q1_sum`
  - `N*cross_im - q0_sum*i1_sum + i0_sum*q1_sum`

Snapshot readback is intentionally disabled:

```text
0x43C00060 SNAPSHOT_COUNT -> 0
0x43C00068 SNAPSHOT_DATA -> 0
0x43C0006c SNAPSHOT1_DATA -> 0
```

## Register Expectation

```text
0x43C00040 SUMMARY_VERSION -> 0x53554D35
0x43C00060 SNAPSHOT_COUNT  -> 0x00000000
```

## Vivado Status

```text
IP packaging: PASS
BD validation: PASS
write_bitstream Complete!
WNS: +0.015 ns
WHS: +0.030 ns
route fully routed
routing errors: 0
```

Note:

```text
The global WNS path is in the existing RGMII receive path. The tap-related clk_fpga_0 timing summary shows positive margin around +0.785 ns.
```

## Bootgen Status

Bootgen status: PASS.

BIF:

```text
image : {
  [bootloader] fsbl_from_pzsdr_fw.elf
  system_top_with_p201_summary_v5.bit
  u-boot_from_pzsdr_fw.elf
}
```

Command:

```powershell
& 'E:\Xilinx\SDK\2019.1\bin\bootgen.bat' -arch zynq -image 'p201_summary_v5_sd.bif' -w -o 'BOOT_p201_summary_v5.bin'
```

## Artifact Directory

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v5
```

Main BOOT:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v5\BOOT_p201_summary_v5.bin
```

Ready-to-copy SD payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v5\sd_payload
```

The `sd_payload` folder contains:

```text
BOOT.bin
devicetree.dtb
uEnv.txt
uImage
uramdisk.image.gz
```

## Hashes

V5 build artifacts:

```text
a9849d26185671c9fb276cdab032913864b379b3c8fcca9286d472be964f0544  BOOT_p201_summary_v5.bin
837ecbfd1ab14c6a65188db9671ff5ed08fd7a926ed8ef7c0ebfacc583564ba0  system_top_with_p201_summary_v5.bit
5115c0e1872c61fe64b9b7ff1c0b448b5afaea2f3f538776368e815f0f393a24  fsbl_from_pzsdr_fw.elf
69b9b060dd7a3525806e98e6c93e77b2b47795993dc9069279b7beca1a4c943d  u-boot_from_pzsdr_fw.elf
```

V5 ready-to-copy SD payload:

```text
a9849d26185671c9fb276cdab032913864b379b3c8fcca9286d472be964f0544  BOOT.bin
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  devicetree.dtb
fb7cf8518740c80afae7c1802dec32bbd89133afaffb1a3030994f6c8565d8a1  README_SD_PAYLOAD_V5.md
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  uramdisk.image.gz
```

## NX Validation Script

Local prepared script:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v5_production.py
```

Target NX path after NX is powered:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/scripts/capture_summary_v5_production.py
```

This script does not depend on snapshot readback. It verifies V5 summary internal consistency by recomputing corrected numerator values on NX from raw summary registers and comparing them with FPGA corrected numerator registers.

Recommended command:

```bash
python3 scripts/capture_summary_v5_production.py --frame-lens 64,128,256 --repeat 5 --out-json logs/summary_v5_production_sweep.json
```

The script records SD hashes, repeated-run pass rate, trigger/write timing, settle timing, register-read timing, NX postprocess timing, total capture timing, summary bytes read, and raw IQ bytes avoided. V5 does not prove same-frame raw IQ equivalence by itself because snapshot is disabled; use V4/V3 for snapshot debug.

`python -m py_compile` passed locally.

Preferred SDR-local performance helper:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v5_local.py
```

Recommended SDR-local command after functional V5 boot/register checks:

```bash
python3 capture_summary_v5_local.py --mode mmap --frame-lens 64,128,256 --repeat 5 --out-json /tmp/summary_v5_local_perf.json
```

This helper uses one local process and `/dev/mem` mmap by default, avoiding SSH-per-register timing overhead. It is still experiment-only and does not replace the active NX SDR computation chain.

## Version Route

Project route:

```text
E:\vivado\fpga_p201pro_accel\VERSION_ROUTE.md
```

Recommended test order:

```text
V5 -> V4 -> V3 -> V2 -> V1
```

## Tomorrow Minimum Validation

1. Copy files from V5 `sd_payload` to a copied/new SDR SD boot partition.
2. Physically power-cycle SDR.
3. Verify SD hashes.
4. Verify:

```bash
devmem 0x43C00040 32
devmem 0x43C00060 32
```

5. Copy/run `capture_summary_v5_production.py` only in the independent NX experiment directory.

Do not replace the active NX SDR computation path until comparison passes.
