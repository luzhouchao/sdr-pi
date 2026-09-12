# B210：AGX USB设备

[设备总入口](../README.md) · [当前实验配置与复现](../../docs/reference/RML2018A_RF_REPRODUCTION.md)

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
用户2026-09-12最新确认RF A TX/RX经20dB衰减器及同轴接P201 RX1；
[有线收发与停止验证](../../docs/validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12同轴衰减接收幅度与主动停止)已完成，波形质量仍待改善。
[20dB匹配增益对照](../../docs/validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-1220db衰减与匹配增益对照)另有记录，不据小批准确率确定最佳衰减或增益。
[干净单音LO对照](../../docs/validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12干净单音与lo跟随分量)已定位LO跟随强分量；
独立入口及固定预算见[说明](../../docs/reference/RML2018A_FULL_RF_CAMPAIGN.md#独立有线lo参考诊断)。该单音诊断不改变数据集发射参数，也不启用校准/滤波。
该入口的`plan --experiment gain-pair`已完成[两次单音幅度/增益配对](../../docs/validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12数字幅度与硬件增益配对)，
LO分量下降约7.3dB且有效信号相近；该单音结果不代替调制波形验证。
随后已完成[OOK/QPSK调制波形配对](../../docs/validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12radioml调制波形的幅度增益配对)，
新`gain-pair-pilot`只允许AGX TX60/RX40、峰值0.632455532和原批次4267/22016；
标准全库profile峰值仍为0.2，24类及低源SNR仍待验证，详见[使用范围](../../docs/reference/RML2018A_FULL_RF_CAMPAIGN.md#有限radioml幅度增益配对)。
增益只能在新有限计划中登记，改变衰减前先停发。
迁移后的[首次天线48条实测](../../docs/validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-11agx本机b210天线收发48条)
已完成显式80/40的有限发射/接收/识别；它不改变新plan默认值或完成有线、全库验收。

本板只能加载`ee03a9e3…fcf9b`的A7-100T镜像，不能加载A7-200T或普通B210镜像。
这些是B210 USB运行时镜像，不是P201 FPGA聚合或BOOT文件；不写EEPROM/flash。
`runtime/nx-reference/`仅保留迁移来源；旧激活脚本使用NX绝对路径及全局镜像安装，不在AGX直接执行。
NX原目录和其历史数据不删除；AGX只复用现有一份RML2018A，不复制NX的数据集或系统修复备份。
