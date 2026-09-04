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

第1—3章的审计结论可以先概括为：

| 章节 | 当前判断 | 主要剩余工作 |
| --- | --- | --- |
| 第1章 | Agent、Web、终端、本机 Spark 和扫频结果界面已部署 | 识别状态的展示、持久化、人工删除和紧凑 Agent 反馈 |
| 第2章 | 扫频、精查、IQ、预算、批准、audit、Planner/SDR stop 已闭环 | 识别 capability、批准、执行、回灌、Worker stop/GPU gate 和完整 Planner 回归 |
| 第3章 | 已完成：有界 RX、inline IQ、取消、恢复、长期重连和固定 RX1 身份均已实机验证 | 无；作为第4章输入合同的稳定硬件基线 |

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
- [ ] 使用 train/validation 与版本化 P201 接收域证据选择并冻结
      `rf_preprocess_v1`，明确频移/重调谐、滤波/重采样、DC、幅度、窗口和质量
      策略；不得在 frozen test 上试凑。

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
- [ ] 只用 train/validation 完成预处理与窗口数消融，冻结 transform、校准和
      acceptance threshold 后再查看 test；分别报告有标签准确率与无标签现场
      质量/置信度/拒识，不能混算。
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

- [ ] 使用冻结的 `rf_preprocess_v1` 在 4090 重训或微调并选择 RF-aligned D8
      checkpoint，在看 frozen test 前锁定源码、split、profile、标签、校准和阈值。
- [ ] 在最终 checkpoint 上比较 FP16/BF16/FP32 的完整准确率、argmax/logits
      偏差、时延和资源，选择 AGX 生产精度。
- [ ] 实现多窗口聚合、置信度校准与 noise/unknown/低质量/低置信度拒识，报告
      rejection rate、false acceptance 和 calibration error。
- [ ] 扩展 Worker 输出为 classified/rejected/unavailable/error、数字标签、
      provisional/可信名称、alternatives、source、model/profile hash、质量、
      window agreement 和完整 timing。
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

## 推荐交付顺序

- [x] A：先补第3章 RX1/A_BALANCED 身份合同和全程不变检查，并与第4章
      `RecognitionInputProfile`/golden fixtures 一起评审。
- [x] B1：完成第4章候选资格/多窗口 capture，以及第5章统一合同、应用自有
      RX-only 语料存储、完整资产校验和可见人工删除。
- [x] B2a：证明 offline/receive corpus 的 source sample、capture session、UTC day
      group-exclusive split 无泄漏，并固定派生数据继承规则。
- [ ] B2b：只用 train/validation 与 receive-domain 证据完成
      `rf_preprocess_v1`、校准和 acceptance threshold 消融与冻结；冻结前不查看
      held-out test。
- [ ] C：在 4090 训练 RF-aligned checkpoint，回到 AGX 完成精度、拒识、资源和
      production Worker 准入。
- [ ] D：最后接入第1—2章 Runner/Agent/Web，完成 health capability、人工批准、
      结果回灌、共享 GPU gate、`/stop` 和 stale-result 全链路。
- [ ] E：按冻结 RX-only 矩阵做一次最终验收和清理，再决定是否允许自动巡航
      触发识别。

## 明确不做

- [x] 不恢复 FPGA、MMIO/UIO、Vivado、DMA、寄存器或 `BOOT.bin` 路线。
- [x] 不在第1—6章加入任何发射动作、发射端 Agent、随机发射或回放验收分支。
- [x] 不把未标注现场 top-1 当正确率，不把 RML 名义 SNR 当 P201 增益或实测
      SNR，不在准入未完成时把 capability 配成 true。
- [x] 不把 AGX 聚合、预处理或 Mamba 下放回 P201。
