# 第1—6章统一 RX-only 实施规划

最后审查：2026-09-05（Asia/Shanghai）

本文是当前第1—6章实施路线，取代原先只覆盖第4—6章的规划视角。状态使用与
项目原清单一致的 `- [x]` / `- [ ]`；每一项只有在代码、部署和该项要求的实机
证据全部成立后才打勾。更细的历史交付项和证据索引仍以
[`SDR_AGENT_PROJECT_CHECKLIST.md`](SDR_AGENT_PROJECT_CHECKLIST.md) 为准。

系统始终是纯接收闭环：

```text
第1章 Agent/Harness
  -> 第2章 Planner 提议 + Rust 校验/批准
  -> 第3章 P201 Linux/IIO 有界 RX
  -> 第4章 AGX 扫频、候选、精查与模型输入
  -> 第5章 输入标准化、接收域对齐与评测治理
  -> 第6章 Mamba 分类/拒识
  -> 有界 RecognitionObservation 返回第1章
```

P201 不发射，Agent 没有发射动作，NX/B210/USRP 不属于当前运行、训练或验收
依赖。历史 B210→P201 RX1 单音试验只证明端口与接收链路，不是未来路线。

以 `2d36bc6` 为基线重新核对后，当前已完成“受控实收 → RF-v1 模型输入 →
FP16 四窗推理”的工程链路，下一阶段是生产准入、识别结果闭环与持续运行。
按章节判断如下；不按历史 checkbox 数量换算总体百分比，因为它们的范围和
验收成本不同。

| 章节 | 已完成的交付边界 | 主要剩余工作 |
| --- | --- | --- |
| 第1章 | Agent、Web、终端、Spark 和扫频结果已部署 | 有状态识别结果、持久化/人工删除、紧凑 Agent 反馈 |
| 第2章 | 扫频/精查/IQ 的批准、执行、预算、恢复和 stop 闭环 | 识别能力来源、人工批准、执行器、Worker-aware stop、结果回灌、固定 Planner 回归 |
| 第3章 | P201 RX1 身份、有界采集/传输、恢复和长期重连均已实机验证 | 当前范围无新增硬件实施项 |
| 第4章 | 扫频/精查、共享 RMS、顺序四窗和 golden parity 已实收 | 将 integration-only profile 随模型准入升级为 production |
| 第5章 | 语料合同/存储、split 隔离、冻结预处理、checkpoint validation 已完成 | RF-v1 独立证据接入、known-RF/OOD 标签、校准/验收隔离、名称映射、locked test |
| 第6章 | epoch-10 FP32 权重/FP16 推理合同、完整 logits/mean-logit 和有限故障验证 | 生产 Worker 生命周期、校准/拒识、共享 GPU gate、长时资源与部署准入 |

`recognizer_available=false` 继续成立。高 softmax、四窗一致和有限实收成功都不
能替代独立标注准确率、OOD false acceptance 或生产 Worker 验收。

## 第1章：Agent/Harness 与用户界面

### 已完成

- [x] AGX 已成为 Agent、Controller、Planner、Web、结果存储和模型接入主机，
      P201 是唯一受控 RX 数据源，树莓派只保留回滚基线。
- [x] Rust Controller 保持唯一硬件与策略权威；Planner 只有结构化
      `submit_plan`，没有 shell、SSH、文件、IIO 或 SDR 权限。
- [x] 本机 Spark-X2.5-4B BF16 已部署为默认 Planner；OpenAI-compatible
      Completions/Responses 接口保留为操作员显式选择的新会话 provider，不做
      自动云端故障切换。
- [x] 终端和 Web 已支持单可信操作员、最多两个历史会话、一个活动控制会话、
      有界上下文/恢复、流式输入、steer/follow-up、批准/拒绝和针对现有
      Planner/SDR 工作的优先 `/stop`。
- [x] Web 已展示真实 PlanningContext、扫频、候选、执行结果和受限 reasoning，
      并提供扫频结果、可选 SigMF 与人工删除路径。
- [x] Planner、Web 和本机 Spark 服务已在 AGX 上启用；2026-09-04 再次确认三者
      均为 active/enabled。

### 还未完成

- [ ] 把三字段 `candidate_id/label/confidence` 升级为有状态
      `RecognitionObservation`，在终端和 Web 展示 classified/rejected/
      unavailable/error、数字标签、可信名称状态、拒识原因、模型/profile、质量、
      来源序号和时延，同时不暴露 IQ 路径或张量。
- [ ] 将完整识别记录写入应用结果存储并提供可见的单条人工删除路径；Planner
      只接收下一步决策所需的紧凑摘要。
- [ ] 用真实识别结果验证 Spark 能解释当前接收结论并显示下一步理由，而不是把
      模型 top-1 直接写成已确认事实。

## 第2章：接收 Planner、Rust 策略与闭环

### 已完成

- [x] 已定义 hold、survey、candidate inspect、bounded IQ、local recognition 和
      stop 六类结构化动作，并由 Rust 校验状态、能力、候选、频率、带宽、采样、
      dwell、字节、批准和 observation 新鲜度。
- [x] `survey_band`、`inspect_candidate` 和 `capture_bounded_iq` 已接入 one-shot
      与交互执行路径；真实 P201 扫频/精查会生成下一轮 Planner observation。
- [x] 自动巡航已有有限 step/time/IQ 预算、独立 SDR/上游重试上限、人工批准门、
      直接硬件取消和停止后的 generation 失效。
- [x] 请求、模型/provider、原始提议、Rust 校验、批准、执行、恢复与 observation
      已进入相关联的 JSONL audit。
- [x] Planner/SDR 的断连、超时、部分动作、取消、迟到 proposal 和恢复路径已做
      隔离测试与真实设备验证。
- [x] `run_local_recognition { candidate_id }` 的协议形状、候选存在性和
      `recognizer_available` 策略校验已经存在。

### 还未完成

- [ ] 由实时 Worker 健康、准入 manifest 和 Chapter 4 profile parity 生成
      `recognizer_available`；当前 Runner 仍从输入 request 继承该布尔值，不能
      作为生产能力来源。
- [ ] 为识别动作冻结批准策略。第一版应进入人工批准门；当前 Rust policy 对
      `RunLocalRecognition` 返回 `approval_required=false`，在能力开启前必须改正
      并覆盖 step/automatic 两种模式。
- [ ] 在 one-shot 和交互 Runner 中调用正式 `RecognitionEngine`；当前 one-shot
      写入 `planned_only`，交互终端显示“没有生产执行器”，自动巡航会按
      unsupported action 停止。
- [ ] 把 classified/rejected/unavailable/error 摘要写回 PlanningContext，启动一轮
      新 Spark turn，并只允许重新精查、有限再捕获/再识别、换候选、继续扫频、
      hold 或 stop。
- [ ] 扩展 `/stop`，同时取消 active SDR capture 和 Recognition Worker，按
      request ID/session generation 丢弃迟到结果，并让取消可靠释放共享 GPU
      inference lease。
- [ ] 建立固定 Planner 回归集，覆盖六类动作、边界、故障和识别结果。当前短烟测
      BF16 仅 4/5 通过（一次产生越界 48 MS/s，虽被 Rust 安全拒绝），不能把
      “Policy 拒绝成功”当成 Planner 质量已经完成。

## 第3章：P201 Linux/IIO 有界 RX 控制面

### 已完成

- [x] `sdrd` 已实现受限 SDRD/1、单连接所有权、能力/健康、请求与 generation
      关联，并移除 FPGA/MMIO 和任何发射路线。
- [x] 已实现单通道 profile、有限 `CAPTURE_POWER`、`CAPTURE_IQ` 和
      `CAPTURE_IQ_INLINE`；AGX 收到精确样本/字节后，P201 临时 IQ 会立即清理。
- [x] 已返回 sequence、dropped、overflow、timeout 和 health 元数据，并在
      apply/readback/capture/断连/取消/错误后停止、拆 buffer、恢复射频状态。
- [x] 已部署私有链路 listener、持久 host key、重复实例门禁和恢复 timer，并
      完成 1,800 秒、100 次有限采集的真实设备重连/故障验证。
- [x] 实验路径已用软件 RX0 的 `voltage0,1` I/Q 对从面板 RX1 收到 1,024 个
      complex-int16 样本并传至 AGX；该证据只证明链路接通。
- [x] 已将生产固定物理输入 `RX1 / A_BALANCED` 实现为 Adapter 只读探测、
      SDRD/1 可审计且失败关闭的版本化身份；capability、health、profile、capture
      与 stop 均返回该身份，所有 session 退出路径验证不变，Rust 客户端严格
      关联，且已完成 ARMv7 部署、有限实收和恢复/清理验证；见
      [`P201_RX1_INPUT_IDENTITY_VALIDATION_2026-09-04.md`](P201_RX1_INPUT_IDENTITY_VALIDATION_2026-09-04.md)。

### 还未完成

- [x] 第3章没有剩余实施项；后续不得把物理端口变成 Planner 可选参数，也不得
      把 AGX 聚合或识别下放到 P201。

第3章的固定物理输入身份缺口已经关闭。现有有限采集、inline 传输、取消、恢复和
长期重连能力足以承载 Chapter 4 单/多窗口捕获；不需要在 P201 增加 DSP、聚合或
模型代码。

## 第4章：AGX 扫频、候选精查与模型输入

### 已完成

- [x] 已实现有界 `SweepPlan`、P201 inline IQ 接收、AGX 软件功率/噪声/削顶
      计算、候选合并和紧凑 Planner observation。
- [x] 初始全段扫频、单候选精查、固定增益读回、结果 SQLite/Web、可选 SigMF、
      人工删除、取消、恢复和无重复启动均已实机验证。
- [x] 已记录 2.1–30.72 MS/s profile 与当前软件/inline transport 的真实吞吐边界，
      没有把未测性能写成能力。
- [x] 一个受限 1,024 点 P201 窗口已经通过 AGX 实验预处理和私有 spool 到达
      Mamba，成功/错误路径均有清理基础。
- [x] 当前 seed44 已接入版本化 `integration_only` 四窗口合同：精查 IQ 在 AGX
      生成同窗频谱中心/噪声/SNR/99% 占用带宽和新鲜 `RecognitionTarget`，一次
      4,096 点 RX1 采集被切成 4 × 1,024 的逐字节可复现输入，并以四个精确
      offset 顺序调用 Worker。真实实收完成 3/4 provisional 多数票、射频恢复与
      spool/Worker/P201 临时数据清理；生产 capability 仍为 false。见
      [`P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md`](P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md)。
- [x] 四窗口故障路径已实收：Worker 在窗口 0 后退出会让窗口 1 显式失败并删除
      32-KiB spool；独立 generation-bound cancel 会产生
      `capture_failed_restored`。两条路径均恢复 P201、删除 AGX/P201 临时数据且
      保持 capability false；见
      [`P201_MAMBA_BATCH_FAILURE_CANCEL_VALIDATION_2026-09-05.md`](P201_MAMBA_BATCH_FAILURE_CANCEL_VALIDATION_2026-09-05.md)。
- [x] AGX 软件 acquisition overload 已完成：超 256-KiB 单点计划在接触 backend/
      射频前拒绝；128 个最大合法窗口共 32 MiB 实收，sequence 连续且 dropped、
      overflow、clipping、timeout、health/身份错误均为 0；IIO deadline 和 AGX
      连接中断均恢复，后续 generation 成功，资源有界且无 IQ 残留。见
      [`P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md`](P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md)。
- [x] FPGA 聚合、MMIO、UIO、Vivado 和 `BOOT.bin` 已从当前路线退役。

### 还未完成

- [ ] 将当前已经实现和实收的 `integration_only` Target/profile/batch 合同升级为
      production profile；只有第5章冻结 `rf_preprocess_v1` 且新 checkpoint 准入
      后才能替换 admission，Planner 仍只能选择 candidate ID。
- [x] 已预注册并仅用 train 统计、完整 validation 伪会话和版本化 P201
      `receive_domain/unknown` 证据冻结 `rf_preprocess_v1` 重训合同：硬件重调谐、
      不做数字频移/额外滤波/重采样、保留 DC、四窗共享 RMS、4 × 1,024 连续窗和
      mean-logit；选择代码未加载 test，见
      [`RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md`](RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md)。
- [x] 用户训练的 RF-aligned epoch-10 checkpoint 已独立下载、逐文件核验并在 AGX
      严格加载；完整 95,607 个 validation 四窗组 accuracy 与 4090 完全一致，NLL
      差 `6.8e-8`，test 未打开且 capability 保持 false。
- [x] 已实现并实收 RF-v1 shared-capture RMS/full-logit runtime：单次 4,096
      点共享 RMS、保留 DC、四窗顺序、FP16 autocast/FP32 常驻权重、每窗完整
      logits 和 AGX float64 mean-logit 后 softmax；冻结 golden hash 一致，来源/
      请求/session/哈希严格关联，成功、Worker 退出和取消均恢复并清理。见
      [`RF_V1_RUNTIME_PARITY_VALIDATION_2026-09-05.md`](RF_V1_RUNTIME_PARITY_VALIDATION_2026-09-05.md)。
- [ ] 仅用 validation 与独立标注 known-RF/OOD 证据冻结温度、置信度、agreement、
      SNR、带宽和质量阈值；最后才能做一次 locked test 准入。

## 第5章：输入标准化、接收域对齐与评测治理

### 已完成

- [x] RML2018A seed44、HisarMod2019 seed43、固定 split、两套 HDF5、最小 D8
      源码和精确 SHA-256 已整理在 AGX 的 Git-ignored 独立资产目录。
- [x] 两套完整 FP32 test split 已在 AGX 重现，并完成同 IQ 的 4090 logits/
      argmax 数值对照、混淆矩阵、逐类与逐 SNR 指标。
- [x] 已明确 P201 现场窗口没有独立标签时只能用于链路、质量、域偏移和拒识
      观察，不能用 Mamba 自己的 top-1 反作 accuracy 真值。
- [x] 已明确数据集名义 SNR、P201 `rx_gain_db`、ADC `raw_rms_dbfs` 和现场
      `estimated_snr_db` 是不同量。
- [x] 已定义并验证统一的 `amc_corpus_manifest_v1` / 流式 JSONL record 合同，
      覆盖离线数据、P201 RX-only 窗口和 golden vectors；逐窗口必须显式使用
      `dataset_ground_truth`、`independent_annotation` 或 `unknown`，同时固定内容、
      profile、预处理、标签、split 和证据哈希。严格校验器已覆盖来源/标签误用、
      临时名称升级、路径/哈希篡改、错误 RX 口、未清理冻结记录和 train/test
      lineage 泄漏；见 [`AMC_CORPUS_MANIFEST_V1.md`](AMC_CORPUS_MANIFEST_V1.md)。
- [x] 已部署 AGX 应用自有的 P201 corpus SQLite/七文件包存储和 `接收语料` 页面；
      loopback-only 入口只接受当前 2.1 MS/s、1.5 MHz、50 dB、4,096-sample RX1
      profile，重新计算 IQ 功率/频谱/削顶并要求恢复与临时清理。一次 433.920 MHz
      实收以 `unknown` 入库，通过完整资产哈希校验和真实页面删除后又按同一内容
      恢复保留；见
      [`P201_RX_CORPUS_STORE_VALIDATION_2026-09-05.md`](P201_RX_CORPUS_STORE_VALIDATION_2026-09-05.md)。

### 还未完成

- [x] 已按不可变 HDF5 `/X` 全局行、capture session 和 UTC 日期证明
      train/validation/test 隔离：两套完整 split 均全覆盖、内部无重复且两两交集为
      0；跨 P201 包审计会拒绝父级血缘改变和三类 group 泄漏，当前唯一
      `receive_domain/unknown` 行不进入准确率。见
      [`AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md`](AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md)。
- [x] 已只用 train/validation 完成五种预处理与 1/2/4 窗、三种聚合消融，冻结
      四窗共享复数 RMS、保留 DC、4 × 1,024 和 mean-logit 作为重训合同；历史
      test 虽已存在，但本次工具拒绝加载 test 成员/结果。P201 `unknown` 的质量和
      置信度单独报告，未混入准确率。
- [x] 最终候选 checkpoint 已返回并完成 AGX FP32 全 validation parity；新温度
      `1.34647` 仅记录为 validation-only candidate，没有误冻结为生产参数。
- [ ] 为 RF-v1 增加版本化语料派生/导入与独立标签证据接入：当前应用入口仍
      固定 legacy profile 且仅写 `unknown`。复用已有合同/存储，保留旧包原始
      哈希；新记录严格关联原始 capture、profile/preprocess 和证据来源，继续
      支持人工删除，不把模型 top-1 或 `unknown` 理由转成独立标签。
- [ ] 补充独立标注 known-RF/OOD 数据，冻结 calibration 与 acceptance threshold，
      再查看该 checkpoint 的 locked test。
- [ ] 解决 RML2018A 数字 ID 到名称顺序争议；解决前数字 ID 是唯一可信类别身份，
      文本名称必须标为 provisional。

## 第6章：AGX Mamba 调制识别与拒识

### 已完成

- [x] 已实现 backend-neutral `LocalRecognizer`、replay/Unix Adapter、bounded IQ
      引用、request/generation/candidate 关联和严格模型 package loader。
- [x] 实验 CUDA/Mamba Worker 已按 checkpoint/source/config/label 哈希加载，使用
      backlog 1、单 Torch CPU thread 和有限 request count，且不能安装为生产服务。
- [x] 当前 seed44 Worker 已消费真实 P201 RX1 的四个连续窗口，逐窗模型哈希一致，
      输出完整 provisional top-1/alternatives 与一个明确未校准的多数票联调摘要；
      临时批次在成功/错误路径删除，未开启 `recognizer_available`。
- [x] seed44/seed43 完整 FP32 离线指标和 AGX/4090 数值 parity 已完成。
- [x] 已完成一次真实 P201 RX1 → AGX → seed44 实验链路，验证 spool 删除与
      SDR 恢复；无标签环境窗口输出没有被宣称为正确类别。
- [x] 已完成 Spark BF16/Q8 与 Mamba 的短时共存/故意重叠测试：模型可同时
      驻留，重叠活跃推理时双方吞吐近似减半，无 OOM。
- [x] 已验证当前 GGUF 不含 MTP/NextN 层，ngram 没有稳定中位收益，社区 Q8
      的五例 Planner smoke 为 3/5，未替换 BF16 默认 Planner。

### 还未完成

- [x] 用户已使用冻结的 `rf_preprocess_v1` 在 4090 微调并按 validation 选择 D8
      epoch 10；AGX 已锁定并验证源码、split、profile、数字标签、训练配置和权重，
      test 保持锁定。见
      [`RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md`](RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md)。
- [x] 已在最终 checkpoint 上按预注册门限比较 FP16/BF16/FP32 的完整 validation
      准确率、argmax/logits/probability 偏差、吞吐和显存；FP16 全部门限通过，
      固定为候选推理精度，BF16 因数值偏差淘汰，test 与生产能力仍保持关闭。见
      [`RF_V1_PRECISION_SELECTION_VALIDATION_2026-09-05.md`](RF_V1_PRECISION_SELECTION_VALIDATION_2026-09-05.md)。
- [x] 已实现 epoch-10 FP16 四窗完整 logits、严格合同关联及 AGX mean-logit 聚合，
      完成 golden、故障/取消测试和 RX1 实收与清理；仍为 integration_only。
- [ ] 实现置信度校准与 noise/unknown/低质量/低置信度拒识，报告 rejection rate、
      false acceptance 和 calibration error；生产准入仍缺独立 known-RF/OOD 标签。
- [ ] 将已有逐窗 logits/关联字段和 AGX mean-logit 结果汇入统一的
      `RecognitionObservation`，补齐 classified/rejected/unavailable/error、
      拒识原因和校准状态；只把有界摘要传给 Planner，完整记录保留在 AGX。
- [ ] 实现 production Worker health/profile parity probe、queue=1、deadline、
      cancel/drop 指标、crash/restart 清理和持续 thermal soak。
- [ ] 让 Spark 与 Mamba 同时常驻但活跃推理严格按 `Spark -> Mamba -> Spark`
      串行；验证取消释放 gate、迟到结果不能污染下一 generation。
- [ ] 部署可回滚的生产 Worker，并在冻结的频率/增益/session 矩阵上完成 RX-only
      端到端验收；只有全部准入门通过后才报告 `recognizer_available=true`。

## 第1—3章审计依据

- [`protocol.rs`](../raspberry-pi/sdr-agent/controller/src/protocol.rs) 的
  `RecognitionSummary` 当前只有三字段。
- [`runner.rs`](../raspberry-pi/sdr-agent/controller/src/runner.rs) 从 request 继承
  `recognizer_available`，且识别动作落入 `planned_only`。
- [`policy.rs`](../raspberry-pi/sdr-agent/controller/src/policy.rs) 对
  `RunLocalRecognition` 当前返回无需批准。
- [`sdr-agent.rs`](../raspberry-pi/sdr-agent/controller/src/bin/sdr-agent.rs) 的交互/
  巡航路径没有识别执行器；
  [`app.js`](../raspberry-pi/sdr-agent/web-console/public/app.js) 也没有识别结果
  渲染路径。
- [`sdrd_iio.c`](../sdr-system/sdrd/src/sdrd_iio.c) 固定启用
  `voltage0,1` scan pair，并只读验证 `voltage0` 的 `rf_port_select=A_BALANCED`；
  [`sdr.rs`](../raspberry-pi/sdr-agent/controller/src/sdr.rs) 对完整 RX1 身份失败关闭。

## 重新安排后的交付顺序（2026-09-05）

历史已完成项保留：

- [x] A：先补第3章 RX1/A_BALANCED 身份合同和全程不变检查，并与第4章
      `RecognitionInputProfile`/golden fixtures 一起评审。
- [x] B1：完成第4章候选资格/多窗口 capture，以及第5章统一合同、应用自有
      RX-only 语料存储、完整资产校验和可见人工删除。
- [x] B2a：证明 offline/receive corpus 的 source sample、capture session、UTC day
      group-exclusive split 无泄漏，并固定派生数据继承规则。
- [x] B2b：只用 train/validation 与 receive-domain 证据完成
      `rf_preprocess_v1` 信号变换、窗口数和聚合消融，冻结供 4090 重训的合同；
      本次选择没有读取 test。
- [x] C1：用户在 4090 完成 RF-aligned checkpoint 训练与 validation 选择；AGX
      完成独立下载、严格 FP32 加载和完整 validation parity。

B2c 的校准/test 准入缺口对应下面 V1—V3。C2 拆成以下明确边界，避免继续把
已完成的精度选择和聚合算作待开发：

- [x] C2a：最终 checkpoint 的完整精度选择已完成，沿用冻结 FP16。
- [x] C2b：RF-v1 runtime/golden/full-logit 和有限成功/失败/取消实收已完成。
- [ ] C2c：校准/拒识与生产 Worker 准入；由下面 S2—S4、V1—V3 和 A1 完成。
- [ ] D：Runner/Agent/Web 闭环；实现可提前进行，生产执行只能在 A1 准入后开启。
- [ ] E：冻结 RX-only 矩阵验收、清理和自动巡航识别准入；不以联调成功代替。

软件工作无需等待独立标签，可按 S1 → S2 → S3 → S4 → S5 → S6 逐个交付。
数据证据 V1 可同期筹备；这里的两条工作线是依赖安排，不要求并发 Agent。
所有开发阶段继续使用 replay、合成 golden 或显式 engineering-only RX 路径，
不得为联调把生产 capability 临时改成 true。

| 单元 | 交付范围 | 完成条件及依赖 |
| --- | --- | --- |
| S1：准入与批准门（下一单元） | 定义 `RecognizerAdmission`/版本化 health 合同；能力由当前 Worker 健康、模型/profile/preprocess/精度和准入记录共同决定；修正 step/cruise 识别人工批准 | 缺失、过期、错误哈希、Worker 重启或未准入均失败关闭；request/template 不能自行宣称可用；真实候选仍 false；无需标签数据 |
| S2：统一识别结果 | 内部完整结果与 Planner 紧凑 observation；四种状态、numeric ID、名称可信度、calibration/rejection identity、质量/来源/timing；预留严格的校准包读取 | schema/负例/序列化/上下文边界验证；未校准实验输出不冒充生产 classified；温度和阈值保持未冻结；依赖 S1 的身份合同 |
| S3：Worker 生命周期 | 明确应用队列边界、整批 deadline、cancel acknowledgement、超时恢复、进程退出/强杀/重启清理、Worker 实例身份和指标 | backlog=1 不作为队列验收；过期/取消任务不能继续占用下一批；迟到结果不能跨 generation/实例；实机故障注入和精确 spool 清理；依赖 S1/S2 |
| S4：共享 GPU 与资源 | Spark/Mamba 常驻、活跃推理串行；租约获得/释放、取消和崩溃释放；queue/drop/deadline/RSS/显存/温度统计 | 实机证明 `Spark → Mamba → Spark`、故障后可继续、无租约泄漏；按预注册时长/负载做资源 soak；依赖 S3，不能复用短时共存当持续验收 |
| S5：Runner 执行与反馈 | one-shot/interactive/cruise 识别执行器、人工批准、预算/audit、SDR+Worker stop、观察回灌和新一轮 Spark | 工程模式完成成功/拒识/不可用/错误/取消/迟到结果全链路；固定六动作 Planner 回归另计模型质量与 Rust 安全；依赖 S2—S4；生产仍由 S1 关闭 |
| S6：用户结果交付 | Web/终端展示四状态及证据；SQLite 完整识别记录、默认不留 IQ、单条人工删除 | 无 IQ 路径/张量进入 Planner；未标注结论不写成已确认事实；真实浏览器、结果恢复/删除和 Spark 摘要验证；依赖 S2/S5 |

| 单元 | 缺失的独立证据与处理 | 完成条件及依赖 |
| --- | --- | --- |
| V1：RF-v1 证据接入与独立标签 | 升级现有 legacy/unknown-only 接入口或提供严格导入/派生工具；明确 known-RF 类别、noise/idle、类外信号、混合/低质量覆盖以及 session/day/source 分组 | 标签由用户或独立证据提供；记录依据、审核/歧义和谱域条件；预注册采样矩阵、覆盖/样本量依据、校准集与独立验收集；已有 unknown 包不自动变真值 |
| V2：校准和拒识 | 在冻结 FP16/mean-logit 下，仅用 validation 与独立校准证据拟合温度及 confidence/agreement/SNR/bandwidth/质量规则 | 独立验收集报告已知类准确率、rejection rate、false acceptance、ECE/NLL 及覆盖限制；失败不靠查看 locked test 调参；依赖 V1/S2 |
| V3：模型准入 | 处理 numeric-ID/文本名称争议，冻结准入 manifest、calibration 和 acceptance 标识，然后执行一次 locked test | 准入规则在查看结果前冻结；test 失败记录失败并回到候选流程，不反复重调同一 test；任何后续重训仍由用户负责；依赖 V2 |

- [ ] A1：S1—S6、V1—V3 证据齐备后，版本化 production profile、部署可回滚
      Worker/Controller，验证实际部署哈希、恢复/清理以及预注册频率/增益/session
      RX-only 矩阵；只有全部门通过，才允许 Adapter 报告能力。首版识别保持人工
      批准，自动巡航也不能绕过；自动触发是否放开留到该验收结论。
- [ ] O1：第8章持续运行交付：可重复故障注入与跨 socket fuzz、日志轮转/
      健康告警/升级回滚流程、24 小时完整闭环 soak。工时和设备占用按独立单元
      记录；此前 P201 1,800 秒验证不能替代 AGX+Planner+Recognizer 全系统 soak。

本次只重排已有工作并补记 RF-v1 证据接入口缺口，没有执行新采集或模型实验，
没有为新软件/准入项打完成勾。独立标签未到位不影响 S1—S6 的实现与工程验证，
但 V2/V3/A1 无法仅靠代码完成，因此不承诺生产上线日期。

## 范围与保留项

第7章“辐射源/设备身份识别”仍是后续独立能力，需要另行定义识别对象和
RF-fingerprint 数据；当前调制识别 checkpoint 不证明发射设备身份。先交付
第1—6章闭环，不把第7章模型或新硬件加入当前关键路径。

冻结的 epoch-10、FP16、预处理和离线精度结果继续复用。不重跑完整精度实验，
不打开 locked test 做开发调试，不自行训练模型。固定物理输入继续为
P201 RX1/RX0/A_BALANCED；FPGA/BOOT/NX offload 和 TX 不在后续计划内。

## 明确不做

- [x] 不恢复 FPGA、MMIO/UIO、Vivado、DMA、寄存器或 `BOOT.bin` 路线。
- [x] 不在第1—6章加入任何发射动作、发射端 Agent、随机发射或回放验收分支。
- [x] 不把未标注现场 top-1 当正确率，不把 RML 名义 SNR 当 P201 增益或实测
      SNR，不在准入未完成时把 capability 配成 true。
- [x] 不把 AGX 聚合、预处理或 Mamba 下放回 P201。
