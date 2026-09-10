# P201 Pro embedded system

当前状态与读取范围见[项目文档入口](../docs/README.md)；[系统历史验证](../docs/validation/README.md#组件目录中的历史实验)按需读取。

This directory tracks only the configuration and evidence needed to optimize
the P201 Pro embedded Linux/IIOD data path. It does not contain credentials,
vendor firmware dumps, SD images, or BOOT binaries.

The first rule for any system optimization is to measure and preserve the
current state. Changes to socket buffers, process affinity, IIOD arguments, or
kernel configuration must be independently reversible. FPGA/MMIO and
`BOOT.bin` work is outside this project.

The SDR-local control plane is under [`sdrd`](sdrd). It is a C11 daemon with a
read-only shadow mode, a bounded controlled Linux/IIO mode and strict
capability negotiation. The active path is Linux/IIO RX transport to AGX
software aggregation.
