# P201 Pro embedded system

This directory tracks only the configuration and evidence needed to optimize
the P201 Pro embedded Linux/IIOD data path. It does not contain credentials,
vendor firmware dumps, SD images, or BOOT binaries.

The first rule for any system optimization is to measure and preserve the
current state. Changes to socket buffers, process affinity, IIOD arguments,
kernel configuration or FPGA images must be independently reversible.

The first SDR-local control-plane slice is under [`sdrd`](sdrd/). It is a C11,
read-only shadow daemon with strict capability negotiation. Its default config
matches the currently loaded original `BOOT.bin` and keeps FPGA MMIO disabled.

The staged custom-FPGA direction is documented in
[`P201_AGENT_FPGA_DIRECTION.md`](docs/P201_AGENT_FPGA_DIRECTION.md). It keeps
the original BOOT as golden rollback and adds acceleration only in measured,
capability-gated slices.
