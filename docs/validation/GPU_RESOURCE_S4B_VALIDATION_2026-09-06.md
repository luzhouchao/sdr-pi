# S4b 资源诊断与候选缓存修正 — 2026-09-06

本轮交付预登记资源工具、候选 CPU prompt-cache 上限和有限实机诊断证据。
**S4b 按用户明确调整后的条件完成隔离资源验收；GPU 温度仍为未测。**
用户在运行中明确回复“没有就不管了，gpu温度”，因此仅豁免这一项缺失，其他
门槛保持不变。保留原始严格运行的失败状态，再对同一完整证据显式重算；没有
把 GPU 温度伪装为通过，也没有更改电源/thermal 设置。

基线 `9c6efc450978e95ea740ec0bc38a6bc1b388f871`，分支
`codex/recognizer-amc-offline-validation`。本单元无 RF/TX/P201/NX 操作、无数据集
或 locked test 读取、无训练/精度实验；冻结 epoch-10 FP16 autocast/FP32 权重与
RF-v1 不变。S3 的 32768-byte 合成四窗仅用于真实 Worker 资源负载。

## 实现

候选 Spark gateway 显式指定 `--cache-ram 256`。当前 llama-server 默认值为
8192 MiB，交替短长历史时诊断观测到 Spark PSS 增长，而 Mamba PSS 与 nvmap
稳定。256 MiB CPU 缓存上限不修改 GPU KV 的 32768 context/f16 或模型 BF16。
实际子进程 argv 已核对；已安装 Spark PID 1150、provider 及其他项目状态未改。

新增资源工具复用原生 supervised replay、实际 Node SDK/Spark JSON adapter 和
共享 gate。每轮将 S2 unavailable 紧凑摘要传给 Planner，只接受 hold。4 档有界
历史为 0/2048/8192/16384 ASCII 字节；每轮最早间隔 12.5 秒，不宣称满上下文或
最大 token 输出吞吐。遥测来自 /proc、固定只读 nvmap、NVIDIA tegrastats 和 GPU
频率节点。源合同见 [S4b 接口](../reference/GPU_RESOURCE_S4B_INTERFACE.md)，验收门槛及各次
仪器更正见 [预登记计划](../evidence/GPU_RESOURCE_S4B_PLAN_2026-09-06.md)。

## 验证

- 6 项 acceptance reducer 测试通过：时长/样本不足、内存超限/增长、温度平台、
  时延退化和默认 GPU 温度缺失均拒绝通过；显式 GPU 豁免不能扩散到其他门槛。
- 22 项共享 lease/gateway/生命周期故障测试通过。
- 原生 Controller 构建与显式 S3 fixture exporter 通过；Node 语法、Python
  解析与 diff 检查通过。未修改 Rust/生产 Web，不把旧全套测试算成本轮新证据。

最终测量 1200.127 秒，96 轮（另有 4 轮预热）、240 个 5 秒遥测样本，202 个
acquire/release 区间完整配对且无重叠。两个 Worker PID 在整个正常负载中不变；
Mamba/Spark 各完成 100 次，busy/failed/expired/cancelled 均为零。Spark 的
restarts=1 表示首次启动，未发生异常重启；Mamba restarts/crashes 均为 0。

| 指标 | 实测 | 判定 |
| --- | --- | --- |
| 四窗原生 replay p50 / p95 | 0.362 / 0.398 秒 | ≤5 秒 p95，通过 |
| Planner p50 / p95 | 2.786 / 4.033 秒 | ≤60 秒 p95，通过 |
| 按历史分组的后/前半段 p50 最大比率 | 1.575（Mamba）；1.004（Planner） | ≤2，通过 |
| 候选合计峰值 PSS | 2150.37 MiB | ≤24 GiB，通过 |
| 首末 5 分钟 PSS 中位数增量 | 4.72 MiB | ≤512 MiB，通过 |
| nvmap 合计 | 固定 10450.84 MiB | 无增长；不与 PSS 相加 |
| 最低系统可用内存 | 30.12 GiB | ≥4 GiB，通过 |
| CPU/SoC/Tj 上报最高温度 | 50.593°C | <80°C，通过 |
| 最后/前一段 5 分钟温度中位数增量 | 0.078°C | ≤5°C，通过 |
| GPU 温度 | 240/240 样本缺失 | 用户明确豁免；未测 |

队列采样最大深度为 0；这证明该串行负载没有积压，不替代 S3/S4a 的突发队列
故障测试。原始 live-summary 按启动时严格规则为 failed/missing temperature
coverage；最终纯 reducer 使用用户明确授权的 GPU-only 豁免，对同一遥测重算，
其余全部门槛通过。新增参数/纯 reducer 的豁免行为另经测试，未重采或改写历史数据。

## 失败保留与解释

第一次直接 thermal sysfs 读取遭遇 EAGAIN/无数据；第二次固定 sudo 和有限重试
仍缺 GPU 温度；第三次 tegrastats 同样在模型常驻阶段不报告 gpu。三次均在早期
结束且确认私有模型回收。完整诊断改为逐次记录缺失，以 CPU/SoC/Tj 作为运行时
安全停止监测，最终 reducer 仍严格拒绝 GPU 覆盖缺失。

默认 prompt cache 的诊断在 23 轮后由 Agent 正常 SIGTERM 中止以修正缓存上限，
报告为 failed/CancelledError，不算作完整持续验收。各次失败/中止摘要、cleanup、
原始日志与遥测哈希均保留。缓存修正后重新创建候选实例并从预热开始。

设备当前 MODE_50W（mode 3）；gpu-thermal 已 enabled。Device tree 将 GPU 绑定
BPMP sensor 1，Tj 绑定 sensor 8；本机 header 将 8 定义为 TJ_MAX。直接 GPU 节点
与 tegrastats 的缺失相符，模型退出后 GPU 温度恢复可读。尚不能据这些现象确定
固件/驱动根因，也没有据 Tj 的存在宣布独立 GPU 遥测通过。NVIDIA 官方说明
GPU/CV power-gating 会使读取返回 EAGAIN；链接与本机读取命令见接口文档。

## 清理与剩余条件

全部尝试的已记录 Worker PID 已退出，候选进程参数不再引用 feature root，
root 内无 socket，最终 incoming/owned 为空。已安装 Spark 仍为 PID 1150、active，
启动时间与测试前相同。退出后直接 GPU 温度读数为 44031（44.031°C）；该读数
仅证明退出后可读，不回填测量时段。

经精确 resolved 路径检查后，已删除 `/var/tmp/sdrharness-dev/s4b-906a/` 并确认不存在。

原始遥测、日志、私有 key、合成 IQ、spool、临时构建和模型缓存均仅位于本单元
目录；未删除用户语料/应用结果或已安装模型。审计保存有界统计、逐轮时延、
初末 health、子进程参数白名单、失败摘要和文件哈希，不保存 IQ、完整 logits
或凭证。见 [有界审计](../evidence/GPU_RESOURCE_S4B_AUDIT_2026-09-06.json)。

GPU 温度缺失按用户决定记录为非阻塞缺口；可独立继续排查读取问题，不能称为
已验证 GPU 独立温度。下一独立单元为 O1a。A1 生产部署、V1b 独立标签、校准和
locked test 准入均未完成；
recognizer_available=false，名称 provisional。O1a 未混入本次交付。
