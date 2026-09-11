# B210：AGX USB设备

[设备总入口](../README.md)

- `b210.py status`：校验专用运行时并查看USB状态，无发射/接收流。
- `b210.py probe --output /var/tmp/sdrharness-dev/b210-agx-<唯一标识>`：有界加载FX3与A7-100T运行时镜像、检查serial2508504、USB3及两次寄存器回环，无RF流。
- `runtime/`：从NX迁来的UHD4.1.0.5-3程序及专用镜像；manifest逐文件校验。系统libuhd与NX同版本同哈希，直接复用，不覆盖全局库/镜像目录。
- `programs/campaign.py`：统一收发工程编排入口，P201接收继续由既有Controller负责。
- `programs/rml2018a-tx.py`：既有有限TX helper的链接，历史文件名仍含nx；现在支持AGX本机或NX。没有精确GO不会发送数据。
- `dataset/`：共享RadioML2018A目录的链接。

```bash
python3 -B devices/b210/b210.py status
local-assets/amc-eval/runtime/venv/bin/python -B devices/b210/programs/campaign.py --help
```

新campaign默认`--tx-host agx`、TX0/RX20；创建计划时才可指定host或增益，执行使用固定计划。
`--tx-host nx`保留旧主机路径，默认值不等于已验证射频参数。源码/运行时改变必须新campaign。
AGX后端本机暂存/启动/回收外部B210，不再SSH到NX；P201仍是唯一生产受控接收设备。
迁移验证未发射，低增益有线收发尚须确认实际连接与有限计划；不要直接沿用空口80/40。

本板只能加载`ee03a9e3…fcf9b`的A7-100T镜像，不能加载A7-200T或普通B210镜像。
这些是B210 USB运行时镜像，不是P201 FPGA聚合或BOOT文件；不写EEPROM/flash。
`runtime/nx-reference/`仅保留迁移来源；旧激活脚本使用NX绝对路径及全局镜像安装，不在AGX直接执行。
NX原目录和其历史数据不删除；AGX只复用现有一份RML2018A，不复制NX的数据集或系统修复备份。
