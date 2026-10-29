# AGX设备工作区

[B210 USB发射设备](b210/README.md) · [P201网口接收设备](p201/README.md) · [项目文档](../docs/README.md)

| 设备目录 | 本机程序/运行文件 | 硬件连接 |
| --- | --- | --- |
| `b210/` | B210状态/初始化入口、有限TX程序、专用UHD运行时 | USB；serial2508504；A7-100T |
| `p201/` | 既有Controller健康入口、sdrd源码和AGX配置入口 | 192.168.1.10:43110；RX1/RX0/A_BALANCED |

论文数据与模型已迁出，本目录不提供数据集链接。
P201 `programs/` 链接指向 `src/` 与 `deploy/agx/`；B210保留本地设备工具，旧实验快捷链接已删除。
B210二进制/固件在Git外的`local-assets/devices/b210/`，与P201的`/sd/sdr-agent/`发布目录无关。
历史实验只从[验证索引](../docs/validation/README.md)按需读取，原IQ与哈希不迁移或改写。
