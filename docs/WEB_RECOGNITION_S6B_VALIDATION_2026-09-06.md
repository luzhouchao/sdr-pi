# S6b 真实闭环浏览器验收 — 2026-09-06

结论：S6b 源码与隔离真实浏览器闭环验收完成，临时数据已精确清理。
基线 `1448b04a675f056fd672a24e8518b597e00fe993`；未安装本次二进制或修改生产 provider。

## 实现与测试

Web 显式 loopback 工程配置接入 S5；当前结果严格关联 S6a 归档；SSE 即时展示；
每次启动持久化新 Controller 代次，恢复不重放旧识别；自动历史摘要排除内部
IQ/batch/logits 诊断；Web shutdown 等待原生终端联合 stop。
接口与运行前提见 [接口说明](WEB_RECOGNITION_S6B_INTERFACE.md)。

- 最终 Web 测试：35 passed、0 failed、2 ignored；显式 fixture 导出测试另行通过。
- Web all-target Clippy（warnings denied）、cargo fmt --check、JS 语法检查通过。
- 最终原生 Chromium 验收七项通过：批准前无执行/归档；实收自动回灌；Worker
  故障；四状态展示；重启恢复隔离；人工删除取消/确认及二次重启；无浏览器错误。
- 桌面及 390px 手机截图已人工检查，来源声明可见，无横向溢出。

## 实际证据和边界

最终验收 generation `1788676095387`。P201 RX1/RX0/A_BALANCED，2.1 MS/s、
1.5 MHz BW、gain 50；433.920 MHz 单点 seed 精查后，在测得候选中心执行两次
工程识别，每次新鲜精查加四窗。一次完整流程最大 RX 81920 字节，模型 spool
最大 32768 字节；起始空闲空间 808056946688 字节。无 TX。

真实 unavailable：request 1、generation `1788676121761`、原始时间
`1788676129559`，原因 production_admission_missing；实验 top-1 ID 22，概率
0.8144363141，仅为未校准预测。真实 error：request 3、同代次、原始时间
`1788676143170`，实际 Worker SIGSTOP/SIGKILL 后 supervisor_batch_failed。
两次真实 Spark 均经 Rust 验证返回 hold，未把预测称为确认分类。
classified/rejected 两条是 synthetic_fixture，引用 synthetic-only，不是实收或准入。

重启后的 Planner generation `1788676175539`，recognition 缺省，无内部 IQ 路径；
历史归档 ID、时间及内容完全相同。浏览器先取消删除，再确认删除四条私有测试
记录；再次重启列表为空，最终只读 SQLite 行数为 0。未触碰用户应用结果。

保留先前失败：首次 256-token fault feedback 未提交下一步计划，测试等待超时；
提高验收 token 上限到 512。第二次详情加载尚未完成即断言，改为等待实际详情
DOM 的 record ID。历史过滤前一次全流程也通过，最终源码再完成一次全流程。
每次尝试的结果、失败与哈希均保留在审计中，不把失败隐去或算作通过。

## 清理与部署状态

最终独立只读复核 P201 与起始状态完全一致：LO 5985999996 Hz、rate 30720000、
BW 30000000、manual gain 60、A_BALANCED，scan/buffer 全 0。sdrd PID 17136，
SHA-256 `77d98a005305a4b7531fc3f133e9b4af521e60b065b29fcc304b4c7db80c45ae`。
全部尝试记录的精确 P201 临时路径不存在，私有 Worker/服务进程与两个控制 socket
不存在；核对 resolved 路径后删除 `/var/tmp/sdrharness-dev/s6b-906a/`，确认不存在。
该目录包含本次 build、私有 DB、spool、缓存、日志与截图。没有删除用户语料或结果，
没有更改其他项目已暂停的采集状态。

[有界审计 JSON](WEB_RECOGNITION_S6B_AUDIT_2026-09-06.json) 保存真实 DTO、Planner
紧凑请求、七项验证、失败摘要、源文件/二进制/日志/截图哈希及清理记录；无 IQ、
张量、完整 logits、凭证或模型资产。冻结 epoch-10、FP16/FP32 权重和 RF-v1 不变。
未读取 locked test、未训练、未新增独立标签或冻结温度/阈值；名称 provisional，
recognizer_available=false。A1 真实已准入 classified/rejected 和部署验收仍未完成。
下一独立单元为 S4b，O1a 另行交付。
