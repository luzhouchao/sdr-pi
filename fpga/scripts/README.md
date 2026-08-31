# Scripts Index

Scripts are grouped by purpose. Read `AGENTS.md` before staging or validating
hardware.

## Vivado Build Scripts

- `vivado_package_*`: package RTL as Vivado IP.
- `vivado_integrate_*`: integrate packaged IP into the copied vendor project.
- `vivado_impl_bitstream_*`: run implementation and bitstream generation.
- `vivado_postroute_physopt_*`: post-route physopt and timing/report extraction.
- `vivado_ooc_*`: out-of-context module checks.
- `xsim_*`: simulation/self-test checks.

## Hardware/NX Validation

- `validate_v8l1_auto_agg_after_powercycle_via_nx.py`
- `validate_v9a_spec9_after_powercycle_via_nx.py`
- `validate_v9b0_minimal_isolation_after_powercycle_via_nx.py`

Newer NX-side validation scripts for V10S0/V10S4 live under:

```text
nx_experiments\sdr_fpga_offload_test\scripts
```

Current mainline NX-side board probes there include:

```text
read_sum8_aggregate_batch_ssh.py
compare_sum8_fpga_assisted_metrics.py
benchmark_v8l1_auto_roll_batch_ssh.py
probe_feature_flag_assist.py
validate_v10s0_submodule_selftest_after_powercycle_via_nx.py
validate_v10s4_nonfft_selftest_after_powercycle_via_nx.py
```

V10S5 has a planned NX-side validation stub in the same directory, but it must
not be used as proof of hardware validation until a V10S5 BOOT hash and SD
payload exist.

## Staging

- `stage_v9a_spec9_payload_via_nx.py`: historical V9A staging helper.
- `nx_experiments\sdr_fpga_offload_test\scripts\stage_version_to_sdr_sd.py`: current versioned SDR `/sd` staging helper.

Do not stage unless the local artifact gate in `AGENTS.md` passes.

## MATLAB And Environment

- `run_psd_reference_tests.m`
- `run_hdl_feasibility_check.m`
- `run_builtin_power_hdl_generation.m`
- `freeze_environment.m`
- `list_xc7z_parts.tcl`

`build_ascii_workspace_seed.ps1` is an early workspace-seed helper. It now
copies current route docs and the archive rather than relying on obsolete root
handoff files.
