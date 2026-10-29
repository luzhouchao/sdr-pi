# 识别与实验配置

本目录保留冻结模型、预处理、标签及历史选择计划，生产识别仍未准入。

- `*.layout-v2.json`：目录迁移后的工程运行 profile，仅更新 `preprocess.spec_path`。
- 同名原始 profile、预处理规范、标签和选择计划：保留原始字节与哈希，不作为新的实验授权。
- 旧模型、数据、审计路径可能已迁出或删除；历史计划不能直接用于新的实验。

两个 layout-v2 profile 分别派生自 `eac1d8c` 的
`jetson-agx/sdrharness/config/amc/rml2018a-d8-current.integration-profile.json` 与
`jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json`。
仅文件路径迁移，不改算法、参数、模型身份或准入门；profile 文件哈希自然变化，
预处理规范字节和哈希不变。完整迁移验证见
[整理记录](../../../../docs/validation/DOCS_CONSOLIDATION_2026-09-07.md)。
