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

2026-09-26用户取消近期自生成及后续诊断，确认删除8个结果目录，并退役AGX独立D8。已删除20个目录、2061个文件、1,369,327,545字节，路径缺失复核通过；原RML2018A源数据、实收IQ、raw/guard及D10结果保留。D10依赖的d8命名源码与混合模型历史审计保留。删除前逐文件大小/SHA及精确路径见[删除清单](evidence/EXPERIMENT_CLEANUP_D8_RETIREMENT_2026-09-26.json)。历史记录中的“保留”是当时状态，清单所列外部结果现已删除，不能再宣称可读回。

四数据集×八模型32份权重已统一导入并通过CPU严格加载；入口为`/home/jetson/models/amc`，见[模型库](reference/RML2018A_MODEL_COLLECTION.md#当前统一库2026-09-26)。新三套CUDA前向及RF尚未执行。

当前目标为RML2016A、RML2016B、HisarMod2019三套D10的发射→接收→处理→识别，沿用原RML2018A流程原则；尚未开始新收发。用户已确认四数据集×source/接收原始IQ/raw/guard共16套数据，模型单独管理；新增要求统一四数据集×八种模型共32份权重。新RF任务样本范围尚待明确。

当前实测报告：D10已补齐369497共同验证成员，当前8模型仅raw/guard；按接收端条件估计SINR分层。
D10总体50.45%→55.09%，低SINR相消退化仍存在；见[大样本结果](validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md#d10补齐369497共同验证成员2026-09-22)。
2026-09-26接收端RMS比值选择规则完成：主评估采集的172218剩余成员49.11%→50.70%，
但四份采集退化、低SINR仍不及raw，保留候选不部署；见[规则及复核](validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md#接收端指标选择相消强度2026-09-26)。
现有条件SINR仅用于离线分层，不作为规则输入；未训练、新推理或收发。

2026-09-26新会话交错试验的源行映射/离线排程准备完成，尚未收发或推理；见[准备与剩余边界](validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md#新会话交错试验映射准备2026-09-26)。

当前实验选择：频段保持 **2455 MHz**；用户2026-09-13最新确认已接回 **B210 RF A TX/RX→20dB衰减器及15cm同轴→P201 RX1**，当前B210停发。参考参数见
[后续实验选择](SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md#后续实验选择)。既有ADC离线诊断后，LO历史/资料及TX校准路径审计已完成，获准镜像重载恢复USB3；用户后续授权有限设备调试，单音功率及事件时间复测完成，频谱检查亦完成，前置保护区相消对照未改善、候选不启用，固定频率幅相诊断已发现相干相位时变结构，用户随后优先低源SNR回退，106条逐行关联未确立相位误差归因，后续D10载荷特征及干预结果见上方最新记录；不微调；完成结果见[离线报告](validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md)。
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
