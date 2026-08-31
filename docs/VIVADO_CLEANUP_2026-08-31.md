# Vivado workspace cleanup — 2026-08-31

This records the cleanup of `E:\vivado` performed while preparing the Raspberry Pi 4B SDR workflow. The cleanup deliberately separates reproducible Vivado output and obsolete installation copies from source, device images, validation evidence, and local Git history.

## Removed from the active workspace

The following paths were validated as children of `E:\vivado` and moved to the Windows Recycle Bin:

| Path | Approximate size | Reason |
| --- | ---: | --- |
| `Vivado_SDK_2019.1_0524_1430_extract` | 22 GiB | Redundant installer extraction; the working Vivado 2019.1 installation is under `E:\Xilinx\Vivado\2019.1`. |
| `Vivado_SDK_2019.1_0524_1430` | negligible | Wrapper directory containing a junction to the extraction tree. The junction itself was removed without traversing its target. |
| `fpga_p201pro_accel_backups` | 3.0 GiB | Four non-Git snapshots from 2026-06-08, predating the current V10S5 work and retained Git history. |
| `_p201v10` | 91 MiB | Reproducible XFFT synthesis project output. |
| `fpga_p201pro_accel_mainline\vivado_out` | 63 MiB | Reproducible Vivado OOC, simulation, probe, and packaging output. |
| `fpga_p201pro_accel_mainline\.Xil` | empty | Vivado cache directory. |
| `fpga_p201pro_accel_mainline\vivado*.log` and `vivado*.jou` | less than 1 MiB | Twelve generated session and backup logs. |

About 25 GiB was removed from the active directory tree. E: free space changed from 574.80 GiB to 577.74 GiB during the operation. The difference is expected because recoverable items can continue occupying the Recycle Bin until it is emptied.

## Explicitly retained

- `fpga_p201pro_accel`: retained intact because it contains uncommitted V10S5 reports, scripts, and bitstream-stage evidence.
- `fpga_p201pro_accel_mainline`: retained as the clean V8-derived mainline source tree; only ignored/generated output was removed.
- `fpga_p201pro_accel_worktrees`: retained because all three worktrees are clean but contain local commits not merged into mainline (`candidate/goertzel-fewbin`, `candidate/multilag-corr`, and `candidate/v10-fft-kernel`).
- `$out`: retained because it contains the Buildroot/Linux source used for SDR system work.
- `deliverables`, `vendor_experiments`, `boot_experiments`, reports, scripts, HDL, version-route documentation, and handoff documentation: retained as build inputs or validation/rollback evidence.
- `p201_mainline_shadow_20260609.patch`: retained because it did not reverse-apply cleanly to the current mainline and therefore was not proven redundant.
- `p201pro_stream_wrapper_synth`, root `nx_experiments`, and `p201pro_2t2r_sd_project`: retained because their small size did not justify deleting unverified reference material.

The original SD-card backup at `C:\Users\20642\Desktop\开发\SDR\2r2t`, the original `BOOT.bin`, and the vendor package at `G:\ROS开发\SDR P201P` were not modified.

## Verification

- Vivado 2019.1 executable verified at `E:\Xilinx\Vivado\2019.1\bin\vivado.bat` before cleanup.
- The mainline worktree remained clean after generated-output removal.
- The dirty V10S5 worktree status was unchanged.
- All four registered Git worktrees remained present after cleanup.

## Recovery and permanent space release

The removed directories were sent to the Windows Recycle Bin rather than permanently erased. They can be restored from there if needed. Emptying the Recycle Bin permanently releases any remaining occupied space and removes that recovery path.
