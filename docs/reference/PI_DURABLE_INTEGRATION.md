# pi-durable 接入与运维

状态：P0—P3及最新版本收敛已在AGX安装，保留思考；会话仅支持durable v2，旧安装包已按用户要求删除。日期：2026-10-27。
进展和边界见[隔离核心验证](../validation/PI_DURABLE_CORE_2026-10-26.md)。
下文设计基线/讨论保留当时语境；当前安装与运维以上方状态及以下运维段为准。
基线为 `490d83e9efda50c867ec16df124d0b805b7b486c`，分支 `codex/sdr-improvements`。
背景对话为 `01a1774c-5117-71f0-9de9-192cbd48a2c0`（确认 Pi 与 pi-d 工具）。

自动巡航已实测每轮8步/120秒/1MiB硬预算，两轮分别36/38频点，最终均用完步数退出。
空闲abort不重复发送结束事件；Controller实际执行的request/inspect结果ID增加128位随机epoch，
避免进程重启后请求计数重用覆盖Web历史。同一结果消息重放仍幂等。
已覆盖历史索引按封存结果与两轮API快照恢复，原SigMF不变；见
[巡航验证](../validation/PI_DURABLE_CORE_2026-10-26.md#有界自动巡航与重试2026-10-26)。
当前空闲，Spectrum连续任务保持暂停，不因服务重启恢复巡航。

2026-10-27决策复盘仅确认反馈与有界执行：`latest_sweep.points`是每次调谐后整窗IQ总功率，
`noise_floor_dbfs`是同轮功率上中位参考；小LO步进不代表等宽频谱分辨率。
既有8步不能验收物理带宽/跳频或模型主动停止，详见
[决策复盘](../validation/PI_DURABLE_CORE_2026-10-26.md#自动巡航决策复盘2026-10-27)。

巡航进度门源码/离线验收已完成：自动模式请求新增有界cruise摘要（人工模式省略），
本轮局部访问最多3次、无候选后换段、连续3轮空候选停；细节见
[规则验收](../validation/PI_DURABLE_CORE_2026-10-26.md#巡航规则离线修复2026-10-27)。Controller r5已应用此改动。随后有界实机2轮8点验证相邻换段及第三个违规局部提案拒绝，
射频恢复通过；模型尚未主动停止，连续三空/第四次局部门未在本轮触发。见
[新版实机](../validation/PI_DURABLE_CORE_2026-10-26.md#r5新版巡航实机验收2026-10-27)。

随后确认旧持久会话保存的系统提示未随r5更新；Planner r6在每次attach时原子刷新
model/thinking/instructions/tools并撤销旧请求执行资格。用户要求删除旧聊天，新对话已建立，
28条旧结果保留。新对话完整实测3轮7点：中心区→左相邻→右相邻，三空后Controller停止，
无重复细扫或第四次调用；不等同于模型主动stop。见
[提示刷新与完整巡航](../validation/PI_DURABLE_CORE_2026-10-26.md#持久提示刷新新对话与完整巡航2026-10-27)。

## 当前安装与离线维护

Planner为 `planner/releases/pi-durable-1.4.0-20261027-r6`，通过 `planner/current` 选择；
Controller及Web制品统一为 `releases/pi-durable-1.4.0-20261027-r5`，根均在
`/home/jetson/.local/lib/sdrharness/`。前轮37个旧安装目录及随后替换的Planner r5已删除，旧版回滚路径不再可用；
应用结果、IQ和持久账本保留。精确路径、大小、SHA和清理见
[最新版本验收](../validation/PI_DURABLE_CORE_2026-10-26.md#仅支持最新版与旧包删除2026-10-27)。
OpenCode Go当前选择为 `deepseek-v4.1-flash`，Base URL为
`https://opencode.ai/inference/go/v1`，API为 `openai-completions`；必须匹配当前Pi目录，
旧Zen地址和旧模型别名不再回退。真实hold已通过，新key原地保留且未复制。

- Planner启动必须配置 `SDR_DURABLE_STATE_DIR`，unit设置 `SDR_DURABLE_STATE_DIR=/var/lib/sdrharness-planner`，0700；
  `service.sqlite` 的独占owner锁在触碰socket前取得。每业务会话独立
  `<app_session_id>/planner.sqlite`，0600，最多128个目录、每库64MiB业务门限。
  attach已有会话也会刷新持久Agent配置；软件重启本身不会自动更新库内提示。
  旧隔离开关 `SDR_DURABLE_DB` 会明确拒绝启动，不能静默退回v1。
- Web给Controller传稳定 `SDR_DURABLE_APP_SESSION_ID`，账本根为
  `/var/lib/sdrharness/web-console/plan-ledger`。终端仍可用持久session路径生成稳定ID；
  安装CLI始终使用v2，默认账本根为 `$XDG_STATE_HOME/sdrharness/plan-ledger`，
  未设置XDG时为 `$HOME/.local/state/sdrharness/plan-ledger`；可用 `SDR_DURABLE_CONTROLLER_DIR` 覆盖。
- SIGTERM停止新请求，等待session dispose和进行中的one-shot，再释放根锁。
  正常退出与SIGKILL均不赋予旧请求新的执行资格；新epoch不会恢复旧批准或自动重发未知提案。
- DeepSeek保留原Planner的low思考级别，显式传给Harness及实际模型入口。
  Completions载荷 `thinking.type=enabled` 时使用 `tool_choice=auto`，避免上游拒绝命名工具强制调用；
  唯一模型工具仍为 `submit_plan`，没有有效工具计划时明确报错、零提案。
  其他载荷保留原命名工具选择。没有关闭思考，也没有放宽Controller校验。

维护仅在两服务停机后执行；在线调用明确拒绝。以运行用户jetson执行：

```sh
sudo systemctl stop sdrharness-web.service sdrharness-planner.service
/home/jetson/.local/bin/node /home/jetson/.local/lib/sdrharness/planner/current/src/durable-maintenance.mjs status --state-dir /var/lib/sdrharness-planner
```

在同一入口，使用 `archive --state-dir /var/lib/sdrharness-planner --session-id SESSION_ID --output /私有目录/新文件.sqlite`
做SQLite一致性备份，生成0600的DB及含SHA的manifest并fsync文件/父目录；不会覆盖既有文件。
使用 `delete --state-dir /var/lib/sdrharness-planner --session-id SESSION_ID --yes`
只删除选中的Planner历史，拒绝额外文件/非私有文件/链接；返回关闭前文件数/字节。
Controller账本是独立权威，以上命令不删除它，也不修改Web结果库。
完全人工删除会话时，先核对业务ID及各应用目录，停机后分别处理对应账本；不要清空公共根。

恢复归档时保持两服务停止，将归档复制到私有新会话目录的 `planner.sqlite`，
保持0700/0600，核对manifest的SDK版本、会话ID和SHA；不复制旧owner锁文件。
只支持本版归档，不承诺任意schema兼容。启动时撤销所有历史执行资格；不恢复批准或自动执行。
恢复前须另行备份原Planner库和对应Controller账本，不能用归档覆盖尚未对账的权威结果。
维护后通过systemd启动原两服务；不会新建Web会话或主动触发初始扫描。

## 目标与交付边界

把 Planner 的会话运行层迁到 `@earendil-works/pi-durable@1.4.0`。
先交付会话、输入队列、推理任务的持久恢复。
硬件计划的自动恢复必须另有 Controller 持久去重和对账。
不能用 SQLite 中的一条已提交记录，证明接收动作已经执行或尚未执行。

```text
Web / terminal
    -> Rust Controller（策略、批准、执行、权威结果）
    <-> Planner session adapter
            -> Harness / conversation / inbox / tasks
            -> SQLite（仅 Planner 自有状态，唯一 Worker 持有）
```

本单元不替换 Controller，不迁移 Web 结果库，不开放 shell、SSH、文件或 IIO 工具。
不启用 Code Mode、coding tools、子 Agent 或后台硬件任务。
`recognizer_available=false` 保持原边界。one-shot 路径暂时保留。
首次实施只用模拟模型和虚拟 Controller，不访问 P201。
原AGX Spectrum Agent扫频已按用户后续明确指令暂停；保持暂停，不为接入自行重启。

## 已核实基线

下表为设计时的490d83e基线；后续源码与隔离验证已推进，当前事实见上方验证链接。

| 项目 | 现状及影响 |
| --- | --- |
| SDK | `pi-agent-core`、`pi-ai` 已锁 1.4.0，TypeBox 为 1.3.27；durable 未接入 |
| Node | 22.19.0；已只读验证 `node:sqlite` 内存库可用，无需额外启动参数，仍有实验警告 |
| 会话 | `SessionRuntime` 的 Agent、队列、当前请求和提案去重均在内存 |
| 断连 | `session-server.mjs` 的 socket close 调用 `dispose()`，会清队列、abort、释放租约 |
| 提案 | `submit_plan` 通过 `plan_proposed` 发事件，没有已核实的持久 ACK/执行查询协议 |
| Controller | 按当前 generation 和内存 requests 验证；未知 request 报错；重复计划不是幂等受理 |
| 停止 | `/stop` 有优先路径；旧代次必须失效，批准不能持久恢复为有效授权 |
| 服务 | 系统服务 `sdrharness-planner.service`，安装路径为 `planner/current/src/main.mjs` |
| 资源 | JS 堆上限 192 MiB，MemoryMax=384M；当前未做 durable 资源测试 |
| 写权限 | `ProtectSystem=strict`、`ProtectHome=read-only`；仅有 RuntimeDirectory，无 StateDirectory |
| 上游配置 | 用户已接入 OpenCode Go DeepSeek V4.1 Flash；已核对保存的provider/model及key存在，未读取或输出key内容 |
| 上游验收 | 上一升级单元有71项测试；本次未调用真实提供商，成功hold对话仍需独立验证，不能由健康检查推定 |

源码位于 `raspberry-pi/sdr-agent/`。Planner 服务实际运行安装制品，修改 checkout 不等于部署。
实现前重查 HEAD、依赖、服务和工作区，保留原有未跟踪文件。

## 上游保证与限制

固定使用 [v1.4.0 README](https://github.com/earendil-works/pi/blob/v1.4.0/packages/durable/README.md) 和
[同版 package.json](https://github.com/earendil-works/pi/blob/v1.4.0/packages/durable/package.json)。API 为 experimental。
`pi-durable` 依赖同版 chord、pi-ai、pi-codemode、pi-telemetry；TypeBox 同为 1.3.27。
依赖被安装不代表对应能力允许注册。

- `Harness.open(storage, { models, registry }, context)` 打开会话存储。
- `conversation.submit({ type: "input", content, requestId }, context)` 持久受理输入。
  相同 requestId 返回既有 submission。它不证明 Controller 只执行一次。
- `harness.resume()` 启动调度；submit 和 wait 也可能启动调度。
  不能仅靠“尚未调用 resume”阻止未核对任务运行。恢复出口必须另设门。
- 工具只有声明 `replay: "safe"` 才会在调用中断后重跑。
  默认给模型 interrupted 结果。`submit_plan` 不声明 safe。
  模型收到 interrupted 后仍可能再调用工具，必须有独立的请求/提案状态约束。
- SQLite 入口是 `openNodeSqliteStorage`，导入路径为
  `@earendil-works/pi-durable/storage/sqlite/node`，底层经 chord 使用 Node 内置 SQLite。
- 存储要求单进程拥有，上游不提供跨进程锁。
  默认 WAL + synchronous=NORMAL，能处理进程崩溃，但断电可能丢最新提交。
- `watch()` 重连给当前快照，不保证补发所有历史增量。
  UI 不能把每条 token/event 当成唯一业务记录。
- 默认 restartLimit=5，达到后任务停在 blocked/restart_limit。
  需要诊断和受控重试入口，不能无限自动重启。

## 会话身份与恢复门

新增应用身份，字段名属于本方案，不是现有协议。

| 身份 | 设计用途 |
| --- | --- |
| `app_session_id` | Web/终端逻辑会话稳定 UUID，映射 durable conversation.id |
| `controller_epoch` | Controller 每次启动的新随机 UUID，避免重启后数字代次碰撞 |
| `session_generation` | 现有停止/会话代次，仍由 Controller 管理，不作为长期唯一身份 |
| `request_id` | 现有 Controller 请求；只能在对应 epoch/generation 下解释 |
| durable `requestId` | `epoch:generation:request_id`，同一输入重试必须复用并校验内容摘要 |
| `plan_id` | 对一个请求的首个提案分配稳定 ID，绑定规范化内容摘要；相同 ID 不允许变内容 |

首版对话可恢复，但旧 Controller epoch 的执行上下文不能复活。
旧摘要只能作为不具权限的历史。需要动作时由新请求重新取得实时 observation。
不得把旧计划改写成新 generation 后重发，也不恢复旧批准。

恢复前核对逻辑会话、Controller epoch、generation、未完成请求、截止时间及 provider 身份。
当前没有相应握手和查询保证；不能按现有 get_state 已经具备对账能力来实现。
握手缺失时只允许查看持久历史，不能放行恢复后的 plan_proposed。
恢复门必须覆盖所有调度入口和提案出口，不能让先恢复的推理绕过核对。

## 命令与模型适配

保留 session adapter，逐个映射现有协议。

| 现有命令 | durable 映射与约束 |
| --- | --- |
| open_session | 查找应用会话映射，重连身份核对后打开 conversation，不自动恢复权限 |
| prompt | submit input；原有 busy 拒绝语义用 whenBusy=reject 保持 |
| steer | submit input + whenBusy=steer；只在当前 run 的边界注入 |
| follow_up | submit input 的默认排队语义；保持一项一项处理 |
| clear_queue | 对排队 submission 调 abort，不能误杀当前输入；撤回须持久化 |
| abort / stop | conversation.abort 并清理队列，Controller 先使旧代次失效；wait 的 context 取消不能代替工作取消 |
| close / 断连 | 保留历史，暂停提案出口并取消当前工作；首版不改为无人监听继续跑 |
| get_state | adapter 返回有界状态、队列、恢复/blocked 原因；不暴露数据库内部记录 |

保留队列上限4、帧上限32 KiB、命令关联及停止优先级。
旧客户端不能因收到未知恢复字段而崩溃。严格解析协议需升级时，Controller/Worker同步版本并验证回滚。
one-shot 与 durable session 继续共享同一推理租约。模型调用在恢复路径上也必须取得租约。
一个 run 中存在多个 steer 输入时，工具关联不能只靠可变 currentContext 推断。

`main.mjs` 目前用 `createAgent`、streamFn、onPayload、工具校验与上下文变换。
Durable 使用 Models/Provider；不能假设把旧 Agent 放进 Harness 就能恢复任务。
先验证 Spark JSON planning stream、Responses、Completions、压缩和错误脱敏的等价实现。
载荷钩子是否可等价接入尚未核实；这是首个技术验证项。
不为绕过适配问题改掉用户 provider、模型、Base URL 或 key。

设计时保存配置为 opencode-go/deepseek-v4.1-flash、openai-completions，
Base URL为 https://opencode.ai/zen/go/v1，context_window=500000，key已配置。
这是2026-10-26非秘密字段核对结果，不代表旧地址的在线兼容性已验证。
P0模拟测试通过后，以此用户选择做仅hold/文本的真实提供商验证。
不预设继续使用Spark，也不因此删除Spark回归适配。新请求可产生模型费用，应使用有限重试。

## 提案与硬件结果跨进程对账

Planner 自定义 doc/outbox 只记录提案及投递状态，和 transcript 在同一存储事务提交。
状态至少区分 prepared、dispatch_attempted、accepted、rejected、unknown。
必须在对外发送前记录 dispatch_attempted；发送异常不能回滚成“从未发送”。
abort/clear_queue 不能把已经投递的动作标成已撤销；须由 Controller 确认取消或终态。

第一阶段禁止自动补发。凡可能已经投递、但无权威结果的请求，进入 reconciliation_required。
停止该请求及其排队动作，向 Controller 返回明确的失败/待核对状态，不能无限等候计划。
历史查询、恢复后的推理和新硬件提案分别放行。旧请求不能被模型再次 submit_plan 绕过。

若下一阶段要求自动补发，则必须同时实现以下协议与存储。

1. Controller 持久记录 plan_id、内容摘要、请求身份、判定和执行状态，先受理入账再回 ACK。
2. 重复 plan_id + 同摘要返回已存判定；同 ID + 不同摘要拒绝，不再次进入 pending 或执行。
3. ACK 只代表受理，不代表执行成功。查询应区分 pending_approval、executing、completed、failed、unknown。
4. Worker ACK 丢失时按 plan_id 查询；确认已受理后不重新驱动动作。
5. Controller 在硬件开始后、结果入账前崩溃，仍可能无法确定结果。
   此时只读核对状态/恢复证据，保留 unknown；不把缺少完成记录解释为允许重试。
6. 对账后的动作仍走实时能力、预算、期限和批准门。不得由 durable 自动延续批准或收发授权。

这不承诺外部硬件 exactly-once。先保证不因软件恢复重复执行，代价是某些请求需重新发起。
Planner 记录、Controller 账本和 Web 结果库各守职责，不复制 IQ、张量或完整 logits。

## 存储与部署约束

系统服务现使用 `StateDirectory=sdrharness-planner` 和目录模式0700。
每业务库路径 `/var/lib/sdrharness-planner/<app_session_id>/planner.sqlite`，仅此 Worker 写。
实现时检查实际 unit 合并结果、目录 owner 及 systemd 沙箱中的读写。
在 Harness.open 前取得进程级独占锁，第二实例直接拒绝；systemd 单实例本身不够。
不得放 /run 或安装制品目录。Web 通过接口查询，不能另开同库的 Harness。

保留 SQLite 主文件/WAL/SHM 的一致性备份；用 SQLite 备份方式或停机 checkpoint 后复制。
不要只复制正在写的主库。记录 schema、SDK 版本和备份恢复点。
暂不承诺断电无丢失；如需要更强持久性，先核实同版连接选项并测试 FULL/fsync 成本。
不能只写一个 PRAGMA，就宣称解决跨硬件提交窗口。

仅保存有界 PlanningContext、用户输入、允许的模型回复和状态。
key、鉴权 header、完整 provider 配置、原始 IQ 不入库；错误文本也要脱敏。
定义容量/保留期限、已结束会话归档和人工删除入口。不得直接删活跃 conversation 绕过任务清理。
先沿用现有资源限额；测 RSS、堆、库增长和模型延迟，不能未经测量提高限额。

## 分阶段交付与验收

| 阶段 | 修改范围 | 完成条件 |
| --- | --- | --- |
| P0 技术验证 | 独立 feature 临时目录，锁 durable/chord/pi-ai 1.4.0，模拟模型 | SQLite关闭重开、输入去重、队列撤回、流式适配、Spark等价行为、单所有者和资源预算通过；不能只测内存库 |
| P1 会话接入 | runtime adapter、会话映射、恢复门、服务StateDirectory；模型仅hold/文本或虚拟Controller | 重启恢复历史与推理；abort/断连不复活；同一请求不重复出提案；不向真实硬件发动作 |
| P2 跨域对账 | Controller持久账本、协议版本/握手、plan ACK/status、Worker outbox | ACK丢失/双端重启/未知结果均不重复执行；实时验证与批准门仍有效 |
| P3 可回滚部署 | 独立release、数据库兼容说明、会话状态及离线归档/删除入口 | 模拟端到端、只读健康与版本回滚通过；真实模型/真实RX按当时独立授权验收 |

故障注入至少覆盖：输入提交前后、模型生成中、提案入账前后、socket发送中、
Controller受理前后、ACK丢失、执行开始/完成前后、Worker/Controller分别或同时重启。
还要覆盖 stop/abort与恢复并发、旧epoch/generation、内容冲突、重复输入、重复提案、
队列溢出、第二写者、磁盘满/写失败、blocked任务、WAL恢复和资源耗尽。
存储失败必须停止放行提案，不能静默退回内存模式。

每个场景断言模型调用次数、提案次数、虚拟执行次数、批准状态及最终可见结果。
沿用71项SDK测试，并新增真实durable+临时SQLite的集成测试。
不要用新增测试数代替上述行为断言，也不为纯文档交付跑RF或模型实验。

回滚前停接新输入并使旧Controller代次失效，处理/冻结未决提案，关闭库后备份。
关闭进程不是“所有任务已取消”，重开库仍可能恢复未决任务，必须有持久的暂停/代次门。
以下是历史P3回滚设计；2026-10-27用户要求删除旧安装包后，旧制品已不存在。
历史操作：原子切换 planner/current 回旧制品；旧版不读取或重写新库。
保留隔离后的新库，旧版只可载入不含权限的摘要。再次升级先处理隔离的outbox。

粗估 P0 1–2 人日、P1 2–4 人日、P2 3–5 人日、P3 1–2 人日。
这是实施前的规划量级；实际完成情况以上方状态和部署验证为准。

## 多 AI 讨论与主控取舍

通过 Codex Foreman 调用了 DeepSeek V4.1 Flash（max）、GLM-5.3-Flash（max）、MiMo-V2.6-Pro（high）。
三方仅独立讨论，未起草或修改本文件。主控核对源码、上游固定版本和实际服务后整理。

GLM倾向先做持久账本，MiMo倾向直接迁Harness并同步加入ACK，DeepSeek倾向首版禁止补发。
采用分阶段Harness验证与保守恢复门。暂不接受“只装账本就获得任务恢复”的说法。
不采用MiMo提出的默认断连detach；首版保留取消行为，防止无人监听的工作继续派生提案。
三方指出的输入去重/外部副作用差异、缺ACK、单所有者和systemd写权限均已纳入。
三方部分示例只用generation作身份，主控补入controller_epoch，防止重启碰撞。
SQLite底层及Node可用性已额外核实；provider载荷适配、durable资源占用仍待P0验证。

讨论记录位于主控工作站 `E:\NXB210\.codex\foreman\runs\`，组为 `agx-pi-durable-20261026`。
GLM `20261026-171202-wvnd`；MiMo `20261026-171204-hdit`；DeepSeek续接 `20261026-171249-dd0a`。
DeepSeek首轮因尝试列出范围外目录暂停，主控未扩大范围，续接后完成。
含首轮的工具报告费用合计约0.06964美元；这是工具返回值，不是上游结算凭证。

相关依据：[运行架构](SDR_AGENT_RUNTIME_DESIGN.md)、
[SDK升级验证](../validation/PI_SDK_UPGRADE_2026-10-26.md)、
[上游SQLite实现](https://github.com/earendil-works/pi/blob/v1.4.0/packages/durable/src/storage/sqlite/node.ts)。

## GPT / Gemini 重讨论与实施交接

用户要求补入GPT和Gemini，并保留前组MiMo、DeepSeek、GLM意见。
本轮由GPT-6.1-Sol（high）、Gemini 4 Argon（medium）、Gemini 3.8 Flash（medium）独立讨论。
三方收到相同事实和源码材料，首轮没有收到主控旧结论。
随后就断连、身份与外部去重的实质分歧进行交叉核对。
这仍是技术讨论；文件由主控整理，没有多AI起草流程。

| 参与方 | 保留的主要意见 | 主控限定 |
| --- | --- | --- |
| MiMo-V2.6-Pro | Session Harness + outbox + Controller ACK | 放入分阶段路线；不采用默认断连detach |
| DeepSeek V4.1 Flash | 未知提案首版不自动重发 | 保留，不能把无回执解释为未执行 |
| GLM-5.3-Flash | 先验证账本及模型适配 | 可做技术验证；仅加账本不算完成durable任务恢复 |
| GPT-6.1-Sol | 分离历史/执行恢复，加入Controller启动身份和请求资格 | 纳入；重点测试abort后迟到工具与socket清理竞态 |
| Gemini 4 Argon | session-only、断连abort、保留确定性PlanningContext裁剪 | 纳入；不接受内存去重足够及彻底消除重复风险的断言 |
| Gemini 3.8 Flash | 首版不改Controller执行路径，禁止未知提案重发 | 作为P0/P1范围；若要求跨Controller恢复，仍需P2持久协议 |

以下规则约束后续实施，优先于讨论报告中的示例与乐观断言。

- 输入去重属于Harness，提案唯一性属于Worker业务记录，执行与批准权威属于Controller。
  三者不能互相替代。现有内存requests不构成跨进程执行账本。
- 首版保留异常断连abort与清队列。正常close_session沿用“只在空闲时关闭”的既有约束。
  进程崩溃无法运行清理；重开存储时先撤销旧执行资格，不能仅依赖dispose。
- 同一业务会话映射独立conversation，不能用一个全局root反复reset来冒充多会话隔离。
  provider session UUID、业务输入ID和执行请求身份分开管理。
- 新旧连接切换须等待旧runtime清理与租约交接完成。
  测试abort后迟到submit_plan、工具收到interrupted后模型再次调用，以及旧队列复活。
  不采纳讨论中的任意100ms释放指标；先证明取消和清理完成，再释放租约，不能为达标提前放行。
- 不把持久ACK与断连detach绑定。可以保留断连abort，同时增加Controller权威接收记录。
  如果首版不改协议，就明确不自动恢复旧请求的提案交付，不承诺跨Controller执行恢复。
- 开库前取得跨进程生命周期锁。仅有systemd单unit不够。
  若选O_EXCL锁文件，必须另证崩溃遗留、PID复用和竞争清理的处理；不能将文件存在当成活锁证明。
- StateDirectory只创建指定目录。选sdrharness-planner时库直接放其下；选其他根时显式创建子目录。
  不能依赖讨论示例中“自动创建planner子目录”的说法。
- Harness.close不是取消。submit、wait及其他可能推进调度的调用前均需落实资格守卫。
  关闭自动摘要后还须核实overflow路径，不能让LLM摘要替代最新无线事实。
- API签名、配置键、内存增量和工期均须以固定版本源码与测试确认。
  不采信零回归、必然OOM、回滚零副作用或硬件exactly-once的措辞。

首个独立交付为P0及P1隔离闭环，必须真正使用Harness与磁盘SQLite。
在feature临时目录接入模拟提供商和虚拟Controller，先不切换生产入口。
完成输入幂等、内容冲突拒绝、队列撤回、取消、崩溃重开、恢复门及排他锁测试。
断言同请求受理次数、提案次数、虚拟执行次数以及旧epoch投递次数。
旧epoch投递必须为零。未知提案不得自动补发。
沿用71项既有回归；one-shot共享租约和资源，不能以“未改代码”免做回归。

测试通过后继续P2/P3，不把P0演示当成整个接入完成。
真实DeepSeek验证采用独立会话和hold/文本计划，不让测试连接真实SDR执行器。
允许按项目规则进行源码、协议和隔离测试；切服务前完成制品、健康与回滚核对。
P201真实RX或任何TX不属于本交接新增授权，Spectrum Agent已按用户后续明确要求暂停。
遇到确定的API不兼容，记录具体差异并调整接入，不绕过身份、批准或恢复门。

两组原始意见、第二轮修正及模型验证元数据见
[六方讨论记录](../evidence/PI_DURABLE_DISCUSSION_2026-10-26.json)。
其中报告为各模型意见，不是已实现事实。以本文件的主控限定和后续验证结果为准。
新增GPT及Gemini调用费用未由工具提供，记为未知，不并入上一组已报告金额。

本轮组名为 `agx-pi-durable-gpt-gemini`。
首轮GPT `20261026-173508-wo1c`、Gemini4 `20261026-173535-8osk`、
Gemini3.8 `20261026-173733-3mu6`；交叉核对分别为
`20261026-173941-rur5`、`20261026-174143-yetc`、`20261026-173943-z0fl`。
两款Gemini均由适配器确认原生模型匹配，请求/实际模型元数据保存在讨论记录中。
交叉核对后，Gemini撤回了默认detach、内存去重足够或彻底消除重复执行的表述。
未采纳意见仍保留在原始记录，不改写其历史回答。
