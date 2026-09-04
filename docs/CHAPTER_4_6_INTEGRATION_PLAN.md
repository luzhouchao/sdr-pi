# 第4—6章协同接入规划

最后审查：2026-09-04（Asia/Shanghai）

本文把项目清单第4节“AGX 采集、聚合与扫频”和第6节“本地调制识别”整理为
一个可验证的数据闭环。项目清单第5节仍是 FPGA 退役边界，不恢复 FPGA、
MMIO、UIO、Vivado 或 `BOOT.bin` 路线。

如果“第4—6章”同时指论文正文，建议正文使用下面的叙事结构：

- 第4章：宽带感知、候选检测与受限 IQ 获取；
- 第5章：射频回放、候选对齐、输入标准化与数据集构建；
- 第6章：Mamba 调制识别、拒识、部署与系统闭环。

也就是说，第5章不再写成一条 FPGA 实现路线，而是承担第4章实测 IQ 到第6章
训练分布之间最关键的“数据桥”。仓库清单仍保留第5节的退役记录，作为架构
约束和历史审计。

## 1. 总体判断

第4章不应包含 Mamba 网络内部实现，第6章也不应直接控制 P201。两章唯一的
正式连接点应是一份版本化、可复现、与后端实现解耦的
`RecognitionInputProfile`：

- 第4章负责找到一个可信候选，按 profile 获取有限 IQ，并在 AGX 生成模型
  就绪窗口及质量元数据；
- 第6章只接受满足 profile 的窗口，完成模型推理、多窗口聚合和拒识；
- Runner 负责把两段串起来，向 Planner/Web 只暴露有界摘要，不暴露 IQ 文件、
  PyTorch/CUDA 对象或硬件写接口；
- `recognizer_available` 必须来自 Worker 健康探针和已准入 manifest，不能由
  配置文件写成 `true`；
- P201 始终只做 Linux/IIO 有界 RX 与传输，所有预处理、存储和推理留在 AGX。

当前一次 `P201 RX1 → AGX → seed44` 实验只证明接收与软件链路已经接通。
它使用单位复数 RMS 作为临时桥接，而 seed44 没有按这个变换训练；8,192 条固定样本的 accuracy
从原始输入 `63.5986%` 变为 `53.2959%`。因此 seed44 应保留为基线和回归夹具，
不应直接晋升为生产模型。

## 2. 目标数据流

```text
第4章
宽带扫频
  -> CandidateSummary
  -> 有界精查与候选资格判定
  -> RecognitionTarget
  -> Rust 根据已准入 profile 推导捕获计划
  -> P201 RX1 / SDRD inline IQ
  -> AGX 对齐、质量检查、预处理和有限分窗
  -> ModelReadyBatch（私有临时文件 + 版本化元数据）
                                |
                                v
第6章
Worker 运行时健康/模型准入
  -> CUDA/Mamba 单窗口推理
  -> 多窗口聚合
  -> closed-set 分类或 rejected/unknown
  -> RecognitionObservation
                                |
                                v
系统闭环
Runner audit -> ObservationSummary -> Planner / Web / 可选结果持久化
```

NX/B210 只作为独立的已知标签测试发射端，不进入生产 Controller，也不向 P201
增加发射能力。当前确认的物理测试路径仍是：

```text
B210 RF A / TX-RX / UHD channel 0 -> P201 面板 RX1
```

## 3. 当前已有能力与真实断点

| 环节 | 当前状态 | 还缺什么 |
| --- | --- | --- |
| P201 有界 RX | 已部署并多次验证 | 继续保持单通道、有限字节、可取消和状态恢复 |
| AGX 扫频/候选 | 已进入 Planner observation 和 Web | 候选精查后的“可识别资格”及来源关联 |
| 选定窗口到 Worker | 1 个 1,024 点窗口已跑通 | 版本化 profile、对齐、批窗口和生产错误策略 |
| seed44 | AGX/4090 数值一致，原始 test accuracy 约 63.82% | 不匹配真实 RF 预处理，不能生产晋升 |
| 标签 | 0—23 数字类别可信 | RML2018A 名称顺序仍有争议 |
| Worker | 实验 Worker、backlog 1、单线程、严格哈希 | 正式服务部署、运行时 capability、取消/丢弃/并发/thermal soak |
| 拒识 | 无 | 噪声、空闲频点、未知制式和低置信度会被强制分到 24 类之一 |
| Planner action | 已有 `run_local_recognition { candidate_id }` | Runner 仍返回 `planned_only`，没有执行器 |
| Agent/Web 结果 | 协议预留了简单 recognition summary | 缺少状态、拒识原因、模型/预处理 ID、来源和时延 |

## 4. 第4章应完成的工作

### 4.1 候选必须先达到“可识别”状态

宽带扫频发现的粗候选不能直接触发模型。先做一次有限精查，生成内部
`RecognitionTarget`：

```text
candidate_id
source_sweep_id, source_sequence, measured_at_ms, age_ms
refined_center_hz, occupied_bandwidth_hz
peak_dbfs, noise_floor_dbfs, estimated_snr_db
rx_port, rx_gain_db
clipped_samples, dropped_samples, overflow, health_flags
```

资格判定至少要求：候选仍新鲜、中心和带宽在硬件及模型 profile 范围内、没有
削顶/丢样/溢出、测量健康、能量高于最低门限。未达标时应返回“需要重新精查”
或“不可识别”，不能把噪声窗口强行送入 closed-set 模型。

### 4.2 Planner 只选择候选，不选择模型 DSP

保留现有 `run_local_recognition { candidate_id }` 形状。采样率、RF 带宽、增益、
窗口数、归一化和模型由 Rust 根据已准入 profile 确定，不能让上游模型临时
发明参数。这样可以避免 Planner 选择一个与训练合同不一致的采集配置。

第一个可交付的生产 profile 建议先限制为固定域：

```text
1024 samples/window
2.1 MS/s capture rate
one P201 RX path
bounded occupied bandwidth eligibility
finite, versioned gain-selection policy
finite window_count selected before acceptance testing
```

这里的 `2.1 MS/s` 只是 P201 固定 RF 实验域，不应声称它是 RML2018A 的原始
物理采样率。超出该域的候选应明确返回 `profile_incompatible`；多采样率或按
符号率归一化属于后续 profile v2。

### 4.3 明确区分增益、强度和 SNR

后续接口和 UI 禁止只写含糊的“20 dB”或“50 dB”：

- `rx_gain_db`：P201 硬件接收增益；当前 433.92 MHz 端口对照使用 50 dB，
  不能推广为所有频率和信号的固定最佳值；
- `tx_gain_db`：B210 测试发射增益；
- `raw_rms_dbfs`：ADC 窗口强度；
- `estimated_snr_db`：第4章由实测噪声基线估计的相对 SNR；
- `dataset_snr_label_db`：RML 数据生成时的名义 AWGN 标签。

后三者尤其不能互换。RML 的 20 dB SNR 样本并不表示 P201 使用了 20 dB
接收增益。

### 4.4 冻结 AGX 预处理而不是继续试凑缩放

第4章和第6章共同选择 `rf_preprocess_v1`，但实现归第4章/AGX acquisition
侧所有。至少比较并记录：

1. 依据精查中心进行数字频移或直接精确重调谐；
2. 抗混叠带限及是否重采样；
3. 是否去除每窗口 DC；
4. 定长裁剪、滑窗或基于前导相关的对齐；
5. 单位复数 RMS、全局标定缩放或幅度增强方案；
6. 静默、削顶、DC 比例、PAPR、残余频偏和带外能量质量门限；
7. 连续捕获后切成多少个 1,024 点窗口，以及窗口聚合规则。

推荐方向是：训练与推理都使用同一版本化变换，并用幅度/gain augmentation
消除模型对绝对幅度这一不可迁移捷径的依赖。`raw_rms_dbfs` 和
`estimated_snr_db` 作为独立质量元数据保留，不应靠未经标定的 IQ 幅度暗示
SNR。最终选择必须看验证集和实收 validation corpus，不能再用测试集调参。

### 4.5 第4章交付物

- `RecognitionInputProfile` schema、版本和内容哈希；
- Rust profile validator 与 replay golden vectors；
- 候选精查/资格判定器；
- 有限连续 IQ 捕获、分窗与质量统计；
- `ModelReadyBatch` 私有 spool 生命周期及失败清理；
- 单独的采集准确性、吞吐、过载、取消和恢复证据。

第4章到此结束，不输出调制名称。

## 5. 第5章建议承担的“数据桥”

仓库第5节继续保留 FPGA 退役事实；论文第5章建议改为下面五部分。

### 5.1 固定测试链路与回放协议

- B210 固定使用 RF A `TX/RX`、UHD channel 0；P201 固定使用物理 RX1；
- 每个发射任务记录 dataset、数字 class ID、source sample ID、发射频率、
  sample rate、TX/RX gain、数字幅度、距离/线缆、时间和软件哈希；
- RML2018A 文件本身没有可直接采用的可信物理采样率；回放 manifest 必须定义
  “一个数据集 sample 对应多少秒/多少符号”的固定映射，不能称为原生采样率；
- 每次发射必须有有限时长和直接停止，接收按精确最大字节计划执行；
- 若具备合适衰减器，先做有线衰减基线，再做室内 OTA；没有衰减器时不得直接
  用同轴连接两台 SDR；
- 先用数字类别 `0..23` 做闭环，名称映射解决前不生成可信调制名称结论。

### 5.2 帧与窗口同步

不能只把 1,024 个样本发送一次并希望 P201 碰巧对齐。测试发射器应使用有限
重复帧，例如：

```text
guard -> known preamble -> RML payload -> guard
```

AGX 用前导相关找到 payload 边界，只把 payload 对应窗口送模型。host 日志保存
source sample ID 和发射序号；这些控制元数据不通过 Planner，也不混入模型 IQ。
同时保留无前导、随机裁剪实验，用来验证模型对异步窗口的真实鲁棒性。

### 5.3 校准和条件矩阵

先做小型 smoke，再冻结 acceptance matrix：

- 24 个数字类别全部覆盖；
- low/mid/high 三个实测 SNR 区间，而不是直接拿 RML 名义 SNR 当实测值；
- 至少两个合法测试频段、两个不同日期/session；
- 多个 TX/RX gain 组合，包含接近噪声、正常动态范围和接近削顶三档；
- 每个 class/condition 在冻结测试集中有足够重复样本，并在看测试结果前固定
  样本数和通过阈值。

训练、验证和测试必须按 source sample、采集 session 和日期分组隔离，禁止同一
RML 片段的不同空口副本跨 split，避免看似很高的射频准确率其实是数据泄漏。

### 5.4 输入分布对齐实验

对每个候选预处理计算训练数据和实收数据的 RMS、DC、PAPR、频偏、PSD、带外
能量和预测分布；同时记录 overall accuracy、macro-F1、逐类 recall 和按实测
SNR 的 accuracy。旧 seed44 只作为对照。选定 `rf_preprocess_v1` 后冻结参考
实现、golden IQ、预期张量和 SHA-256，4090 与 AGX 必须使用同一合同。

### 5.5 第5章交付物

- 可复现的有限 RML/B210 回放工具和 manifest；
- 捕获/标签索引，不把大体积原始 IQ 加入 Git；
- 无泄漏的 train/val/test split；
- 预处理消融表和最终 `rf_preprocess_v1`；
- 有线/OTA 条件边界和结论限制。

## 6. 第6章应完成的工作

### 6.1 重新训练或微调，而不是直接包装 seed44

4090 训练输入必须调用或逐向量等价于 `rf_preprocess_v1`。建议保留两条基线：

- seed44：原始 RML 输入的历史基线；
- RF-aligned D8：使用冻结预处理、幅度/频偏/IQ 不平衡和信道增强重新训练，
  再按验证集选择 checkpoint。

只有 RF-aligned 模型通过完整离线 split、实收 validation corpus 和 4090/AGX
同 IQ logits 对照后，才能生成 production manifest。FP16/BF16/FP32 的选择也
应在这个最终模型上重做，不能沿用旧权重的结论。

### 6.2 模型 manifest 必须反向约束第4章

production manifest 至少包括：

```text
model_id, checkpoint_sha256, source_commit
numeric_label_schema_id, trusted_label_map_id
recognition_input_profile_id, preprocessing_sha256
sample_rate_policy, samples_per_window, window_count
precision, runtime/thread/queue limits
quality thresholds
calibration/rejection artifact hashes
acceptance corpus and metric thresholds
```

Worker 启动时验证全部制品；Controller 的健康探针同时比较 Worker 返回的 profile
ID 与第4章实现的 profile ID。不一致时能力必须为 unavailable。

### 6.3 结果必须支持拒识

把现有三字段 `RecognitionSummary` 扩展成有状态结果，建议最小形状为：

```text
status: classified | rejected | unavailable | error
candidate_id, source_sweep_id, source_sequence
numeric_label_id, trusted_label_name?
calibrated_confidence, alternatives
rejection_reason?
model_id, model_sha256
recognition_input_profile_id, preprocessing_sha256
window_count, agreement, quality_summary
capture_us, preprocess_us, inference_us, total_us
```

噪声、低能量、profile 不兼容、质量失败、窗口间分歧过大和低校准置信度都应
输出 `rejected`，不能伪装成某个 RML 类别。标签名称未解决时只允许输出数字
类别和 `provisional` 显示名。

### 6.4 Runner 与 Web 接入

Runner 为 `RunLocalRecognition` 增加真正的 `RecognitionEngine` 依赖：

1. 按 candidate ID 取最新候选并验证 age/source；
2. 调用第4章 target/profile/capture/preprocess；
3. 调用第6章 Worker、聚合与拒识；
4. 先恢复并复查 SDR，再更新 observation；
5. audit 记录计划、字节、profile/model 哈希、质量、结果、失败与清理；
6. Planner 只接收 compact `RecognitionSummary`，Web 结果页显示完整受限记录；
7. `/stop` 同时取消 SDR session 和当前 Worker 请求，迟到结果按 generation 丢弃。

识别动作最初应要求人工批准；在 closed-set、拒识、取消和误触发证据充分后，
再单独决定是否允许自动巡航触发。不能因为 Worker 进程存在就自动打开能力。

### 6.5 第6章交付物

- RF-aligned、版本化 production checkpoint 与 manifest；
- 可信数字标签/名称映射和校准拒识制品；
- bounded queue=1 的生产 Worker、健康探针、取消及 drop 指标；
- `RecognitionEngine` replay/live Adapter 与 Runner/Web 集成；
- 完整 offline、实收 closed-set、noise/unknown、跨频率/日期及 thermal soak
  证据；
- 可回滚的 AGX 服务部署，运行时 capability 实测后才变为 true。

## 7. 推荐实施顺序和门禁

| 阶段 | 工作 | 完成条件 | 依赖 |
| --- | --- | --- | --- |
| A | 冻结字段语义与 `RecognitionInputProfile` v1 草案 | gain/SNR/sample-rate 不再混淆，schema 和 golden vector 评审通过 | 无 |
| B | 建立 B210 已知标签有限回放与前导对齐 | 数字 sample ID 可从 TX 日志关联到 P201 payload，零丢样/溢出/削顶并恢复 | A |
| C | 做预处理和窗口数消融 | 只用 train/val 选择 `rf_preprocess_v1`，固定 test 前锁定阈值 | A、B |
| D | 4090 训练 RF-aligned D8 | 完整离线指标、源码/权重/配置/split 哈希齐全 | C |
| E | AGX 模型准入 | FP32 parity 后选择精度，实收 validation、拒识和资源门禁通过 | D |
| F | Worker 生产化 | queue/cancel/drop/concurrency/thermal、服务回滚和 runtime health 通过 | E |
| G | Runner/Web 闭环 | `run_local_recognition` 真执行、summary/audit/UI/stop/stale-result 全链路通过 | F |
| H | 端到端验收 | 冻结 test matrix 一次性执行，射频恢复、清理和结论边界完整 | G |

阶段 A—C 是第4/5章与第6章共同设计的关键，不能先把 seed44 包装成生产服务
再补预处理。阶段 D 以后模型实现归第6章；阶段 G 才将能力交给 Agent。

## 8. 每层单独验收的指标

### 第4章验收

- 计划样本数、实际样本数和传输字节完全一致；
- dropped/overflow/clipped/timeout/health 全部可测且失败关闭；
- 候选中心、带宽、噪声、实测 SNR 和 gain 语义明确；
- profile 输出张量逐字节可复现，临时 IQ 成功/错误/取消均删除；
- P201 LO、采样率、带宽、gain mode、RF port 和 scan mask 恢复；
- 完成现有待办的 AGX 有界 acquisition overload 测试。

### 第5章验收

- TX sample ID 与 RX payload 对齐可证明；
- train/val/test 不跨 source sample/session/day 泄漏；
- 预处理选择只看 train/val，test 阈值事先冻结；
- 每个结论附频率、增益、距离/线缆、日期和实测 SNR 范围；
- 所有大 IQ 留在受控结果/本地资产目录，Git 仅保存脚本、manifest、哈希和指标。

### 第6章验收

- 完整 test accuracy、macro-F1、逐类 recall、按实测 SNR 指标和 confusion
  matrix；
- 4090/AGX 同 IQ logits、所选精度误差和 argmax 一致率；
- noise/unknown/quality-failure 的拒识率、误接受率和置信度校准；
- 单窗口及多窗口 p50/p99、GPU/RSS/CPU、queue drop 和持续温度；
- Worker crash/timeout/cancel/restart 后不留下 IQ、不污染下一 generation；
- capability 只在 manifest、Worker health、profile parity 全部通过时为 true。

### 系统验收

- Planner 只能选择已有候选，不能注入 DSP、路径或模型参数；
- Agent observation 能区分 classified、rejected、unavailable 和 error；
- Web 可追溯 candidate → capture → preprocessing → model → result；
- `/stop` 能直接停止硬件和推理，迟到结果不会覆盖当前会话；
- 用户保存的结果有手动删除入口，开发临时数据按 feature 精确清理。

## 9. 明确不做

- 不恢复 FPGA 聚合、寄存器、DMA、Vivado 或 BOOT 路线；
- 不让 P201 发射，也不把 NX/B210 发射控制放入生产 Agent；
- 不把 P201 的 50 dB gain 当成 RML 的 20 dB SNR；
- 不把一次环境噪声的 top-1 当作正确调制结果；
- 不在标签、预处理和拒识未解决时打开 `recognizer_available`；
- 不用同一 RML source sample 的空口副本同时训练和测试；
- 不为了降低传输量把 AGX 预处理重新搬回 P201。

## 10. 最近的两个交付单元

下一步不应直接做 Runner。建议先按两个独立交付单元推进：

1. **共享输入合同与回放 smoke**：实现 profile schema/golden vectors、B210
   有限帧回放、P201 payload 对齐，以及 gain/SNR 明确命名；仅覆盖数字类别和
   小样本，不训练新模型。
2. **预处理冻结与 4090 重训**：完成 train/val 消融，冻结
   `rf_preprocess_v1`，在 4090 训练 RF-aligned D8，再回到 AGX 做完整离线和
   实收 validation。

这两个交付完成之前，现有 experimental Worker 只保留为链路回归工具。
