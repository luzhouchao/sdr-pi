# SDR Agent 实际推进顺序

更新：2026-09-11。本文只维护施工顺序，不复制完成状态。
完成条件和证据以[权威 checklist](SDR_AGENT_PROJECT_CHECKLIST.md)为准；
范围以[第1—6章规划](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md)为准。
历史实验结果按[验证索引](validation/README.md)查询，不再在本文件逐次追加旧排期。

## 当前执行选择

用户现明确要求开发NX控制外部SDR发射RadioML2018A全量样本、P201接收和AGX冻结模型识别。
范围为原HDF5全部2555904条样本，包含历史划分的所有成员；先有限先导验证，再按预算分批续跑。
允许此任务的工程推理，不恢复训练/微调，不更改独立locked-test准入或生产recognizer_available。
[接收域适配建议](reference/RF_DOMAIN_ADAPTATION_DEFERRED_2026-09-07.md)只作后续参考。

S1/S2/V1a/S3/S4a/S6a/S5/S6b/S4b/O1a 已有源码、对应隔离验证和清理，不能重做。
[统一 CLI](validation/UNIFIED_CLI_VALIDATION_2026-09-07.md)已安装：交互、脚本与
恢复使用同一个 `sdr-agent`，旧 CLI 兼容修复已结束。当前 Controller/交互代码已
进入已安装制品。[Web 后台升级与会话恢复验收](validation/WEB_RECOVERY_UPGRADE_VALIDATION_2026-09-07.md)
也已完成实际安装、回滚和清理；现有归档界面已进入 Web 制品，Worker、profile/
校准和准入配置未整体部署，这不是 A1。

[非模型运维配置部署](validation/OPERATIONS_RX_DEPLOYMENT_VALIDATION_2026-09-08.md)已完成：
Web/Planner 日志限额、实际 health 兼容、只读定时检查、本地去重告警和配置回滚
均已验收。随后用户授权的[日常 RX 使用验收](validation/DAILY_RX_USE_VALIDATION_2026-09-08.md)
也完成三段有限实收、结果管理、停止/监控共存和状态文案修正。上述已完成单元
不要重做。

## 后续实验选择

用户于2026-09-11明确已换成2.4GHz，覆盖2026-09-10的433MHz选择。后续实验收发默认
**2455MHz**（沿用历史实验中心，非当前空闲频点实测结论）；天线型号/参数未核实。
沿用当前选择，不因新对话重复询问频段，不自行切到其他频段。

历史433MHz已验证的单音参考组合：TX70dB / RX50dB、幅度0.2、rate2.5MS/s、TX BW500kHz / RX BW1MHz，
+100kHz偏移意味着名义空口单音434.020MHz。它是后续有限计划的参考，不是所有波形的
通用功率设置或连续发射安排；调制波形/新带宽等按当前全量RF任务登记；仅运行该任务授权的工程推理。
频段偏好不修改生产扫描范围、冻结profile或历史runner默认；本任务RF仅按有限campaign计划执行。

全量RF脚本操作见[说明](reference/RML2018A_FULL_RF_CAMPAIGN.md)，实际先导及质量边界见
[验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md)。当前已按用户要求调整2455MHz及SINR记录合同；
下一单元为新计划下的有限2.4GHz背景/高源SNR收发基线，核对过载和频谱占用，再决定固定滤波及扩量。
保留RadioML原始Z为source_snr_db；X已含源损伤，不能把源标签、相关度或RX-X残差直接记成总SINR。
当前rx_sinr_db未测为null，缺少干净参考及已验证分量估计器；不得以空字段完成SINR实测。
必要时另设小规模干净参考实验，不因此训练模型或重建数据集。旧433MHz保留IQ仍可按需离线诊断，
不把其相关改善等同于新频段识别或全库质量通过。源码变更必须新建campaign，旧计划及结果不改写。
既有脚本、取消/恢复与续跑不重做；旧逐条循环10秒程序不直接套全库，当前不自动启动数周全量执行。

实验资料按需打开，不默认展开正文或证据：

- [历史433MHz接法的验证依据](validation/B210_433920_ANTENNA_VALIDATION_2026-09-10.md)
- [历次射频排查索引](validation/README.md#近期射频排查2026-09-09至10)
- [原始证据索引](evidence/README.md#近期射频试验附件2026-09-10)

完成状态只在checklist维护，本文不复制实验过程、结果表或历史接法。

已完成单音单元不重做，不自行增加巡航或无预算采集。全量工程推理不自动启动校准、独立locked test或A1；
生产主线仍须满足下列独立证据条件。
O1b仍是最终完整闭环验收，不能把仅Web/Planner监控运行满一天记作完成。

## 识别主线：按证据条件恢复

| 顺序 | 单元 | 前置条件与边界 |
| --- | --- | --- |
| 1 | V1b | 获得并审核独立 known-RF/OOD 标签及覆盖；V3a 已按用户指定的 4090 原始表冻结 server-v1，生产映射引用随 A1 接入。名称映射不替代独立 RF 标签 |
| 2 | V2 | 用合格 validation/独立校准组拟合和冻结温度、拒识规则；独立验收组报告准确率、拒识、false acceptance、ECE/NLL |
| 3 | V3b | 模型、映射、profile、精度及规则冻结后执行一次 locked-test 准入；失败保留证据，不反复使用同一 test 调参 |
| 4 | A1 | 证据齐备后的协调部署、回滚、真实 RX 矩阵与实际 capability；识别先保持人工批准 |
| 5 | O1b | 最终完整闭环的有限预算 24小时验收，含停止、恢复、日志与清理；不绕过批准策略 |

用户恢复的是全量RF工程推理，不能仅因表中顺序就执行独立准入或训练。非模型运维部署不提前勾选 A1，
S4b 的 GPU 温度缺失按明确豁免保持未测，不再用它阻塞已通过的资源单元。

## 固定边界与外部信号源

- 冻结 epoch-10、FP16 autocast + FP32 权重、RF-v1；不自行训练、不重跑完整精度实验、全量工程源访问按AGENTS当前授权执行，不重跑独立locked-test准入。
- `recognizer_available=false`；数字 ID 可信，文本 provisional；独立证据不足时不冻结生产温度或拒识阈值。
- P201 Linux/IIO 有界 RX → AGX 处理。当前天线 RX1，身份 RX1/RX0/A_BALANCED；sdrd 可在启动配置选择 RX1/RX2，冻结 profile 仍只接纳 RX1。
- NX+B210仅在明确授权和登记计划内作有限外部信号源；后续实验频段按上方2455MHz选择执行。P201/生产Agent保持RX-only。
- 未标注实收只证明链路与质量，不能把 top-1、置信度或 train 波形诊断补成独立验收标签。RF 失败及保留证据见验证/证据目录；继续物理来源隔离需确认适当负载或衰减器，不无衰减直连 TX/RX。
- FPGA/BOOT、P201 TX 和 NX 推理 offload 不进入主线；第7章辐射源身份识别按用户 2026-09-08 指令暂缓，已移出当前待办，须明确恢复后再排期。

## 每次交付

核对分支/HEAD/工作区，读 AGENTS 与相关合同；完成适当测试及实机验证后，精确
清理本单元临时数据、登记最小必要证据、更新 checklist 与验证记录、review diff，
聚焦 commit 并立即 push。不得删除用户应用结果或已有保留证据来充当开发清理。
