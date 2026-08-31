# P201 Summary V5 Production No-Snapshot

Generated: 2026-06-08 01:10 Asia/Shanghai

## Purpose

This was a large-step FPGA offload candidate that moved more SDR reduction work
into FPGA while keeping NX flexible: FPGA computes fixed high-rate summary
kernels, and NX reads registers to do light math, calibration, aggregation, and
frontend/ROS publication later.

Test this version before V4. If V5 boots and `SUMMARY_VERSION` reads `0x53554D35`, continue validation from V5. If V5 fails, fall back to V4 because V4 retains raw snapshot debug readback.

## Performance Review Decision

A pre-write performance review concluded that V5 should remain the burnable
large-step candidate for that gate. Adding a V6 FFT/window/PSD HDL kernel in the
same step was a no-go because it required a new buffering, scaling, coefficient,
FFT-IP/DMA/register, and validation contract while risking the already burnable
V5 path.

FFT/window/PSD should be treated as next-stage architecture after V5 hardware validation. The intended shape is a Python-callable NX API over optional FPGA kernels, not one rigid all-in-FPGA business algorithm.

## FPGA Logic Changes

V5 keeps V4 raw summary outputs and adds production-oriented corrected numerator registers:

- Dual-RX sample count.
- RX0/RX1 raw power sums.
- RX0/RX1 peak power and peak index.
- Cross real sum: `sum(I0*I1 + Q0*Q1)`.
- Cross imag sum: `sum(Q0*I1 - I0*Q1)`.
- Signed I/Q sums for both receivers.
- Mean-corrected numerator registers:
  - `N*rx0_power - i0_sum^2 - q0_sum^2`
  - `N*rx1_power - i1_sum^2 - q1_sum^2`
  - `N*cross_re - i0_sum*i1_sum - q0_sum*q1_sum`
  - `N*cross_im - q0_sum*i1_sum + i0_sum*q1_sum`

The expensive snapshot array readback was intentionally disabled for timing. `REG_SNAPSHOT_COUNT` returns `0`, and `REG_SNAPSHOT_DATA` / `REG_SNAPSHOT1_DATA` return `0`.

## Register Map

Base address:

```text
0x43C00000
```

Key registers:

```text
0x40 SUMMARY_VERSION       0x53554D35 ("SUM5")
0x48 SUMMARY_FRAME
0x4c SUMMARY_SAMPLES
0x50/0x54 RX0 power sum compatibility mirror
0x58 RX0 peak power
0x5c RX0 peak index
0x60 SNAPSHOT_COUNT        0 in V5 production
0x70 DUAL_SAMPLES
0x74/0x78 RX0_POWER
0x7c/0x80 RX1_POWER
0x84/0x88 CROSS_RE
0x8c/0x90 CROSS_IM
0x94 RX1_PEAK_POWER
0x98 RX1_PEAK_INDEX
0x9c/0xa0 I0_SUM
0xa4/0xa8 Q0_SUM
0xac/0xb0 I1_SUM
0xb4/0xb8 Q1_SUM
0xbc/0xc0/0xc4 RX0_CORR_PWR_NUM  64-bit value with sign-extension high word
0xc8/0xcc/0xd0 RX1_CORR_PWR_NUM  64-bit value with sign-extension high word
0xd4/0xd8/0xdc CORR_CROSS_RE_NUM 64-bit value with sign-extension high word
0xe0/0xe4/0xe8 CORR_CROSS_IM_NUM 64-bit value with sign-extension high word
```

## Vivado Status

```text
IP packaging: PASS
BD validation: PASS
write_bitstream Complete!
WNS: +0.015 ns
WHS: +0.030 ns
Route status: fully routed
Routing errors: 0
```

Implementation report source:

```text
E:\vivado\fpga_p201pro_accel\reports\stage4_ad9361_tap_bitstream
```

## Bootgen

BIF:

```text
image : {
  [bootloader] fsbl_from_pzsdr_fw.elf
  system_top_with_p201_summary_v5.bit
  u-boot_from_pzsdr_fw.elf
}
```

Bootgen command:

```powershell
& 'E:\Xilinx\SDK\2019.1\bin\bootgen.bat' -arch zynq -image 'p201_summary_v5_sd.bif' -w -o 'BOOT_p201_summary_v5.bin'
```

Bootgen status: PASS.

## Hashes

```text
a9849d26185671c9fb276cdab032913864b379b3c8fcca9286d472be964f0544  BOOT_p201_summary_v5.bin
837ecbfd1ab14c6a65188db9671ff5ed08fd7a926ed8ef7c0ebfacc583564ba0  system_top_with_p201_summary_v5.bit
5115c0e1872c61fe64b9b7ff1c0b448b5afaea2f3f538776368e815f0f393a24  fsbl_from_pzsdr_fw.elf
69b9b060dd7a3525806e98e6c93e77b2b47795993dc9069279b7beca1a4c943d  u-boot_from_pzsdr_fw.elf
```

Expected BOOT size:

```text
4565732 bytes
```

## Historical Validation Gate

Copy only this file to the copied/new SDR SD boot partition as `BOOT.bin`:

```text
BOOT_p201_summary_v5.bin
```

Keep the validated LVDS-bias `devicetree.dtb`, `uEnv.txt`, `uImage`, and `uramdisk.image.gz` from the known-good SD-ready deliverable. Do not copy `bootgen_inputs` and do not modify the original SD backup.

After copy, physically power-cycle SDR. Then read:

```bash
devmem 0x43C00040 32
devmem 0x43C00060 32
```

Expected:

```text
0x43C00040 -> 0x53554D35
0x43C00060 -> 0x00000000
```

NX validation script for this version:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test/scripts/capture_summary_v5_production.py
```

Local source copy:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v5_production.py
```

Recommended command:

```bash
python3 scripts/capture_summary_v5_production.py --frame-lens 64,128,256 --repeat 5 --out-json logs/summary_v5_production_sweep.json
```

The script records pass rate, register-read timing, NX postprocess timing, and summary bytes read versus raw IQ bytes avoided. V5 validates production summary consistency, not same-frame raw IQ equivalence, because snapshot is disabled.

Preferred performance helper after functional validation:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v5_local.py
```

Run it on the SDR as root to avoid SSH-per-register timing overhead:

```bash
python3 capture_summary_v5_local.py --mode mmap --frame-lens 64,128,256 --repeat 5 --out-json /tmp/summary_v5_local_perf.json
```

## Rollback

Rollback to V4 if:

- SDR does not boot.
- `SUMMARY_VERSION` is not `0x53554D35`.
- AD9361/IIO health regresses.
- V5 production script fails internal consistency.

V4 fallback:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v4\BOOT_p201_summary_v4.bin
```

## Known Risks

- V5 is PC-built and timing-clean but not hardware-tested yet.
- Snapshot readback is intentionally disabled, so V5 cannot do same-frame raw sample equality checks. Use V4 for snapshot debug.
- Corrected numerator registers are 64-bit values exposed as 96-bit-shaped registers with sign-extension in the high word.
