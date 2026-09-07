# P201 → AGX seed44 四窗口联调验证 — 2026-09-04

## 结论与边界

当前 RML2018A D8 seed44 权重已经接到版本化的候选精查和四窗口输入链路：

```text
P201 RX1 / RX0 / voltage0+1 / A_BALANCED
  -> AGX 同窗频谱精查与 RecognitionTarget
  -> 一次连续 4,096 complex-int16 有界采集
  -> AGX 切分为 4 × 1,024 窗口
  -> 每窗不去 DC、不重采样、复数单位 RMS、planar f32
  -> 同一个 mode-0600 32,768-byte spool 的四个精确 offset
  -> seed44 FP32 CUDA/Mamba Worker 顺序推理
  -> 四窗 top-1 多数票联调摘要
  -> 删除 spool、停止 session、恢复并复查 P201
```

这只是 `integration_only` 联调。生产 capability 仍为 false，现场没有独立标签，
所以 Worker 的类别输出不能作为真实调制结论或准确率样本。模型重训或微调没有
在本次执行，也没有修改 checkpoint。

## 固定资产与合同

| 资产 | SHA-256 |
| --- | --- |
| seed44 `best.pt` | `e5a1bccdaf4b0290f41b26cb05b8b98565df9d5b07147727d79bbf43f6cb42dd` |
| `rml2018a-d8-current.integration-profile.json` | `7d2347550939be13d3ccde84add514ca5b4e549783fbc8e724124b4f0f4358ba` |
| `legacy-adc-unit-rms-v0.json` | `20f2f21b9d01a5163806a2b1e88c2e1ff0975647eb9da27071ea3f1d61a80303` |
| experimental Worker | `928eaa61e9b9451642a839cc8a25135d7338bb80dcf8b728513755b311aab9f1` |
| 验证用 release Controller | `ecf5a616f33d658a0f8862953d186a99c4a3abb92330474b0b73de25692b552b` |
| 验证后加强关系校验的 release Controller | `1c1f38b2e45cb3ca32b7c92b5cecedeaaee641084ca17c85f64339eb005cdf30` |

Profile 固定物理 RX1、软件 RX0、`A_BALANCED`、2.1 MS/s、1.5 MHz、手动
50 dB、100 ms settle、4 × 1,024 点、16,384-byte P201 原始 IQ 和
32,768-byte AGX 模型输入。manifest 与预处理规范都必须是仓库内非 symlink
有界文件且通过精确哈希校验。模型 ID/哈希必须与每个 Worker 响应一致。

`ModelReadyBatch` 的 golden fixture 为
`raspberry-pi/sdr-agent/controller/tests/fixtures/model-ready-batch-v1.json`：

```text
raw bytes/SHA-256:   16,384 / 9ddea8749993725208a8828bc68294396a9a50e4b5a4d242625d462913e518b6
model bytes/SHA-256: 32,768 / 30a315ea74bbb39719e58498651f9e54e24d28129e10367d01dc3a602a1275df
```

## 同窗候选精查

每个新的 `SweepPoint` 都记录 `SpectralSummary v1`。AGX 对同一次 complex IQ
做有界 radix-2 FFT、Hann 窗、仅用于频谱测量的均值/DC 抑制、频谱噪声底、
最强频率、实测 peak-to-noise SNR，以及最强连通频谱分量内的 99% 占用带宽。
模型预处理仍明确不去 DC；频谱测量算法不会静默改变模型张量。

第一次精查正确地没有进入 Worker，因为旧的全频带 99% 累加把噪声起伏也算入，
得到 2,027,710 Hz，占用带宽超过 1.5 MHz profile 门限。该失败关闭事件之后，
P201 已停止并恢复。算法随后改为只在最强连通分量中计算 99% OBW，并增加
单音频率/SNR/带宽回归测试。成功精查得到：

```text
tuned center:          433,920,000 Hz
estimated target:      433,330,913 Hz
peak frequency:        433,330,913 Hz
FFT/bin:               4,096 / 512.6953125 Hz
peak/noise:            -60.45267 / -92.632454 dBFS
measured SNR:          32.179783 dB
occupied range:        433,330,400 .. 433,331,426 Hz
occupied bandwidth:    1,539 Hz
dropped/overflow/clip: 0 / false / 0
health/RX identity:    healthy, flags=0 / verified RX1 A_BALANCED
```

`RecognitionTarget` 使用这些同窗值和精查 sequence `4`，不再用不同增益的旧
扫频候选反推噪声。目标在 5 秒内使用；精查 gain 必须与 profile 的 50 dB
完全一致。

## 有限实机计划与结果

Feature ID 为 `ch4-seed44-batch-20260904-v1`。执行前 P201 只有 PID `17136`
的一个 `sdrd` 和一个 `192.168.1.10:43110` listener；二进制 SHA-256 为
`77d98a005305a4b7531fc3f133e9b4af521e60b065b29fcc304b4c7db80c45ae`。
密码文件是 regular mode-`0600`，严格 host-key SSH 和 TCP 探测通过。

AGX `/var/tmp` 和 `/run` 可用空间分别为 `809,008,054,272 B` 和
`13,108,662,272 B`。单次成功路径最多接收 32,768 B 空口 IQ，spool 最多
32,768 B。包括一次资格拒绝、一次原因诊断和最终成功路径在内，所有计划上限
合计 81,920 B，实际从 P201 接收 65,536 B；没有保存 raw IQ。

最终 capture 为 request `44002`、session `20260904045`、P201 sequence `5`：

```text
samples/bytes:         4,096 / 16,384
capture elapsed:       3,799 us / 1,000 ms limit
dropped/overflow:      0 / false
health:                healthy, flags=0, iio_adapter
model-ready SHA-256:   03673c85e0361cd1693f2a2a276d68d610ad5ec135d4cec0ef040e8e3e234471
window raw RMS codes:  3.59416, 3.52765, 3.66958, 3.70520
normalized RMS:        1.000000019, 0.999999999, 0.999999984, 1.000000001
clipped samples:       0, 0, 0, 0
window offsets:        0, 8,192, 16,384, 24,576 bytes
```

同一个有限 Worker 先处理一次 health probe，再处理四个窗口后正常退出。四窗
top-1 结果为：

| 窗口 | provisional top-1 | confidence | inference |
| ---: | --- | ---: | ---: |
| 0 | `22:OOK` | 0.5675365 | 111,590 us |
| 1 | `18:64QAM` | 0.51707155 | 43,572 us |
| 2 | `18:64QAM` | 0.73621595 | 36,556 us |
| 3 | `18:64QAM` | 0.7942079 | 36,133 us |

联调多数票为 provisional numeric ID `18`，3/4 一致，agreement `0.75`，投票
窗口平均 confidence `0.68249846`。这不是校准概率或开放集拒识；在没有独立
标签的房间环境下也不能声称实际收到 64QAM。

## 恢复、清理与测试

最终读取 P201 得到：

```text
RX LO=2,400,000,000 Hz
sample rate=30,720,000 samples/s
RF bandwidth=18,000,000 Hz
gain mode=slow_attack
rf_port_select=A_BALANCED
RX buffer=0
scan mask voltage0..3=0000
sdrd PID/listener=17136 / exactly one 43110 listener
```

Controller 最终 observe 为 online/healthy、flags zero、retune/capture true 和
verified RX1 identity。Worker socket 已移除，`/run/sdr-agent/iq` 为空，P201
对应 inline 临时目录不存在。仓库外 feature 根在记录完成后删除。

验证同时通过 Controller 68 个 lib tests、11 个 terminal tests、Clippy
`-D warnings` 和 venv 中的 3 个 Worker tests。系统 Python 没有 Torch，因此
Worker tests 必须使用保留的 AMC venv；这不是运行时失败。

实收后只加强了 profile 相对路径解析、频谱字段内部关系和目标 SNR 关系的
失败关闭校验；第二个 Controller 哈希是该加强版本，已重跑上述完整测试但没有
声称它执行了额外 RF capture。

尚未完成的生产工作保持未勾选：`rf_preprocess_v1`、RF-aligned checkpoint、
标签顺序、精度选择、校准/拒识、Worker health capability、GPU gate、Runner/
Agent/Web 回灌、错误/取消实机矩阵和 bounded acquisition overload。
