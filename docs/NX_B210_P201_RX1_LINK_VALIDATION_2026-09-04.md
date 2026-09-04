# NX B210 RF A 到 P201 RX1 链路验证 — 2026-09-04

## 结论

- 当前 B210 天线插在面板 `RF A / TX/RX`；该物理口实测应使用 UHD
  `channel 0`，UHD 运行时将其显示为 `FE-TX2`。有限发射时 RF A TX
  指示灯由用户现场确认点亮。
- P201 天线插在面板 `RX1`，不是 `TRX1`。SDRD 当前单通道路径为软件
  RX0 / AD9361 `voltage0,1`，RF 输入读回 `A_BALANCED`。
- P201 已证明能够完成有界 Linux/IIO RX 采集；P201 前面板灯不亮不表示
  接收未工作。
- 截至本记录，空口功率对照仍不足以证明 P201 收到了 B210。该项保持
  “未确认”，不得作为调制识别链路已经打通的证据。

## B210 端口辨识

板卡为 NX 上的 `MyB210`，serial `2508504`，UHD `4.1.0.5-3`，A7-100T
镜像，USB 3.0。照片显示天线位于 `RF A / TX/RX`，RF B 两口仍有保护帽。

两次 2.450 GHz 指示灯观察均使用有限 `tx_waveforms`，2.5 MS/s、500 kHz
模拟带宽、100 kHz 正弦偏移、20 dB TX gain、数字幅度 0.2、15 秒，且结束
后确认无 `tx_waveforms` 进程：

| UHD 选择 | UHD 前端名 | 现场结果 |
| --- | --- | --- |
| `--channels 1 --ant TX/RX` | `FE-TX1` | 未看到面板灯点亮 |
| `--channels 0 --ant TX/RX` | `FE-TX2` | RF A TX 指示灯点亮 |

因此后续使用当前 RF A 天线时固定选 `channel 0`。前端内部名称中的数字
不能替代面板指示灯和实际接线验证。

## P201 RX 工作性验证

受控 SDRD 在 `192.168.1.10:43110` 保持一个 PID、一个监听器。捕获只走
P201 Linux/IIO bounded RX 和 AGX 内存聚合，不修改 TX、FPGA、BOOT 或任意
IIO 属性，也不保存原始 IQ。

用于观察的计划为 2.4465--2.4535 GHz、500 kHz 步进、15 点，2.5 MS/s、
1 MHz RF 带宽、固定 20 dB RX gain、每点 8,192 个复数 int16 样本。有限
最大量为 491,520 字节，计划估算上限 30,000 ms，实测总耗时 19,375 ms。
AGX 开始前可用 840,637,296,640 字节。

结果 sequence 从 13 连续递增到 27。15 个点均满足：

- `samples_captured=8192`；
- `dropped_samples=0`、`overflow=false`、`clipped_samples=0`；
- `timeout.timed_out=false`；
- `health.healthy=true`、`health.flags=0`、
  `health.source=iio_adapter`。

P201 系统只读检查显示 `led0:blue`、`led1:blue` 的 trigger 均为
`heartbeat`，没有与 IIO RX buffer 绑定的证据。接收工作性应以上述 IQ
响应和恢复门禁判断，而不是以前面板灯为判断条件。

## 当前空口对照

正确的 RF A/channel 0 下做了同参数即时对照：2.450 GHz 接收中心、
2.5 MS/s、1 MHz RF 带宽、P201 固定 20 dB、8,192 样本；B210 发射为
100 kHz 正弦偏移、20 dB TX gain、0.2 数字幅度。

| 状态 | P201 band power |
| --- | ---: |
| B210 停止（sequence 11） | -62.52387 dBFS |
| B210 RF A/channel 0 发射（sequence 12） | -62.26420 dBFS |
| 差值 | +0.25967 dB |

两次捕获均零丢样、零溢出、零削顶并完成状态恢复，但 0.26 dB 变化不足以
排除瞬时噪声起伏。后续验证应使用正确 channel 0 做有限增益阶梯，并优先
保存一段有界 IQ 在 AGX 上比较预期 `+100 kHz` 频谱峰；在出现稳定、可重复
且高于基线的峰值前，空口链路仍为未确认。

## 恢复与清理

最后一次接收后，P201 恢复为 2.4 GHz LO、30.72 MS/s、18 MHz RF 带宽、
`slow_attack`、`A_BALANCED`；RX buffer 为 0，四个 scan element 均为 0。
SDRD 保持一个 PID 和一个 `192.168.1.10:43110` 监听器，健康观察仍报告
online/healthy/IIO visible/can retune/can capture IQ 全部为 true。NX 上无
残留 `tx_waveforms` 进程。

AGX 临时目录
`/var/tmp/sdrharness-dev/b210-p201-rx1-link-20260904/` 已按精确 realpath
校验后删除并确认不存在；P201 上无匹配的
`/tmp/sdr-agent-dev/agx-sweep-20260904*` 临时目录。没有用户可见结果或模型
资产被删除。
