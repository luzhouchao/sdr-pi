# P201 Pro embedded system

This directory tracks only the configuration and evidence needed to optimize
the P201 Pro embedded Linux/IIOD data path. It does not contain credentials,
vendor firmware dumps, SD images, or BOOT binaries.

The first rule for any system optimization is to measure and preserve the
current state. Changes to socket buffers, process affinity, IIOD arguments,
kernel configuration or FPGA images must be independently reversible.
