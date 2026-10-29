# SDR Harness

Jetson AGX 上的 SDR 控制与分析工程。生产数据路径为 **P201 Linux/IIO 有界接收 → AGX 软件处理**。
Controller 负责硬件执行、预算和批准；Planner 提出结构化计划；Web 提供会话、扫描结果和单窗分析。
生产识别准入状态仍以 checklist 为准，`recognizer_available=false`。

## 从哪里开始

- 使用、配置与部署：[AGX 操作说明](deploy/agx/README.md)。
- 修改程序：[源码入口](src/README.md)。
- 访问设备：[设备入口](devices/README.md)。
- 查当前状态与历史证据：[文档入口](docs/README.md)。
- 开发规则：[AGENTS.md](AGENTS.md)；凭证处理：[SECURITY.md](SECURITY.md)。

## 目录分类

```text
src/                      程序实现
  agent/controller/       Rust 安全控制器与统一 sdr-agent CLI
  agent/planner-worker/   Planner 框架与模型适配
  agent/web-console/      Web 服务、网页及单窗 IQ 分析
  sdrd/                   P201 C11 接收与传输服务

deploy/                   构建、配置和运维
  agx/config/             AGX 配置模板与历史实验合同
  agx/scripts/            构建、运维、验证与离线诊断脚本
  agx/systemd/            AGX 服务模板
  agx/tests/              配套脚本测试
  p201/                   P201 部署说明与本地凭证目录规则

devices/                  B210 / P201 操作入口与源码链接
docs/                     文档、checklist 与证据
  reference/              架构和接口
  validation/             已执行验证、失败及回滚记录
  evidence/               封存审计、图表与原始清单
local-assets/             Git 外的设备运行时等本机资源
```

`.codex/skills/` 是项目设备工作流；`.codegraph/` 是本机代码索引；
`.artifacts/` 是 Git 忽略的构建暂存，不是源码。新开发临时数据按 AGENTS 规则存放。
每个组件内部继续按 `src`、`tests`/`test`、`config` 和 `scripts` 分类，避免混入生成产物。

## 只读检查与构建

```bash
cd /home/jetson/sdrharness
bash deploy/agx/scripts/verify-checkout.sh
bash deploy/agx/scripts/check-toolchain.sh
bash deploy/agx/scripts/build-agent-runtime.sh
```

构建与部署是不同操作；以上入口不授权新的 RF 收发。部署前按组件说明执行验证。

## 历史与项目边界

旧 `raspberry-pi/sdr-agent/` 是 AGX 仍在使用的实现，现已迁至 `src/agent/`。
`Pi Agent` 框架名称不表示运行在树莓派。旧 Pi 独立 libiio 采集程序和网络配置已退役删除；
独有测试记录保留于 [Pi 历史验证](docs/validation/README.md)。
旧 `jetson-agx/sdrharness/` 已迁至 `deploy/agx/`，旧 `sdr-system/sdrd/` 已迁至 `src/sdrd/`。

论文专属数据、模型和评估记录由 [paper1sdr](https://github.com/luzhouchao/paper1sdr) 独立维护。
封存实验记录中的原路径、哈希和旧命令保持历史语义，不作为当前运行入口。
密码、原始 IQ、权重、缓存和构建产物不入 Git；P201 FPGA 聚合与 BOOT 路线保持退役。

未启用的独立识别 Worker、旧 RF/模型实验脚本及配套测试已退役。Rust 中的安全门、历史结果解析和语料合同继续保留；论文实验不在本项目重新安装环境。
