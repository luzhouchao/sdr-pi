# P201：AGX网口接收设备

[设备总入口](../README.md)

- `python3 -B devices/p201/p201.py health`：既有唯一Controller的严格只读健康检查。
- `programs/daemon-source/`：现有Linux/IIO有界RX服务源码链接。
- `programs/controller-source/`、`programs/agx-config/`：既有Controller源码和配置入口。
- `dataset/`：与B210共享同一份RadioML2018A，实际由AGX读取；P201不保存数据集或跑模型。

固定链路：P201 `192.168.1.10:43110` → AGX接收/存储/预处理/识别。
射频输入RX1/RX0/A_BALANCED。设备发布仍为`/sd/sdr-agent/current/`，本机Controller仍为
`/home/jetson/.local/lib/sdrharness/bin/sdr-agent`；本次只整理入口，没有移动或替换已安装制品。
这个目录不使用UHD/B210镜像，不提供TX、FPGA烧写或BOOT操作。
实操继续遵守[P201工作流](../../.codex/skills/p201-sdr-workflow/SKILL.md)。
