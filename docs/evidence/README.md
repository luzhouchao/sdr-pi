# 原始证据附件

这里集中保存审计 JSON、保留文件清单、预登记计划和图表，均从旧 docs 根目录
逐字节迁移；文件 SHA-256 不变。读结论请先看[验证索引](../validation/README.md)。

- `*_EVIDENCE_*.json`：外部保留 IQ/诊断包的路径、用途、哈希和删除依据，必须保留。
- `*_AUDIT_*.json` 及其他审计 JSON：有界结果、失败、执行/清理记录，不能当成新的标签或准入证据。
- `*_PLAN_*.md`：当时预登记的有限预算和判定条件；不是下一步任务。原文、包括历史相对路径，保持不变以便核验原哈希。
- PNG：原始诊断图，按同名实验查验证报告。

历史记录内部的 `docs/<文件>` 或同名文件引用，如已迁移，则当前位置为
`docs/evidence/<同名文件>`；指向验证报告时查 `docs/validation/`，接口查
`docs/reference/`。原始旧树固定可从提交 `7115b50` 查询。应用结果、外部 IQ 路径
以及其哈希未改动；开发清理不能删除这些用户数据。修改读取脚本的定位路径不
会追溯改写旧审计记录的脚本哈希。

## 保留数据的删除依据

- [3500MHz低增益单音完整对照与失败证据](B210_3500_TONE_EVIDENCE_2026-09-10.json)

- [历史宽频背景对照派生汇总与源文件清单](HISTORICAL_BACKGROUND_COMPARISON_EVIDENCE_2026-09-09.json)

- [P201 5GHz Wi-Fi中心90次背景证据与清理](P201_WIFI5_BACKGROUND_EVIDENCE_2026-09-09.json)

- [P201 2.4GHz背景分布225点证据与清理](P201_BACKGROUND_MAP_EVIDENCE_2026-09-09.json)

- [P201 50Ω负载六次背景证据与清理](P201_TERMINATION_BACKGROUND_EVIDENCE_2026-09-09.json)
- [P201 接回原天线六次背景证据与清理](P201_ANTENNA_RETURN_EVIDENCE_2026-09-09.json)
- [P201 再接50Ω负载六次背景证据与清理](P201_TERMINATION_RETURN_EVIDENCE_2026-09-09.json)

- [Web UI 制品、截图与清理审计](WEB_UI_REDESIGN_AUDIT_2026-09-07.json)

- [B210_2455_MARGIN_EVIDENCE_2026-09-07.json](B210_2455_MARGIN_EVIDENCE_2026-09-07.json)
- [B210_BACKGROUND_EVIDENCE_2026-09-07.json](B210_BACKGROUND_EVIDENCE_2026-09-07.json)
- [B210_LO_REJECTION_EVIDENCE_2026-09-07.json](B210_LO_REJECTION_EVIDENCE_2026-09-07.json)
- [B210_MULTICLASS_EVIDENCE_2026-09-07.json](B210_MULTICLASS_EVIDENCE_2026-09-07.json)
- [B210_RX1_NEW_ANTENNA_EVIDENCE_2026-09-07.json](B210_RX1_NEW_ANTENNA_EVIDENCE_2026-09-07.json)
- [RF_V1_EVIDENCE_V1A_AUDIT_2026-09-06.json](RF_V1_EVIDENCE_V1A_AUDIT_2026-09-06.json)

其余附件按原文件名与验证报告一一对应，无需为浏览重复复制一份内容。

## 冻结路径例外

下面三份原始审计由冻结配置按固定路径引用，保留在 docs 根目录且不复制：

- [split 审计](../AMC_SPLIT_ISOLATION_AUDIT_2026-09-05.json)
- [预处理选择审计](../RF_PREPROCESS_V1_SELECTION_AUDIT_2026-09-05.json)
- [RF-aligned checkpoint 审计](../RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_AUDIT_2026-09-05.json)

整理不能为了目录整齐改变这些引用或重新冻结模型配置。

- [3500MHz负载背景证据与清理](P201_3500_TERMINATION_EVIDENCE_2026-09-10.json)

- [3500MHz重发预登记](B210_3500_RETRY_PLAN_2026-09-10.md)
- [3500MHz重发证据库存](B210_3500_RETRY_EVIDENCE_2026-09-10.json)

- [3500MHz增益矩阵预登记](B210_3500_GAIN_PLAN_2026-09-10.md)
- [3500MHz增益矩阵证据清理](B210_3500_GAIN_EVIDENCE_2026-09-10.json)
