# S4b 持续资源验收预登记 — 2026-09-06

基线 9c6efc450978e95ea740ec0bc38a6bc1b388f871。本文在运行前固定验收范围与门槛。
S4b 验证隔离候选对的资源，不代表 A1 部署、独立标签/校准准入或 O1b 24 小时闭环。

## 负载和预算

复用 S3 的 32768-byte 合成 RF-v1 四窗，通过原生 Rust supervised replay、真实
冻结 epoch-10 FP16 Mamba，再将 S2 unavailable 紧凑结果交给实际 Node Spark adapter。
Spark BF16 使用既有 binary/model、32768 context、单并发，输出预算 512 tokens。
两模型共享 S4a gate。循环覆盖短摘要与逐渐增大的有界历史（约 0/2/8/16 KiB），
检验不同 prefill 负载，不把短 hold 的输出速度称为最大 token 生成吞吐。

先预热 4 轮，再测量 96 轮，每轮最早间隔 12.5 秒，测量至少 1200 秒；负载较慢
则自然延长。总执行 deadline 2400 秒，候选服务 lifetime 3000 秒；最多 104 个
Spark 请求与 104 个 Mamba batch，最多 2 次异常重启，验收不允许非预期重启。
总 RF 字节 0，不读取任何 dataset/split，不访问 P201/NX/B210，不发射。
唯一临时目录 /var/tmp/sdrharness-dev/s4b-906a/；先校验空间至少 4 GiB。
取消通过脚本 SIGINT/SIGTERM，finally 终止并回收私有子进程，核对 socket/spool 清理。
不停止已安装服务或修改其他项目采集状态。

## 观测与门槛

每 5 秒采样 /proc 内存、进程 RSS/PSS/CPU、thermal zones、GPU 当前频率和
只读 nvmap clients（sudo -n cat 固定路径）。Jetson 使用统一内存，nvmap 是驱动
分配记账，不等于 Torch allocator 的精确 allocated/reserved；PSS 和系统可用
内存共同判断压力，不叠加为物理占用。候选 gateway 丢弃 backend 日志，因此不声称另有 CUDA buffer 日志；以 nvmap 实测为准。
每轮读取两 supervisor health、queue depth、lease 等待/持有计数及推理/规划时延。

通过条件：
- 96 轮均得到四窗有效 S2 unavailable 和合法 hold；没有生产 capability 提升。
- 无 OOM、异常 Worker 重启、deadline、失败或正常负载丢弃，队列深度不超过 1。
- 全部 acquire/release 成对、无重叠；两个 Worker 保持原 PID。
- 系统 MemAvailable 始终至少 4 GiB；候选合计 PSS 不超过 24 GiB，nvmap 不超过
  24 GiB；最后 5 分钟相对最初 5 分钟的中位 PSS/nvmap 增长不超过 512 MiB。
- 最高 CPU/GPU/SoC 温度低于 80°C；最后 5 分钟最高温度中位数相对前一个
  5 分钟增长不超过 5°C。记录频率与温度，不仅凭降频就断言 thermal throttle。
- 原生四窗 replay p95 ≤ 5 秒，Planner p95 ≤ 60 秒；分别按历史长度分组报告，
  后半段与前半段 p50 比值 ≤ 2（固定 50 ms 下限避免小数值比率失真）。
- 样本覆盖至少 95% 预期间隔；任何遥测缺失、失败或 cleanup 未确认均不勾选。

退出前保留有界统计、逐轮时延/health、原始遥测/日志/源文件哈希及失败原因。
精确删除本单元临时数据，验证进程、socket 和目录不存在，更新 checklist 后单独
commit/push。若失败，保留证据、定位原因，不事后放宽门槛把失败改成通过。

遥测实现更正（首轮无有效样本后、正式重跑前）：只读取门槛涉及的 CPU/GPU/SoC/Tj
温度，排除本负载不使用且返回 EAGAIN 的 CV 节点；固定 sudo 只读 cat，短暂 EAGAIN
最多重试 5 次（每次 50 ms）。耗尽重试仍失败关闭，温度/覆盖门槛保持原值。

第二次遥测更正：直接 GPU temp 在 power-gating 时仍会持续 EAGAIN；改用 NVIDIA
tegrastats 连续 1 秒输出的温度读数，保留每行原始记录及时间。5 秒资源采样必须
有不超过 2 秒的最新 tegrastats 行且包含 CPU/GPU/SoC 温度，否则仍失败；门槛不变。
不把工具上报的温度解释为可独立验证的传感器刷新时刻。

完整诊断运行：已确认模型常驻时 GPU 温度也可能缺失于 tegrastats。为获得其他
维度的完整证据，记录 missing_temperatures 并继续受 CPU/SoC/Tj 安全门保护的
有限测量；最终 reducer 仍拒绝任何 GPU 温度覆盖缺失，不将诊断完成记为 S4b 通过。

候选实现修正：诊断发现 llama-server 默认 8192 MiB CPU prompt cache 随历史
轮换持续增长。保留该失败/中止记录，候选 gateway 显式指定 --cache-ram 256。
此项修改缓存容量，不改模型权重、GPU KV 格式、输出合同或验收门槛；正式测量
从新实例和 4 轮预热重新开始。生产已安装实例不变。

## 用户明确调整（运行中，2026-09-06）

用户对“GPU 温度缺口导致总体验收失败”明确回复：“没有就不管了，gpu温度”。
据此，GPU 温度缺失在本次 S4b 不再是阻塞条件，保留 missing/未测状态；CPU/SoC/Tj
安全监测、资源、队列、时延、样本量和清理条件全部不变。运行中的原始报告仍按
启动时严格规则输出；最终审计使用显式 allow_missing_gpu_temperature=true 重算，
保留原始失败与豁免依据，不把 GPU 温度写成已验证或将旧报告悄悄改成通过。
