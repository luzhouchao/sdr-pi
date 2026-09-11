# SDR Harness for Jetson AGX Orin

P201 Pro SDR、Jetson AGX Orin、Rust 安全控制器、Pi Agent Planner 和后续 CUDA
识别后端的统一工程仓库。

主运行节点已从 Raspberry Pi 4B 调整为 Jetson AGX Orin。目标 clone 路径固定为
`/home/jetson/sdrharness`。Pi 上已经完成的控制、扫频、Web Console 和回滚证据继续
保留，但不再是新功能的算力或数据面目标。

设备入口已分为[B210 USB](devices/b210/README.md)和[P201网口RX](devices/p201/README.md)，
两者共享同一份RadioML2018A；目录与运行时说明见[设备工作区](devices/README.md)。

## 目标架构

```text
operator / trusted-LAN Web Console
                |
                v
       AGX SDR Harness
  Rust Controller + Pi Agent Planner
  local Spark (default) / operator-selected compatible API
  acquisition / aggregation / bounded CUDA/Mamba recognizer
                |
                v
      SDRD/1 over 192.168.1.x
                |
                v
      P201 Pro SDR + AD9361 Linux/IIO RX
```

AGX 负责 Agent、控制器、Web、扫频编排、结果存储、预处理和模型接入。当前
Planner 默认使用本机 Spark-X2.5-4B BF16；Web 配置的 OpenAI-compatible
Completions/Responses 接口继续保留为人工选择的 provider，不做自动云端切换。
实验 CUDA/Mamba Worker 已接通但仍禁止生产启用。P201 SDR 只运行 `sdrd`，负责
有界 RX 采集与传输，并保留独占所有权、限幅、停止和射频状态恢复。

## 当前状态

当前状态以[权威 checklist](docs/SDR_AGENT_PROJECT_CHECKLIST.md)为准，
下一独立交付以[实际推进顺序](docs/SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md)为准。

AGX 已接管 P201 接收和软件处理；网页、交互终端、脚本及恢复共用已安装的
`sdr-agent`。RF-v1、epoch-10 FP16 和识别工程闭环已有隔离验证，完整生产识别
尚未准入，`recognizer_available=false`。训练、微调及进一步模型诊断按用户选择暂停，树莓派保留为历史/回滚基线。
后续实验频段选择见[当前实验设置](docs/SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md#后续实验选择)。
实验记录和附件按需通过[文档入口](docs/README.md)读取，不默认展开历史资料。

## 目录

| 目录 | 内容 |
| --- | --- |
| [`jetson-agx/sdrharness/`](jetson-agx/sdrharness) | AGX clone 后的构建、配置和 systemd 入口 |
| [`raspberry-pi/sdr-agent/`](raspberry-pi/sdr-agent) | 已验证的 Controller、Planner、终端、Web 与历史识别 seam |
| [`raspberry-pi/p201pro-rust/`](raspberry-pi/p201pro-rust) | Rust/libiio 采集和软件扫频参考实现 |
| [`sdr-system/`](sdr-system) | P201 Pro 内嵌系统与 `sdrd` |
| [`docs/`](docs) | 当前设计、迁移记录、检查清单和验证证据索引 |

## AGX 快速开始

AGX 上线后：

```bash
git clone https://github.com/luzhouchao/sdr-pi.git /home/jetson/sdrharness
cd /home/jetson/sdrharness
bash jetson-agx/sdrharness/scripts/verify-checkout.sh
bash jetson-agx/sdrharness/scripts/check-toolchain.sh
bash jetson-agx/sdrharness/scripts/build-agent-runtime.sh
```

上述命令只验证和构建，不安装 systemd、不启动第二套采集，也不修改 SDR。部署步骤见
[`jetson-agx/sdrharness/README.md`](jetson-agx/sdrharness/README.md)。

## 安全边界

- 不提交密码、私钥、API key、原始 IQ、训练数据集、缓存或环境目录。
- 未完成采集切换门禁前，不启动第二套 SDR 采集；必须先确认没有其他采集器
  占用接收路径。
- 不生成、复制或覆盖 `BOOT.bin`，不启用 FPGA 聚合；该路线已正式退役。
- CUDA 模型权重按大小使用 GitHub Release 或其他带 SHA-256 的制品渠道，不直接混入源码历史。
- 所有能力默认关闭，只有负责的 Adapter 通过实机探测后才能报告可用。

文档入口见 [`docs/README.md`](docs/README.md)，当前第1—6章勾选式路线见
[`docs/CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](docs/CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md)，
权威明细进度见
[`docs/SDR_AGENT_PROJECT_CHECKLIST.md`](docs/SDR_AGENT_PROJECT_CHECKLIST.md)。
