# HDL Sources

Current canonical RTL sources:

- `p201pro_ad9361_power_tap_axi_regs.v`: main AXI-Lite tap/register RTL.
- `p201pro_ad9361_power_tap_cdc.xdc`: CDC/timing constraints for the tap.
- `p201pro_stream_power_axi_regs.v`: earlier stream-power AXI register wrapper.

Versioned or experimental variants live under `experiments/` and are copied into
versioned artifact directories under `boot_experiments/` when packaged.

Do not silently change an existing register meaning. Update `VERSION_ROUTE.md`,
the artifact README, and the applicable contract document for register ABI
changes.
