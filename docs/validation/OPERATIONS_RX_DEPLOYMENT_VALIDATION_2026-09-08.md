# 非模型运维配置部署 — 2026-09-08

基线 `c00cf8a`，分支 `codex/recognizer-amc-offline-validation`，工作区干净；前次中断
没有留下部署进程或改动。本次安装现有 O1a 的 RX-only 运维配置，完成真实停服
告警/去重/恢复、日志轮转、配置回滚和最终核验。没有开展模型、RF 采集或 24 小时
识别闭环验收。证据见[审计](../evidence/OPERATIONS_RX_DEPLOYMENT_AUDIT_2026-09-08.json)。

## 现场审计和最小依赖

- Web PID 496587，制品 `7c374774…`，health ready/false；保留已完成界面重构。
- Planner PID 62839，自 2026-09-03 13:39 运行，向真实 planner.sock 发送只读 health
  返回 `request contains unknown field operation`。没有把旧进程当成健康接口已上线。
- 当前源码与对应单操作员版本 `600cbb7` 的生产源码差异仅五个文件：main 的只读
  health、session-server 的帧期限/队列边界，以及 S2 的 protocol、recognition
  observation validator 和 system prompt。GPU 相关提交在此目录只增加验证脚本；
  runtime 路由、Node 依赖锁、provider 选择、模型端点没有本次修改。
- 以既有 unit 重启 Planner，加载已有当前源码，未安装新源码副本、Node 依赖或模型。
  精确源文件、Node 和 lockfile 哈希见 release source receipt；当前源码允许未来
  继续开发，但运行中进程不会自动重载，后续重启仍须重新审计差异。
- 原 Web/Planner 没有日志 drop-in，health service/timer/config/script 及专用 journal
  配置均不存在；systemd 249 支持 journal namespace。可用磁盘超过 809 GB。
- 保留原两个会话、complete 初扫、2 条结果、1 条语料；配置、Web/CLI 二进制哈希
  在所有部署阶段均相同。Spark 未重启，P201 一直为 PID 5909。

## 实际安装

| 内容 | 实际路径/边界 |
| --- | --- |
| health 配置 | `/etc/sdrharness/health.json`，jetson:jetson 0600；Web loopback HTTP、Planner Unix socket、`/var/lib/sdrharness` 空间 ≥4 GiB |
| health 工具 | `/home/jetson/.local/lib/sdrharness/scripts/operations-health.py`，与 O1a 源码相同，不从可变 checkout 执行 |
| unit/timer | `/etc/systemd/system/sdrharness-health.service` / `.timer`；10 秒总执行预算，每次结束后 30 秒再次执行，2 秒精度，timer enabled/active |
| 状态 | `/var/lib/sdrharness/health/state.json` 及永久 `.lock`，jetson 0600；存有界状态，不存用户会话/结果 |
| 日志 drop-in | Web、Planner 各自 `/etc/systemd/system/<service>.d/30-operations.conf`；只设置 LogNamespace 与 stdout/stderr 路由 |
| journald | `/etc/systemd/journald@sdrharness.conf`：persistent 128 MiB、runtime 32 MiB、单文件 8 MiB、14 天，30 秒/1000 条速率限制；不向 syslog/wall 转发 |

健康 service 独立于 Web/Planner 的启动依赖，业务停止后仍能探测。使用现有严格
schema/false capability 校验、原子状态替换和 flock；网络被 systemd 限制为本机，
没有 shell/重启/采集/模型/外部消息动作。正常快照 `events=[]`；只有状态变化产生
alert/recovered，stdout 仅写入本地 journal。systemd 的例行启动/退出日志不是告警。

不配置尚未部署的 Mamba supervisor 和 Spark GPU gateway；此服务不声称覆盖模型
可用性或准确率。P201 保留既有 recovery timer，新的 30 秒探针不连接 SDRD，避免
在接收 busy 时引入竞争。当前交互路径未启用工程 recognition audit；O1a 的 Runner
8 MiB×4 JSONL 轮转已经在统一 CLI 中，本次不凭空创建该日志，也不迁移用户结果。

## 验证结果

- 原有 Python operations tests 10/10、Node 全套 56/56 通过；覆盖只读健康协议、
  失败关闭、去重、空间状态、私有文件、发布校验、会话队列/代次和单操作员边界。
  本次没有改动 Rust 或前端行为，因此没有重建 Web/Controller 或重跑模型测试。
- systemd-analyze verify 成功，仅有三个已存在的无关 unit 警告；配置 JSON、脚本
  AST、diff、文档链接及实际安装文件哈希检查通过。
- 实际新→回滚→新配置切换：每次先 `/stop` 并等待确认，停 Web 后停 Planner；
  恢复后原 session IDs、complete 状态、结果/语料 API 和配置/二进制哈希相同。
  恢复定时器在切换期间暂停，随后恢复。没有重扫或新建生产会话。
- 首次安装后 Planner health 返回 service=planner、ready=true、capability=false。
  最终 Web `/status` 显示会话打开、模型空闲、队列 0、没有待批准计划、巡航未启用。
- 暂停 health timer 后，通过真实 oneshot 检查验证：Web 停止一次 alert，重复检查无
  新告警；再停 Planner 仅新增 Planner alert，再次检查仍静默；启动 Planner 只产生
  Planner recovered；Web 恢复产生 Web recovered，后续没有重复恢复事件。监控没有
  自动启动两个业务服务。每次检查验证新 InvocationID，原状态文件没有删除或重置。
- 空间低阈值用私有配置和私有 state 模拟，实际工具产生一次 low_space alert、重复
  静默及恢复事件；没有填盘、改生产阈值或制造实际空间故障。
- 实际专用 journald 启动日志确认 max 128 MiB；执行限定 namespace 的 `--rotate`
  和 `--sync`，确认产生活动及归档 journal，各文件 8 MiB。没有对公共 journal 做
  vacuum，也没有用填满 128 MiB 的压力实验冒充必要验收。14 天自然到期尚未等待，
  不宣称实测时间淘汰；保留配置/真实轮转证据。
- 最终 enabled/active timer 实际自动执行的连续四条快照间隔为 [31993, 31340, 31664] ms，
  全部 healthy、events=[]；期间没有人工 start。oneshot Result=success、exit=0。
- 按 P201 技能用已有保护凭证与严格主机校验读取前后状态；LO 5,985,999,996 Hz、
  rate 30,720,000、BW 30,000,000，两路 RX manual/60 dB/A_BALANCED，全部 scan
  mask/buffer 为 0，前后完全相同，唯一 sdrd PID 5909。未写 IIO、未重启 P201。

### 失败记录

现场旧 Planner 对 health 的拒绝是依赖审计结果，重启加载已有实现后兼容。
首次故障脚本在 10 秒内连续启动健康 service 超过 systemd 默认 5 次门限，第五次
未真正执行。脚本误读上次 journal 为新结果而断言失败；finally 恢复 Web/Planner
和 timer。修正脚本，在密集人工测试间 `reset-failed` 并核验新 InvocationID 后完整
矩阵通过。没有改生产 StartLimitInterval/Burst，也没有放宽 health 合同；正常
30 秒 timer 周期不触发此次密集启动条件。失败日志 receipt 保留。

## 回滚和保留

- Release：`/home/jetson/.local/lib/sdrharness/releases/20260908-rx-operations-v1/`。
- Rollback：`/home/jetson/.local/lib/sdrharness/releases/20260908-before-rx-operations-v1/`。
- release 含 7 个部署文件、源码/依赖身份 receipt 和 manifest；rollback 含原 Web/
  Planner unit、原本不存在的新路径清单及 manifest。全部用既有 verify-release
  校验哈希、单链接、大小和完整清单；此工具的 installed=false 只表示它不执行安装。

回滚本次配置：先 `/stop` 并确认空闲，暂停 recovery timer，停止 Web/Planner；
`sudo systemctl disable --now sdrharness-health.timer`，停止 health service。核验
release 后，只移除与 release 哈希匹配的上述 7 个新增安装文件及空的两个 drop-in
目录。daemon-reload，启动 Planner 再启动 Web，确认两者 LogNamespace 为空、
原会话/结果/health 正常；停止不再使用的 `systemd-journald@sdrharness.service`、
`systemd-journald@sdrharness.socket` 和 `systemd-journald-varlink@sdrharness.socket`，
恢复 recovery timer。已实际执行并验证，然后重新安装最终配置。

这是**配置回滚**：不回退当前 checkout，不恢复旧进程内存中的 Planner 版本；
已有当前 Planner 源码兼容原 Web/CLI，回滚后 health 仍可用。原 unit 未被改写，
无需覆盖；保存副本用于事故复核。用户数据库、后续结果和 health 去重状态不覆盖。
日志/状态保持应用运维所有权，不因回滚删除历史。识别 Worker/profile/阈值和
准入配置不在此 release，A1 与 O1b 仍未完成。

已确认无进程引用本单元开发目录，删除 `/var/tmp/sdrharness-dev/ops-908a/` 的
**19 个文件 / 96,579 logical bytes** 并核验路径不存在；内容包括
测试临时文件、部署/故障脚本、配置草稿、日志和私有空间状态。没有创建 P201 临时
路径或保留 IQ；不清理用户结果、语料或原 RF 证据。额外保留两个发布/回滚包共
**13 个文件 / 20,415 bytes**。已安装的 7 个文件、health 状态与专用 journal
继续服务，属于实际运维数据；不把它们称为已清理。

发布/回滚包每文件的精确路径、大小和 SHA-256 在审计内；不涉及 model/profile/
preprocess 或 source capture 身份。只有新配置已被其他版本接替后才可人工删除
release；只有决定放弃该回滚才可删除 rollback，分别核对真实解析路径后执行
`rm -r -- /home/jetson/.local/lib/sdrharness/releases/20260908-rx-operations-v1` 或
`rm -r -- /home/jetson/.local/lib/sdrharness/releases/20260908-before-rx-operations-v1`。
当前运行日志由 journald 的限额/保留期管理，state 是当前去重依据，不属于开发
临时垃圾，也不是新 IQ 证据包。
