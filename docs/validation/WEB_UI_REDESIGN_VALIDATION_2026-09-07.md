# Web 界面重构验收 — 2026-09-07

基线 `a41a8715a8334be530c9785180a71cc36d7fbbae`，分支
`codex/recognizer-amc-offline-validation`，开始时工作区干净，上游为同名 origin 分支。
本次只交付 Web 界面，优先于原推进顺序；没有开展日志/监控、模型或 RF 后续单元。
完整制品、部署、测试及清理清单见[审计记录](../evidence/WEB_UI_REDESIGN_AUDIT_2026-09-07.json)。

## 设计与功能

- 重组原生 HTML/CSS/JS：固定导航、独立会话列表、对话主区、接收进度及系统状态侧栏。
  浅灰白底、墨色正文、低饱和青绿强调；停止固定在顶栏，确认对话框内也保留停止入口。
- 对话按角色排版；有意义的系统反馈保留在对话中，原始全部记录、模型上下文、reasoning
  和校验依据放入可展开诊断。未变化的事件不反复重建消息区域。
- 设置保留全部原字段，按模型/API、上下文、首次扫描和 IQ 存储四组折叠。
  显式保存、同 URL 空密钥保留、未保存离开/浏览器关闭提示保持；保存期间的新编辑
  不被回执覆盖，过期模型查询不写入已修改的接入配置。
- 频谱结果、识别归档和语料入口完整保留。图表改为清晰功率线、噪声虚线、候选标记，
  增加可展开频点表；MHz 刻度按频段精度显示，窄频段不再出现相邻重复标签。
  删除使用明确的页面内确认框；取消不写入。原 139 个 ID 均保留，无框架或构建工具迁移。
- 新增请求序号保护迟到状态/详情；旧会话的命令回执不清空新草稿，旧回执不覆盖停止反馈。
  SSE 合并并串行刷新，慢响应不会因持续事件而一直失去显示机会。失败启动仍连接 SSE，
  断连保留最近状态并警示过时，重连/重试不创建会话或补扫。
- Controller 仍是唯一硬件/批准/策略权威。API 路由、Rust 后端、会话持久化及
  request/session/generation 合同未修改，识别显示不可用。

## 已执行验证

- 原生 Web：36 passed，2 个显式 fixture export ignored；AArch64 stripped release 构建、
  动态依赖解析、JS syntax 和 git diff --check 通过。
- 前端：10 个无依赖 Node 回归通过，覆盖迟到状态/详情、跨会话回执、停止优先、UTF-8
  限制、未保存导航、部分启动失败、非法 JSON、慢 SSE 合并与窄频段刻度。
- 固定数据预览在 `192.168.50.75:8798` 独立运行；没有 API 转发、Controller、
  上游请求、RF 或生产存储访问，CSP 限制同源。固定数据与状态选择条明显标识。
  POST/PUT/DELETE 只修改内存测试记录，删除验证仅针对测试结果 9001。
  可复用入口见 [tests/README](../../raspberry-pi/sdr-agent/web-console/tests/README.md)。
- 实际 Chromium 验证 1440×900、1280×800、390×844：四页导航、折叠配置、模型查询、
  保存、扫描预算、取消/放弃未保存编辑、会话创建/切换、流式消息、SSE、快捷控制、
  Ctrl+Enter、停止、空/加载/错误/断连/恢复、迟到详情及确认删除均检查。
  Tab 焦点可见，Esc 取消并保留修改，焦点返回；手机无页面横向溢出，图表独立横向滚动。
  6 组主要文字/背景对比度抽检为 4.69–14.28。没有宣称覆盖所有浏览器或完整 WCAG 认证。
- 私有原生 Web 使用独立状态、数据库、端口 8799、私有路径及不可执行硬件的配置。
  无会话、无 RX；health false，三份 HTTP 静态资源 SHA-256 与最终源码一致。
  未使用 networkidle 判定 SSE 页面就绪。
- 生产浏览器仅查看既有会话、真实曲线、语料和设置；未创建生产测试会话、发送自然语言
  测试、查询真实模型或删除用户数据。密钥字段 password 且空白，原 Spark 配置及
  743 点 / 约 189 秒 / 约 11.6 MiB 初扫预算不变；无页面 JS 错误。
- v1 已实际执行 新→原恢复版→新 的回滚验证；随后 v2 修正横轴精度，并再次做原生
  内嵌资源核验和实际安装。每次服务重启都恢复原 2 个会话、complete 初扫、2 条结果和
  1 条语料，代次增加，未重复扫描。最后 Web PID 496587，唯一 CLI 子进程
  496590，health ready/false，NRestarts=0。
  原 recovery timer 恢复 active，oneshot Result=success / ExecMainStatus=0。
- 本轮没有发起 RF 采集，因此不把 UI/mock 验证说成新的射频恢复矩阵。沿用前次
  [真实 RX/恢复证据](WEB_RECOVERY_UPGRADE_VALIDATION_2026-09-07.md)；
  未训练、未微调、未运行模型诊断、未读取 locked test，未操作 NX/B210、P201/FPGA/BOOT。

## 失败与修正

OpenDesign 三次生成均因其服务重启中断，没有可用设计制品；未宣称使用了成功生成的设计。
随后按已确认方向直接实现并在侧栏显示隔离预览。旧 window.confirm 阻塞嵌入式浏览器，
改用可键盘操作的原生 dialog；慢 SSE 刷新饥饿与窄频段重复刻度在验收中发现并修正。
一次截图抓取失败后重试成功。工具等待超时但控件实际已渲染时，通过随后 DOM 核验，
没有放宽生产合同或把等待超时记成业务成功。编辑传输期间的脚本引用/空白错误也在写入、
构建或 diff 校验阶段修正，未作为候选部署。

## 制品与回滚

最终 Web SHA-256：`7c374774b006ca8633fb74589878bc8af073f4d738ec95f87982d61cc2b6acf4`。
实际安装：`/home/jetson/.local/lib/sdrharness/bin/sdr-agent-web-console`；UI 标识 `20260907-web-ui-v2`。

- 最终发布包：`/home/jetson/.local/lib/sdrharness/releases/20260907-web-ui-v2/`。
- 回滚包：`/home/jetson/.local/lib/sdrharness/releases/20260907-before-web-ui-v1/`。
- 每包保留 Web、原 service、源身份 receipt 和 release.json；均由现有 verify-release.py
  校验大小、SHA-256、单链接和完整清单。中间 v1 已删除，其校验及实际回滚记录保留在审计。
- Controller、service、runtime.env、request.json、provider.json 哈希均与基线相同。
  只通过目标目录临时文件加 atomic rename 替换 Web。没有覆盖或回滚数据库。

回滚到原恢复版：确认可中断当前工作，向活动会话发送 `/stop`；暂停原 recovery timer，
停止 `sdrharness-web.service` 并确认 CLI 退出。运行
`python3 jetson-agx/sdrharness/scripts/verify-release.py --root /home/jetson/.local/lib/sdrharness/releases/20260907-before-web-ui-v1`，
通过后将包内 Web 复制到 bin 内唯一临时文件，chmod 0755，再原子 rename 覆盖
`sdr-agent-web-console`；启动 Web，核验运行 /proc/PID/exe 为原
`c2e19b171e30475a06e38a074ec55282bf55f0f3ffe5de6cf1a8a730b957a0fe`，
原会话/结果及 health，再恢复 timer。service/config 本轮未变，不需要替换或 daemon-reload。
不要恢复旧数据库覆盖用户后来产生的结果。

## 清理与保留

已停止本次预览和私有 Web；允许的私有 socket 未创建且确认不存在。
清理构建、Cargo 缓存、测试数据库、脚本/日志、预览文件及中间 v1：
**6701 个文件 / 971493196 logical bytes**。逐个验证精确路径不存在。
本次开发根现在只剩 evidence 内 4 张交付截图；不清理公共临时根或既有 RF 证据。

必要保留：2 个发布/回滚包共 **8 文件 / 6567960 bytes**；
4 张截图共 **137031 bytes**，位于
`/var/tmp/sdrharness-dev/web-ui-20260907-2238/evidence/`。截图的 source/session/request、每文件大小与 SHA-256 见审计；
UI 制品不涉及 model/profile/preprocess 身份，也不额外保存 IQ。
另保留相同字节的 4 张 Codex 本地交付镜像，用于最终消息内显示，精确位置见审计。

人工删除截图时先确认无需保留视觉证据，核对真实路径后删除精确目录
`rm -r -- /var/tmp/sdrharness-dev/web-ui-20260907-2238`；该目录仅剩本次截图。发布包只有在已被其他已验证版本接替后，
回滚包只有在明确放弃该回滚后，才分别核对清单与解析路径并删除上面对应的精确 release
目录；不得删除正在使用的 bin 或用户结果。Windows 交付镜像可删除审计列出的 sdr-ui
精确目录，不触碰用户上传的剪贴板图片。

权威 checklist 随同本次提交更新；日志/监控与识别准入仍属于后续独立单元。
