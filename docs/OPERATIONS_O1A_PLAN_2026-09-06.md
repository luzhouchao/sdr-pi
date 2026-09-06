# O1a 故障与运维验证预登记

基线 30448e247d293fd50560b146076cfa1007a25c1c。本单元复用 S1–S6b/S4b，
不训练、不读 locked test、不采 RF、不发射、不安装或替换生产服务。
recognizer_available=false；GPU 温度缺失沿用用户明确的非阻塞决定。
唯一开发目录 /var/tmp/sdrharness-dev/o1a-906a/，所有 build/测试/私有状态置于此。
Node Unix socket 仅使用 allowlist 下带 o1a 标识的私有路径，结束逐一核对删除。

## 固定矩阵

| 边界 | 有界验证 | 必须满足 |
| --- | --- | --- |
| SDRD C 请求/恢复 | 固定种子变异 + 现有 fake-radio 故障用例 | 不崩溃、响应有界、shadow 不执行 |
| Rust SDR/Planner/Recognizer/Runner | 既有断连、deadline、取消、身份/乱序/迟到响应负例 | 不执行未批准动作，恢复/归档失败明确 |
| Node Planner/session | 固定种子畸形结构 + 实际 Unix 分片、超长、多帧、慢半帧/拥塞 | 有界拒绝、队列/组帧不无限占用，后续可恢复 |
| S3 control/data、S4a HTTP | 复用实际 socket fake-child 测试并加固定种子畸形帧 | 无未授权推理、无残留 ownership/gate |
| Web HTTP/归档 | 原生 Web 测试及隔离健康/负例 | 不暴露路径、凭证、上下文；不把服务活着当作识别准入 |
| JSONL audit | 小阈值跨多次轮转、并发锁、坏文件、超长事件 | 完整行、有限备份、拒绝链接/冲突、失败关闭 |
| 健康告警 | 健康→故障→重复故障→恢复、probe 超时/畸形、磁盘不足 | 本地结构化状态变化事件，去重、恢复可见，零外发消息 |
| 升级/回滚流程 | 清单/哈希/path/symlink/非准入检查和私有文件演练 | 验证失败不切换、旧版本可恢复、用户数据库不回滚覆盖 |

固定 mutation seed 为 20260906，每个 fuzz target 256 个有界案例；额外 framing
边界案例单独计数。重跑相同 seed 得到相同 corpus hash。此处是有限确定性回归，
不声称穷尽或长时覆盖引导 fuzz。统一脚本记录每套命令、退出码和日志哈希。

交付日志策略：Runner JSONL 8 MiB×4（current + 3 backups），永久锁 inode +
append 时轮转；候选 service stdout 的独立 journald namespace 提供示例上限。
仅定义/验证配置，不更改当前主机 journal。应用 SQLite/corpus/IQ 不参与日志轮转。

健康工具仅 GET/health 或专用 read-only health frame；本地输出/状态文件，不发送
邮件/聊天消息，不自动重启、部署、改 Planner capability 或切换云端。升级/回滚
runbook 遵循已有 P201 工作流；O1a 私有演练不算 A1 生产部署，也不算 O1b 24 小时。
结束保留有界证据，停止全部私有进程、精确清理后才更新 checklist、commit/push。
