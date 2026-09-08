# SDR Agent 实际推进顺序

更新：2026-09-08。本文只维护施工顺序，不复制完成状态。
完成条件和证据以[权威 checklist](SDR_AGENT_PROJECT_CHECKLIST.md)为准；
范围以[第1—6章规划](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md)为准。
历史实验结果按[验证索引](validation/README.md)查询，不再在本文件逐次追加旧排期。

## 当前执行选择

用户要求暂缓训练、微调和进一步模型诊断，先推进模型以外的工作。
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

## 后续选择

当前已授权的这批非模型独立交付已结束。先按已安装日志/监控观察日常使用中的
实际问题；如有新功能或运行问题，另界定独立单元，不自行增加巡航或采集负载。
模型工作仍暂停，没有可在证据不足时自动启动的校准、locked test 或 A1 单元。
恢复识别主线须用户明确选择，并先满足下列独立证据条件；O1b 仍是最终完整闭环
验收，不能把仅 Web/Planner 监控运行满一天记作完成。

## 识别主线：按证据条件恢复

| 顺序 | 单元 | 前置条件与边界 |
| --- | --- | --- |
| 1 | V1b | 获得并审核独立 known-RF/OOD 标签及覆盖；V3a 已按用户指定的 4090 原始表冻结 server-v1，生产映射引用随 A1 接入。名称映射不替代独立 RF 标签 |
| 2 | V2 | 用合格 validation/独立校准组拟合和冻结温度、拒识规则；独立验收组报告准确率、拒识、false acceptance、ECE/NLL |
| 3 | V3b | 模型、映射、profile、精度及规则冻结后执行一次 locked-test 准入；失败保留证据，不反复使用同一 test 调参 |
| 4 | A1 | 证据齐备后的协调部署、回滚、真实 RX 矩阵与实际 capability；识别先保持人工批准 |
| 5 | O1b | 最终完整闭环的有限预算 24小时验收，含停止、恢复、日志与清理；不绕过批准策略 |

用户尚未恢复模型工作，不能仅因排在表中就执行。非模型运维部署不提前勾选 A1，
S4b 的 GPU 温度缺失按明确豁免保持未测，不再用它阻塞已通过的资源单元。

## 固定边界与外部信号源

- 冻结 epoch-10、FP16 autocast + FP32 权重、RF-v1；不自行训练、不重跑完整精度实验、不读取 locked test。
- `recognizer_available=false`；数字 ID 可信，文本 provisional；独立证据不足时不冻结生产温度或拒识阈值。
- P201 Linux/IIO 有界 RX → AGX 处理。当前天线 RX1，身份 RX1/RX0/A_BALANCED；sdrd 可在启动配置选择 RX1/RX2，冻结 profile 仍只接纳 RX1。
- 用户曾明确授权 NX+B210 在 2.4 GHz 作有限外部信号源；这不增加生产 Agent/P201 TX 能力，本轮 Web/运维工作无需发射。
- 未标注实收只证明链路与质量，不能把 top-1、置信度或 train 波形诊断补成独立验收标签。RF 失败及保留证据见验证/证据目录；继续物理来源隔离需确认适当负载或衰减器，不无衰减直连 TX/RX。
- FPGA/BOOT、P201 TX 和 NX 推理 offload 不进入主线；第7章辐射源身份识别按用户 2026-09-08 指令暂缓，已移出当前待办，须明确恢复后再排期。

## 每次交付

核对分支/HEAD/工作区，读 AGENTS 与相关合同；完成适当测试及实机验证后，精确
清理本单元临时数据、登记最小必要证据、更新 checklist 与验证记录、review diff，
聚焦 commit 并立即 push。不得删除用户应用结果或已有保留证据来充当开发清理。
