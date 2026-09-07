# P201 → AGX AMC-Mamba 实验性端到端验证 — 2026-09-04

## 准入结论

本记录只验证一条受限实验链路：P201 从物理 `RX1` 做一次有限 Linux/IIO
采集，AGX 将 inline complex-int16 IQ 转为 planar float32 临时文件，由
CUDA/Mamba Worker 返回相关联的识别响应，并在结束后删除临时 IQ、恢复
射频状态。它不打开生产能力：`recognizer_available` 仍为 `false`，结果的
`admission` 必须为 `experimental_rf_only`，RML2018A 名称必须带
`provisional:` 前缀。

原因是 seed44 的冻结训练加载器直接使用数据集原始 float32 IQ；真实 P201
ADC 幅度没有与训练分布建立可迁移标定。相同 8,192 条固定测试样本的横向
实验为：原始输入 `63.5986%`，逐窗口复数单位 RMS 后 `53.2959%`，去直流
后 `42.2729%`，去直流加单位 RMS 后 `41.3574%`。按各 SNR 档训练样本 RMS
中位数缩放仍只有 `53.3936%`，均值缩放为 `20.2026%`。这些数字不是模型
随运行次数退化，而是不同预处理造成的一次性输入分布偏移。单位 RMS 仅作为
本次把 ADC 窗口送入旧权重的实验桥接；正式方案需要在 4090 使用固定 RF
预处理重新训练或微调，并重新验证完整 test split。

## 实现边界

数据路径固定为：

```text
P201 RX1 / software RX0 / voltage0,1
  -> SDRD/1 CAPTURE_IQ_INLINE（1024 个 ci16 复数样本）
  -> AGX 检查丢样、溢出、削顶与状态恢复
  -> 不去直流、不重采样、逐窗口复数单位 RMS
  -> mode-0600 planar f32 临时文件（8192 B）
  -> 单线程、queue/backlog=1 的 Unix-socket CUDA/Mamba Worker
  -> provisional top-1 + 最多 8 个 alternatives
  -> 删除临时文件
```

模型清单为
`jetson-agx/sdrharness/config/amc/rml2018a-d8-seed44.experimental.json`，
checkpoint SHA-256 为
`e5a1bccdaf4b0290f41b26cb05b8b98565df9d5b07147727d79bbf43f6cb42dd`。
Worker 严格核对 checkpoint、配置、11 个最小源码文件及标签文件，使用
FP32、真实 Mamba2 CUDA 后端和一个 Torch CPU thread。systemd 模板明确为
experimental，故没有 `[Install]` 段，不能随系统自动启用。

最终 release Controller、Worker 源文件和实验 manifest 的 SHA-256 分别为：

```text
0fb0a6a790e75603d3a2cf3c8c87021f149e89e6138aa379a680e2e50e068685  sdr-agent-controller
928eaa61e9b9451642a839cc8a25135d7338bb80dcf8b728513755b311aab9f1  amc-mamba-worker.py
1b7ad226bf88b8f8d363df384ddcbfb65c83db51b0ec305742be2ad5a082698e  rml2018a-d8-seed44.experimental.json
```

Controller 新增直接的 `--mode recognize-live`：它创建一个受控 SDRD session，
应用单 RX profile、捕获 inline IQ、停止 session、验证 P201 健康，写入私有
spool，调用现有 backend-neutral `UnixRecognizerAdapter`，随后通过 RAII 在
成功和错误路径删除 IQ 文件。现有 `--mode cancel --session-generation N`
仍是独立连接的直接停止路径。

## 现场 RX 前冻结计划

本节在现场捕获前写入。没有安排或启动任何 RF 发射。

| 项目 | 冻结值 |
| --- | --- |
| feature ID | `amc-p201-live-e2e-20260904-v1` |
| 中心频率 / 点数 | `433,920,000 Hz` / 1 点 |
| P201 输入 | 面板 `RX1`；软件 RX0 / `voltage0,1`；一个复数通道 |
| 采样率 / RF 带宽 | `2,100,000 / 1,500,000 Hz` |
| RX gain / settle | 手动 `50 dB` / `100 ms` |
| 样本 / capture timeout | `1,024` complex-int16 / `1,000 ms` |
| P201 最大原始 IQ | `1,024 × 4 = 4,096 B` |
| AGX 最大 spool IQ | `1,024 × 2 × 4 = 8,192 B` |
| 有限 IQ 表示总量 | `12,288 B`；P201 数据经 inline 接收后不持久保存 |
| Worker deadline | `5,000 ms`；单线程、listen backlog 1 |
| 估计时长 | 按 settle + capture + Worker 上限为 `6.1 s`；各 SDRD 命令另受 5 s socket timeout 约束 |
| AGX 临时根 | `/var/tmp/sdrharness-dev/amc-p201-live-e2e-20260904-v1/` |
| P201 临时根 | `/tmp/sdr-agent-dev/agx-recognize-2026090402-7002/` |
| 直接停止 | Controller `--mode cancel --session-generation 2026090402`，或终止客户端触发 SDRD 断连恢复 |

捕获前 AGX `/var/tmp` 可用 `810,188,181,504 B`，远大于精确上限。P201
密码文件为 regular mode-`0600`，严格 host-key SSH 通过。`sdrd` 只有 PID
`1738` 和一个 `192.168.1.10:43110` listener，当前二进制 SHA-256 为
`458365bcd2231b622b8175ca618726ed9d7e16efb0e5c5c36f4ea22e30ae44dd`；
持久二进制、配置与启动脚本均存在。AGX 没有 `tx_waveforms`、
`benchmark_rate` 或 `uhd_siggen` 进程，计划对应的 P201 临时目录不存在。

捕获前 P201 状态为：

```text
RX LO=2400000000
sample rate=30720000
RF bandwidth=18000000
gain mode=slow_attack
RF port select=A_BALANCED
RX buffer enable=0
scan elements voltage0..3=0,0,0,0
```

`slow_attack` 下瞬时 hardware gain 会自动变化，因此恢复判据比较 LO、采样率、
带宽、gain mode、RF port、buffer 和 scan mask，不把瞬时 gain 数字错误地当作
持久配置。

## 已完成的离线 Worker 链路

真实 CUDA Worker 自检严格加载上述 checkpoint，返回
`production_enabled=false`。随后从 RML2018A 固定 test split 选取全局样本
`81923`（SNR `20 dB`、数字类别 `0`），只读取该行并转换为 8,192-byte
mode-`0600` 单位 RMS fixture。fixture SHA-256 为
`512bf72a5663d8da832157d6ff58d11c77a96e12d83c267d9c44425cbac6ba87`；
原始/转换后复数 RMS 为 `1.43456137 / 0.99999988`。

这条 fixture 经 `UnixRecognizerAdapter` 调用同一 Worker，正确返回
`provisional:00:32PSK`，置信度 `0.99136764`，响应中的 checkpoint 哈希、
request/session/candidate 关联、线程数和时延均通过 Rust 校验。该结果只证明
文件到模型的协议接线正确，不把 provisional 名称升级为可信标签。

## 现场结果、恢复与清理

冻结计划经 Rust `validate_live_plan` 再次校验，并在接触硬件前打印完整 JSON、
P201 `4,096 B` 上限和 AGX `8,192 B` 上限。唯一一次现场采集完成，工具测得
端到端墙钟时间 `3.572 s`：

```text
SDRD sequence=41
samples_captured=1024
bytes_transferred=4096
dropped_samples=0
overflow=false
capture elapsed=3691 us / limit=1000 ms
health=true, flags=0, source=iio_adapter
raw complex RMS=3.85111084 ADC codes
clipped_samples=0
normalization scale=0.25966534
normalized complex RMS=0.999999996
spool bytes=8192
transient_iq_removed=true
```

CUDA/Mamba Worker 返回 `provisional:18:64QAM`、置信度 `0.42434704`；第二名
为 `provisional:17:AM-SSB-WC`、`0.41570273`，推理/Worker 总时延为
`180,870 / 182,435 us`。请求 `7002`、session `2026090402` 和 candidate
`live-rx1-433920000` 在 capture、Worker 响应及最终 report 中完全一致，模型
哈希也与 manifest 一致。

这次明确没有发射，输入只是 433.92 MHz 的室内环境信号/噪声，也没有开放集
拒识或置信度校准。因此上述类别不是“现场确认有 64QAM”，只能证明实收 IQ
确实到达了模型并得到结构有效的实验响应；不得用它计算空口准确率。后续若要
验证识别正确率，需要单独批准 NX/B210 发射带已知标签的有限 RML2018A 波形，
并先冻结发射缩放、重采样和窗口对齐。

结束后再次读取 P201 sysfs，LO `2.4 GHz`、采样率 `30.72 MS/s`、带宽
`18 MHz`、`slow_attack`、`A_BALANCED`、buffer `0` 和四个 scan element
`0,0,0,0` 均与捕获前一致。`sdrd` 仍只有 PID `1738` 和一个 43110
listener，Controller 的结束观察也为 online/healthy/IIO visible/can retune/
can capture IQ 全 true。P201 精确临时目录不存在。

Worker 最后一个健康探针继续返回 experimental/production-disabled 及正确模型
哈希，随后按本次 `max_requests=4` 有界设置正常退出；AGX 无 Worker 或 TX
残留进程。实时 `recognition-2026090402-7002.f32` 已由 RAII 删除，仅用于离线
协议检查的 8,192-byte fixture 随后以精确路径 `unlink`，两个已验证 realpath
的空目录以 `rmdir` 删除。AGX feature 根和 P201 feature 根均确认不存在。
fixture 与开发临时目录不可从回收站恢复，但 fixture 可从保留的 HDF5 第
81923 行按上述合同重新生成；数据集、checkpoint、结果和任何用户可见数据
均未删除。

本轮完成的是“选定有限 IQ 窗口进入本地识别”的第四章到第六章实验接线，
不是生产模型准入，也没有将识别结果接入自主 Runner/Agent observation。
