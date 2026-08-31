# P201Pro V8L1 Auto Aggregate Bitstream Gate

Date: 2026-06-08

## Result

PC artifact gate: PASS after post-route phys_opt.

This is not hardware validation. V8 remains the highest hardware-validated version until this candidate boots on SDR and passes AD9361/IIO plus register/hash capture checks.

## Evidence

- Candidate: V8-derived low-NX-load AGG8 auto-roll, tagged V8L1.
- Initial implementation bitstream completed, but timing failed:
  - WNS -0.172 ns
  - WHS +0.052 ns
  - TNS failing endpoints 7
  - Route errors 0
  - Report dir: `reports/stage4_ad9361_tap_bitstream_v8l1_auto_agg`
- Post-route phys_opt passed:
  - `phys_opt_design -directive AggressiveExplore`: PASS
  - `route_design -directive Explore`: PASS
  - `write_bitstream`: PASS
  - `write_hwdef`: PASS
  - WNS +0.004 ns
  - WHS +0.052 ns
  - TNS 0.000 ns
  - THS 0.000 ns
  - Route errors 0
  - DRC errors 0
  - Report dir: `reports/stage4_ad9361_tap_bitstream_physopt_v8l1_auto_agg`

## Utilization After PhysOpt

- Slice LUTs: 18367 / 53200, 34.52%
- Slice Registers: 26195 / 106400, 24.62%
- DSPs: 80 / 220, 36.36%
- Block RAM Tile: 6 / 140, 4.29%

## Artifacts On Disk

- Bitstream: `reports/stage4_ad9361_tap_bitstream_physopt_v8l1_auto_agg/system_top_with_p201_tap_v8l1_auto_agg_physopt.bit`
  - Size: 4045670 bytes
  - SHA256: `57F90D7C582857D1837550E2F9C1536FDF7886B62EA0D6A937EC3DD078F6B468`
- HWDEF: `reports/stage4_ad9361_tap_bitstream_physopt_v8l1_auto_agg/system_top_with_p201_tap_v8l1_auto_agg_physopt.hwdef`
  - Size: 430854 bytes
  - SHA256: `71D3ACB61ED1BB64C7D4D4BDBE8807EF490290181C61CDDE045D96AB07389E47`

## Next Gate

Generate a BOOT.bin/SD payload from the phys_opt bitstream, stage it to SDR `/sd`, then power-cycle the SDR and run:

- `/sd` hash verification
- SUM8/QUA8/AGG8/V8L1 register checks
- AD9361/IIO health, including `cf-ad9361-lpc`
- Minimal no-motion hardware capture
