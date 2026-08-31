# P201Pro Phase 1 fpga_fft_shadow ABI Draft

Date: 2026-06-09

## Result

Software ABI draft PASS.

This is not FPGA hardware, not FFT/PSD implementation, not board validation, and
not active runtime integration. It defines the register contract that later
isolated RTL/self-test work can target.

## ABI Decision

The `fpga_fft_shadow` page starts at offset `0x400` from AXI-Lite base
`0x43C00000`.

Rationale:

- `0x000..0x1FC` remains SUM8/QUA8/AGG8.
- `0x200..0x2FC` remains the historical SPEC9 four-bin proxy page.
- `0x400` is a clean new page for a real FFT/PSD shadow ABI and avoids silently
  promoting the SPEC9 proxy as FFT.

## Shape

The first draft exposes:

- identity: magic, build ID, ABI version, capability bitmap;
- frame/status: sequence, valid, stale, overflow, low-confidence,
  sample-mismatch, sample count, NFFT, sample rate, window ID, scale exponent;
- summary: RSSI, peak bin, peak offset Hz, peak power, noise floor, prominence,
  and band power as signed `dBFS x100` style fields where applicable;
- top peaks: four `(bin, power_dbfs_x100)` pairs;
- coarse PSD: 128 reserved register slots, with supported count `64..128` and
  preferred first count `96`.

Coarse PSD bins begin at `0x500`. With 128 slots, the reserved window ends at
`0x6FC`; a 96-bin implementation uses `0x500..0x67C`.

The bin spacing field is `coarse_bin_step_q16` rather than an integer group
size, because common inputs such as 2048 FFT bins do not divide evenly into 96
coarse bins.

## Software Files

- `sdr_fpga_offload_test/sdr_kernel_contract.py`
- `sdr_fpga_offload_test/fft_shadow_client.py`
- `scripts/test_fft_shadow_contract.py`
- `scripts/dump_sdr_kernel_contract.py`
- `SDR_KERNEL_CONTRACT.json`

## Verification

Commands run:

```text
python -m py_compile nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\sdr_kernel_contract.py nx_experiments\sdr_fpga_offload_test\sdr_fpga_offload_test\fft_shadow_client.py nx_experiments\sdr_fpga_offload_test\scripts\dump_sdr_kernel_contract.py nx_experiments\sdr_fpga_offload_test\scripts\test_fft_shadow_contract.py
python nx_experiments\sdr_fpga_offload_test\scripts\test_fft_shadow_contract.py
wsl --cd /mnt/e/vivado/fpga_p201pro_accel_mainline sh -lc "python3 -m py_compile nx_experiments/sdr_fpga_offload_test/sdr_fpga_offload_test/sdr_kernel_contract.py nx_experiments/sdr_fpga_offload_test/sdr_fpga_offload_test/fft_shadow_client.py nx_experiments/sdr_fpga_offload_test/scripts/dump_sdr_kernel_contract.py nx_experiments/sdr_fpga_offload_test/scripts/test_fft_shadow_contract.py && python3 nx_experiments/sdr_fpga_offload_test/scripts/test_fft_shadow_contract.py"
python nx_experiments\sdr_fpga_offload_test\scripts\dump_sdr_kernel_contract.py --out nx_experiments\sdr_fpga_offload_test\SDR_KERNEL_CONTRACT.json
python -m json.tool nx_experiments\sdr_fpga_offload_test\SDR_KERNEL_CONTRACT.json
```

Result:

```text
fft_shadow_contract fake-register test PASS
```

## Not Run

- No RTL simulation or synthesis.
- No Vivado implementation.
- No SDR board readback.
- No ROS, SDR streaming runtime, mapping, RTAB-Map, navigation,
  `robot_controller`, `cmd_vel`, or robot motion.
- No active `robot_control` modification.

## Next Safe Step

Use this ABI for P1.2 reference-vector/tolerance work and for a later isolated
P1.3 self-test page. If the implementation becomes a proxy rather than real
FFT/PSD, rename the capability and do not use this `FFT1` identity.
