# 项目文档入口

论文专属收尾代码与证据已迁至 [paper1sdr](https://github.com/luzhouchao/paper1sdr)；本项目继续维护 SDR 控制和使用说明。论文数据独立维护，本项目目录布局见[仓库首页](../README.md)。

默认阅读范围：

2026-10-29 按用户要求删除网页历史 IQ；用户随后明确保留论文实验数据。旧 P201 语料已删除，冻结选择计划对其 manifest 的引用不再可用；其他原有封存实验数据和证据未因本次操作删除。删除范围及结果见[清单](evidence/IQ_CLEANUP_2026-10-29.json)。

1. [AGENTS.md](../AGENTS.md)：工作规则与读取边界。
2. [当前执行选择](SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md#当前执行选择)及[后续实验选择](SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md#后续实验选择)。
3. [checklist 状态速览](SDR_AGENT_PROJECT_CHECKLIST.md#当前交付状态速览2026-09-10)；具体条目按任务定位。

[章节范围](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md)、接口和实验资料按需打开。
**默认不读取实验正文、图表、计划、证据清单或原始数据**，也不递归展开下面的链接；
需要核对参数、排查问题、执行相关硬件操作或复核结果时，只打开直接相关记录。

然后按当前任务选择下面的目录，不必逐份重读历史实验。

| 目录 | 用途 |
| --- | --- |
| [reference/](reference/README.md) | 当前架构、接口合同、采样规范、运维流程与决策 |
| [validation/](validation/README.md) | 按主题索引的已执行验证、部署和回滚记录 |
| [evidence/](evidence/README.md) | 原始审计 JSON、保留证据清单、预登记计划和图表 |

其他资料入口（按需）：

- [9月8—14日实验阶段报告（离线HTML）](reports/SDR_EXPERIMENT_REPORT_2026-09-08_2026-09-14.html)

- [AGX设备工作区：B210 USB / P201网口 / 共享数据集](../devices/README.md)
- [既有ADC离线基线与幅度处理诊断](validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md)
- [seed42验证集8模型识别、筛选与进度/混淆矩阵](reference/RML2018A_MODEL_COLLECTION_EVALUATION.md)
- [4090模型集合与四窗微调权重删除后的使用边界](reference/RML2018A_MODEL_COLLECTION.md)
- [RadioML2018A全量RF脚本操作](reference/RML2018A_FULL_RF_CAMPAIGN.md)
- [当前RF配置与复现、同轴/空口论文适用范围](reference/RML2018A_RF_REPRODUCTION.md)
- [Agent、控制与部署记录](validation/README.md#agent控制与部署)
- [识别软件交付记录](validation/README.md#识别软件交付)
- [架构、接口与运维](reference/README.md)
- [各组件操作文档](reference/README.md#组件操作文档)
- [完整实验附件目录](evidence/README.md#保留数据的删除依据)
- [文档整理记录](validation/DOCS_CONSOLIDATION_2026-09-07.md)

实际完成和部署状态以 checklist 对应条目为准，入口不重复维护历史结果。

历史文档中的“下一步”、旧命令和待批准操作只描述当时状态，不构成当前施工指令。
历史成绩、清理清单与封存数据状态以 checklist、validation 和 evidence 为准，首页不重复维护。
本仓库仍被配置引用的冻结审计保持原路径和字节；迁出的论文资料通过上述索引查阅。
