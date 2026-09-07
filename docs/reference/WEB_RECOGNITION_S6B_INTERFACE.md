# S6b Web 真实闭环结果接口

S6b 完成源码及隔离实机浏览器验收；已安装服务未切换，生产识别不可用。
复用 S5 工程 Runner 与 S6a 应用 SQLite/API，不建立第二套结果存储。

## 显式工程配置

仅主机环境可同时设置绝对路径 `SDR_WEB_ENGINEERING_RECOGNITION_ROOT` 与
`SDR_WEB_RECOGNITION_AUDIT`；Web 必须监听非零端口的 loopback 地址。
缺项、相对路径或非 loopback 地址启动失败。默认未配置时保持工程执行器关闭。
Web 将 root/audit 和自身归档地址传给原生终端的 S5 参数；UI 无生产能力开关。
工程 `/recognize <candidate_id>` 仍须 `/approve`，预算、实时 health 和联合 stop
由既有 Rust/S3/S4a 控制。

## 当前结果与历史

`Session.recognition_archive_id` 是可选归档行 ID。收到严格校验的 observation 后，
按 runner generation、request、candidate 查询既有唯一键，再验证 engineering_rx
来源和完整 observation 相等（包括原始时间）；只有完全匹配才提供当前结果按钮。
SSE 立即发布当前结果，按钮打开准确行；找不到记录则显示不可用入口。
详情保留 S6a 的四状态、数字 ID、provisional 名称、校准/拒识引用、来源、质量和
时延；实收实验与合成演示明确区分。默认不额外保存 IQ。

每次原生终端启动分配并先持久化新的 `controller_generation`，大于模板、历史
识别和持久化代次；整数溢出拒绝启动。恢复请求保留候选，但删除旧 recognition，
强制 recognizer_available=false，不改写归档时间。自动历史摘要过滤内部 IQ
路径、batch 诊断和完整结果字段；原始应用诊断事件仍独立保留。

人工删除归档同时清除匹配会话的结果指针和 observation.recognition，发布状态；
历史对话事件不是归档行，不随归档删除。取消删除不改变记录，确认删除后重启仍为空。
Web 退出发送优先 `/stop` 后关闭 stdin，让终端完成联合回收；工程子进程等待
40 秒，Web 等待 process gate 最多 42 秒。默认 RX 子进程预算仍为 4 秒。

## 验证入口

`jetson-agx/sdrharness/scripts/validate-closed-loop-results.py` 是有限验收脚本，
复用 S5 helpers，要求专用 `/var/tmp/sdrharness-dev/s6b-906a/`、本次构建三种原生
binary、S6a 导出的明确合成 fixtures、既有冻结模型资产及 Python Playwright。
脚本不是安装入口；运行前必须完成 AGENTS 的计划/空间/停止检查。
一次完整流程最多 81920 RX 字节；只采 RX，故障注入针对私有 Worker。
浏览器使用 DOM 和 SSE 在线状态等待，持续 SSE 不适用 networkidle。

证据：[S6b 验证](../validation/WEB_RECOGNITION_S6B_VALIDATION_2026-09-06.md)。
