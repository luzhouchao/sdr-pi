# 架构、合同与操作参考

这里维护当前实现的职责与接口；是否已安装、是否获准用于生产，仍查
[权威清单](../SDR_AGENT_PROJECT_CHECKLIST.md)。旧版本 profile 的历史约束不等于
当前生产能力，不能凭接口存在打开识别或发射。

| 主题 | 文档 |
| --- | --- |
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
