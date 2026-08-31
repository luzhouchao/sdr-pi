# Iteration workflow

All new Raspberry Pi, SDR-system, and FPGA work is tracked in this repository.

## Branch and commit rules

1. Start from `main` and create a focused branch such as
   `pi/rust-dsp-pipeline`, `sdr/iiod-throughput`, or `fpga/fft-shadow-v1`.
2. Keep commits small and evidence-based: source change, test, then result
   documentation.
3. Do not mix Raspberry Pi runtime changes, SDR firmware changes, and FPGA
   bitstream changes in one unreviewable commit.
4. Update the relevant README, test result, version route, and rollback note in
   the same branch.

## Required evidence

Raspberry Pi/Rust changes:

- formatting and unit-test result;
- target architecture and SHA-256;
- hardware probe/capture result when applicable;
- final SDR configuration readback.

SDR-system changes:

- pre-change snapshot;
- exact changed files/sysctls/process arguments;
- throughput, errors, CPU, temperature, and IIO health before/after;
- rollback procedure.

FPGA changes:

- XSIM/OOC/IP/BD/bitstream status as applicable;
- WNS/WHS, route status, routing errors and critical warnings;
- Bootgen and hashes;
- unique artifact name and rollback version;
- physical power-cycle validation before claiming hardware validation.

## Binary artifacts

Generated ARM64 binaries, bitstreams, BOOT images and SD payloads do not belong
in Git history. After all gates pass, publish them as a versioned GitHub Release
with hashes and a link to the exact source commit.
