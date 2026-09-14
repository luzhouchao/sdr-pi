# 架构、合同与操作参考

这里维护当前实现的职责与接口；是否已安装、是否获准用于生产，仍查
[权威清单](../SDR_AGENT_PROJECT_CHECKLIST.md)。旧版本 profile 的历史约束不等于
当前生产能力，不能凭接口存在打开识别或发射。

| 主题 | 文档 |
| --- | --- |
| 4090原始模型及2018A基线权重、旧epoch-010删除边界 | [模型集合](RML2018A_MODEL_COLLECTION.md) |
| AGX双SDR目录、独立运行时与共享RadioML2018A | [设备工作区](../../devices/README.md) |
| RadioML2018A全部原始样本的B210发射/AGX工程识别 | [全量脚本操作](RML2018A_FULL_RF_CAMPAIGN.md) |
| 当前RF配置、优化适用条件、复现及论文表述 | [复现与论文范围](RML2018A_RF_REPRODUCTION.md) |
| Agent / Controller / Planner 分工 | [运行架构](SDR_AGENT_RUNTIME_DESIGN.md) |
| 有界 RX、AGX 聚合和结果 | [采集处理架构](SDR_PREPROCESSING_SWEEP_ARCHITECTURE.md) |
| 识别接口、模型输入和准入 | [本地 Recognizer](LOCAL_RECOGNIZER_INTERFACE.md) |
| 数据集与接收语料合同 | [Corpus manifest](AMC_CORPUS_MANIFEST_V1.md) |
| RF-v1 导入、派生和标签证据 | [V1a 接口](RF_V1_CORPUS_EVIDENCE_INTERFACE.md) |
| 独立 known-RF/OOD 采样与覆盖 | [采样规范](RF_V1_KNOWN_RF_OOD_SAMPLING_V1.md) |
| Worker 生命周期 | [S3](WORKER_SUPERVISOR_S3_INTERFACE.md) |
| 共享 GPU 与资源边界 | [S4a](GPU_LEASE_S4A_INTERFACE.md)、[S4b](GPU_RESOURCE_S4B_INTERFACE.md) |
| 执行、联合取消和反馈 | [S5](RUNNER_RECOGNITION_S5_INTERFACE.md) |
| 识别归档、查看与删除 | [S6a](RECOGNITION_ARCHIVE_S6A_INTERFACE.md)、[S6b](WEB_RECOGNITION_S6B_INTERFACE.md) |
| 日志、只读监控、升级与回滚 | [O1a runbook](OPERATIONS_O1A_RUNBOOK.md) |
| FPGA 退役边界 | [决策](FPGA_RETIREMENT_DECISION_2026-09-02.md) |
| 暂缓的模型域适配建议 | [决策与后续条件](RF_DOMAIN_ADAPTATION_DEFERRED_2026-09-07.md) |

AGX 安装布局与命令见[部署入口](../../jetson-agx/sdrharness/README.md)，开发流程见
[AGENTS.md](../../AGENTS.md)。不再维护独立迁移待办或另一份迭代规则。

## 组件操作文档

这些文档留在对应代码目录，按任务打开；构建/部署示例不代表需要立即执行。

| 主题 | 入口 |
| --- | --- |
| 仓库介绍与构建起点 | [根 README](../../README.md) |
| AGX 构建、安装与服务 | [AGX 操作入口](../../jetson-agx/sdrharness/README.md) |
| 共享 Controller、Planner、Web | [Agent 组件](../../raspberry-pi/sdr-agent/README.md) |
| Recognizer 接口组件 | [Worker 文档](../../raspberry-pi/sdr-agent/recognizer-worker/README.md) |
| Web 浏览器验证方法 | [测试入口](../../raspberry-pi/sdr-agent/web-console/tests/README.md) |
| P201 系统职责 | [系统入口](../../sdr-system/README.md) |
| SDRD 协议与构建 | [sdrd 文档](../../sdr-system/sdrd/README.md) |
| SDRD 控制平面设计 | [接口设计](../../sdr-system/docs/SDRD_CONTROL_PLANE_DESIGN.md) |
| 历史树莓派布局 | [Pi 入口](../../raspberry-pi/README.md) |
| 历史直接 IIOD 工具 | [Rust/libiio 参考](../../raspberry-pi/p201pro-rust/README.md) |

## 访问、凭证与许可

| 主题 | 入口 |
| --- | --- |
| 项目协作与按需读取规则 | [AGENTS](../../AGENTS.md) |
| P201 硬件访问流程 | [工作流技能](../../.codex/skills/p201-sdr-workflow/SKILL.md)、[访问与部署细则](../../.codex/skills/p201-sdr-workflow/references/access-and-deploy.md) |
| 安全报告 | [SECURITY](../../SECURITY.md) |
| 私有目录约定（不含凭证） | [private README](../../sdr-system/private/README.md) |
| Planner 第三方许可 | [Third-party notices](../../raspberry-pi/sdr-agent/planner-worker/THIRD_PARTY_NOTICES.md) |

历史系统与Pi实验结果从[验证索引](../validation/README.md#组件目录中的历史实验)进入。

## CodeGraph 代码导航

本仓库已初始化本地CodeGraph。理解/定位代码优先使用`codegraph explore`，MCP调用传
`projectPath=/home/jetson/sdrharness`；它不替代按需读取实验记录或真实测试。

```bash
codegraph status --json /home/jetson/sdrharness
codegraph explore validate_rf_case
codegraph sync /home/jetson/sdrharness
```

状态有待更新文件时使用sync。索引在`.codegraph/`，由Git忽略，其他checkout需要单独初始化；
初始化和CLI/MCP验收见[记录](../validation/CODEGRAPH_INITIALIZATION_2026-09-10.md)。
