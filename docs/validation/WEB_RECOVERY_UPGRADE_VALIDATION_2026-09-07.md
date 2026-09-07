# Web 后台升级与会话恢复验收 — 2026-09-07

基线 `c3a4411a1b2d84efcb3c7e82d0e2b9cf6f59b18a`，分支
`codex/recognizer-amc-offline-validation`，开始时工作区干净。此次完成独立的
Web RX-only 升级、实机/浏览器验收及实际回滚；不是 A1。机器记录见
[有界审计](../evidence/WEB_RECOVERY_UPGRADE_AUDIT_2026-09-07.json)。

## 实际差异与部署范围

| 项目 | 开始时实际安装 | 本次处理 |
| --- | --- | --- |
| Web | PID 475400，`4e2a56eb…`，与 `20260905-p201-corpus-store-v1` 制品相同；HTTP app.js/index.html 与 `df7f8c3` 字节一致 | 替换为下列最终 Web 制品 |
| Controller CLI | `24b8340d…`，统一 `sdr-agent` | 保持原二进制；新版 Web 继续调用它 |
| Web service | 退出预算 8 秒 | 使用已有模板的 50 秒预算；其他 service 设置相同 |
| 配置 | 原 runtime.env、request.json、Spark provider.json；未设置工程识别参数 | 三份文件哈希均不变；仓库 request 与现场只在 observation 不同，无需覆盖 |
| P201 | PID 5909，`83a661a8…`，单 listener，RX1/RX0/A_BALANCED | 不替换、不重启；前后 PID/状态相同 |

旧 Web 的普通接收、展示、删除和停止已有实测，本轮没有认定它故障。与当前源码
相比，新 Web 包含 S2 严格 observation 校验、V1a 语料接口、S6a 归档、S6b 持久化
Controller generation/恢复请求过滤/联合退出及 O1a 只读 health。它们复用同一
Web 可执行文件及应用 SQLite，随本次编译链接进入制品；没有另建存储，也没有
部署 Worker、profile、校准/准入配置、GPU gateway 或重启 Planner/Spark。
工程识别仍未配置，`recognizer_available=false`。新增归档表兼容旧 Web，真实
回滚时直接读取同一数据库，没有复制 IQ，也没有用旧数据库覆盖用户结果。

## 本次修正

原 Web 的 stdout/stderr 任务和退出通知仅按 session ID 关联。同一会话重建子进程
后，旧读取任务可能晚到并更新其 observation、扫频结果或状态。现在每个子进程
拥有独立实例标识；记录输出、退出和领取初始扫描前同时检查会话与实例。已经被
替换的排队 actor 不启动，旧实例不能更新当前会话或写归档；退出前等待两条输出
流结束，再释放单进程所有权。会话切换时将尚在运行的首次扫描标记失败，恢复不
补扫；领取首次扫描时持久化失败也不启动该扫描。

沿用既有 Controller/Node 的 request/session-generation 校验，Web 新代次仍在
启动前持久化，恢复请求移除旧 recognition 并强制 capability false。`complete`
是现场及当前源码的完成状态；恢复仍压缩历史并保留最近 48 条事件，不要求整个
历史数组字节不变。

## 验证

- Web：36 tests passed，2 个显式导出 fixture ignored；新增回归覆盖同会话旧进程、
  错会话、迟到扫频/观测/模型输入/退出及排队 actor。Web fmt、Clippy `-D warnings`
  与 stripped AArch64 release 构建通过，系统 SQLite/glibc 等动态依赖均可解析。
- Controller：125 tests passed，1 个 fixture export ignored，包含真实 socket 的
  request/generation 乱序、迟到、停止和健康拒绝回归。Node：56 tests passed。
  Python AST、systemd unit verify 和 diff 检查通过；unit verify 仅有三个无关旧
  service 警告。没有调用模型、训练、精度实验或 locked test。
- 候选和最终安装制品各通过一次完整私有原生 Web + 真实统一 CLI + Node + P201
  RX 矩阵。Chromium 根据 state HTTP 200 和实际控件判定就绪，SSE 不用 networkidle
  作为完成条件。两次完整矩阵均无页面 JS 错误、无模型 HTTP 请求、无 IQ 保留。
- 正常两点扫描进入结果库；关闭页面并重启 Web 后原 session/result/detail 保留，
  Controller generation 增加、recognition 清空、首次扫描仍 complete，没有重扫。
  浏览器查看曲线，点击可见删除按钮并确认，重启/切换后记录仍为空。
- 接收时点击 `/stop`，轮询确认完整射频恢复。向 inactive session 发命令返回 409；
  切回原会话不重复扫频，其他会话观测不混入。
- 接收时 SIGKILL **私有 Controller 子进程**，连接关闭后 P201 恢复；Web 重启后
  interrupted 扫描为 failed，不重复。另在接收时正常 SIGTERM 私有 Web，验证
  `/stop`/EOF 回收和恢复；再启动也不补扫。浏览器 SSE 关闭本身只是断开观察者，
  不被误当成硬件停止请求。
- 实际生产服务执行新→旧→新切换，全部保持原两个 session ID、complete 状态、
  2 条扫频结果和 1 条语料记录。三次核验 `/proc/PID/exe` 的 Web/CLI 哈希、单
  Controller 子进程、配置哈希、P201 PID 和完整状态。没有新建生产测试会话、
  删除用户结果或触发其全频段首次扫描。
- 最终生产 Chromium 页面实际打开既有曲线、显示两条历史及删除控件；只查看，
  未点击删除用户记录，前后 state/results/corpus API 内容相同。实例 health 返回
  ready/false，服务 active，NRestarts=0。原恢复 timer 已恢复 active，oneshot
  Result=success、ExecMainStatus=0，严格只读 RX1 health 通过。

重新执行本单元私有矩阵时，使用现有工具的 `--phase web --recovery`，显式提供
`--controller /home/jetson/.local/lib/sdrharness/bin/sdr-agent`；`--web` 可指定候选，
默认使用已安装 Web。`--root` 必须是 `/var/tmp/sdrharness-dev/` 下新的唯一直接子
目录。执行前仍须核对单接收者、空闲实机、恢复 timer、计划和空间；工具不负责
部署或清理整个开发目录，结束后按审计精确删除。未加 `--recovery` 的旧模式只
用于此前 Web 的兼容性审计，不能替代新版恢复验收。

### 有限计划与恢复

每次尝试预登记最多 50 点 / **819,200 ci16 原始字节**，不保存 SigMF：
2.455–2.470 GHz、1 MHz 步进、10 MS/s、10 MHz 带宽、手动 20 dB、单路 RX1、
每点 4096 complex-int16 样本、1 frame、250 ms deadline。正常成功两点使用
20 ms settle；停止/断连/Web 退出各最多 16 点，1000 ms settle。单次保守 RX
时长上界 62,550 ms，四次尝试合计登记上界 **3,276,800 字节 / 250,200 ms**；
失败尝试未执行余下场景，不能将上界说成实际收到字节。每次采集前可用空间均
超过 807 GB。计划、实际 generation 和每点精确临时路径在各次 audit 中。

AGX 使用 `/var/tmp/sdrharness-dev/web-recovery-907a-{live1,live2,live3,installed}/`；
P201 使用既有 inline transport 的 `/tmp/sdr-agent-dev/agx-sweep-<generation>-<point>`，
全部枚举并核验不存在。`/stop`、独立 `--mode cancel --session-generation N` 和
信号清理始终可用，busy 期间不另开普通状态连接。实机只用一个接收者；生产 Web
保持空闲，私有 Node 使用独立 allowlist sockets；恢复 timer 在接收矩阵期间暂停。

所有路径轮询比较 LO、采样率、带宽、**两路** RX 增益模式/增益/端口，以及全部
scan mask/buffer。恢复值为 LO 5,985,999,996 Hz、30,720,000 S/s、30,000,000 Hz，
两路 manual/60 dB/A_BALANCED，所有 scan/buffer 为 0。P201 始终 PID 5909。

### 失败记录

初次编辑有一个重复参数导致编译失败，修正后才进行完整测试/构建。Controller
第一次回归因长 TMPDIR 下的 Unix socket 名超过 SUN_LEN 而失败，换用独立短目录
`/var/tmp/sdrharness-dev/w907t` 后完整 all-target 回归通过，未修改协议 allowlist。

live1 已通过接收、重启、删除和停止，但脚本错误索引了停止前尚未生成的可选
observation；改为比较可选字段。live2 又通过会话切换，但 Jetson 内核不提供
`/proc/PID/task/PID/children`；改用 `ps --ppid` 识别私有 Controller。两次均保存
失败结果，停止私有进程，验证 P201 完整恢复和临时路径不存在。live3 及安装后
矩阵全部通过；没有改变本次候选 binary、放宽 RX 预算或模型准入来通过验收。

## 安装与可执行回滚

最终 Web 为 3,278,112 bytes，SHA-256：
`c2e19b171e30475a06e38a074ec55282bf55f0f3ffe5de6cf1a8a730b957a0fe`。
实际路径 `/home/jetson/.local/lib/sdrharness/bin/sdr-agent-web-console`。

- 新 release：`/home/jetson/.local/lib/sdrharness/releases/20260907-web-recovery-v1/`。
- 旧 rollback：`/home/jetson/.local/lib/sdrharness/releases/20260907-before-web-recovery-v1/`。
- 每包仅含 Web、service unit 和 `release.json`；由既有 `verify-release.py` 验证
  单链接、完整清单、大小及 SHA-256 后，使用目标目录临时文件加 atomic rename
  切换。审计内 verifier 的 `installed=false` 表示该工具自身只校验；其外层
  deployment stages 记录了实际安装、回滚和最终进程身份。
- 回滚：空闲时向当前会话发送 `/stop`，轮询完整恢复；暂停 recovery timer，停止
  Web 并确认其 CLI 退出；验证上述 rollback 包，把其中 Web 恢复到 bin、service
  恢复到 `/etc/systemd/system/sdrharness-web.service`（各自同目录临时文件及原子
  rename）；daemon-reload 后启动 Web，核验 `4e2a56eb…`、唯一 CLI、旧 8 秒预算、
  原会话/结果/语料与 radio health，最后恢复 timer。本轮已实际执行该过程，随后
  用同流程恢复最终 release 和 50 秒预算。无需回滚或覆盖应用数据库。

## 清理与保留边界

已停止全部本单元进程并核对 /proc；8 个私有 socket 已不存在。删除上述四个
实机目录、构建/测试主目录及短 socket 测试目录，共 **4,116 个文件 /
1,646,544,604 logical bytes**，6 个真实解析路径均核验不存在。P201 的
208 个已登记路径检查均为不存在。临时浏览器截图、私有 SQLite、脚本/日志、
构建和缓存已删除；Git 保留有界审计及源文件/临时验证材料 hash receipts。

仅额外保留发布/回滚两包的 **6 个文件 / 5,616,804 bytes**，以及正常安装的 Web/
service；没有新增保留 IQ 包。原 2 条用户结果、1 条语料及已登记 RF 证据均未删除。

发布/回滚包是必需保留的程序恢复制品；其精确文件、字节与 SHA-256 在审计中。
模型/profile/preprocess 身份不适用于 Web 程序包；本次未读取/复制模型或 IQ。
只有明确决定废弃回滚后，核对清单及真实解析路径，才可人工执行
`rm -r -- /home/jetson/.local/lib/sdrharness/releases/20260907-before-web-recovery-v1`；
当前 release 必须待另一已验证版本接替后，才可对精确路径
`/home/jetson/.local/lib/sdrharness/releases/20260907-web-recovery-v1` 作同样人工删除。
不能删除正在使用的 bin 或用户应用结果来替代程序包清理。

epoch-10、FP16 autocast + FP32 权重、RF-v1 与全部模型准入门不变，识别能力仍 false。
日志轮转/健康监控的生产配置部署及完整长期运行验收留在后续独立单元。
