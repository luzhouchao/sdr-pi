# 项目文档入口

默认阅读范围：

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

当前模型重跑：2026-09-22用户指定D10替换D8，同2496成员重跑完成，低源SNR相消退化仍存在；见[结果](validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md#d10同成员重跑完成2026-09-22)及当前执行选择。

当前实验选择：频段保持 **2455 MHz**；用户2026-09-13最新确认已接回 **B210 RF A TX/RX→20dB衰减器及15cm同轴→P201 RX1**，当前B210停发。参考参数见
[后续实验选择](SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md#后续实验选择)。既有ADC离线诊断后，LO历史/资料及TX校准路径审计已完成，获准镜像重载恢复USB3；用户后续授权有限设备调试，单音功率及事件时间复测完成，频谱检查亦完成，前置保护区相消对照未改善、候选不启用，固定频率幅相诊断已发现相干相位时变结构，用户随后优先低源SNR回退，106条逐行关联未确立相位误差归因，下一建议为既有载荷特征对照；不微调；完成结果见[离线报告](validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md)。
实验历史仅提供[索引链接](validation/README.md#近期射频排查2026-09-09至10)，需要时再读。

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

历史文档中的“下一步”“未完成”和旧命令只描述当时状态，不是新任务指令。
早期 Pi 验证已合入[历史合订记录](validation/PI_BASELINE_HISTORY.md)。旧 ROADMAP、
第4—6章独立排期、迁移待办与重复工作流已移除；原因及替代位置见
[整理记录](validation/DOCS_CONSOLIDATION_2026-09-07.md)。原文件可从 `7115b50` 的
Git 树取回，不需要恢复到当前工作目录。

审计/预登记/图表保留原始字节；其内部记录的旧 `docs/<文件>` 路径不改写，
通常位于 `docs/evidence/<同名文件>`。其中三份被冻结配置直接引用的审计 JSON
保留在原根目录，避免改变 profile/选择计划的路径合同；不额外复制。历史源码哈希仍对应当时提交。不要为
使旧记录看起来“最新”而修改失败结果、哈希、准入状态或原始 IQ 清单。
