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
