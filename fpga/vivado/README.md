# Vivado Workspace

This folder is for generated local Vivado package/IP workspace contents.

Regenerable local directories include:

```text
vivado\ad9361_tap_ip_packager_project*
vivado\ip_packager_project
vivado\ip_repo
```

Build scripts in `scripts/` recreate the generated IP and project outputs.
The portable evidence is kept as text reports under `reports/` and manifests
under `boot_experiments/`.

It is safe to remove generated Vivado project/cache directories during cleanup
when no Vivado process is running.
