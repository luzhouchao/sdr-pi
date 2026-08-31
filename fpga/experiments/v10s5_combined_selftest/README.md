# V10S5 Combined Self-Test

Current source-level candidate for a V8D0/V8L1-style base plus an isolated
combined AXI-Lite self-test page at `0x43C30000`.

## Contents

- `rtl/p201_v10s5_fft_family_selftest_core.v`: FFT-family sidecar core test.
- `rtl/p201_v10s5_nonfft_selftest_core.v`: non-FFT sidecar core test.
- `rtl/p201_v10s5_combined_selftest_axi_regs.v`: combined AXI-Lite register page.
- `test/`: deterministic testbenches for the sidecar cores and combined wrapper.

## Status

Source and scripts are prepared. Sidecar module checks were reported by
subagents. The combined wrapper XSIM and OOC synth gates passed on PC. The
candidate has no IP package, BD integration, bitstream, Bootgen output, SD
payload, staging, or hardware validation.

## Important Detail

The combined wrapper defaults to deterministic internal mirrors for the
combined AXI self-test. The external FFT-family and non-FFT sidecar cores are
not the default wrapper path unless the wrapper/core interface is explicitly
reviewed and enabled. Treat V10S5 as a candidate under review, not as a
finished burnable artifact.
