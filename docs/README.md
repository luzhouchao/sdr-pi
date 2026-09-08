# 项目文档入口

日常继续开发只需要先读根目录的四份文件：

1. [AGENTS.md](../AGENTS.md)：工作规则、硬件边界、证据保留与清理。
2. [权威 checklist](SDR_AGENT_PROJECT_CHECKLIST.md)：哪些已完成、哪些仍未完成。
3. [实际推进顺序](SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md)：下一独立单元及其依赖。
4. [第1—6章范围](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md)：各章完整交付边界。

然后按当前任务选择下面的目录，不必逐份重读历史实验。

| 目录 | 用途 |
| --- | --- |
| [reference/](reference/README.md) | 当前架构、接口合同、采样规范、运维流程与决策 |
| [validation/](validation/README.md) | 按主题索引的已执行验证、部署和回滚记录 |
| [evidence/](evidence/README.md) | 原始审计 JSON、保留证据清单、预登记计划和图表 |

最近完成[本地 Planner 恢复](validation/LOCAL_PLANNER_REPAIR_VALIDATION_2026-09-08.md)：
本地 Spark 已在原会话验证正常回复，在线网关按用户要求暂不处理。
此前完成[新版网页日常 RX 使用验收](validation/DAILY_RX_USE_VALIDATION_2026-09-08.md)：
三段实收、停止恢复、结果管理与监控共存通过，实际发现的扫描/取消文案已修正。
此前完成[非模型运维部署](validation/OPERATIONS_RX_DEPLOYMENT_VALIDATION_2026-09-08.md)：
Web/Planner 专用日志、只读健康与本地去重告警已安装，识别仍关闭。
此前完成[Web 界面重构与部署验收](validation/WEB_UI_REDESIGN_VALIDATION_2026-09-07.md)：
固定导航、折叠设置和可读频谱已安装，原会话/结果保留，识别仍关闭。
此前完成[Web 后台升级与会话恢复验收](validation/WEB_RECOVERY_UPGRADE_VALIDATION_2026-09-07.md)，
Web 制品和退出预算已更新，原会话/结果保留并已实际回滚验证；识别仍关闭。
此前已安装[统一 CLI](validation/UNIFIED_CLI_VALIDATION_2026-09-07.md)：
Web/终端/脚本/恢复共用 `sdr-agent`。识别系统尚未整体生产准入；源码完成、隔离
验证通过、实际安装和生产能力开放须分别核对。状态只在 checklist 维护，顺序
只在推进文档维护。

历史文档中的“下一步”“未完成”和旧命令只描述当时状态，不是新任务指令。
早期 Pi 验证已合入[历史合订记录](validation/PI_BASELINE_HISTORY.md)。旧 ROADMAP、
第4—6章独立排期、迁移待办与重复工作流已移除；原因及替代位置见
[整理记录](validation/DOCS_CONSOLIDATION_2026-09-07.md)。原文件可从 `7115b50` 的
Git 树取回，不需要恢复到当前工作目录。

审计/预登记/图表保留原始字节；其内部记录的旧 `docs/<文件>` 路径不改写，
通常位于 `docs/evidence/<同名文件>`。其中三份被冻结配置直接引用的审计 JSON
保留在原根目录，避免改变 profile/选择计划的路径合同；不额外复制。历史源码哈希仍对应当时提交。不要为
使旧记录看起来“最新”而修改失败结果、哈希、准入状态或原始 IQ 清单。
