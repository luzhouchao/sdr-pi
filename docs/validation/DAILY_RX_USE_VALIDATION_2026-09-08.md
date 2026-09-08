# 新版网页日常 RX 使用验收 — 2026-09-08

基线 `0078372`，分支 `codex/recognizer-amc-offline-validation`，开始时工作区干净。
本轮按用户新授权执行有限日常接收验收，检查新版网页、实际服务、结果与监控；
只修复现场发现的状态显示及取消反馈可读性问题。不属于 A1 或 O1b 24 小时完整闭环。
原始有界结果、制品和清理见[审计](../evidence/DAILY_RX_USE_AUDIT_2026-09-08.json)。

## 实际运行方式与用户数据保护

使用实际 `sdrharness-web.service`、已安装 `sdr-agent`、生产 Planner socket 和 P201，
不是 fixture 或第二个 collector。通过唯一临时 Web drop-in，追加本单元 Web
环境文件及 BindPaths/ReadWritePaths，使现有 PrivateTmp/ProtectSystem 限制下的
Web 能访问私有会话、配置、SQLite、capture/corpus 根。原生产数据路径不被覆盖。

切换前先 `/stop` 并确认，然后只停/启 Web；原 Planner、Spark、P201 未替换。
私有 provider 使用不可用 loopback 测试地址，不复制生产凭证；Planner 的原 provider
配置不改。本轮浏览器只设置扫描参数、确认创建、查看结果及 `/stop`，没有自然
语言、模型查询、识别或巡航指令。结束及失败清理都移除 drop-in，再恢复原 Web。
两条原用户结果、一条语料和两个 complete 会话保留，生产配置/CLI 哈希不变。

新的 Web/Planner/磁盘健康监控一直启用；它不访问 SDRD。旧 P201 recovery timer
仅在每次 RX 矩阵期间暂停，最后恢复，避免它在设备 busy 时发普通健康连接。
本单元逐个实际 generation 枚举 P201 inline 临时路径，使用专用 cancel 和只读
射频属性轮询；不另开普通 SDRD 状态连接争夺接收所有权。

## 预登记有限计划

每次矩阵全部采用 RX1/RX0/A_BALANCED、单通道、10 MS/s、10 MHz 带宽、manual
20 dB、每点 4096 ci16 样本、1 frame、250 ms capture deadline，不保存原始 IQ。

| 场景 | 频点 | 停留/settle | 最大原始字节 |
| --- | --- | --- | --- |
| 433 MHz | 433–435 MHz，1 MHz 步进，3 点 | 20 ms | 49,152 |
| 2.4 GHz | 2400–2480 MHz，8 MHz 步进，11 点 | 20 ms | 180,224 |
| 5.8 GHz | 5725–5805 MHz，8 MHz 步进，11 点 | 20 ms | 180,224 |
| 接收中停止 | 2455–2470 MHz，1 MHz 步进，最多 16 点 | 1000 ms | 262,144 |

每次最多 **41 点 / 671,744 字节**；以最大 settle/deadline 计的保守 RX 估计
51,291 ms，脚本在开始每轮前检查 300 秒验收时间预算，外部调用也各自有界。
这不是 300 秒硬实时总 watchdog；故障清理另有停止/恢复预算。每次采集前检查
可用空间大于最大字节 +64 MiB，现场超过 808 GB；每次创建前记录 generation 和
精确 `/tmp/sdr-agent-dev/agx-sweep-<generation>-<point>` 路径。
停止入口是可见全局 `/stop`；异常 finally 使用独立 CLI cancel，恢复原 service。

## 实收与浏览器结果

- 三段扫描完成并归档，频点数、频率、固定增益与预登记一致；功率/噪声值有限，
  浏览器结果标题准确关联当前 session/sweep，SVG 和频点表可查看。
- 433 MHz 和 5.8 GHz 首轮没有候选；2.4 GHz 首轮有一个功率候选。这些都是未标注
  现场窗口，不能据此认定协议/调制类别或评估识别准确率。Web 聚合接口不返回
  每窗全部采集质量计数，本轮不额外声称完整逐点 dropped/clipping 指标为零。
- 首轮正常扫描耗时分别为 1091 / 1713 / 1691 ms，噪声基线约
  −53.43 / −53.87 / −52.77 dBFS。原始窗口没有保留，功率摘要保存在审计中。
- 创建会话先取消一次：没有创建或采 RF；随后显式确认才接收。第三个测试会话
  淘汰旧私有会话时，原测试结果仍在归档，未触碰真实用户历史。
- 1440×900 桌面和 390×844 窄屏实际浏览器检查完成；频点数据和曲线能查看，
  手机页面无全局横向溢出。SSE 使用 state HTTP 响应和已渲染控件判定就绪。
- 在实际接收期间调用已安装 health oneshot，Web/Planner/disk 都 healthy。
  停止后完整射频恢复，首轮点击至恢复约 721 ms；Controller 明确报告取消/恢复。
- 三条测试结果在服务重启后仍在，初扫不补跑。删除先取消确认并核验记录仍在，
  再逐条用页面确认删除，最终私有结果库为空；原用户结果恢复后仍为 2 条。
- 第二轮最终 RX 矩阵再次通过三段扫描、结果管理和监控共存；页面正确显示
  “首次扫描进行中”和“首次扫描已取消”，取消后颜色中性。停止至完整恢复约
  684 ms，两轮都无浏览器 JS 错误。共登记最多 **82 点 / 1,343,488 字节**；
  两次正常扫描合计完成 50 点，取消场景均提前结束，上界不是实际接收总量。

所有正常完成/取消及最终还原均比较完整射频状态：LO 5,985,999,996 Hz、rate
30,720,000、BW 30,000,000，两路 manual/60 dB/A_BALANCED，全部 scan mask/buffer
为 0。设备一直为唯一 sdrd PID 5909；P201 无持久改动或新临时数据保留。

本轮采集/维护时段截取的 36 条健康快照均报告 Web/Planner/disk healthy，
状态变化事件为 []；不把这些 liveness 当作射频质量或模型健康。

## 现场发现与修正

首轮实际自定义 2455–2470 MHz 扫描，右侧却显示“首次全频扫描中”；点击停止、
Controller 已确认取消并完成恢复后，页面仍显示红色“首次扫频失败”。截图与
Controller 输出对应，证明是实际 UX 问题，不是射频失败。

现在进行中统一显示“首次扫描进行中”。保持后端持久化 `failed` 和不重扫逻辑；
只有当前会话最后一条相关 sweep 事件明确为“首次扫频已取消并完成恢复”，才把
展示状态转为 cancelled，显示“首次扫描已取消”和中性底色，会话列表同步显示。
真实失败、只有停止命令/通用停止通知、operator 文本、取消后又发生失败、没有
相关记录时都保持失败；不从按钮点击推定设备已恢复。老取消事件被历史压缩移除
时也保守退回原状态，不改写后端或归档。

第二轮截图还发现取消消息把底层 JSON 铺在主对话和侧栏；现将这条明确的
Controller 取消记录显示为简短中文说明，原字节仍保留在折叠诊断中。该最后显示
调整用刚才真实取消记录在最终安装 HTTP 页面上回放，不再增加 RF。

新增前端回归覆盖上述正反例及不修改持久化状态；前端 **12 tests passed**，
原生 Web **36 passed / 2 显式 fixture exporter ignored**，JS syntax、Python AST、
release 构建及 diff 检查通过。未改 Rust/Controller/Planner 协议，无需模型或
全套 RF 故障矩阵；第二轮真实接收专门验证最终已安装制品与更新后的显示。

## 安装、回滚及工具入口

最终 Web 为 3,282,208 bytes，SHA-256
`9095a1be2aedd57cb08d02b9d1e772ab8f17137e84160877194baf14b474449d`，
安装路径 `/home/jetson/.local/lib/sdrharness/bin/sdr-agent-web-console`，UI 标识
`20260908-rx-daily-v2`。release 为
`/home/jetson/.local/lib/sdrharness/releases/20260908-rx-daily-ui-v2/`，回滚为
`/home/jetson/.local/lib/sdrharness/releases/20260908-before-rx-daily-ui-v1/`。

每包只含 Web、source receipt 和 release.json，既有 verify-release 已校验。
v1 实际执行新→原 UI→新切换并通过用户数据/健康/RF 核验；第二轮真实 RX
使用 v1。v2 仅增加取消诊断的可读摘要，重新构建安装后使用第二轮真实会话
记录回放验证，HTTP 三份静态资源与最终源码字节一致，原诊断未改。
中间 v1 的制品身份及阶段记录保留在审计，制品目录已在最终验证后删除。

回滚：空闲时 `/stop` 并确认，停 Web，验证上述 rollback 包，然后把包内 Web
复制到 bin 的唯一临时文件，chmod 0755 后 atomic rename；启动 Web，核对
运行制品为 `7c374774…`、原两个 complete 会话、结果/语料及 health。无需替换
service/配置、回滚数据库或重启 Planner/P201。

复用脚本：
`python3 -B jetson-agx/sdrharness/scripts/validate-daily-rx-use.py --root /var/tmp/sdrharness-dev/<唯一新目录>`。
此脚本会临时重启实际 Web、切私有存储并真实采 RX，只能在确认空闲、用户允许的
本单元边界内运行；不是纯 UI mock。不要在同一失败目录重跑。保持原两个会话时
必须让 finally 移除 `/etc/systemd/system/sdrharness-web.service.d/90-rx-daily.conf`
并重启原 Web；若宿主进程被强杀，按其本轮 overlay.conf/plan/audit 核对后人工
停止私有 Web、取消/恢复 RF、移除该唯一 drop-in、daemon-reload/start 原服务，
恢复 P201 recovery timer，再按审计清理。不能直接删除仍被服务绑定的开发目录。

## 清理和能力边界

已停止本单元浏览器/辅助进程，原 Web 不再绑定开发目录，唯一临时 drop-in
已移除。精确删除两个验收根、构建根和中间 v1 release，共 **2,181 个文件 /
894,469,112 logical bytes**，4 个路径都验证不存在。未创建私有 socket；
P201 的 **82 个**预登记临时路径均已核验不存在。截图、私有数据库、配置、
构建、缓存及临时脚本已删除；仅在 Git 保留有界结果/receipt，不额外保存 IQ。

保留最终发布/原 UI 回滚两包 **6 个文件 / 6,570,276 bytes**，每文件哈希和用途
在审计中，UI 包不涉及模型/profile/capture 身份。当前部署与原用户结果/语料、
既有 RF 证据不参加开发清理。发布包待被其他已验证版本接替、回滚包待明确废弃
后，分别核对清单与真实路径才可人工删除精确目录
`rm -r -- /home/jetson/.local/lib/sdrharness/releases/20260908-rx-daily-ui-v2` 或
`rm -r -- /home/jetson/.local/lib/sdrharness/releases/20260908-before-rx-daily-ui-v1`。

不训练、不微调、不做模型诊断、不读取 locked test；epoch-10、FP16 autocast +
FP32 权重、RF-v1 不变，recognizer_available=false。无 NX/B210 发射、FPGA/BOOT
或 offload。日常短扫描仅验证接收/交互/恢复和有限监控共存，不构成生产识别准入
或 24 小时完整闭环验收。
