# pi-durable 隔离核心验证 — 2026-10-26

基线 `c7d250a`，分支 `codex/sdr-improvements`。本单元实现真实 Harness + 磁盘 SQLite
的独立 Planner 核心，生产 main/session 协议尚未切换。不是整个 pi-durable 接入完成。

## 实现和实测

锁定 durable/chord 1.4.0；registry 仅注册 submit_plan，无 coding tools/Code Mode。
每业务会话使用独立 conversation。请求绑定 app session、Controller epoch、generation、
request ID、内容摘要和期限。持久记录工具意图及 prepared/dispatch_attempted/ACK 状态。
提案和 transcript 在同一事务保存；发送前先持久记录 dispatch_attempted。
ACK 缺失保留 unknown，不能自动重发。ACK 受理不等于硬件执行完成。

开库前使用独立、无业务数据的 SQLite EXCLUSIVE 事务作生命周期锁；第二进程被拒绝，
SIGKILL 后内核释放锁。主库目录0700、文件0600，拒绝符号链接/其他 owner/共享权限。
重开先撤销全部请求资格；仅同身份、无工具意图且未过期的请求允许显式恢复。
工具不声明 replay:safe；工具意图栅栏阻止 interrupted 后模型重新提交。

固定版本的 beforeRequest hook 异常会被上游报告后吞掉，因此另在真实 Models.streamSimple
入口执行身份/期限/预算守卫，不能依赖 hook 抛错取消调用。交付出口重复检查资格。
关闭自动压缩及 overflow 摘要，继续使用确定性 PlanningContext 裁剪。
Completions/Responses 强制 submit_plan；Spark 保留 JSON 载荷适配钩子。

共享 RunLease 保持到 Harness 实际空闲；取消期间迟到工具不能投递。
现有 session-server 的 socket 预约也保持至旧 runtime.dispose 完成，清理失败不放行新连接。
Harness.close 不被当成 abort。存储预算或写入失败后停止提案放行。
上限为16业务会话、每会话128请求、4项排队；64MiB为写入前预算门，
不宣称文件系统硬配额或单个事务绝不超出预算。

最终90项测试全部通过、无跳过（71项既有回归 + 19项新增），Node 22.19.0，
显式 TMPDIR、隔离 npm cache，`--max-old-space-size=192 --test --test-concurrency=1`。
新增测试实际执行子进程 SIGKILL、WAL重开、同epoch显式推理恢复、旧epoch零投递、
prepared/attempted不重发、内容冲突、队列撤回、延迟工具取消、期限、generation、
写失败、真实loopback HTTP/SSE三种适配及socket交接。失败恢复采用withdraw策略，
排队新输入会被撤回，需新请求重新发起；不把撤回解释为已执行。

32次连续hold峰值RSS151166976字节、heap50295232字节，SQLite/WAL/SHM共4456168字节。
这是有限隔离负载，不是满容量或24小时soak；SQLite默认WAL+NORMAL，不承诺断电无丢失。

## 真实提供商与设备停止

保留用户 opencode-go/deepseek-v4.1-flash、openai-completions、
`https://opencode.ai/zen/go/v1`及当前key。未改保存配置，也没有将key放入库或审计。
首次1024输出预算调用1次，未产生提案，原因为未保留，不能推断服务地址失效。
第二次4096输出预算调用1次、约3.04秒，返回submit_plan/hold，虚拟Controller确认accepted。
仅使用隔离模型→Harness→虚拟Controller，没有连接真实SDR执行器；不替代Web全链路验收。

用户后续明确要求停止原Spectrum扫频，覆盖草案中“不得中断”的旧限制。
通过原应用 `/api/collection/stop` 发送暂停确认，SIGTERM关闭collector945217；
数据集状态paused、完成335轮，暂停时间2026-10-26T09:49:44Z。
collector仅剩父Web尚未回收的zombie，无资源占用；不停止其Web/预测服务。
AGX至P201控制连接0；P201只读核对单sdrd1318，RX buffer/四路mask/TX buffer均0。
保留上次扫频LO/采样率/带宽/增益，不声称恢复未知的原配置；未恢复扫描。

## 边界与清理

生产Planner/Web未部署或重启；Rust未改。本单元无新RX/TX、训练或识别准入。
仍需session协议adapter、Controller持久账本/epoch/ACK/status、blocked任务运维、
归档/删除入口及可回滚部署，父checklist保持未完成。

已删除本单元隔离目录13500文件、96968164字节，临时保留0，路径不存在已核验。
测试socket由测试逐项删除，未修改现有应用结果。保留的是Git中的最小统计证据，
见[审计](../evidence/PI_DURABLE_CORE_2026-10-26.json)；无IQ、SQLite、key、构建或依赖制品入Git。

## v2会话与Controller对账（后续独立单元）

基线 `5d4d3b8`。源码新增默认关闭的v2会话adapter和Controller持久账本；
生产安装制品尚未切换。Worker用`SDR_DURABLE_DB`选择隔离数据库，
Controller用`SDR_DURABLE_CONTROLLER_DIR`明确启用v2；两端不同版本直接拒绝，不静默降级。
P3将进一步提供服务状态目录和运维入口，不能提前把这两个源码开关视为已部署。

会话握手带稳定业务session ID、Controller新启动epoch及generation；现有严格PlanResponse
仍为v1，仅外层v2 event携带plan ID、规范化action摘要、完整请求身份和绝对期限。
Controller先核对摘要、请求、实时策略、停止门及期限，再fsync持久接收判定并发送ACK。
同plan ID/身份返回旧ACK，冲突或同请求的第二计划拒绝；重复不再进入批准/执行分支。
Controller账本在独立0700目录、0600单链接文件中，用flock保持单所有者；
8MiB/4096项上限，临时快照fsync→rename→父目录fsync，写失败锁定失败状态。
账本只保存身份、判定及状态，不保存IQ、模型key、批准凭证或新硬件权限。

实际硬件worker启动前记录executing；结果后记录completed/failed，待批准为pending_approval。
重开将未终结的accepted/pending/executing改unknown，不恢复待批准对象或自动启动动作。
停止代次使未执行计划cancelled，执行窗口无法证明终态时保留unknown。
人工批准也受原绝对期限约束。hold完成仅表示建议处理完成，不代表做过硬件动作。
历史查询返回权威判定/执行状态；Worker只更新禁用的旧记录，不启用请求或补发提案。
重复ACK幂等；未知ACK的后续判定可记录，但不能因此推断执行完成。

adapter断连先关闭投递门、打断等待ACK的工具，再join abort；空闲close保留历史。
get_state仅返回最近16项有界状态和blocked原因；缺少任务定义/restart_limit等不自动重试，
通过abort退出阻塞，租约保持到真正清理完成。修正了idle交接微任务中的租约竞态。
Spark受控检索复用现有host适配，每个物理模型调用都重新检查身份、期限和4次预算，
不能仅在外层流入口检查一次后让检索循环绕过恢复门。

最终Node **99项通过、0失败/跳过**，设置192MiB heap并提供本单元Rust测试二进制。
Rust **139项通过、1项既有显式忽略**（bounded synthetic replay export），格式及
all-targets Clippy `-D warnings`通过。新增真实Controller/Worker/loopback HTTP闭环：
代理丢弃ACK后SIGKILL Controller，再以同业务session重启，旧判定只读对账；
两次新输入只有两次模型调用、两条completed记录，epoch不同，无旧请求重放。
另覆盖Controller重复提案、停止门、期限/迟到批准、进程锁/崩溃及写失败；
blocked缺定义任务可见且abort前不释放租约，ACK重复/冲突和Spark检索期限门通过。

首轮Rust两项旧socket测试因TMPDIR路径过长失败，改用更短的独立feature临时目录；
未放宽socket或生产预算。旧fuzz假定session只支持v1，按显式v2更新断言；
Planner请求仍只接受v1。Clippy发现一次无用Box转换，已修正。

真实OpenCode Go DeepSeek V4.1 Flash保持原配置/key/`/zen/go/v1`，本单元又执行一次
隔离真实Worker→新Rust Controller的hold：约3.77秒、退出码0、账本1条accepted/completed。
未配置SDR执行器，无RX/TX；这仍不是安装制品或Web浏览器全链路验收。

清理两个feature临时根，共17342文件、1364786325字节，临时保留0，均核验不存在。
最小统计及血缘见[协议审计](../evidence/PI_DURABLE_PROTOCOL_2026-10-26.json)。
生产Planner/Web、原SDK release和Spectrum暂停状态保持；后续是状态/归档删除、
服务单所有者与正常关闭、独立制品/回滚及安装验证。

## P3持久目录维护与实际部署

2026-10-26完成并安装在AGX。Planner使用每业务会话独立SQLite和根目录单所有者锁，
在操作socket前取得锁；Web把稳定业务ID传给Controller，Controller账本独立保存。
SIGTERM等待真实dispose及one-shot结束后释放根锁；未知提案/旧批准仍不自动重放。
生产 `recognizer_available=false`，Spectrum扫频仍暂停。

最终验证：Node **106通过、0失败/跳过**（192MiB堆，实际Rust二进制参与闭环）；
Controller **139通过、1项原有ignored**，Web **37通过、2项原有ignored**；
两Rust包fmt及all-target Clippy `-D warnings`通过。
新增覆盖服务根锁在socket处理前拒绝第二Worker、SIGTERM后接手、实际清理屏障、
稳定Web业务ID在 `--session-state off` 下跨Controller重启保持、在线拒绝维护、
SQLite归档完整性/哈希/恢复后的资格撤销、精确删除及其他会话保留、
异常文件/链接拒绝和通过 `current` 符号链接执行维护CLI。

真实安装hold第一次失败：上游HTTP400明确表示思考模式不支持强制指定命名工具，
Controller账本0提案。用户明确要求保留思考后，最终采用显式low思考级别和
`thinking.type=enabled` 时的 `tool_choice=auto`，模型仅注册 `submit_plan`；
未提交工具计划时明确失败，不把文字当动作。请求身份/期限/批准/去重门不变。
最终已安装r2的真实hold约**4433ms**完成：退出0，1次模型尝试，1条accepted/completed；
响应含1个非空thinking块。未提供 `--sdrd`，Controller无SDR执行器。
最终r3仅修正维护CLI的符号链接入口识别，全部源码逐文件与安装制品核对一致；
无须因此重复发模型请求。生产Web真实聊天和浏览器本轮未验收，未新建Web会话。

实际修正还包括：维护删除最初误拒SQLite owner journal，增加精确私有文件白名单后通过；
线上的维护命令最初因 `current` 与真实模块路径不同而未进入CLI，canonical入口检查修正后，
实际调用退出1并报告already-owned；一次错误从仓库根启动的Node检查已中止，最终只采用
隔离candidate的106项结果，遗留的两个socket已清理。
未放宽Unix socket长度、权限、预算或执行准入。

安装制品根为 `/home/jetson/.local/lib/sdrharness/`：

| 保留路径（相对该根） | 用途 | 文件数/逻辑字节（含manifest和链接） |
| --- | --- | --- |
| `planner/releases/pi-durable-1.4.0-20261026-r3` | 当前Planner、固定依赖与NOTICE | 12684 / 82240232 |
| `releases/pi-durable-1.4.0-20261026` | Controller/Web及对应unit模板 | 5 / 5980955 |
| `releases/pre-durable-20261026` | 匹配旧二进制、unit及Planner指针 | 6 / 5870340 |

每目录 `release-manifest.json` 记录版本、逐文件大小/SHA及删除方法，manifest自身SHA见
[P3证据](../evidence/PI_DURABLE_DEPLOYMENT_2026-10-26.json)。不含key/完整provider配置。
新Controller SHA为 `0ff37a800499cdcc102a69eeee60a5734179b4887061a60b46183354246609cf`；
新Web SHA为 `ee89bea61154b3a274245e5cb99316dba890c82ea61cd385faad7b274592e601`。
实际unit保留 `30-operations.conf`、192MiB堆及原资源/沙箱限制。
Planner增加0700 StateDirectory，实际DB/owner文件0600。
最终观察MemoryCurrent约34.3MB/1.5MB（Planner/Web），这是当前值，不是峰值；未提高限额。

完成新版→旧版→新版切换，最终r3再次做旧新切回及健康检查。
旧版运行期间，新库停机快照的4个文件SHA完全不变；旧unit不含durable开关，
没有读取/迁移新库。最终Planner健康返回session_protocol=2、durable=true；两服务active。
现有两个Web会话的initial_survey_status均complete，重启未触发新扫描。
实际Web Controller的环境身份与原session ID相同，账本及Planner库使用该ID。

回滚操作必须先停Web和Planner，等待Controller/Worker退出，再从
`releases/pre-durable-20261026` 恢复两个匹配二进制和两份unit，
将 `planner/current` 原子切到 `planner/releases/pi-1.4.0-20261026`，
`systemctl daemon-reload` 后启动Planner/Web。保留原operations drop-in；
旧unit移除双方durable环境开关，**不删除新库，也不让旧版打开新库**。
重新升级同样先停双方，用新制品目录恢复二进制/unit，再原子切回r3、reload/start。
任何未决动作保留unknown，不把回滚当成已取消或可重新执行的依据。
新库备份、恢复及精确人工删除方法见[当前运维入口](../reference/PI_DURABLE_INTEGRATION.md#当前安装与离线维护)。

最终P201只读复核：单sdrd PID1318，RX/TX buffer及全部scan mask均0，
AGX到30431/43110的控制连接0。Spectrum collector945217仅剩zombie、无资源；
保留Web/预测服务和既有用户数据，未宣称恢复未知扫描前RF基线。

清理 `/var/tmp/sdrharness-dev/pd3-1026`、本单元两个已替代Planner release和两个孤立socket，
共**47867个文件/链接，2264951962逻辑字节**，逐项确认路径不存在，临时保留0。
当前安装与回滚制品按上表保留；生产Planner历史和Controller账本属于应用存储，
不参与开发清理，其路径、用途、大小/SHA时点快照及人工删除方法见P3证据。
原两个未跟踪用户文件保留，无新IQ、模型或射频实验。

## 真实Web两点扫频2026-10-26

用户随后要求走一遍扫频流程，新增本次有界RX授权；原Spectrum连续采集仍暂停。
本轮使用已安装生产Web/Controller/Planner和真实OpenCode Go DeepSeek V4.1 Flash，
在原活动会话 `session-1789273063753` 中执行，不新建会话、不触发初扫、不改变provider/key。

实际浏览器流程：查看状态/逐步批准模式 → 输入精确两点扫频指令 → 等模型生成计划 →
核对Rust已验证计划的频率、采样率、带宽和停留时间 → 点击批准 → P201 RX/AGX聚合 →
打开“频谱结果”确认图表、指标、IQ保留和删除入口 → 点击“立即停止” → 查看最终状态。
只有一次实际模型调用和一次硬件执行；浏览器pageerror为0。截图已检查，开发副本已删除。

有限计划：2455/2456MHz，步进1MHz，10MS/s、10MHz带宽、固定增益20dB，
每点settle20ms后接收4096点，aggregate=1，point timeout250ms，
最大IQ `2×4096×4=32768` 字节。执行前AGX可用706664181760字节。
Controller的dwell+timeout公式为540ms，不包含连接、配置及传输开销；
执行前预计硬件约2秒，实际1040ms。Planner请求有30秒绝对期限，
浏览器各活动尝试的等待有界，准备/只读复核不计入该尝试时限。

结果：两个频点功率分别−53.537495/−53.754673dBFS，噪声基线−53.537495dBFS，
0个超过阈值的候选、零削顶。不能用本次短时两点接收证明整个频段没有信号。
原接线保持B210停发；没有TX、训练或识别，生产 `recognizer_available=false`。

Controller plan `bfb6b64b-9f06-4e93-a8df-529b4176e0c1` 为accepted/completed；
Planner同计划为accepted、controllerExecution=completed、modelAttempts=1、
停止后enabled=false、reason=reconciliation_complete；旧批准未恢复、没有重放。
最终状态为Holding、模型空闲、队列0、无待批准计划、巡航未启用，待核对/阻塞均0。

执行前后19项P201属性逐字一致：LO、采样率、带宽、两路gain mode/gain/端口，
RX/TX全部buffer及scan mask。实际健康CLI确认RX1/RX0/A_BALANCED、healthy=true；
单sdrd PID1318，控制连接0。精确P201瞬时目录
`/tmp/sdr-agent-dev/agx-sweep-1793013963098-0` 和 `-1` 均不存在。

应用结果新增1条：结果ID16、`request-1`，原始IQ32768字节、SigMF元数据683字节，
合计33451字节保留在应用captures目录，未复制IQ。精确路径、SHA、request/session/plan身份
与人工删除方法见[本轮证据](../evidence/PI_DURABLE_WEB_SWEEP_2026-10-26.json)。
可在网页“频谱结果”选最新request-1后点击“删除这次采集”，或DELETE `/api/results/16`；
不删除其他结果或共享SQLite库。

准备时已修正三类浏览器检查问题：隔离XDG缓存改变浏览器查找位置，改用既有浏览器目录；
SSE持续连接导致networkidle不能收敛，尝试后改等真实控件；
两次状态文字精确匹配超时均发生在模型请求/RX之前，并发送/stop，
最终兼容Idle/Holding后只有一次真实模型及扫频。没有为通过检查修改应用门禁。

本轮无需源码改动或重建。只做实际浏览器/实机验收及文档、链接、diff检查。
删除 `/var/tmp/sdrharness-dev/pd-web-sweep-1026` 的97文件、1589729逻辑字节，
截图、脚本、浏览器缓存均清理，临时保留0；上述应用测量结果按用户设置保留。
Spectrum连续采集仍paused，不恢复后台扫频。

## 有界自动巡航与重试2026-10-26

用户开启自动巡航后，首次8步完成；随后按“重试”再次执行8步。每次独立硬预算为
8步、120秒、1048576字节IQ；任务指令限制2445–2465MHz、单步最多5点，
10MS/s、10MHz带宽、20dB、dwell20ms、settle20ms、每点4096样本。
频段指令不是新增硬频率围栏，Controller既有70MHz–6GHz及单次span20MHz限制仍有效。
完整有限计划、执行前空间、停止路径及临时路径见[本轮证据](../evidence/PI_DURABLE_AUTO_CRUISE_2026-10-26.json)。

首次36频点/589824字节，重试38频点/622592字节；每轮8条Controller账本均
accepted/completed，重试8条Planner请求均只调用模型一次，执行completed。
首轮0候选；重试部分步骤报告候选，仅表示功率候选，无识别/标签确认。保留DeepSeek
low思考及自动工具选择，模型工具仍只有submit_plan；没有TX、训练或生产识别切换。
两轮分别受1MiB预算约束，合计1212416字节不是单轮预算。

首轮结束后出现多余上游retry：自然完成已发送agent_end，随后空闲abort又重复发送。
修复为只有原先active的abort发送结束事件。回归修复前2次结束事件断言失败，
修复后自然完成再abort及活动取消两项均通过。独立Planner r4部署并完成r4→r3→r4健康切回；
重试没有多余retry，实际浏览器观察到“已用完巡航步数”自然退出。
首次监控脚本误匹配退出文案，在140秒发stop时硬件早已完成；重试已纠正文案。

复核发现Web按session/sweep_id唯一保存，而重启Controller会从request-1开始计数，
造成第二轮覆盖原结果16–23的索引payload。原始SigMF均还在。Controller实际request/inspect
执行ID现含128位随机epoch，最长61字节；消费者测试确认新执行独立、同消息重放幂等。
先停止双方服务、保存第二轮payload及临时SQLite备份，事务内将原16从既有封存证据恢复、
17–24从首轮快照恢复，第二轮以独立ID33–40插入。第二轮显示时间按SigMF开始时间加elapsed
重建，为估计完成时间；旧证据不改字节，原始IQ/metadata不改路径或内容。

Node108项、Controller140项（另1忽略）、Web38项（另2忽略）、Rust格式及
all-target Clippy -D warnings通过。新Controller独立release r4已安装，完成新→旧→新切回。
第一次部署验证误用/health路径，纠正为/api/health后完整重做通过；最终Planner/Web健康。
浏览器实际打开第二轮末条、第一轮末条与原单次结果，点数5/4/2，pageerror为0。
本单元未在新Controller安装后额外发RF；新ID由单元/消费者测试验证，实机RF事实来自上述两轮。

19项RF属性与执行前逐项一致，单实例sdrd、控制连接0、两轮P201瞬时目录均不存在。
最终巡航用完8步退出，模型空闲/无待批准；原Spectrum任务仍paused，recognizer_available=false。
两轮用户结果16份IQ与16份metadata保留在应用存储，32文件1231518字节；
每个精确路径/大小/SHA及人工DELETE /api/results/{id}方法见证据。原单次结果继续按原证据保留。
新Planner/Controller release与所需旧回滚release保留，manifest和精确大小见证据；
本单元所有临时脚本、隔离源码、缓存/构建、浏览器文件及SQLite备份均删除，清理数量见证据。

## 自动巡航决策复盘2026-10-27

本单元只读复用2026-10-26重试的8步数据：durable SQLite以mode=ro读取，
按request/toolCallId连接实际输入、submit_plan及Controller状态，再与8条封存结果及
生产结果API逐项核对。无新模型调用、RF操作、服务重启、IQ读取/复制或部署改动。
完成条件为核对7次反馈、候选后续动作、重复扫描及停止原因，而非新增实机验收。
派生记录及父级SHA见[决策审计](../evidence/PI_DURABLE_CRUISE_REVIEW_2026-10-27.json)。

| 步骤 | 实际调谐中心范围 MHz | 步进 MHz | 结果候选数 | 对下一步的影响与复核 |
| --- | --- | --- | --- | --- |
| 1 | 2450–2460 | 5 | 1 | 2450候选触发低侧扩扫 |
| 2 | 2446–2450 | 1 | 1 | 2450仍高，转上侧细扫 |
| 3 | 2450–2452 | 0.5 | 1 | 2450.5功率高，继续缩小网格；不能据此认定跳频 |
| 4 | 2450.25–2451.25 | 0.25 | 0 | 中位参考升到-39.36dBFS；之后仍继续局部细化 |
| 5 | 2450.5–2451 | 0.125 | 0 | 理由把上一轮2450.25误写为2446.25MHz；动作参数未越界 |
| 6 | 2450.55–2450.95 | 0.1 | 0 | 有“复核可重复性”理由，但未保持相同网格 |
| 7 | 2450.1–2450.5 | 0.1 | 0 | 以“已定位上缘、测下缘”解释，物理定位证据不足 |
| 8 | 2450–2455 | 1.25 | 0 | 换邻域；执行后Controller用完8步强制退出 |

8个计划与实际中心网格一致；步骤2–8输入中的上一轮中心、功率和候选数量全部匹配，
功率序列化误差最大1.85e-6dB。顺序候选数为1/1/1/0/0/0/0/0，
不能按恢复后数据库ID顺序推断执行顺序。38次测量覆盖26个不同调谐中心，
12次中心复测，没有完全相同网格重复；有解释的重叠不等于已实现硬性重复抑制。

结论：反馈传递及候选触发缩小调谐网格通过，物理定位与自主结束未验收。
`sweep.rs::analyze_ci16_window`的band_power是整窗IQ总功率，Planner只接收
调谐中心/总功率对，不接收点内SpectralSummary。全程采样率/射频带宽仍为10MHz，
缩小LO步进到100kHz不等于100kHz信号分辨率。各点是先后接收的4096样本
（每窗0.4096ms，不是连续20ms测量），不能将时变与滤波响应直接解释成窄带边缘或跳频。

`sweep.rs::median_power_dbfs`以同轮各点总功率的上中位数作为noise_floor_dbfs，
`merge_candidates`采用该参考+12dB门。步骤4–6参考升至-39.36/-35.12/-33.70dBFS，
导致局部细扫无候选；此值是相对功率参考，不是独立噪声测量，相对差也不是物理标定SNR。
没有候选不能推导无信号。模型第5–7步仍细化同一区域，与任务“无候选时换相邻位置”存在偏离；
Controller当前校验合法参数/预算，不裁决这项语义。第5步错误频率与第7–8步过强定位解释
也未被参数校验门发现。应保留思考，但不能把模型给出的理由当成已验证测量结论。

8步均为survey_band，stop_session为0；预算停止有效，却没有验证信息增益不足时的主动结束。
已安装system prompt只说明stop_session用于明确停止请求，未定义自主完成/低信息增益的具体停止条件。
下一独立单元应先修正Planner测量语义与有界局部复查/停止规则，并用本轮已存观测离线回归；
规则需硬性约束时仍由Controller负责，再按有限计划进入新RX验证。当前未开始这些代码修改。

更正前节“首轮0候选”：首次8步的request-3/result18实际包含1个候选，其余7步为0；
原封存JSON已有该事实，之前文字汇总有误。本节追加更正，不改封存证据字节/哈希。
本次仅新增派生审计JSON，未新增临时目录、构建、缓存或应用IQ；原应用结果照原删除API保留。
最终Web记录为空闲/无待批准/巡航未启用，Spectrum仍paused。纯记录修改仅核对事实、链接及diff，
未重跑Rust/Node/模型/RF测试；服务安装继续为前单元r4。
本次保留派生审计：`docs/evidence/PI_DURABLE_CRUISE_REVIEW_2026-10-27.json`，41458字节，
SHA-256 `29d254c00f279b601dc1697a2b85b64ba099cdadc35da8ff37981613bd80868a`；删除该精确文件并同步移除本文/checklist/索引引用即可，不删除源应用结果。

## 巡航规则离线修复2026-10-27

已实现测量语义修正及Controller进度门，完成条件是记录回放、硬门/账本及SDK传输离线验证；
本单元未部署或新增RF。证据见[规则验收](../evidence/PI_DURABLE_CRUISE_POLICY_2026-10-27.json)。
Planner明确整窗总功率、同轮上中位参考及相对+12dB候选的含义，不将调谐步进当成频谱分辨率，
不据此报告物理边缘/带宽/跳频；4096点短窗不称连续dwell积分。保留思考模式。

Controller自动巡航新增硬规则：同一调谐中心范围最多3次重叠访问，上一轮0候选后只能换相邻范围或停；
连续3轮0候选提前结束。两段多点范围可共用边界，点复查落在旧范围内仍计数；
规则覆盖survey/inspect，网格/带宽/候选ID变化不清计数，显式新巡航才重置。
这些是保守工作量门，不是物理RF判定；边界重叠较宽的新探索也可能被门拒绝，明确停止而不放宽。
拒绝在durable账本accept/ACK前登记rejected，执行前再次复核，重放不会操作硬件。

每轮新请求的cruise字段携带剩余steps/ms/IQ bytes、两个上限、空候选连续计数及最多8条访问摘要；
Controller保留最多128条完整本轮访问，摘要截断不绕过旧访问计数。当前人工模式无此字段。
Rust/Node都校验字段/数量/频率上限，最大768点/32候选加摘要仍在32KiB门内。
Planner允许目标完成或无有用且获准动作时主动stop；不强迫花完8步。

旧真实轨迹前4步通过，第5步无候选局部细化被拒；替代相邻探索被允许并在第三轮空候选结束。
含网格抖动/inspect绕过、旧访问摘要截断、预算运算、恶意越频/TX、主动stop及durable拒绝重放回归。
Controller149通过/1忽略、Node110通过、Web38通过/2忽略，Rust格式及all-target Clippy -D warnings通过。
Pi SDK真实HTTP/SSE传输只连接本地模拟上游，验证摘要及观测进入payload；未证明真实提供商会遵守新语义。
首次测试TMPDIR过长触发SUN_LEN，缩短本feature路径后完整复测；测试event信封与SDK文本块解码纠正记录在证据。
当前生产仍是r4；旧协议删除按用户后续明确要求另一个独立单元执行。临时构建/依赖缓存与测试目录删除数量见证据。
本单元清理13037文件/2138743892字节及10个符号链接，feature新旧路径均不存在。
保留规则证据7826字节，SHA-256 `487afdc9fd2bf02c4f313d75cc7b622bc1239aa2a8425a7dee843ccb2aa83bac`；无新应用数据。


## 仅支持最新版与旧包删除2026-10-27

按用户“只兼容最新”“旧的可以直接删”要求，已删除旧SessionRuntime及其测试，
会话协议统一为v2；Planner强制持久目录，独立Controller默认使用XDG/HOME状态账本。
当前one-shot及只读health的v1是不同合同，继续使用；PlanningContext拒绝退役FPGA字段，
安装请求已迁移。OpenCode仅接受当前Pi目录的模型/API/地址，移除Zen地址及旧模型回退。
第三方NOTICE同步标明已启用pi-durable，原版权保留。

Planner/Controller/Web统一安装r5，包含前单元巡航进度门。实际使用
`opencode-go/deepseek-v4.1-flash`、`https://opencode.ai/inference/go/v1`。
新key原地保留，未复制或备份。两服务启动正常，v2/durable健康与recognizer=false通过。
真实模型仅一次hold，Controller accepted/completed；浏览器预设和历史5点结果读回通过，
页面异常0，26条历史结果摘要不变。思考low保留并有SDK载荷测试；本次hold没有独立思考事件，
不据此声称新推理流已观察到。未启动新RX/TX，Spectrum仍paused；新版巡航RF行为尚未重验。

Controller150通过/1忽略，Node100通过，Web38通过/2忽略，格式及all-target Clippy -D warnings通过。
旧同步response/get_state和地址测试夹具迁移后全通过。首次Web制品门发现嵌入旧静态资源，
在停服/改配置前拒绝，重新release构建后通过。原子安装后的第一次健康查询早于Planner socket创建，
等待就绪后完成核验，无第二次重启或放宽门禁。

按明确授权删除37个旧release目录，共48136文件、384112999字节；仅保留两套r5目录。
旧回滚制品不再存在，历史封存记录不改写；应用结果、IQ和持久状态保留。
本单元构建、测试缓存及脚本清理13591文件2352324146字节、10个链接，临时根确认不存在且无遗留测试socket。
保留r5共12686文件89270878字节；manifest、SHA、人工删除方法见
[最新版本证据](../evidence/PI_DURABLE_LATEST_ONLY_2026-10-27.json)。


## r5新版巡航实机验收2026-10-27

用户继续后，登记8步/120秒/1MiB的有限计划，单步最多5点、每点4096样本，
10MS/s、10MHz、20dB、dwell/settle20ms。首轮2450/2455/2460MHz；任务范围2445–2465MHz，
它仍是mission限制，Controller原硬频率范围未改变。执行前AGX可用706847399936字节，
P201单sdrd PID1318、无活动控制连接；两路端口A_BALANCED，scan mask/buffer均0。
停止路径为同业务会话`/stop`及专用cancel；完整计划及前后射频状态见
[实机证据](../evidence/PI_DURABLE_CRUISE_R5_LIVE_2026-10-27.json)。

实收2轮/8频点/131072字节IQ，约27.7秒含结束核验：
第一轮2450–2460MHz、5MHz步进、3点；第二轮换到相邻2460–2465MHz、1.25MHz步进、5点。
候选数按执行顺序为[0,0]。第三个模型提案为2461.5–2463.5MHz、0.5MHz步进，
重叠上一空候选范围，Controller以AdjacentSweepRequired拒绝并退出，未执行第三轮。
因此已实测相邻换段与空候选后局部细扫拒绝，且退出早于步数/时长/字节预算。
这不是模型主动stop：Planner仍提出违规细化，不能据此验收自主决策质量。
局部第四次访问门、连续三空候选停止及模型stop_session本轮未触发，保留既有离线依据。
无候选仅指同轮上中位参考+12dB门未过，不证明无信号、边缘或占用带宽。

三个Planner请求各调用模型一次；Controller前两accepted/completed，第三rejected/failed，
Planner对应状态一致。浏览器实际读回新增3/5点结果，页面异常0；原26条结果摘要不变。
自然拒绝退出后发`/stop`撤销旧代次，最终上游空闲/队列0/无待批准/巡航已退出。
19项射频属性逐项恢复，单sdrd且控制连接0，P201本轮临时路径不存在，Spectrum仍paused。
保留DeepSeek low思考，无TX/训练/识别准入或软件部署变更；recognizer_available=false。

保留应用IQ/metadata共4文件133216字节，精确路径/SHA和Web人工删除入口见证据；
本单元临时脚本/浏览器缓存共83文件890027字节全部删除，临时根确认不存在、无测试socket。
本轮仅追加实机记录，未改源码或重跑Rust/Node测试；JSON、链接及diff核验后提交。


## 持久提示刷新、新对话与完整巡航2026-10-27

只读诊断发现旧`session-1789273063753`的pi.agent.instructions仍是初建时提示，
SHA为930450bf0f06bae9c1bef3b4580310f740083ac835a136fc01d6432c0a80621a，
缺少巡航进度与整窗功率解释。Harness持久化Agent配置，之前仅createConversation设置，
attach已有会话未刷新。因此前轮实机虽有新Controller硬门，不能宣称模型收到新提示。
前轮失败记录保留，根因与派生验收见[本轮证据](../evidence/PI_DURABLE_POLICY_REFRESH_2026-10-27.json)。

每次attach现使用SDK configure，在撤销旧请求资格的同一事务更新model/thinking/instructions/tools，
然后才发布attachment。真实磁盘旧配置回归修复前失败、修复后通过：同conversation ID/history保留，
旧请求不重放，后续实际SDK上下文含新提示与最新cruise摘要。Node101全部通过、无跳过，
含实际已安装Controller丢ACK/重启端到端。隔离目录初次依赖复制/夹具缺失修正后重跑通过，
没有生产执行失败。未修改Rust，无需重跑其源码测试。

用户随后明确删除旧对话、使用新对话：离线维护删除旧Planner历史5文件336384字节（关闭前计数），
移除2个旧Web聊天，新建`session-1793070425380`“新版巡航”；结果数据库、IQ和权威Controller账本保留。
新建时临时禁用初始扫频并立即恢复原全局偏好，新对话初始扫描标记skipped，未自动接收。
Planner r6已安装，旧Planner r5包12681文件83256894字节/2链接删除；Controller/Web仍是当前r5。
新持久提示与源码字节一致，SHA eafb9dbb620f186fa0431a75de431e4f095468e718a9194c6fa6ebedd6b5b850，
思考low、唯一submit_plan工具保留，key值未改或复制。

用户再要求新对话跑完全程后，另登记8步/120秒/1MiB有界计划，执行前空闲/单sdrd/空间核验通过。
10MS/s、10MHz、20dB、dwell/settle20ms、每点4096样本，约17.9秒完成：
2450–2460MHz三点→2445–2450MHz两点→2460–2465MHz两点；共3轮7点114688字节IQ。
三轮均0候选，模型按摘要选择相邻区域、没有重复局部细扫；第三轮结果后Controller以EmptySweepLimit退出，
无第四次模型调用/扫描，未耗尽步数/时长/字节预算。3个请求各一次模型、双端accepted/completed。
这验收了本轮换段与三空硬停止，不是模型主动stop_session的证据，局部第四次访问门仍未实机触发。
空候选仅为相对上中位参考+12dB门，不能解释为频段无信号或占用带宽真值。

浏览器逐项读回3/2/2点，无页面异常，28条旧结果摘要不变，当前共31条。
19项射频属性恢复、单sdrd/控制连接0、P201本轮临时路径不存在；最终模型空闲/队列0/无待批准/巡航已退出，
Spectrum仍paused，recognizer_available=false。无TX/训练/识别准入。
新结果IQ/metadata保留6文件116931字节；r6保留12681文件83257328字节，逐项SHA/人工删除方法见证据。
最终暂存143文件1306109字节/1链接清理；初始化时误复制的依赖另删12659文件79552235字节
（按未变依赖字节重建计数），临时根与测试socket不存在。旧封存证据不追溯改写。


## 人工批准过期不再退出终端2026-10-27

用户报告11:22:00计划提示批准、11:22:35首次/approve即报
`plan cannot cross execution boundary again`并退出。账本期限实际为11:22:24.319（+08:00），
批准已晚约11秒；旧PlanLedger.begin将deadline与执行状态冲突合并为InvalidData，CLI直接传播退出。
第二次approve重开Controller后无pending；旧pending按原恢复门成为unknown，不追溯改为未执行或自动重试。
事件/身份与具体SHA见[过期验收](../evidence/PI_DURABLE_APPROVAL_EXPIRY_2026-10-27.json)。

修复保留原期限：合法待执行状态超过deadline返回TimedOut，重复执行/终态仍返回InvalidData。
Controller在真正创建硬件worker前将过期计划持久取消，提示重新提交且正常返回；
capture执行器还回Console，survey/inspect/recognition共用同一门。人工计划显示剩余有效秒数，
不延长deadline，不恢复旧批准。磁盘取消失败仍报错拒绝，不能作为过期成功掩盖持久化失败。

新增晚批准回归修复前复现原报错；修复后零worker、executor保留、重复批准正常、重启后仍cancelled。
另测过期与重复执行错误区分。Rust152通过/1忽略，库114、CLI25、巡航6、运维1、恢复6；
仓库JavaScript117全部通过，含新Controller丢ACK/重启端到端；格式和all-target Clippy -D warnings通过。
首次长TMPDIR触发既有Unix socket SUN_LEN限制，缩短feature根为a1027后完整重跑通过。

Controller/Web制品包r7已部署（Web字节未改），Planner仍r6；当前会话/status和浏览器输入可用、页面异常0。
旧unknown记录、结果摘要与corpus均保持不变；未调用模型、未重发原采集或执行“10次”。
生产只核验安装/同会话状态/数据保留，实际过期批准路径由隔离真实Console/ledger测试覆盖，未新增RF。
旧r5二进制包删除，当前制品保留5文件6014008字节，manifest见证据。构建/测试/浏览器暂存10931文件1405134610字节及1链接已清理，目录及测试socket不存在。

## 过期后点击批准重新规划2026-10-27

用户选择“过期后点击批准，自动重新规划，再确认新计划”。Controller保存待批准计划对应的原始任务，
使其在agent_end清空瞬时请求表后仍可用于本代次重新规划。逾期点击先持久取消旧计划，清除候选、
最近扫频和识别摘要，刷新设备健康，再按原任务提交一次新请求；使用新请求ID与新期限。
健康刷新不能证明旧RF证据新鲜，因此不会携带旧候选作为当前观测。新计划仍停在人工批准门，
运行中的重复点击不会排入第二次重规划。执行预检期间到期也在最终执行门取消并重新规划。
没有后台续期、不延长旧deadline、不恢复历史批准或unknown；原任务缺失时提示重新提交。

新增回归先复现无重规划行为，再验证原任务跨agent_end保留、旧记录cancelled、清除候选、
一次新prompt、双击去重和新计划零worker/等待批准。初次测试fixture的max_span不满足真实submit，
修为20MHz且替换提案使用独立plan ID后通过。Rust153通过/1忽略（库114、CLI26、巡航6、运维1、恢复6），
格式、all-target Clippy -D warnings、release构建通过；Node117全部通过，含新二进制丢ACK/重启端到端。

Controller/Web制品包r8已安装（Web字节未改），Planner保持r6。真实浏览器最初用单点survey，
被start_hz < stop_hz策略正确拒绝，随后stop；改用2455/2456MHz、1MHz步进、10MHz采样率/带宽、
20ms每点停留的两点计划重试。request2计划待批准后，等待账本deadline过去再点击approve，
旧计划cancelled，生成request3/新deadline并再次待批准；验收点击reject，最终Holding、模型空闲、
队列0、无待批准。页面异常0；未执行新RX、32份结果及corpus摘要与部署前一致，历史unknown未重放。
本单元只验证计划流程，不追加原“采样10次”。两生产服务active，思考仍为low开启，未修改/复制key。

旧r7包5文件6014008字节已删除；当前r8保留5文件6018105字节，manifest与二进制SHA及精确删除方法见
[本单元证据](../evidence/PI_DURABLE_APPROVAL_REPLAN_2026-10-27.json)。
构建/测试/浏览器暂存10111文件1146414309字节已删除，`/var/tmp/sdrharness-dev/r1027`及测试socket不存在。
保留当前安装、既有会话账本/结果和历史RF证据，没有新增IQ副本；旧封存证据不改写。

## 自然语言统一自动任务2026-10-27

用户明确需要理解自然语言目标、根据每轮结果自动决策，不把入口写死为固定重复/探索两种模式。
最终实现没有扫描句式解析器或固定频段重放。Planner通过同一submit_plan提出`start_task`，
包括任务正文、完整扫描目标数、动作/时长/IQ总预算和调谐频率围栏。Controller严格验证，等待当前
模型周期结束，检查存储空间并建立新代次；配置动作本身不采样，账本completed仅表示配置完成。
嵌套任务不能给自己追加预算。新动作仍过原能力、每动作预算、期限、批准门；/stop优先，重启不恢复自动执行。

只有完整survey成功落盘、健康和射频恢复通过才计扫描轮数；复查/采集只消耗动作和字节预算。
正目标数达到后停止，正常空候选不会替代该目标；其余预算/错误/安全停止仍有效，提前停止报告未完成。
目标数0表示语义/时间或扫描后还有工作的复合目标，模型从最新观测选择下一步或停止，保留探索进度门。
目标频次任务也记录有界扫描历史；不把计数交给模型、不固定复用上一轮参数。完成后的新请求清除旧任务执行状态，
防止新计划被旧的inactive-cruise分支静默忽略。普通解释问题仍是hold。

新增有限预算/围栏/嵌套拒绝、不同轮数目标、自适应参数、复查不计扫描、失败不计数/不自动重启、
旧代次任务不激活、结束后新请求及新协议归一化回归。Rust158通过/1忽略（库115、CLI30、巡航6、运维1、恢复6），
fmt、all-target Clippy -D warnings、release通过；Node118通过，含真实Controller丢ACK/重启端到端及持久提示刷新。
开发中固定参数/句式方案按用户澄清废弃；r9首次浏览器输入被旧压缩摘要包住，仅生成未批准计划，stop后无RF。
统一任务由模型读取压缩上下文，无需在Web保留特定句式。一次JS测试字符串换行断言和一次新增字段的fixture编译失败已修正，最终检查通过。

实际浏览器/真实OpenCode Go模型，在会话`session-1793076607439`按预登记总2MiB RX预算验证：

- “完成四轮并根据结果决定下一轮”：配置目标4、最多8动作/300秒/1MiB，自动完成4轮17频点，
  2455–2456→2456–2460→2460–2464→2445–2455MHz，最后一轮步进调整为2.5MHz；
  目标达到即停，无第5轮，所有空候选也未冒充目标完成。
- “先寻找候选，有则复查，无则结束”：配置语义目标0、最多3动作/300秒/1MiB，
  自动完成2455/2456MHz两点扫描，0候选后模型主动stop_session；未耗尽动作预算。
  本次没有候选，候选复查这一新实机分支未触发。

两目标共约64秒、5份结果、19频点、311296字节IQ；未逐轮批准，未发射/识别/训练。
19项射频属性前后相同，单sdrd/接收所有者、最终控制连接0，实际代次P201临时路径缺失。
原34结果/corpus保留，现39结果；历史unknown未重放，thinking仍low开启，key未改动或复制。

两目标RF流程在Controller r10/Planner r8上完成。随后r11只补任务结束后的新请求入口状态清理，
该回归及完整Rust检查通过；r11实际安装哈希/status与浏览器真实解释hold通过，零新增RF/结果，
没有把这次hold称作r11重跑RF。最终/stop及/status确认Holding、模型空闲/队列0、无待批准/巡航未启用。
Web二进制字节未改，两生产服务active。包与每份新IQ/metadata SHA、实际计划/提案、原始事件见
[统一任务证据](../evidence/PI_DURABLE_AUTONOMOUS_TASK_2026-10-27.json)。

删除r8/r9/r10二进制包和Planner r6/r7，共25377文件181071680字节及4链接；
当前r11保留5文件6042662字节、Planner r8保留12681文件79734832字节及2链接。
5新结果IQ/metadata保留10文件316463字节，具备Web删除入口；不复制原IQ。
开发暂存10918文件1492011222字节已清理，`/var/tmp/sdrharness-dev/b1027`及测试socket不存在。
保留会话/账本、原用户结果及封存证据，包目录树摘要和精确删除方法已登记。
