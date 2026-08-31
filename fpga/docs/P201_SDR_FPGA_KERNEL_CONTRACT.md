# P201 SDR FPGA Kernel Contract

Last updated: 2026-06-09 19:20 Asia/Shanghai

This is the canonical contract for the independent SDR FPGA offload experiment. It is not connected to the active `robot_control` runtime.

## Design Rule

FPGA should expose stable, fixed-shape SDR kernels. NX should compose algorithms in Python/C++/CPU/GPU above those kernels.

This avoids hard-coding one full business algorithm into FPGA while still reducing NX load from repeated raw-IQ transfer and high-rate reductions.

## Safety Boundary

Do not use this contract to modify active NX runtime, ROS launch files, SDR streaming workers, mapping, RTAB-Map, `robot_controller`, `/cmd_vel`, or motion paths.

## Address Range

```text
AXI-Lite base: 0x43C00000
Range:         0x00010000
```

## Control And Read Order

Existing control registers:

```text
0x00 CONTROL      bit0 enable, bit1 clear/trigger edge
0x04 FRAME_LEN    requested frame length
0x08 STATUS       pending/status mirror
```

Safe register-only sequence:

```text
1. Write FRAME_LEN.
2. Write CONTROL = 0x2 to clear.
3. Write CONTROL = 0x1 to enable/capture.
4. Poll frame/sample/status or wait a bounded settle time.
5. Read SUMMARY_VERSION.
6. Read version-specific result registers.
7. Do not replace active NX compute chain until side-by-side validation passes.
```

## Common Diagnostics

```text
0x30 DEBUG_FLAGS
0x34 DEBUG_CLK
0x38 DEBUG_VALID
0x3c DEBUG_ACCEPT
```

Interpretation:

- `DEBUG_CLK` grows: AD9361 `l_clk` reaches the tap.
- `DEBUG_VALID` grows: AD9361 RX valid reaches the tap.
- `DEBUG_ACCEPT` reaches frame length: tap accepted a frame.

## Common Summary Header

```text
0x40 SUMMARY_VERSION
0x44 SUMMARY_FLAGS
0x48 FRAME_COUNTER
0x4c SAMPLE_COUNT
0x50 SUMMARY_SUM_LO
0x54 SUMMARY_SUM_HI
0x58 PEAK_POWER
0x5c PEAK_INDEX
```

Version magic:

```text
SUM1 0x53554D31
SUM2 0x53554D32
SUM3 0x53554D33
SUM4 0x53554D34
SUM5 0x53554D35
SUM6 0x53554D36
SUM7 0x53554D37
SUM8 0x53554D38
```

## SUM3 Debug Snapshot ABI

Purpose: hardware-validated same-frame dual-RX debug baseline.

```text
0x60 SNAPSHOT_COUNT
0x64 SNAPSHOT_INDEX
0x68 SNAPSHOT_DATA    RX0 {Q[15:0], I[15:0]}
0x6c SNAPSHOT1_DATA   RX1 {Q1[15:0], I1[15:0]}
0x70 DUAL_SAMPLES
0x74/0x78 RX0_POWER   unsigned 48-bit
0x7c/0x80 RX1_POWER   unsigned 48-bit
0x84/0x88 CROSS_RE    signed 48-bit
0x8c/0x90 CROSS_IM    signed 48-bit
0x94 RX1_PEAK_POWER
0x98 RX1_PEAK_INDEX
```

Use SUM3 when same-frame raw sample proof is needed.

## SUM4 Mean-Corrected Debug ABI

Purpose: SUM3 snapshot debug plus signed I/Q sums for NX-side mean-corrected AoA math.

Adds:

```text
0x9c/0xa0 I0_SUM      signed 48-bit
0xa4/0xa8 Q0_SUM      signed 48-bit
0xac/0xb0 I1_SUM      signed 48-bit
0xb4/0xb8 Q1_SUM      signed 48-bit
```

Corrected numerator math is performed on NX:

```text
rx0_corr = N*rx0_power - i0_sum^2 - q0_sum^2
rx1_corr = N*rx1_power - i1_sum^2 - q1_sum^2
cross_re = N*cross_re_raw - i0_sum*i1_sum - q0_sum*q1_sum
cross_im = N*cross_im_raw - q0_sum*i1_sum + i0_sum*q1_sum
```

Use SUM4 as the first fallback after SUM5.

## SUM5 Production Summary ABI

Purpose: production-shaped constant-size register summary. Snapshot readback is disabled to improve timing and represent the intended low-bandwidth FPGA/NX split.

SUM5 keeps SUM4 raw reductions and adds corrected numerator registers:

```text
0x60 SNAPSHOT_COUNT        0
0x68 SNAPSHOT_DATA         0
0x6c SNAPSHOT1_DATA        0
0xbc/0xc0/0xc4 RX0_CORR_PWR_NUM   signed 64-bit, high word sign extension
0xc8/0xcc/0xd0 RX1_CORR_PWR_NUM   signed 64-bit, high word sign extension
0xd4/0xd8/0xdc CORR_CROSS_RE_NUM  signed 64-bit, high word sign extension
0xe0/0xe4/0xe8 CORR_CROSS_IM_NUM  signed 64-bit, high word sign extension
```

SUM5 corrected-numerator validation is limited to frame length `1..256` because the current HDL narrows post-frame I/Q sums to 24 bits before corrected numerator products.

Historical SUM5 bring-up check:

```text
devmem 0x43C00040 32 -> 0x53554D35
devmem 0x43C00060 32 -> 0x00000000
```

## NX Composition Contract

FPGA returns fixed-shape primitive results. NX may then:

- Compute `coherence = hypot(corr_re, corr_im) / sqrt(rx0_corr * rx1_corr)`.
- Compute `phase = atan2(corr_im, corr_re)`.
- Apply calibration and antenna geometry.
- Aggregate across frames.
- Choose CPU/GPU/Python/C++ algorithms for higher-level decisions.
- Publish later to frontend/ROS only after side-by-side validation passes.

## Python/C++ Interface Files

Python:

```text
nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\sdr_kernel_contract.py
nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\sdr_kernel_client.py
```

C++:

```text
nx_experiments\sdr_fpga_offload_test\include\p201_sdr_kernel_contract.hpp
```

## Future ABI Route

## SUM6 Block ABI Candidate

Purpose: SUM5-compatible production summary plus stable metadata for Python/C++ clients. SUM6 is hardware-validated and remains the production-summary fallback.

SUM6 keeps the SUM5 register layout and adds:

```text
0xec ABI_VERSION        0x00010000, major 1 minor 0
0xf0 CAPABILITY_BITMAP  bit0 dual_rx
                         bit1 raw_power
                         bit2 peaks
                         bit3 cross
                         bit4 iq_sums
                         bit5 corrected_numerators
                         bit6 snapshot_disabled
                         bit7 wide_corrected_path
0xf4 LIMIT_FLAGS        bit0 frame_len_limited
                         bit1 arithmetic_overflow
                         bit2 corrected_valid
                         bit3 snapshot_disabled
0xf8 MAX_CORR_FRAME_LEN 65535
0xfc BUILD_ID           0x56360001
```

SUM6 expected boot checks:

```text
devmem 0x43C00040 32 -> 0x53554D36
devmem 0x43C00060 32 -> 0x00000000
devmem 0x43C000EC 32 -> 0x00010000
devmem 0x43C000F0 32 -> 0x000000FF
devmem 0x43C000F8 32 -> 0x0000FFFF
devmem 0x43C000FC 32 -> 0x56360001
```

Use SUM6 when a simpler validated production-summary fallback is needed.

## SUM7 Quality Page Candidate

Purpose: SUM6-compatible production summary plus a second AXI-Lite page with low-cost signal quality primitives. SUM7 is hardware-validated and remains the quality-page rollback behind SUM8.

SUM7 keeps the SUM6 `0x00..0xff` register layout and changes:

```text
0x40 SUMMARY_VERSION    0x53554D37 ("SUM7")
0xec ABI_VERSION        0x00010001, major 1 minor 1
0xf0 CAPABILITY_BITMAP  0x000001ff, SUM6 bits plus bit8 quality_page
0xfc BUILD_ID           0x56370001
```

New quality page:

```text
0x100 QUALITY_VERSION   0x51554137 ("QUA7")
0x104 QUALITY_FLAGS     reserved/status flags
0x108 QUALITY_FRAME     latched frame counter
0x10c QUALITY_SAMPLES   latched sample count
0x110 RX0_CLIP_COUNTS   upper16 Q clip count, lower16 I clip count
0x114 RX1_CLIP_COUNTS   upper16 Q clip count, lower16 I clip count
0x118 RX0_ZC_COUNTS     upper16 Q zero-cross count, lower16 I zero-cross count
0x11c RX1_ZC_COUNTS     upper16 Q zero-cross count, lower16 I zero-cross count
0x120 SIGN_SAME_COUNTS  upper16 Q0/Q1 same-sign count, lower16 I0/I1 same-sign count
0x124 QUAD_COUNTS       upper16 RX1 I/Q same-sign count, lower16 RX0 I/Q same-sign count
0x128..0x134            reserved abs-sum registers, read 0 in timing-clean SUM7A
0x138 QUALITY_CAP       0x0000000f
0x13c QUALITY_BUILD_ID  0x51370001
```

SUM7 expected boot checks:

```text
devmem 0x43C00040 32 -> 0x53554D37
devmem 0x43C000EC 32 -> 0x00010001
devmem 0x43C000F0 32 -> 0x000001FF
devmem 0x43C000FC 32 -> 0x56370001
devmem 0x43C00100 32 -> 0x51554137
devmem 0x43C00138 32 -> 0x0000000F
devmem 0x43C0013C 32 -> 0x51370001
```

Performance decision: a fuller V7 with four abs-sum accumulators produced a timing-clean bitstream write but failed timing at `WNS -0.371 ns`, so it was not packaged as burnable. The handed-off SUM7A build removed active abs-sum computation, keeps those offsets reserved/read-zero, and restored timing to `WNS +0.015 ns`, `WHS +0.003 ns`.

Use V7 after V5 and V6 if you want to test the 12-bit register decode and quality page ABI.

## SUM8 Aggregate ABI

Purpose: SUM7-compatible production summary plus a hardware multi-frame aggregate
page. SUM8 is hardware-validated after a physical SDR power-cycle. V8L1 remains
the current highest forward hardware-validated baseline; the current-loaded
V10S0/V8D0 board tests use this SUM8/QUA8/AGG8 primitive family through explicit
arm/read probes.

SUM8 keeps the SUM7 register layout and changes:

```text
0x40 SUMMARY_VERSION    0x53554D38 ("SUM8")
0xec ABI_VERSION        0x00010002, major 1 minor 2
0xf0 CAPABILITY_BITMAP  0x000003ff, SUM7 bits plus bit9 aggregate_page
0xfc BUILD_ID           0x56380001
0x100 QUALITY_VERSION   0x51554138 ("QUA8")
0x13c QUALITY_BUILD_ID  0x51380001
```

New aggregate page:

```text
0x180 AGG_VERSION       0x41474738 ("AGG8")
0x184 AGG_CONTROL       bit0 enable, bit1 clear/arm write, bit4 done, bit5 overflow
0x188 AGG_TARGET        target frame count, 1..65535
0x18c AGG_FRAMES        latched aggregate frame count
0x190 AGG_SAMPLES       latched aggregate sample count
0x194..0x1c0            corrected power/cross numerators, signed 96-bit
0x1c4..0x1d8            raw RX0/RX1 power, unsigned 96-bit
0x1dc..0x1ec            aggregate quality counts
0x1f0                   last frame counter included
0x1f4 AGG_CAP           0x0000001f
0x1f8 AGG_BUILD_ID      0x41380001
0x1fc AGG_LIMIT         65535
```

Hardware validation:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_summary_v8_hardware_validation_20260608.md
```

Primary aggregate validation passed 5 / 5 captures at `frame_len=64`,
`agg_frames=16`. The reusable SUM8 client passed 6 / 6 captures across
`agg_frames=4,16,64`.

## Future ABI Route

SUM9 or later should add FFT/PSD summary only after a performance review:

- Register-controlled `nfft`.
- Window ID.
- Scale exponent.
- Top peaks, band power, noise floor, limited PSD bins.
- Avoid full-spectrum readout unless required.

## Phase 1 `fpga_fft_shadow` ABI Draft

This is a software contract draft only. No hardware version is promoted by this
section.

The first real FFT/PSD shadow page should not reuse the historical SPEC9 proxy
page at `0x200..0x2fc`. Use a new page:

```text
0x400 FFT_SHADOW_MAGIC          0x46465431 ("FFT1")
0x404 FFT_SHADOW_BUILD_ID       0x46505331 draft ("FPS1")
0x408 FFT_SHADOW_ABI_VERSION    0x00020000
0x40c FFT_SHADOW_CAPABILITY     capability bitmap
0x410 FFT_SHADOW_SEQUENCE       monotonic result sequence
0x414 FFT_SHADOW_STATUS         bit0 valid
                                  bit1 busy
                                  bit2 stale
                                  bit3 overflow
                                  bit4 low_confidence
                                  bit5 sample_mismatch
                                  bit6 proxy_not_fft
0x418 FFT_SHADOW_SAMPLE_COUNT
0x41c FFT_SHADOW_NFFT
0x420 FFT_SHADOW_SAMPLE_RATE_HZ
0x424 FFT_SHADOW_WINDOW_ID      0 rectangular, 1 Hann, others reserved
0x428 FFT_SHADOW_SCALE_EXP      signed scale exponent
0x42c FFT_SHADOW_COARSE_COUNT   64..128, preferred 96
0x430 FFT_SHADOW_COARSE_STEP_Q16 FFT bins per coarse PSD bin in Q16.16
0x434 FFT_SHADOW_RX_MASK        bit0 RX0, bit1 RX1 reserved
0x438 FFT_SHADOW_SOURCE_FRAME
0x43c reserved
```

Summary fields:

```text
0x440 RSSI_DBFS_X100            signed
0x444 PEAK_BIN
0x448 PEAK_OFFSET_HZ            signed, NX adds LO for absolute frequency
0x44c PEAK_POWER_DBFS_X100      signed
0x450 NOISE_FLOOR_DBFS_X100     signed
0x454 PEAK_PROMINENCE_DB_X100   signed
0x458 BAND_POWER_DBFS_X100      signed
0x45c SUMMARY_FLAGS             reserved/status extension
```

Top peaks:

```text
0x460 TOP_PEAK_COUNT            0..4
0x464 TOP_PEAK_VALID_MASK       bit per peak entry
0x468 TOP0_BIN
0x46c TOP0_POWER_DBFS_X100      signed
0x470 TOP1_BIN
0x474 TOP1_POWER_DBFS_X100      signed
0x478 TOP2_BIN
0x47c TOP2_POWER_DBFS_X100      signed
0x480 TOP3_BIN
0x484 TOP3_POWER_DBFS_X100      signed
```

Coarse PSD:

```text
0x500..0x6fc COARSE_PSD_DBFS_X100[0..127] signed
```

Phase 1 should implement 96 coarse bins first if timing and register cost remain
reasonable. A 64-bin implementation is acceptable if documented before testing;
bins above `COARSE_COUNT` are reserved and should read zero.

P1.2 reference gate uses the current NX Hann/fftshift/coherent-gain PSD math and
exact-count 96-bin max-hold coarse PSD for this ABI. For `nfft=2048` and
`coarse_bin_count=96`, `COARSE_STEP_Q16` is `1398101`. The active UI compressor
currently uses max-hold groups and maps a 2048-bin PSD to 98 UI bins when
`max_bins=96`; this is documented as a UI compatibility difference rather than
changing the FPGA ABI count.

P1.3 adds a PC-only isolated RTL fixture for this exact register page under:

```text
experiments\phase1_fft_shadow_selftest
reports\p201_phase1_p1_3_fft_shadow_selftest_20260609.md
```

It proves ABI readback shape with a deterministic P1.2 synthetic fixture. It is
not live AD9361 FFT/PSD hardware and does not promote an FPGA version.

P1.3b adds a PC-only isolated signed top-4 PSD peak reducer primitive under the
same experiment. It uses ready/valid backpressure, guard-bin suppression, and a
timing-clean multi-cycle state machine. XSIM PASS and OOC timing PASS at
8.138 ns with WNS +1.102 ns, WHS +0.129 ns, 340 LUT, 509 FF, 0 BRAM, 0 DSP:

```text
reports\p201_phase1_p1_3b_fft_shadow_top4_reducer_20260609.md
```

It is a post-PSD helper only, not a complete FFT, PSD, coarse-bin generator,
live AD9361 integration, or hardware version.

P1.3c adds a PC-only exact 2048-to-96 signed PSD max-hold reducer primitive. It
matches the P1.2 exact-count grouping rule and keeps
`COARSE_STEP_Q16=1398101`. XSIM PASS and OOC timing PASS at 8.138 ns with
WNS +2.264 ns, WHS +0.185 ns, 2138 LUT, 3275 FF, 0 BRAM, 0 DSP:

```text
reports\p201_phase1_p1_3c_fft_shadow_coarse96_reducer_20260609.md
```

It is a coarse-bin helper only, not a complete FFT/window/PSD generator, live
AD9361 integration, or hardware version. The 96-direct-register resource cost
must be reviewed before this shape is integrated into a live candidate.

P1.3d adds a PC-only 4-point complex FFT smoke core under the same experiment.
It proves a minimal true FFT butterfly datapath with per-bin power, total power,
and peak summary. XSIM PASS and OOC timing PASS at 8.138 ns with WNS +1.424 ns,
WHS +0.132 ns, 1299 LUT, 856 FF, 0 BRAM, 8 DSP:

```text
reports\p201_phase1_p1_3d_fft_shadow_fft4_smoke_core_20260609.md
```

It is an FFT smoke test only, not a 2048-point FFT/window/PSD generator, live
AD9361 integration, or hardware version. The register ABI remains the
`0x400..0x6fc` `fpga_fft_shadow` draft until P1.4 integration review changes it
and documents the change before testing.

P1.4a records the PC-only integration review for the low-resolution
`fpga_fft_shadow` route:

```text
reports\p201_phase1_p1_4a_fft_shadow_integration_review_20260609.md
```

It does not change the ABI. It confirms that the missing piece is a real
2048-point FFT/window/PSD generator and recommends an isolated Xilinx FFT IP or
equivalent OOC probe before live AD9361 coupling, bitstream/BOOT generation,
board staging, or version promotion. Do not treat the FFT4 smoke core as the
2048-point FFT path.

SUM10 or later should add DMA only after register kernels prove value:

- Ring metadata.
- Buffer ownership.
- Sequence/timestamp.
- Dropped-frame counters.
- DMA for raw IQ, FFT bins, or batch summaries.
