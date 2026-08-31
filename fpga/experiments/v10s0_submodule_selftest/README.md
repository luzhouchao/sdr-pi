# V10S0 Submodule Self-Test

Isolated AXI-Lite self-test page for reusable FFT-adjacent SDR helper blocks.

## Contents

- `rtl/`: frame packer, bin-power, FFT summary, bandpower, correlation, and AXI self-test wrapper.
- `test/`: deterministic AXI wrapper testbench.

## Status

PC build, XSIM, OOC, IP package, BD integration, bitstream, Bootgen, and SD
payload have passed. SDR `/sd` staging and post-power-cycle validation passed
on 2026-06-09. Hardware-validated only as an isolated deterministic self-test
page on a V8D0 live tap base.

## Notes

V10S0 is isolated from AD9361 live sample, valid, clock, and reset nets. It is
not active NX runtime integration. The image includes a V8D0 live SUM8/QUA8/AGG8
base that has passed independent passive shadow and feature-flag primitive-assist
board probes, but that does not promote V10S0 to live runtime integration.
