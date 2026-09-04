# NX B210 RF A 到 P201 RX1 链路验证 — 2026-09-04

## 结论

- 当前 B210 天线插在面板 `RF A / TX/RX`；该物理口实测应使用 UHD
  `channel 0`，UHD 运行时将其显示为 `FE-TX2`。有限发射时 RF A TX
  指示灯由用户现场确认点亮。
- P201 天线现已插在面板 `RX1`，不是 `TRX1`。SDRD 当前单通道路径为
  软件 RX0 / AD9361 `voltage0,1`，RF 输入读回 `A_BALANCED`。现场照片
  `IMG20260904154905.jpg` 清楚显示电缆接在 `RX1`，照片 SHA-256 为
  `ded9048dc55949d48f511d206618a9b77dc9d80c4bf50f4d038e2c4064547beb`。
- P201 已证明能够完成有界 Linux/IIO RX 采集；P201 前面板灯不亮不表示
  接收未工作。
- 433.92 MHz 同参数频谱对照已经确认 **P201 通过物理 RX1 收到了 B210
  RF A/channel 0 的信号**：发射时在预期 `+100.098 kHz` 处出现尖峰，
  该频点相对停发对照提高 `52.875 dB`，而频谱中值噪声只变化约
  `0.354 dB`。这证明射频链路可用，但不等同于 RML2018A 波形发射、
  Mamba 推理或端到端调制识别已经完成。

## 最终可复用配置

| 设备 | 项目 | 本次确认值 |
| --- | --- | --- |
| NX/B210 | 设备 | `MyB210`，serial `2508504`，USB 3.0，UHD `4.1.0.5-3` |
| NX/B210 | 物理发射口 | 面板 **RF A / TX/RX**，该口接发射天线；RF B 未使用 |
| NX/B210 | UHD 选择 | `--channels 0 --ant TX/RX`；运行时显示 `TX Channel: 0 / FE-TX2` |
| NX/B210 | 射频参数 | 433.920 MHz LO、2.5 MS/s、500 kHz 模拟带宽、70 dB gain、幅度 0.2 |
| NX/B210 | 验证波形 | `SINE`，基带偏移 `+100 kHz`，因此空口单音约为 434.020 MHz |
| P201 | 物理接收口 | 面板 **RX1** 接接收天线；不是 `TRX1`，也不是 `RX2`/`TRX2` |
| P201 | SDRD/IIO 路径 | SDRD 软件 RX0，AD9361 `voltage0,1` I/Q，仅启用一个 RX 通道 |
| P201 | RF 输入读回 | `A_BALANCED`；不得把 AD9361 的 A/B 名称直接当作面板口名 |
| P201 | 验证参数 | 433.920 MHz、2.5 MS/s、1 MHz RF 带宽、手动 50 dB gain |
| P201 | 有界捕获 | 每次 65,535 个复数 int16，即 262,140 字节；AGX 内存 FFT，不落原始 IQ |
| 现场条件 | 天线与距离 | 两端均无功放，室内约 5 米，弹簧天线标称 100 MHz--6 GHz |

本次 B210 验证命令的关键参数如下；只能在相同天线、距离、合法频段和有限
时长条件下复用：

```bash
timeout --signal=INT --kill-after=2s 30s \
  /usr/lib/uhd/examples/tx_waveforms \
  --args type=b200,serial=2508504 \
  --channels 0 --ant TX/RX \
  --freq 433920000 --rate 2500000 --bw 500000 \
  --gain 70 --wave-type SINE --wave-freq 100000 --ampl 0.2
```

P201 对应的 SDRD/1 profile 参数顺序为：

```text
APPLY_PROFILE <generation> 433920000 2500000 1000000 manual 50 1
CAPTURE_IQ_INLINE <generation> 65535 262140 <feature-id> 1000
```

最后一个 `1` 表示只启用一个复数 RX 通道；在当前部署中它对应软件 RX0 /
`voltage0,1`，现场天线必须接 `RX1`。每次都必须先 `START_SESSION`，结束或
异常时执行 `STOP_SESSION` 并检查 `restored=true`，不能裸写 IIO 属性。

这里最容易混淆的是：这块 B210 克隆板的面板 `RF A/TX-RX` 实测对应
UHD `channel 0`，但 UHD 把该前端打印成 `FE-TX2`。后续应以“物理口 +
channel 0 + 已点亮的 RF A TX 灯”这组三重证据为准，不能仅凭前端名称
里的数字选通道。

## 为什么早期没有确认出来

1. **最初选错 B210 通道。** 曾按 `FE-TX1` 的名字选择 channel 1，但当前
   天线实际在 RF A；面板灯试验后来证明 RF A 必须选 channel 0/`FE-TX2`。
   channel 1 发射时，信号并没有从接天线的物理口正常送出。
2. **早期检测量不适合窄带单音。** 2.45 GHz 对照使用 20 dB TX gain、
   20 dB RX gain，并比较整个约 1 MHz 接收带宽的 RMS。单音只占很少的
   FFT bin，宽带 RMS 只增加 0.25967 dB，无法排除环境噪声变化。
3. **把“不亮灯”误当成“没有接收”。** P201 LED1/LED2 是 RF 通道状态灯，
   不是功率表；当前 Linux/IIO `sdrd` 没有驱动这些前面板灯。因此 P201
   灯不亮与 IQ buffer 是否成功采集没有必然关系。
4. **RX1/TRX1 需要物理对照。** `A_BALANCED` 只说明 AD9361 的内部 RF1
   选择，不能单独证明机箱外部 SP2T 当前接到了 `RX1` 还是 `TRX1`。
   相同 50 dB RX gain 下，TRX1 发射时峰突出度为 13.606 dB，而 RX1 为
   57.246 dB，现场照片与实测共同确认当前主要接收路径是 RX1。

所以早期 0.26 dB 的结果被正确保留为“证据不足”，并非测试程序假装成功。
最终结论来自正确物理端口、同一接收增益、停发/发射/再停发三段对照，以及
预期 `+100 kHz` FFT 峰随发射启停出现和消失。

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

## 早期 2.45 GHz 空口对照

正确的 RF A/channel 0 下做了同参数即时对照：2.450 GHz 接收中心、
2.5 MS/s、1 MHz RF 带宽、P201 固定 20 dB、8,192 样本；B210 发射为
100 kHz 正弦偏移、20 dB TX gain、0.2 数字幅度。

| 状态 | P201 band power |
| --- | ---: |
| B210 停止（sequence 11） | -62.52387 dBFS |
| B210 RF A/channel 0 发射（sequence 12） | -62.26420 dBFS |
| 差值 | +0.25967 dB |

两次捕获均零丢样、零溢出、零削顶并完成状态恢复，但 0.26 dB 变化不足以
排除瞬时噪声起伏，因此该轮本身不作为链路证明。下面的 433.92 MHz、
50 dB RX gain 频谱试验取代了这一未确认状态。

## 433.92 MHz RX1 频谱确认

用户先把同一根接收天线从 `TRX1` 换回照片所示的 `RX1`。正式对照固定为：

- P201：433.920 MHz 中心、2.5 MS/s、1 MHz RF 带宽、手动 50 dB，
  每次 65,535 个复数 int16 样本（262,140 字节）；
- B210：`type=b200,serial=2508504`、RF A `TX/RX`、`channel 0`、
  433.920 MHz LO、2.5 MS/s、500 kHz TX 带宽、70 dB TX gain、幅度
  0.2、`+100 kHz` SINE；实际单音位于约 434.020 MHz；
- 室内约 5 米、两端无功放，天线标称 100 MHz--6 GHz；B210 发射由
  `timeout` 限制在 30 秒内，捕获完成后立即以 SIGINT 停止；
- 三次接收（发射前、发射中、发射后）总理论上限 786,420 字节，IQ 只在
  AGX 内存中做 FFT，不写入文件。开始前 AGX 可用 840,609,853,440 字节。

sequence 38 的发射前基线完成后已恢复。决定性比较使用紧邻的发射中
sequence 39 与发射停止后 sequence 40：

| 指标 | 发射中，sequence 39 | 停发后，sequence 40 | 差值 |
| --- | ---: | ---: | ---: |
| RMS | -30.737849 dBFS | -54.878486 dBFS | +24.140637 dB |
| 预期频带峰偏移 | +100.097656 kHz | +125.732422 kHz | 发射时命中目标 |
| 预期频带峰功率 | -32.056300 dBFS/bin | -84.931469 dBFS/bin | +52.875169 dB |
| 频谱中值噪声 | -89.301929 dBFS/bin | -89.655698 dBFS/bin | +0.353769 dB |
| 峰高于中值噪声 | 57.245629 dB | 4.724229 dB | +52.521399 dB |

两次均为 65,535 样本、262,140 字节、零丢样、零溢出、零削顶，并由
SDRD 确认 `restored=true`。发射时的 IQ SHA-256 为
`a8ebc3567751347e48010b7b859fd3fce7a5153f92372ae45bbc05b8641b6bab`；
停发后为
`c35a5e8dabed75d5c26e9df0800c3daa0ff35334ab5891e9e4cdf1c91d34c210`。
这些哈希仅标识内存中收到的两个有界缓冲区，原始 IQ 没有落盘。

此前把天线临时接到 `TRX1` 的同为 50 dB RX gain 的诊断中，发射前
sequence 36 的峰突出度为 4.211 dB，发射中 sequence 37 为 13.606 dB；
能检出信号但明显弱于 RX1 的 57.246 dB。结合当前 `A_BALANCED` 读回，
这说明目前外部 RF1 路径主要选择 `RX1`；LED1 只能表示 RF 通道 1 的
TX/RX 状态，不能区分 `RX1` 与 `TRX1`，也不是信号强度指示。

## 恢复与清理

最后一次接收后，P201 恢复为 2.4 GHz LO、30.72 MS/s、18 MHz RF 带宽、
`slow_attack`、`A_BALANCED`；RX buffer 为 0，四个 scan element 均为 0。
SDRD 保持一个 PID 和一个 `192.168.1.10:43110` 监听器，健康观察仍报告
online/healthy/IIO visible/can retune/can capture IQ 全部为 true。NX 上无
残留 `tx_waveforms` 进程。

AGX 临时目录
`/var/tmp/sdrharness-dev/b210-p201-rx1-link-20260904/` 和本轮
`/var/tmp/sdrharness-dev/p201-rx1-port-proof-20260904/` 均按精确 realpath
校验后删除并确认不存在；P201 上无匹配的
`/tmp/sdr-agent-dev/agx-sweep-20260904*` 或
`/tmp/sdr-agent-dev/rx1-port-proof-*` 临时目录。没有用户可见结果或模型
资产被删除。
