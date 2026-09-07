# S5 Runner 识别执行、联合 stop 与 Spark 回灌验证

S5 源码、有限实机验证和精确清理已完成。最终验证基线为
`dcc7a485319184a05ddc11fe00b9129b7bf74762`；S5 开发最初基线为
`134c479780fbd45bb3702a75dd54eb8c8a368385`，期间两次独立 B210 交付不混入本提交。
分支 `codex/recognizer-amc-offline-validation`。已安装服务未替换，生产能力仍为 false。

接口见 [S5 interface](../reference/RUNNER_RECOGNITION_S5_INTERFACE.md)，完整有界证据见
[S5 audit JSON](../evidence/RUNNER_RECOGNITION_S5_AUDIT_2026-09-06.json)。下一独立单元为 S6b。

## 本次完成边界

- one-shot/execute/interactive 显式工程入口接通既有 S3 Worker、S4a GPU gate、
  S2 结果及 S6a 应用归档。普通生产路径仍拒绝未准入识别；工程选择不由 Planner
  字段控制，也不会临时开启 `recognizer_available`。
- 人工批准后先重新精查，再立即生成新鲜 Target 并采集 RF-v1 四窗。每次最多
  两次 4,096 ci16，即 32,768 RX 字节；归一化 spool 最多 32,768 字节。
  保留冻结 epoch-10、FP16 autocast/FP32 权重、共享 RMS 和 mean-logit。
- step/automatic 批准门、巡航步数/原始绝对截止时间/字节预算、audit、优先 stop
  与迟到结果隔离。巡航等待批准不会重新获得时间预算。30 秒 watchdog 触发取消，
  不宣称整个恢复必在 30 秒内完成；恢复/Worker 回收不确定时保持 fault。
- 完整结果内部归档，来源为 `engineering_rx`；只把紧凑 S2 observation 回灌。
  **识别完成自动启动一次真实 Spark 规划轮次**，不需要用户再输入提示。
  unavailable/error 要求 hold 解释；后续硬件提案仍按正常批准规则处理，不重启
  已停止的巡航。`/stop` 完成前禁止新动作和续代。
- 修复 native S3 handoff 的取消竞态：先删除 producer-owned incoming，再检查
  owned；已接管的数据只能由服务确认取消并清理。没有改变 S3 wire 合同。

## 软件验证

| 检查 | 结果 |
| --- | --- |
| Controller library | 96 passed，1 项既有 exporter ignored |
| 交互 terminal | 16 passed |
| Web archive | 32 passed，2 项既有测试 ignored |
| Node Planner/session | 52 passed |
| Controller/Web Clippy | all-targets，warnings denied，通过 |
| Rust fmt、JS/Python 语法、diff | 通过 |

新增覆盖六动作/数字边界、工程批准、stale/foreign generation、Worker busy/queue/
GPU gate、归档 receipt 关联、stop 保留 owner/丢弃迟到结果、原始巡航三类预算、
自动反馈恰好一次和不暴露内部结果，以及迟到 handoff。
验证脚本另检查 IIOD/scan/buffer 空闲和 Planner 禁止字段；拒绝 Python `-O`，
避免检查被优化掉。没有训练、完整精度重跑或 locked test 访问。

## 最终实机证据

最终 generation **1788672799762**，脚本
`jetson-agx/sdrharness/scripts/validate-runner-recognition.py`。
私有 Worker/Spark/Node/Web 均位于本 feature，Web 复用既有 SQLite 实现但使用
独立测试数据库；默认应用结果没有被导入、删除或修改。

计划：433.920 MHz 一个 seed inspection，2.1 MS/s、1.5 MHz、50 dB、100 ms，
4,096 ci16；随后最多五次双采集工程执行，总 RX **上限 180,224 字节**。
实际中心由同次有限频谱精查生成，P201 RX1/RX0/A_BALANCED 固定。每次都打印
free-space、计划、字节上限、generation stop 和精确 P201 路径。本轮没有发射。
该上限属于最终一轮；历史重试各自有有限计划，不冒充整个开发会话的总实收量。

| 实机路径 | 结果 |
| --- | --- |
| one-shot pending / automatic | 等待批准 / 拒绝，均不启动 RX |
| one-shot operator | 新鲜 RX→四窗 Worker→S2 unavailable→归档成功 |
| 阻塞真实 Worker 后 SIGTERM | 确认取消，回收 Worker，恢复，丢弃迟到结果 |
| 实际 RX profile 生效时 SIGTERM | generation-bound 停止，射频恢复 |
| 交互 `/recognize`、`/approve` | 批准前无 RX；批准后真实执行并归档 |
| 完成后的自动反馈 | 无额外用户 prompt，真实 Spark 接收本轮紧凑摘要并返回验证后的 hold |
| 交互 Worker `/stop` | 等回收后续代，旧结果不进入新上下文 |
| 固定真实 Spark 回归 | 8/8 符合预期；每个接受提案均通过 Rust policy |

八项回归覆盖 error/hold、stop、指定参数 inspect、指定样本数 capture、指定频段
survey、recognition unavailable，以及明确合成的 classified/rejected。后两项
使用 synthetic 前缀和零哈希引用，Spark 必须说明合成性质；不使用真实未标注
窗口制造 classified，也不刷新旧实收结果时间冒充新观察。

S4a 共享 GPU 日志共有 **34 条 acquire/release 事件，零重叠、结束零活动租约**。
最终私有归档行 11、12 均为 engineering_rx/unavailable、非生产、不留 IQ，
通过既有 DELETE 接口删除后数据库行数为零。

## 保留的失败与修正

- 早期完整通过 `1788658761448` 仅作为初步证据，不替代最终源码验证。
- `1788663700223` 的 seed capture_failed_restored / health flags=16 及独立恢复
  读回不一致保留为失败。后查明另一项目直接 IIOD 长期采集占用 P201；用户明确
  允许后，通过该应用正常暂停入口停止，未强杀或改写其数据。它完成当前轮并记录
  `2026-09-06T04:09:31Z paused signal=SIGTERM`，连接和 scan/buffer 随后释放。
- `1788672098587` 全流程通过但仍靠用户提示触发反馈，审查后补上自动反馈；
  不能用这次通过掩盖 S5 自动反馈缺口。
- `1788672630638` 自动反馈已执行，但脚本把 identity 中的算法名称
  `float64_arithmetic_mean_logits_then_softmax` 误判为 logits 泄漏；修正为递归
  检查 JSON 字段名，完整 logits 数组仍禁止。该轮私有行 9、10 按精确
  session/generation 核对后清理，最终重新跑全流程通过。
- 更早的 Node socket 路径、控制 timeout、等待窗口和 RX 取消注入定位失败，
  按保留记录/日志哈希记入审计，不计为完成证据，也未放宽生产/射频检查。

## 恢复、清理和未完成项

最终独立核验 P201 恢复至原采集服务暂停后的基线：LO 5,985,999,996 Hz、
30.72 MS/s、30 MHz、manual 60 dB、A_BALANCED，所有 scan/buffer 关闭。
SDRD PID 17136、SHA-256
`77d98a005305a4b7531fc3f133e9b4af521e60b065b29fcc304b4c7db80c45ae` 未变，
Controller 只读 observe 为 healthy 且固定 RX1 身份正确。

四个最终私有模型 PID 已消失；所有 feature 进程停止。55 个从保留记录提取的
精确 P201 transient 路径均不存在。两枚 `/run/user/1000/sdrharness/s5-906a-*`
控制 socket 已删除；完整 `/var/tmp/sdrharness-dev/s5-906a/` 经 realpath 校验后
删除，包含构建、测试 DB、临时 IQ/spool、日志、私有 provider/key 和 CUDA/Triton
缓存。有界摘要与哈希保留在 Git；未删除用户已有结果、语料、模型或工具链。

S6b 实际浏览器闭环验收、S4b 资源 soak、V1b 独立标签、V2 校准/拒识、V3b/A1
生产准入及部署仍未完成。S5 不把这些父项或未来能力提前勾选。
