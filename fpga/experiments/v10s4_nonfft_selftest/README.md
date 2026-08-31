# V10S4 Non-FFT Self-Test

Isolated AXI-Lite self-test page for the V10S1/S2/S3 non-FFT helper modules.

## Contents

- `rtl/p201_v10s4_nonfft_selftest_axi_regs.v`: deterministic AXI-Lite wrapper.
- `test/tb_p201_v10s4_nonfft_selftest_axi_regs.v`: wrapper testbench.

## Status

XSIM, OOC, IP package, BD integration, bitstream, Bootgen, and SD payload have
passed. SDR `/sd` staging and isolated self-test register checks passed after
power-cycle, but AD9361/IIO health failed. V10S4 is not hardware validated.

## Notes

V10S4 is not FFT, not PSD, not live AD9361 integration, and not active NX
runtime integration. It must pass `/sd` hash, AD9361/IIO health, base register,
self-test register, and validation-script checks after a physical power-cycle
before it can be called hardware validated. The 2026-06-09 attempt failed that
gate at AD9361/IIO health.
