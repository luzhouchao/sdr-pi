# V10S3 Energy Peak

Reusable non-FFT RTL for energy, peak, second-peak, noise-floor proxy,
prominence, and threshold-count reduction.

## Contents

- `rtl/p201_v10s3_energy_peak_reducer.v`: scalar reducer.
- `test/tb_p201_v10s3_energy_peak_reducer.v`: deterministic module testbench.

## Status

XSIM passed and the module is included in the V10S1/S2/S3 combined OOC pass.
It has no standalone SD payload and is not hardware validated.

## Integration Rule

The input can be FFT bin power or ordinary scalar power windows. Do not label it
as FFT by itself.
