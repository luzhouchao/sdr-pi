# P201Pro Summary V8 Hardware Aggregate Candidate

Status: PC-built, timing-clean, Bootgen PASS, hardware-validated after physical SDR power-cycle.

Historical test order: V8 became the highest hardware-validated candidate at
that point. For present work, use `VERSION_ROUTE.md`; V8L1 is now the highest
forward hardware-validated baseline.

## Performance Decision

V8 is the first FPGA/NX load-reduction candidate after V7 validation. It does not add FFT, DMA, vector buffers, or a streaming runtime. It keeps the fixed-shape kernel split:

- FPGA: per-frame SUM8 reductions plus multi-frame aggregate accumulators for corrected power, corrected cross, raw power, and quality counts.
- NX: register orchestration, divide/sqrt/atan2, calibration, CPU/GPU algorithm composition, later frontend/ROS publication.

The aggregate path is explicitly armed by NX and locks when the target frame count completes. This lets NX read one stable low-rate page instead of repeatedly polling and aggregating many single-frame summaries. V8 may insert a few post-processing clock gaps between hardware frames; it is a side-band validation kernel, not a gapless SDR streaming replacement.

## FPGA Logic Changes

V8 keeps V7-compatible SUM/quality offsets and updates version metadata:

```text
0x040 SUMMARY_VERSION    0x53554D38 ("SUM8")
0x0ec ABI_VERSION        0x00010002
0x0f0 CAPABILITY_BITMAP  0x000003FF
0x0fc BUILD_ID           0x56380001
0x100 QUALITY_VERSION    0x51554138 ("QUA8")
0x138 QUALITY_CAP        0x0000000F
0x13c QUALITY_BUILD_ID   0x51380001
```

New aggregate page:

```text
0x180 AGG_VERSION        0x41474738 ("AGG8")
0x184 AGG_CONTROL        bit0 enable, bit1 clear/arm write, bit4 done, bit5 overflow
0x188 AGG_TARGET         target frame count, 1..65535
0x18c AGG_FRAMES         latched aggregate frame count
0x190 AGG_SAMPLES        latched aggregate sample count
0x194..0x19c             RX0 corrected-power numerator, signed 96-bit
0x1a0..0x1a8             RX1 corrected-power numerator, signed 96-bit
0x1ac..0x1b4             corrected cross real numerator, signed 96-bit
0x1b8..0x1c0             corrected cross imag numerator, signed 96-bit
0x1c4..0x1cc             RX0 raw power, unsigned 96-bit
0x1d0..0x1d8             RX1 raw power, unsigned 96-bit
0x1dc                   aggregate RX0 clip count
0x1e0                   aggregate RX1 clip count
0x1e4                   aggregate RX0 zero-cross count
0x1e8                   aggregate RX1 zero-cross count
0x1ec                   aggregate same-sign count
0x1f0                   last frame counter included
0x1f4 AGG_CAP           0x0000001F
0x1f8 AGG_BUILD_ID      0x41380001
0x1fc AGG_LIMIT         65535
```

Snapshot readback remains disabled.

## Vivado Status

```text
IP packaging: PASS
BD validation: PASS
write_bitstream Complete!
WNS +0.011 ns
WHS +0.053 ns
route fully routed
routing errors 0
```

Resource snapshot:

```text
Slice LUTs       17877 / 53200  33.60%
Slice Registers  26120 / 106400 24.55%
DSPs                80 / 220    36.36%
Block RAM Tile       6 / 140     4.29%
```

## Bootgen

BIF:

```text
image : {
  [bootloader] fsbl_from_pzsdr_fw.elf
  system_top_with_p201_summary_v8.bit
  u-boot_from_pzsdr_fw.elf
}
```

Command:

```powershell
& 'E:\Xilinx\SDK\2019.1\bin\bootgen.bat' -arch zynq -image 'p201_summary_v8_sd.bif' -w -o 'BOOT_p201_summary_v8.bin'
```

Bootgen status: PASS.

## Hashes

```text
6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb  BOOT_p201_summary_v8.bin
e5114fb025ccc11e465e54dd34047a5e455f3636f393d46327ef9479ca1385b3  system_top_with_p201_summary_v8.bit
5115c0e1872c61fe64b9b7ff1c0b448b5afaea2f3f538776368e815f0f393a24  fsbl_from_pzsdr_fw.elf
69b9b060dd7a3525806e98e6c93e77b2b47795993dc9069279b7beca1a4c943d  u-boot_from_pzsdr_fw.elf
960173542b3724c356f2390ca0fd716282ed23aa9e34ba98f36bebb9f8d6cf5a  sd_payload/devicetree.dtb
2133e06d15d56aac7a0e2fdadbcb0739490cce9b7d4e97617148b6c09950119f  sd_payload/uEnv.txt
e7a0554bbf5410e2279c58a0ae1463552de5fe6f3661ca6b8209a1d0d6dfedd5  sd_payload/uImage
0a3121fd5fb5827b2f386829ecbe42256aa452136d64c2a703bcbde99c498c55  sd_payload/uramdisk.image.gz
```

## Safe SD Copy

Ready-to-copy payload:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\sd_boot_rebuild_p201_summary_v8\sd_payload
```

Copy only these files to a copied/new SDR SD boot partition or SDR `/sd` experiment card:

```text
BOOT.bin
devicetree.dtb
uEnv.txt
uImage
uramdisk.image.gz
```

Do not copy anything into the original vendor SD backup.

## NX Validation

NX validation must stay inside:

```text
/home/wheeltec/ros2_ws/src/robot_control/sdr_fpga_offload_test
```

Prepared local experiment script:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\capture_summary_v8_aggregate.py
```

Reusable client/API added after hardware validation:

```text
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\sdr_kernel_client.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\scripts\read_sum8_aggregate_client.py
E:\vivado\fpga_p201pro_accel\nx_experiments\sdr_fpga_offload_test\include\p201_sdr_kernel_contract.hpp
```

Suggested first validation after physical SDR power-cycle:

```bash
python3 scripts/capture_summary_v8_aggregate.py --frame-len 64 --agg-frames 16 --repeat 3 --out-json logs/summary_v8_aggregate_after_reboot.json
```

Expected key registers:

```text
0x43C00040 -> 0x53554D38
0x43C000EC -> 0x00010002
0x43C000F0 -> 0x000003FF
0x43C000FC -> 0x56380001
0x43C00100 -> 0x51554138
0x43C00180 -> 0x41474738
0x43C001F4 -> 0x0000001F
0x43C001F8 -> 0x41380001
```

## Hardware Validation

Report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8_hardware_validation_20260608.md
```

Result:

```text
physical power-cycle validation: PASS
/sd/BOOT.bin hash: 6c40f07a46cc5321b2eb5bd85bbc226255996c0d3719909b8a9dee6d72becfcb
SUM8/QUA8/AGG8 metadata: PASS
primary aggregate validation: 5 / 5 captures passed at frame_len=64, agg_frames=16
reusable client validation: 6 / 6 captures passed at frame_len=64, agg_frames=4,16,64
```

The new client validation proves NX can use one typed bypass API to arm AGG8,
wait for completion, and read normalized aggregate primitives for later CPU/GPU
coordination.

## Known Risks

- Timing is clean but thin (`WNS +0.011 ns`); keep V7 available as rollback.
- V8 aggregates fixed-shape summaries and is not a replacement for the active NX SDR chain.
- Do not start ROS, SDR streaming runtime, robot control, mapping, RTAB-Map, or motion paths during validation.
