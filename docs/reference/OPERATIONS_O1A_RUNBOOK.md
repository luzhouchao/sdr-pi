# O1a 日志、健康、升级与回滚

这是 AGX 候选运行栈的可重复运维交付，未安装新服务。P201 仍只提供有界 Linux/IIO
RX，AGX 处理/保存/推理；不增加 TX、FPGA/BOOT、NX offload。V1b/V2/V3b/A1 数据与
生产准入门不因运维工具可用而完成。实际完成状态以权威 checklist 为准。

## 日志保留

Runner `JsonlAuditAdapter` 保留 current 与 `.1/.2/.3`，每段最多 8 MiB；单事件
仍最多 32 KiB，完整 JSON 加换行写入。append 前按文件大小轮转，不 copytruncate。
永久 `.lock` inode 使用非阻塞 flock；其他 writer 持锁、锁替换、写失败或异常
文件均返回错误，Runner 不绕过 audit 继续执行。每次 append 重新打开 current，
所以不同已打开的 Adapter 不会继续写已轮转的旧 inode。

锁、current、backup 必须为当前 UID 拥有、无 group/other 权限的普通单链接文件；
符号链接、硬链接和超限历史段被拒绝。轮转先检查全部管理文件再修改；只删除最旧
`.3`，不碰 SQLite/corpus/用户选择保存的 IQ。目录本身必须由受信操作员管理，
这不是对同 UID 恶意替换目录的隔离机制。备份轮转不是跨文件事务，断电时可能
留下段号间隙；I/O 中断也可能留下未完成的尾行。遇到写失败保持执行停止，先
保留原文件/hash 并离线检查，不能直接把损坏日志当作正常记录继续使用。这里不
宣称磁盘事务、fsync 级审计持久性或无限历史保存。

迁移旧 audit：先正常 `/stop` 并确认所有 writer 退出，保留原文件与 SHA-256 到
操作员指定的历史归档位置，检查空间，再使用新的空 current。大于 8 MiB 的旧
文件不会被新代码静默截断。不要在 writer 运行时删除/替换 `.lock`。需要更长
审计保留时先制定归档策略；不通过放宽现场磁盘限额或禁用 audit 临时绕过。

候选 stdout/stderr 的
[`journald-sdrharness.conf.example`](../../jetson-agx/sdrharness/config/operations/journald-sdrharness.conf.example)
定义独立 `sdrharness` journal namespace：persistent 总量 128 MiB、runtime 32 MiB、
单文件 8 MiB、14 天、30 秒 1000 条速率限制。示例 drop-in 将 stdout/stderr 送入
该 namespace，并给 Web 联合 shutdown 50 秒预算（S6b 内部最多 42 秒）。限额达到
时可能淘汰旧 journal 或限流，不能以其替代关键 audit。O1a 不修改现有 host journal。
这些文件是 A1 的候选配置，不能直接套用到 P201 BusyBox。

P201 继续沿用既有 sdrd 恢复/lifecycle。现场诊断只收集有界 tail 和 release/hash，
不增加持续 SDR 本地 IQ 或大日志文件。Pi 保持停机回滚基线，不重新激活采集。

## 只读健康与本地告警

Web `GET /api/health` 返回 schema_version/service/ready/recognizer_available 四项，
`Cache-Control: no-store`，不读会话、结果库、IQ、凭证或 provider。Planner Unix
socket 的精确帧 `{"protocol_version":1,"operation":"health"}\n` 返回同类 liveness；
不创建 Agent、不请求模型、不改变 session。ready 只证明服务能够响应，不表示
SDR 链路、模型准确率、GPU 调度或生产准入通过。

`operations-health.py --config ABSOLUTE_CONFIG --state ABSOLUTE_STATE` 读取 mode-0600
配置，最多 8 个固定名称探针。HTTP 只允许 loopback `/health`、`/api/health`，不跟随
重定向，禁止凭证嵌 URL、query、proxy；header ≤8 KiB、body ≤16 KiB、总 deadline
2 秒。Unix 为既有 Mamba control health 或 Planner liveness，connect/read 各最多
1 秒、reply ≤16 KiB。磁盘检查只用 statvfs，不创建采集。

当前工具针对未准入候选，必须看到明确 false capability；未知/畸形/超时/错误
响应都成为 unavailable。Mamba 还验证 queue capacity/depth。A1 若部署真正已准入
Worker，须接入 S1 的完整准入/实例/时间/hash 探测，不能仅把此脚本改为信任 true。

状态通过永久 flock 和 mode-0600 临时文件原子替换；重复故障不重复 alert，恢复
产生 recovered，移除探针显式报告 unmonitored。stdout 仅包含白名单状态、事件和
空间，不包含请求体、URL、错误原文、key 或 IQ。exit 0 全部 healthy，2 表示服务或
磁盘状态异常，3 是 monitor 自身配置/状态错误。**不自动重启、部署、外发消息或
切换上游。** `.service/.timer` 无 `[Install]`，O1a 不 enable/start。A1 安装时确认
配置的 loopback 端口与 socket，不能让未配置探针假装覆盖整个生产链路。

## 升级前检查

1. 记录当前 Git/release、binary/profile/preprocess/checkpoint hash、服务 PID、
   provider 路由和固定 RX1/RX0/A_BALANCED；保存本次拟上线清单、依赖 lock 和回滚路径。
2. 在独立版本目录构建/测试，不覆盖运行中的 checkout 或 executable。候选 manifest
   `release.json` 固定 schema/version/kind=false capability 和每个文件的路径/字节/hash。
   `verify-release.py --root ABSOLUTE_RELEASE` 仅校验，不部署；拒绝链接、路径逃逸、
   漏列文件、哈希/大小不匹配、读取期间变化和任何生产能力声明。
3. manifest 最多 256 文件、单文件 512 MiB、总计 1 GiB，适用于程序和配置；大模型
   仍用外部冻结资产与准入 receipts，不复制模型来塞入此包。保留输出 manifest hash。
4. A1 还必须验证 S1 所有准入证据、V1b/V2/V3b 结果、依赖 ABI/权限、GPU gate 同一
   inode和所有生产调用路由、实际服务单位及资源限额。candidate 文件校验不替代它们。
5. 定义可回滚的数据迁移。用户结果/语料保持应用所有权；需要备份时用 SQLite
   backup API 或停 writer 后的一致快照，记录其用途和空间。不要拷贝运行中的 DB
   主文件却漏掉 WAL，也不要为了程序回滚覆盖用户之后产生的结果。

## 切换与回滚顺序（A1 执行，O1a 只做私有文件演练）

1. 先阻止新工作，发送正常 `/stop`，等待 Rust terminal 联合停止 RX/Worker/Planner。
   Web 最多留 50 秒退出预算。确认旧 terminal、模型子进程退出、owned spool 清空、
   GPU gate 释放；未知回收状态保持关闭，不能 unlink gate 来伪造释放。
2. 保留旧版本目录及指针。新版本 `verify-release` 必须成功后才通过同目录 temporary
   symlink + rename 切换 AGX release 指针；新旧相同文件系统，目标版本不可原地修改。
   同步配置的 release 路径，不能只切 binary 却继续运行旧脚本/不相容依赖。
3. 按已审核 service dependency 启动共享 gate 的模型候选/Planner/Web，先只读 health，
   再人工批准的有限 RX 验收。O1a 不进行该生产启动，也不开启 capability。
4. 失败则停止新版本并确认回收，重新校验旧包/hash，将指针切回旧版本，启动旧服务
   并确认既有 receive-only 能力。保留失败产物/原因。若数据库 schema 不支持旧 binary，
   保持服务关闭并走预先审核的数据迁移方案，不能恢复旧 DB 覆盖新用户数据。
5. P201 如确需升级，必须另按
   [P201 skill](../../.codex/skills/p201-sdr-workflow/SKILL.md) 的 access/deploy 文档执行
   ARMv7 ABI、单 daemon、stop/replace/start、持久 release 和 readonly probe/恢复门。
   不使用 AGX release 指针流程修改 P201 volatile 根目录或 boot chain。

私有演练测试 A→损坏 B 拒绝且指针仍 A→修复 B 后切换→校验 A 并回滚，用户结果
sentinel 全程不变。它验证操作流程的前置校验，不冒充生产 upgrade/rollback 已部署。

## 重复验证入口与边界

`validate-operations.py --feature-directory /var/tmp/sdrharness-dev/o1a-UNIQUE` 统一运行
Rust/Node/Python/C sanitizer 测试，再启动私有原生 Web/Node，做固定 seed 的畸形
Planner/HTTP帧和健康→故障→去重→恢复。`--skip-suites` 只用于原生烟测，报告明确
列出实际运行的 suite，不得把省略部分算作通过。Worker parser 单元测试使用已安装
冻结 venv 的 Torch/NumPy，只有 synthetic 文件，不构造模型或读取数据集。

变异覆盖当前应用自有协议：SDRD parser、Rust PlanningContext/Planner response/
RecognitionObservation、Node Planner/session、S3 control/data、S4a HTTP、Web归档。
现有 Rust 真 socket 断连/超时/乱序/迟到和 fake-radio 恢复、S3/S4a 强杀/取消测试也
统一运行。私有 per-window Worker 使用既有合同/断管测试；IIOD/SSH/外部 HTTP 服务
不是本仓库实现，不宣称 fuzz 了第三方栈。有限确定性 mutation 不等于穷尽 fuzz。

所有 log、私有 DB、合成 IQ、构建和缓存在专用 root；结果只保留有界汇总/hash。
精确清理该 root 以及报告列出的私有 control sockets，不删除用户结果。后续 O1b
仍是另一个 24 小时完整闭环单元；O1a 不把短期回归作为长时运行证据。
