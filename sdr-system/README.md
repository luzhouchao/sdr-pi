# P201 Pro embedded system

This directory tracks only the configuration and evidence needed to optimize
the P201 Pro embedded Linux/IIOD data path. It does not contain credentials,
vendor firmware dumps, SD images, or BOOT binaries.

The first rule for any system optimization is to measure and preserve the
current state. Changes to socket buffers, process affinity, IIOD arguments, or
kernel configuration must be independently reversible. FPGA/MMIO and
`BOOT.bin` work is outside this project.

The SDR-local control plane is under [`sdrd`](sdrd/). It is a C11 daemon with a
read-only shadow mode, a bounded controlled Linux/IIO mode and strict
capability negotiation. The active path is Linux/IIO RX transport to AGX
software aggregation.
