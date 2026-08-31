# V10S1 Quality Stats

Reusable non-FFT RTL for fixed-shape I/Q quality statistics.

## Contents

- `rtl/p201_sdr_quality_stats.v`: sample count, I/Q sums, squared sums, cross term, peak, clipping/saturation, valid/drop counters.
- `test/tb_p201_sdr_quality_stats.v`: deterministic module testbench.

## Status

XSIM passed and the module is included in the V10S1/S2/S3 combined OOC pass.
It has no standalone SD payload and is not hardware validated.

## Integration Rule

Keep this as a reusable primitive. NX should still handle division, sqrt,
calibration, policy, fallback, logging, and publication.
