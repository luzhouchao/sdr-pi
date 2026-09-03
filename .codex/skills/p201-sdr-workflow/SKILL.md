---
name: p201-sdr-workflow
description: Safely access, build for, deploy to, and validate the P201 SDR at 192.168.1.10. Use for P201 SSH, sdrd lifecycle, ARMv7 cross-compilation, bounded RX capture, rollback, or live radio-state validation; do not use for FPGA/BOOT or transmit work.
---

# P201 SDR workflow

Use the P201 only as a bounded RX acquisition and transport target. AGX owns
software aggregation, result storage and model-facing summaries.

Before any mutation or live capture, read
[references/access-and-deploy.md](references/access-and-deploy.md). Follow its
credential handling, duplicate-instance gate, ABI gate, staging roots,
stop/replace/start sequence and cleanup requirements exactly.

For ARMv7 `sdrd` builds on this AGX, use the persistent verified toolchain only
through
[`scripts/build-sdrd-armv7.sh`](scripts/build-sdrd-armv7.sh). The script fixes
the toolchain/image paths, restricts output to a feature directory and performs
the ELF, GLIBC and retired-symbol gates. Do not redownload a toolchain for each
feature or replace the script with `/usr/bin/arm-linux-gnueabihf-gcc`.

Hard boundaries:

- Never print, copy, log or commit the SSH password. Use the existing mode-0600
  password file only through `sshpass -f`.
- Do not modify `BOOT.bin`, uramdisk, FPGA registers/images, TX state or arbitrary
  IIO attributes. Do not start a second collector or `sdrd`.
- Every live sweep needs an explicit finite plan, maximum byte calculation, AGX
  free-space check, direct stop path and verified radio-state restoration.
- The P201 root filesystem is volatile. Persistent release files belong below
  `/sd/sdr-agent/`; transient feature data belongs below
  `/tmp/sdr-agent-dev/<feature-id>/` and must be removed after AGX receipt.
- A P201 binary is deployable only after ARM/EABI inspection and version-info
  proves it requires no unavailable glibc symbol. Verified project baselines
  are Xilinx SDK 2019.1 hard-float and the official Arm GNU 8.2-2018.08
  hard-float sysroot; both produce a highest GLIBC requirement of 2.17. Never
  deploy an AGX `/usr/bin/arm-linux-gnueabihf-gcc` artifact without this gate.

If the required compatible cross-toolchain is unavailable, stop before
replacing the live daemon. Do not weaken the ABI check or substitute a static
controlled-mode binary.
