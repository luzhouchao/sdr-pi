# V8-Derived Low-NX-Load Experiment

Status: PC-side RTL experiment only. NOT BURNABLE. NOT HARDWARE VALIDATED.

This directory contains an experimental copy of the P201Pro AXI-Lite tap RTL for a small V8-derived rolling aggregate mode. It was copied from the required pre-V9A snapshot:

```text
E:\vivado\fpga_p201pro_accel\boot_experiments\v9a_spec9_work_snapshots\p201pro_ad9361_power_tap_axi_regs.pre_v9a_continue_20260608.v
```

Experiment RTL:

```text
hdl\p201pro_ad9361_power_tap_axi_regs.v
```

Main idea:

- keep SUM8/QUA8/AGG8 register identities and existing AGG8 data offsets;
- add `AGG_CONTROL[2]` as `auto_roll`;
- add read-only `AGG_SEQUENCE` at `0x17c`;
- let FPGA latch the latest aggregate and continue automatically after each `AGG_TARGET` window.

Report:

```text
E:\vivado\fpga_p201pro_accel\reports\p201_v8_derived_low_nx_load_design_20260608.md
```

Do not copy this to SDR `/sd`, do not package as a boot artifact, and do not use it for active NX/robot runtime integration until the normal OOC, integrated timing, artifact, and hardware validation gates are satisfied.
