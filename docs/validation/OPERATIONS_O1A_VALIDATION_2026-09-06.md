# O1a 故障、日志与运维验证 — 2026-09-06

O1a 源码、可重复工具、流程定义及隔离验证完成，精确清理完成；未替换或启用生产
服务。本轮基线 `30448e247d293fd50560b146076cfa1007a25c1c`，分支
`codex/recognizer-amc-offline-validation`。预登记矩阵见
[O1a 计划](../evidence/OPERATIONS_O1A_PLAN_2026-09-06.md)，使用与部署边界见
[运维 runbook](../reference/OPERATIONS_O1A_RUNBOOK.md)。

## 结果和修正

- Runner audit 原来只有单事件上限，现为 8 MiB current + 3 个同限备份，永久
  flock/原子 rename 后重新打开 current，完整行写入；锁冲突、替换、链接、超限
  旧文件或写失败均失败关闭。多 Adapter 交替写入、轮转和用户 sentinel 保留通过。
- Session socket 新增 1 秒半帧组装期限、32 个待处理帧上限与 64 KiB 待写上限，
  超限关闭并释放连接；一条完整帧后的超长残余也立即拒绝。补齐旧接口缺少的
  组帧/队列边界，原有正常 session、优先 abort、代次隔离回归继续通过。
- 原生 Web GET health 与 Planner Unix health 仅返回 liveness；不读会话/凭证、
  不调用模型、不采 RF、不更改 capability。新健康工具校验、去重/恢复、总 HTTP
  deadline、不可跟随重定向、FIFO/深 JSON/坏状态拒绝和私有状态写失败清理通过。
- Release 校验器对同一 manifest 字节校验/计算 hash，逐文件有界读取，拒绝篡改、
  链接、逃逸、漏列和生产能力声明。它只 verify，不 install；用户结果不参与回滚。
- 独立 journald namespace/health service/timer 提供待部署示例；Web service
  模板停止预算从 8 秒改为 50 秒以容纳 S6b 联合 stop。systemd-analyze verify
  返回 0，只有当前主机其他旧 unit 的已存在警告；配置未安装/启动。

## 自动化与原生隔离证据

| 验证 | 结果 |
| --- | --- |
| Controller 最终 all-target tests | 100 library + 16 terminal + 1 integration 通过；1 显式 fixture export ignored |
| Web tests | 35 通过，2 显式 exporter ignored |
| Node tests | 56 通过 |
| Python O1a 最终 tests | 12 通过（含两套实际 socket mutation） |
| Python 既有共享 gate / S3 / Worker 合同 | 分别 22 / 10 / 3 通过 |
| C fake-radio/协议 | ASan + UBSan 编译运行通过，无 sanitizer 报错 |
| 格式与静态检查 | Rust fmt、Controller/Web Clippy warnings denied、Python/Node 语法、diff 检查通过 |

固定 seed=20260906，11 个 target 各 256 条，总计 2816 次有界变异执行。覆盖 C SDRD、
Rust request/response/recognition summary、Node request/session、S3 data/control、
Spark HTTP 及实际原生 Planner/Web HTTP。保留可取得的 corpus SHA-256 和全部
源文件/日志 hash；C target 的生成规则、种子和实际次数也保留。变异中合法的语法
可能被纯 parser 接受，这不触发任何 executor。既有真实 socket 的断连、超时、
重复/乱序/迟到、错误身份、generation 及取消负例同样运行；另补明确的 inline IQ
transport overflow 注入，验证拒绝并发送 STOP_SESSION/恢复。它们不是实机 RF。

原生隔离 Web/Node 的 health 正常；256 条坏 Planner 帧和 256 条坏归档 HTTP 请求
均被有界拒绝，之后服务仍能响应 health。停止私有 Web 后只产生一次 unavailable
alert；重复探测不重复告警；重启后产生 recovered。没有启动 Agent 会话，Web
测试 executor 固定为 `/bin/false`，SDR/上游地址为未使用的 loopback port 9。
Worker 合同测试用现有冻结 venv 导入 Torch/NumPy，仅处理合成文件和 manifest
元数据，不构造模型或读取数据集。

完整矩阵先通过；末轮接口加固后的原生 smoke 也通过。单独复核最终 audit helper、
新增 overflow 故障、健康/发布校验硬化及全套 Controller。各报告列出实际运行
suite，未把 `--skip-suites` 冒充完整矩阵。最初矩阵因系统 Python 缺少 Torch 在
Worker 合同测试退出，改用既有冻结 venv 后通过；失败摘要与日志 hash 保留。
早期测试的连接关闭同步、C 临时路径 buffer 和 overflow 预期错误码在开发中修正。
没有用失败验证换取任何生产 capability。

## 私有升级与回滚演练

将已安装旧 Web 的只读副本（2336008 bytes）和新构建 Web（67130312 bytes）放在
私有 previous/candidate 两个 release 目录，分别建立并验证 manifest。坏 hash
返回 exit 2，current 指针仍为 previous；恢复有效 manifest 后切换到 candidate，
再校验 previous 并回滚。独立私有 SQLite 用户结果 sentinel 的 hash 全程不变。
只切换了开发目录中的 symlink，没有切换任何已安装程序、服务或用户数据库。
两个实际 artifact 的 hash、manifest 和演练结果保留在审计。

## 清理和完成边界

全部私有进程已退出；检查 /proc 后确认没有引用本 feature 的进程，也没有测试
fake-child 命令残留。两个报告列出的 `/run/user/1000/sdrharness/o1a-906a-*.sock`
不存在；Node framing 测试的 o1a 私有 socket 也无残留。核对 resolved 路径后删除
`/var/tmp/sdrharness-dev/o1a-906a/` 并确认不存在，内容包括临时构建、合成 IQ、
私有 DB、release 副本、日志和缓存。未删除用户语料、结果或模型资产。

[有界审计](../evidence/OPERATIONS_O1A_AUDIT_2026-09-06.json) 保存完整矩阵/末轮 smoke、故障
转移、发布演练、失败摘要、来源与产物 hash 和清理证明；不保存 IQ、模型张量、
完整 logits 或凭证。无 P201/NX/B210 操作、TX、FPGA/BOOT、训练或 locked test 读取。

O1a 完成的是源码/工具/流程与隔离验证；生产日志/监控配置安装和真实升级回滚仍
属 A1。O1b 24 小时完整闭环仍未完成。数字 ID/冻结 epoch-10/FP16/RF-v1 不变，
名称 provisional，recognizer_available=false；S4b GPU 温度非阻塞例外没有扩展为
其他准入豁免。下一步先核验 V1b/V3a 证据，满足前置条件才可开展 V2；不跳入
校准、locked test 或生产部署。
