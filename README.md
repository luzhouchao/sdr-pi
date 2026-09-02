# SDR Harness for Jetson AGX Orin

P201 Pro SDR、Jetson AGX Orin、Rust 安全控制器、Pi Agent Planner 和后续 CUDA
识别后端的统一工程仓库。

主运行节点已从 Raspberry Pi 4B 调整为 Jetson AGX Orin。目标 clone 路径固定为
`/home/jetson/sdrharness`。Pi 上已经完成的控制、扫频、Web Console 和回滚证据继续
保留，但不再是新功能的算力或数据面目标。

## 目标架构

```text
operator / trusted-LAN Web Console
                |
                v
       AGX SDR Harness
  Rust Controller + Pi Agent Planner
       third-party model API
  acquisition / aggregation / future CUDA recognizer
                |
                v
      SDRD/1 over 192.168.1.x
                |
                v
      P201 Pro SDR + AD9361 Linux/IIO RX
```

AGX 负责 Agent、控制器、Web、扫频编排、预处理和未来 CUDA/Mamba 推理。P201
SDR 继续运行 `sdrd`，保留独占所有权、限幅、停止和射频状态恢复。模型接入当前
明确延期：小型 Pi ONNX 模型不进入迁移主线，后续单独接入 AGX CUDA 后端。

## 当前状态

- Pi 侧 Rust Controller、Planner Worker、终端和 Web Console 已实机验证，作为可回滚基线。
- SDR 侧受控 `sdrd` 已验证只接收扫频、限幅 IQ、取消和状态恢复。
- AGX 迁移目录、配置、systemd 模板和本机构建入口已纳入 Git。
- AGX 已在 `/home/jetson/sdrharness` 完成 aarch64 原生构建、测试和
  loopback 运行验证；P201 的持久 `sdrd` 经重复实例门禁后恢复，AGX
  对 `192.168.1.10:43110` 的只读 SDRD 观察已通过。
- AGX Web 可将 OpenAI-compatible Completions/Responses 上游写入
  不被 Git 跟踪的 `0600` 私密配置；按用户要求监听所有 IPv4
  接口，不得做公网端口映射。
- CUDA/Mamba 模型、权重和推理 Worker 暂不包含在本次框架迁移中。

## 目录

| 目录 | 内容 |
| --- | --- |
| [`jetson-agx/sdrharness/`](jetson-agx/sdrharness/) | AGX clone 后的构建、配置和 systemd 入口 |
| [`raspberry-pi/sdr-agent/`](raspberry-pi/sdr-agent/) | 已验证的 Controller、Planner、终端、Web 与历史识别 seam |
| [`raspberry-pi/p201pro-rust/`](raspberry-pi/p201pro-rust/) | Rust/libiio 采集和软件扫频参考实现 |
| [`sdr-system/`](sdr-system/) | P201 Pro 内嵌系统与 `sdrd` |
| [`fpga/`](fpga/) | 已退役的 FPGA 探索源码、Vivado 脚本和历史硬件证据（不再开发或部署） |
| [`docs/`](docs/) | 跨层架构、迁移记录、检查清单和验证证据 |

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
[`jetson-agx/sdrharness/README.md`](jetson-agx/sdrharness/README.md) 和
[`docs/AGX_SDRHARNESS_MIGRATION.md`](docs/AGX_SDRHARNESS_MIGRATION.md)。

## 安全边界

- 不提交密码、私钥、API key、原始 IQ、训练数据集、缓存或环境目录。
- 未完成 SDRD 只读观察和采集切换门禁前，不停止现有
  Spectrum Agent/Qwen，不启动第二套 SDR 采集。
- 不生成、复制或覆盖 `BOOT.bin`，不启用 FPGA 聚合；该路线已正式退役。
- CUDA 模型权重按大小使用 GitHub Release 或其他带 SHA-256 的制品渠道，不直接混入源码历史。
- 所有能力默认关闭，只有负责的 Adapter 通过实机探测后才能报告可用。

权威进度见 [`docs/SDR_AGENT_PROJECT_CHECKLIST.md`](docs/SDR_AGENT_PROJECT_CHECKLIST.md)。
