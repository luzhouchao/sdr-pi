# S5 Runner 工程识别执行接口

源码、有限真实 Worker/Runner/Spark 验证和精确清理已完成；状态见
[验证记录](../validation/RUNNER_RECOGNITION_S5_VALIDATION_2026-09-06.md)。不修改已安装服务。

## 入口与批准

Controller `--mode run-once` / `--mode execute` 显式同时配置
`--engineering-recognition-root <绝对 S3 runtime 路径>` 与
`--recognition-archive <loopback IP:port>` 才启用工程执行器。
交互 `sdr-agent` 使用同名配置，另须提供绝对 `--recognition-audit` 路径和
`--sdrd` 地址。one-shot 使用现有 `--audit-log` JSONL。

`/recognize <candidate-id>` 只提交工程提案，仍须 `/approve`；`/reject` 拒绝。
step 等批准，cruise 停在批准门，one-shot automatic 拒绝识别。
正常 Policy 继续依据 S1 health 拒绝未准入识别。工程入口不改变协议 capability，
`recognizer_available=false`，也不赋予 Planner 开启该入口的字段。

批准执行前重新验证 request/generation、候选、健康与预算，并要求 S3 Worker
ready、无活动/排队批次、generation 未过期且已配置 S4a GPU gate。
巡航批准等待计入原始时间预算；步数、时间或剩余字节不足时在 RX 前拒绝。
执行中的取消 token 沿用巡航绝对截止时间，不因预检或批准重新计时。

## 有界执行

每次执行先在候选中心作新鲜精查，再立即从同窗频谱生成 Target 并采集四窗，
避免把等待模型/批准之前的五秒 Target 直接用于采集。
固定 P201 RX1/RX0/A_BALANCED、2.1 MS/s、1.5 MHz 带宽、50 dB、100 ms settle。
精查和识别各 4,096 complex-int16，共最多 **32,768 RX 字节**；归一化 spool
最多 32,768 字节。控制与 capture deadline 复用冻结 RF-v1 profile。
中心受请求频率限制，候选带宽不得超过 RF-v1；不增加 TX 或硬件处理后端。

沿用冻结 epoch-10、FP16 autocast/FP32 权重、共享 RMS、连续四窗及 mean-logit。
S3 接管整批 spool，S4a 负责实际模型 GPU 租约。未标注实收结果经 S2 严格校验，
生产状态只能 unavailable/error，实验 top-1 单独保存，名称仍 provisional。
不读取 locked test，不训练，不冻结温度/拒识阈值。

## 取消与结果

交互 `/stop`、one-shot SIGINT/SIGTERM、巡航 deadline 和 30 秒 watchdog 请求
停止。30 秒是触发取消的上限，**不是保证整个恢复过程在 30 秒内结束**。
SDR 阶段发送 generation-bound CANCEL；Worker 阶段由 S3 Adapter 确认取消。
恢复/回收未确认时保留失败状态，不能因 stop flag 已设置就宣布安全完成。
会话在活动任务返回前不续代、不接受新动作；确认后续代并丢弃迟到结果。

S3 handoff 错误路径先关闭并删除 producer-owned incoming，再检查 owned；
防止检查后发生迟到 rename。若服务已接管，仍由服务确认取消并清理。

内部完整 S2 记录 POST 到 S6a 既有 SQLite，origin=`engineering_rx`，默认不留 IQ。
归档请求最多 66,560 字节，响应最多 16,384 字节，总 HTTP I/O deadline 1.5 秒；
严格核对 receipt 的身份、状态和内容长度。失败显式返回 archive_error，不能宣称
已经保存。用户仍可通过现有 Web/终端按 ID 人工删除，无清理级联到原始语料。

Planner 只收到紧凑 RecognitionObservation；IQ 路径、张量及完整 logits 不回灌。
归档恢复不会刷新观测时间，过期/外来 generation 摘要在构造请求时丢弃。
交互成功执行后自动启动一次 Spark 规划轮次，无需额外用户提示；unavailable/error
要求 hold 解释。该轮不重启已停止的巡航，硬件提案仍遵守正常批准规则；固定回归使用明确标注的合成 classified/rejected
输入，不把演示值或未标注预测作为事实。真实浏览器闭环验收单列 S6b。
