# Pi SDK 1.4.0升级与部署 — 2026-10-26

基线 `47c8a56`，分支 `codex/sdr-improvements`。用户授权先完成兼容升级、
验证和可回滚部署，随后明确旧key不保留、之后填新key。本单元未接入pi-durable。

## 修改与验证

Planner的`pi-agent-core`、`pi-ai`锁定1.4.0，TypeBox同步1.3.27，
Node保持现有22.19.0。新版将prompt及工具声明放入system transcript；
Spark JSON适配先重放系统消息，再剥离原生工具声明，继续只允许submit_plan。
上下文估算改用pi-ai公共导出，压缩保留重放后的规则及当前工具集合。
Pi目录迁移到OpenCode的`/inference`后，保存的官方`/zen`地址继续使用原地址；
仅对既有精确provider/model/协议/官方地址保留兼容元数据，不改写用户选择。
已移出Go目录的deepseek-v4-flash保留旧版已支持的配置；不代表其在线服务已验收。

最终**71项测试全部通过，无跳过**，在feature目录隔离执行，未使用真实key或SDR。
新增6项真实Pi SDK集成测试，启动实际main.mjs，使用loopback模拟HTTP/SSE：
Completions、Responses、Spark JSON、交互会话关联/结束、超时释放租约、
steer/follow_up入队后的abort/断连与共享租约释放。另新增系统消息压缩和
新旧OpenCode目录的精确地址/协议边界测试。npm安装审计报告0漏洞。

首轮发现估算函数导出位置、system工具声明和目录变化的兼容问题，已修正。
隔离副本首次没有保留仓库相对布局，导致1项fixture路径失败；补齐跟踪的request.json
及原布局后通过，没有放宽解析或预算。Rust、Web源码未改，无需重建其二进制。

## AGX实际部署与边界

Planner systemd模板及实际unit改为使用
`/home/jetson/.local/lib/sdrharness/planner/current`。
保留既有30-operations.conf日志命名空间及全部资源/系统保护配置。
独立release仅包含源码、锁文件、第三方许可、依赖和SHA清单，不含运行配置或key。
checkout原有node_modules移入旧release，再链接到current依赖；gitignore同时覆盖目录和链接。

先从Web向原会话发送/stop，正常停止Web/Planner，再切换版本。
实际执行1.4.0→0.84.4→1.4.0，旧版/新版的运行目录、依赖版本与Planner只读health均核对。
最终Planner/Web为active，health均ready，recognizer_available=false。
没有新收发、训练、识别、权重加载或P201部署；没有重新执行首次扫描。

用户要求不保留旧key后，正常停止进程，原地原子清空
`/var/lib/sdrharness/web-console/provider.json`的api_key，保留0600及非秘密设置；
不备份、不归档、不输出旧key。新版单次规划在缺key时返回unavailable且无action；
交互Controller因此退出，等待配置有效key。服务health通过**不等于模型可用**。

实际Chromium/Playwright检查：原活动会话`session-1789273063753`和既有结果保留，
设置页可打开，模型设置保留、key输入为空；提交“升级验证：请保持等待，不执行硬件操作。”
后记录缺key错误，无硬件计划。原始错误位于既有技术诊断折叠区，展开后可见，JS错误0。
页面SSE长连接使networkidle超时，改用已渲染表单及事件就绪；首次按含装饰字符的
accessible name定位设置按钮失败，改用实际DOM id后通过。未修改前端以迁就测试。

真实提供商鉴权、模型回复及Web→Planner→Controller的成功hold对话仍待新key。
用户之后在Web“设置→模型与API”填入新key并保存，再恢复原会话；无需重跑首次扫描。
pi-durable、持久任务恢复和硬件重放不属于本次交付。

## 制品、回滚与清理

版本、逐文件大小/SHA清单位置及精确人工删除方法见
[本单元审计](../evidence/PI_SDK_UPGRADE_2026-10-26.json)。
每个release中的release-manifest.json记录自身之外的所有文件及链接，审计另记录
manifest自身大小/SHA和包含它的完整总量。运行profile为Pi版本，无模型/预处理制品。

回滚时停止Web和Planner，将current原子指向保留的
`/home/jetson/.local/lib/sdrharness/planner/releases/pi-0.84.4-47c8a56`，
启动Planner/Web并复核health；不会恢复已清空的key。
人工删除当前选中的release前，必须先停止服务并切换到另一个已验证版本。

本单元临时目录`/var/tmp/sdrharness-dev/pi-upgrade-20261026/`已删除并核验不存在；
仅保留两份已登记安装/回滚制品及Git内有界审计。测试socket、临时浏览器和候选Worker
均已退出/移除。用户原有两份未跟踪SINR文件、结果库和既有RF证据未动。
