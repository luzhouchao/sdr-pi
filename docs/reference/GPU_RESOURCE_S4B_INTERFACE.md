# S4b 有限资源验收接口

S4b 复用 S3 supervised replay 和 S4a 共享 gate，新增独立验证工具，不修改模型、
Worker wire contract、生产服务或准入配置。完成状态以权威 checklist 为准。

## 工具

`jetson-agx/sdrharness/scripts/validate-gpu-resources.py` 接受显式参数
`--feature-directory /var/tmp/sdrharness-dev/s4b-906a`。要求 root 已存在、resolved
路径一致、无旧 live-summary、至少 4 GiB 空间，以及当前源码构建的原生 Controller
和 S3 fixture exporter 生成的 model.f32/replay.json。每个后续实测须审阅并更新
专用 feature ID，不能覆盖既有结果。脚本不包含 dataset 或 SDR 客户端。

脚本启动私有 Mamba supervisor 和 Spark gateway，两者使用同一 gate，保留默认
冻结模型；Spark CPU prompt cache 显式限制 256 MiB，避免默认 8 GiB 缓存随
历史轮换占用主机内存。GPU KV 仍为 32768 context、f16。每轮调用原生四窗 replay，传给实际 Node SDK/本地 JSON adapter 的只有
S2 observation；完整 batch/logits 随原生调用完成释放，不进入 Planner prompt。
Node 负载工具 `validate-resource-planner.mjs` 限定四档 ASCII 历史长度和 hold schema，
无硬件执行器、shell 工具或生产 capability。长历史是明确的合成 unavailable 记录。

总量/时长/阈值见 [预登记计划](../evidence/GPU_RESOURCE_S4B_PLAN_2026-09-06.md)。脚本强制
4 轮预热、96 轮测量、至少 1200 秒、2400 秒 deadline、每 5 秒资源采样。
子进程请求有独立 timeout；SIGINT/SIGTERM 取消主任务后在 finally 回收私有模型。
每轮确认两个模型 PID 不变、S2 四窗有效、能力 false、spool 为空以及错误/丢弃为零。
验收结束校验完整 lease 日志的 acquire/release 严格配对且无交叠。

## 输出与解读

临时目录保存 live.log、telemetry.jsonl、live-summary.json、私有服务日志、key、
单个轮换 observation/request 和合成输入。失败同样保存 status=failed 与原因和
回收证据。测试不自动删除 root，交付收尾先保留有界审计和哈希，再核对精确路径删除。
用户结果/语料、已安装服务、模型资产和其他项目数据不属于该清理范围。

遥测区分进程 RSS/PSS、累计 CPU ticks、系统 MemAvailable/swap、nvmap 按 PID 分配、
CPU/GPU/SoC/Tj 温度和 GPU 频率。nvmap 是 Jetson 驱动的统一内存分配记账，不是
Torch allocator 精确 reserved/allocated，不能与 PSS 相加成物理总量。固定 sudo
命令只读 nvmap，温度使用 NVIDIA tegrastats 连续输出，不改 GPU clock、电源、风扇或 thermal 配置。
CV 节点及 power-gated GPU 直接节点可能返回 EAGAIN，改用 tegrastats。GPU 温度缺失会显式记录并使最终验收失败；CPU/SoC/Tj 缺失
或最新工具行超过 2 秒则立即中止测量；不声称独立获知底层传感器刷新时刻。GPU 频率为 0 可表示空闲 power-gating，不独自证明热降频。

该负载是有节奏的串行识别/规划资源验收：每轮 4×1024 Mamba 加一轮有界 hold
规划，最多 16 KiB 合成历史；不声称最大输出吞吐、32K 满上下文、无线采集吞吐或
生产端到端时延。S3/S4a 已验证突发队列和取消正确性，本次观察持续串行负载的队列、
丢弃与时延。已安装 Spark 和其他 GPU 程序不加入候选 gate；记录其存在，不能据此
声称全主机 GPU 隔离。部署所有生产调用进入 gate 属 A1，24 小时运行属 O1b。

## 验证 reducer

`PYTHONDONTWRITEBYTECODE=1 python3 jetson-agx/sdrharness/scripts/test-gpu-resources.py`
只使用内存内合成遥测，覆盖合法完成、时长/样本缺失、资源超限/持续增长、温度
未稳定、时延超限与后半段退化。它证明门槛计算，不替代真实候选测量。

## GPU 温度缺失的显式用户豁免

默认仍拒绝 GPU 温度覆盖缺失。用户在本次运行中明确要求缺失时不阻塞，新增
`--allow-missing-gpu-temperature` 供显式授权运行使用；它仅豁免 missing 集合中的
`gpu`，不豁免 CPU/SoC/Tj、温度上限、资源/时延/覆盖或清理。6 项 reducer 测试
覆盖豁免有效和不可扩散到其他门槛。原始运行按启动时旧规则保留失败状态，最终
审计对同一完整遥测显式重算并记录用户原话；GPU 温度始终是未测，不是通过。

## AGX Orin 温度读取依据

[NVIDIA Jetson Linux r36.4.4 官方文档](https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/SD/PlatformPowerAndPerformance/JetsonOrinNanoSeriesJetsonOrinNxSeriesAndJetsonAgxOrinSeries.html#sensors-and-sensor-groups)
说明 GPU/CV 电源域可在空闲时关闭，此时传感器读取返回 `-EAGAIN`。本机按 type
确认 `gpu-thermal` 位于 `/sys/class/thermal/thermal_zone1`，`temp` 为毫摄氏度；
也可用 `tegrastats --interval 1000` 查看 `gpu@...C`。不要跨设备固定猜 zone 编号。
本次二者均出现 GPU 温度缺失，记录为不可用，不用零值或 CPU 温度伪装为 GPU
读数。该官方机制解释了 EAGAIN 的一种正常原因，但本次未证明整个缺失时段的
底层电源状态，因此不宣称已定位硬件/固件故障。没有关闭 power-gating 或修改
clock/thermal/fan 来强行获取读数。
