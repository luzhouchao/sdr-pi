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
