# 第1—6章统一 RX-only 实施规划

最后审查：2026-09-06（Asia/Shanghai）

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
| 第2章 | S1 与 S5 工程 Runner/联合 stop/自动回灌/固定回归完成隔离实机验证 | 已准入版本部署、生产执行与浏览器闭环验收 |
| 第3章 | P201 RX1 身份、有界采集/传输、恢复和长期重连均已实机验证 | 当前范围无新增硬件实施项 |
| 第4章 | 扫频/精查、共享 RMS、顺序四窗和 golden parity 已实收 | 将 integration-only profile 随模型准入升级为 production |
| 第5章 | 语料合同/存储、split 隔离、冻结预处理、checkpoint validation 已完成 | RF-v1 独立证据接入、known-RF/OOD 标签、校准/验收隔离、名称映射、locked test |
| 第6章 | epoch-10 FP32 权重/FP16 推理合同、完整 logits/mean-logit 和有限故障验证 | 生产 Worker 生命周期、校准/拒识、共享 GPU gate、长时资源与部署准入 |

`recognizer_available=false` 继续成立。高 softmax、四窗一致和有限实收成功都不
能替代独立标注准确率、OOD false acceptance 或生产 Worker 验收。

2026-09-07 运行入口更新：[统一 CLI](validation/UNIFIED_CLI_VALIDATION_2026-09-07.md) 已将
当前 Controller/交互代码装入单个 `sdr-agent`，并供 Web 与恢复服务调用。
这是 RX 控制入口交付；下文各识别单元的“未部署”仍指生产识别系统未整体上线，
Worker、识别 Web、校准/profile 和准入配置未随本次入口合并部署，A1 保持未完成。

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

- [ ] 在实际接收闭环的终端和 Web 展示 classified/rejected/unavailable/error、
      数字标签、名称可信状态、拒识原因、模型/profile、质量、来源和时延；不暴露
      IQ 路径或张量。S5/S6b 原生及浏览器隔离闭环已完成，生产部署仍属 A1。
  - [x] S6b 真实 unavailable/error、合成 classified/rejected 展示、精确归档关联、
        重启隔离、删除和 Spark hold 通过；见 [S6b 验证](validation/WEB_RECOGNITION_S6B_VALIDATION_2026-09-06.md)。
  - [x] S2 有状态 observation 合同已完成；S6a 已在归档 Web/终端验证全部展示字段，
        实验回放与合成演示明确分开，未将演示算作生产准入。
- [x] S6a 将完整识别记录写入既有应用 SQLite，提供可见单条人工删除、分页和
      重启恢复；只返回有界摘要，不把完整 logits/IQ 送入 Planner。源码及隔离
      Web/CLI/浏览器验收完成，临时数据已清理，未部署。见
      [`RECOGNITION_ARCHIVE_S6A_VALIDATION_2026-09-06.md`](validation/RECOGNITION_ARCHIVE_S6A_VALIDATION_2026-09-06.md)。
- [x] S6b 用真实 unavailable/error 验证 Spark 解释当前失败关闭状态并返回 hold，
      未将实验 top-1 写成已确认事实；已准入分类结论仍待 A1。

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

- [x] 已实现 S1 版本化准入/health 合同和当前 Worker 探测，Controller/Runner/
      terminal 不再继承 request/template 的可用布尔值；缺失、过期、哈希/精度
      不符及同 generation 的 Worker/准入记录更换均失败关闭。真实候选 health
      验证和完整临时数据清理已完成，能力仍为 false。见
      [`RECOGNIZER_ADMISSION_S1_VALIDATION_2026-09-06.md`](validation/RECOGNIZER_ADMISSION_S1_VALIDATION_2026-09-06.md)。
- [x] `RunLocalRecognition` 已要求人工批准；step 待批准、cruise 停在批准门、
      one-shot automatic 拒绝和批准时重新检查均通过测试。
- [ ] 在 A1 部署已准入版本并实机验收生产能力与批准执行链；S1 只完成源码和
      隔离 Worker 验证，未替换当前已安装的 Controller/Planner/Web 服务。
- [ ] 在 A1 部署已准入 production profile/Worker；普通生产路径仍因准入缺失而拒绝识别。
  - [x] S5 显式工程执行器已接入 one-shot/execute/交互 Runner，人工批准后执行新鲜
        精查、RF-v1 四窗、S3/S4a 与 S6a 归档，预算/audit/恢复和精确清理已验证。
- [x] S5 将紧凑 observation 写回 PlanningContext，并自动启动一次 Spark 规划轮；
      真实 unavailable 及明确合成的其余状态回归通过，后续仍须正常批准；不宣称
      生产 classified/rejected 已实收准入。见 [S5 验证](validation/RUNNER_RECOGNITION_S5_VALIDATION_2026-09-06.md)。
- [x] S5 联合 `/stop`、generation-bound RX cancel、Worker 回收/共享租约释放和
      迟到结果隔离已完成源码及有限实机验证；生产服务未替换。
- [x] 六动作/边界/状态/故障测试与八项真实 Spark 固定回归通过；每个接受提案
      均经 Rust policy 验证，不再以旧 4/5 短烟测作为当前完成证据。

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
      [`P201_RX1_INPUT_IDENTITY_VALIDATION_2026-09-04.md`](validation/P201_RX1_INPUT_IDENTITY_VALIDATION_2026-09-04.md)。

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
      [`P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md`](validation/P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md)。
- [x] 四窗口故障路径已实收：Worker 在窗口 0 后退出会让窗口 1 显式失败并删除
      32-KiB spool；独立 generation-bound cancel 会产生
      `capture_failed_restored`。两条路径均恢复 P201、删除 AGX/P201 临时数据且
      保持 capability false；见
      [`P201_MAMBA_BATCH_FAILURE_CANCEL_VALIDATION_2026-09-05.md`](validation/P201_MAMBA_BATCH_FAILURE_CANCEL_VALIDATION_2026-09-05.md)。
- [x] AGX 软件 acquisition overload 已完成：超 256-KiB 单点计划在接触 backend/
      射频前拒绝；128 个最大合法窗口共 32 MiB 实收，sequence 连续且 dropped、
      overflow、clipping、timeout、health/身份错误均为 0；IIO deadline 和 AGX
      连接中断均恢复，后续 generation 成功，资源有界且无 IQ 残留。见
      [`P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md`](validation/P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md)。
- [x] FPGA 聚合、MMIO、UIO、Vivado 和 `BOOT.bin` 已从当前路线退役。

### 还未完成

- [ ] 将当前已经实现和实收的 `integration_only` Target/profile/batch 合同升级为
      production profile；只有第5章冻结 `rf_preprocess_v1` 且新 checkpoint 准入
      后才能替换 admission，Planner 仍只能选择 candidate ID。
- [x] 已预注册并仅用 train 统计、完整 validation 伪会话和版本化 P201
      `receive_domain/unknown` 证据冻结 `rf_preprocess_v1` 重训合同：硬件重调谐、
      不做数字频移/额外滤波/重采样、保留 DC、四窗共享 RMS、4 × 1,024 连续窗和
      mean-logit；选择代码未加载 test，见
      [`RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md`](validation/RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md)。
- [x] 用户训练的 RF-aligned epoch-10 checkpoint 已独立下载、逐文件核验并在 AGX
      严格加载；完整 95,607 个 validation 四窗组 accuracy 与 4090 完全一致，NLL
      差 `6.8e-8`，test 未打开且 capability 保持 false。
- [x] 已实现并实收 RF-v1 shared-capture RMS/full-logit runtime：单次 4,096
      点共享 RMS、保留 DC、四窗顺序、FP16 autocast/FP32 常驻权重、每窗完整
      logits 和 AGX float64 mean-logit 后 softmax；冻结 golden hash 一致，来源/
      请求/session/哈希严格关联，成功、Worker 退出和取消均恢复并清理。见
      [`RF_V1_RUNTIME_PARITY_VALIDATION_2026-09-05.md`](validation/RF_V1_RUNTIME_PARITY_VALIDATION_2026-09-05.md)。
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
      lineage 泄漏；见 [`AMC_CORPUS_MANIFEST_V1.md`](reference/AMC_CORPUS_MANIFEST_V1.md)。
- [x] 已部署 AGX 应用自有的 P201 corpus SQLite/七文件包存储和 `接收语料` 页面；
      loopback-only 入口只接受当前 2.1 MS/s、1.5 MHz、50 dB、4,096-sample RX1
      profile，重新计算 IQ 功率/频谱/削顶并要求恢复与临时清理。一次 433.920 MHz
      实收以 `unknown` 入库，通过完整资产哈希校验和真实页面删除后又按同一内容
      恢复保留；见
      [`P201_RX_CORPUS_STORE_VALIDATION_2026-09-05.md`](validation/P201_RX_CORPUS_STORE_VALIDATION_2026-09-05.md)。

### 还未完成

- [x] 已按不可变 HDF5 `/X` 全局行、capture session 和 UTC 日期证明
      train/validation/test 隔离：两套完整 split 均全覆盖、内部无重复且两两交集为
      0；跨 P201 包审计会拒绝父级血缘改变和三类 group 泄漏，当前唯一
      `receive_domain/unknown` 行不进入准确率。见
      [`AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md`](validation/AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md)。
- [x] 已只用 train/validation 完成五种预处理与 1/2/4 窗、三种聚合消融，冻结
      四窗共享复数 RMS、保留 DC、4 × 1,024 和 mean-logit 作为重训合同；历史
      test 虽已存在，但本次工具拒绝加载 test 成员/结果。P201 `unknown` 的质量和
      置信度单独报告，未混入准确率。
- [x] 最终候选 checkpoint 已返回并完成 AGX FP32 全 validation parity；新温度
      `1.34647` 仅记录为 validation-only candidate，没有误冻结为生产参数。
- [x] 为 RF-v1 增加版本化语料派生/导入与独立标签证据接入：当前已安装入口仍
      固定 legacy profile 且仅写 `unknown`。复用已有合同/存储，保留旧包原始
      哈希；新记录严格关联原始 capture、profile/preprocess 和证据来源，继续
      支持人工删除，不把模型 top-1 或 `unknown` 理由转成独立标签。V1a 源码、
      采样规范和隔离 Web/HTTP/浏览器/删除验证完成；完整临时数据已清理，未部署。
      旧包缺失原始 request 报告时只能 unknown 派生，实际标签/覆盖仍属于 V1b。见
      [`RF_V1_EVIDENCE_V1A_VALIDATION_2026-09-06.md`](validation/RF_V1_EVIDENCE_V1A_VALIDATION_2026-09-06.md)。
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
      [`RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md`](validation/RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md)。
- [x] 已在最终 checkpoint 上按预注册门限比较 FP16/BF16/FP32 的完整 validation
      准确率、argmax/logits/probability 偏差、吞吐和显存；FP16 全部门限通过，
      固定为候选推理精度，BF16 因数值偏差淘汰，test 与生产能力仍保持关闭。见
      [`RF_V1_PRECISION_SELECTION_VALIDATION_2026-09-05.md`](validation/RF_V1_PRECISION_SELECTION_VALIDATION_2026-09-05.md)。
- [x] 已实现 epoch-10 FP16 四窗完整 logits、严格合同关联及 AGX mean-logit 聚合，
      完成 golden、故障/取消测试和 RX1 实收与清理；仍为 integration_only。
- [ ] 实现置信度校准与 noise/unknown/低质量/低置信度拒识，报告 rejection rate、
      false acceptance 和 calibration error；生产准入仍缺独立 known-RF/OOD 标签。
- [x] 将已有逐窗 logits/关联字段和 AGX mean-logit 结果汇入统一的
      `RecognitionObservation`，补齐 classified/rejected/unavailable/error、
      拒识原因和校准状态；只把有界摘要传给 Planner，完整记录保留在 AGX。
      S2 已通过 Rust/Node 合同测试和保留实收报告 replay，并清理临时数据；尚未
      部署；结果存储/归档 UI 已由 S6a 补上，工程 Runner 已由 S5 接入。见
      [`RECOGNITION_RESULT_S2_VALIDATION_2026-09-06.md`](validation/RECOGNITION_RESULT_S2_VALIDATION_2026-09-06.md)。
- [x] S1 health/profile/receipt 探测接口和候选失败关闭验证已完成；生产正向
      capability 仍须完整准入和 A1 部署证据。
- [ ] 实现 production Worker queue=1、整批 deadline、cancel/drop 指标、
      crash/restart 清理和持续 thermal soak。
  - [x] S3 生命周期源码及有限真实 epoch-10 Worker 验证完成：单活动批次/单等待位、
        整批与独立队列 deadline、取消确认、实例/generation 隔离、进程强杀/重启
        清理和指标；临时数据已清理。见
        [`WORKER_SUPERVISOR_S3_VALIDATION_2026-09-06.md`](validation/WORKER_SUPERVISOR_S3_VALIDATION_2026-09-06.md)。
  - [x] S4b：20 分钟代表性候选串行资源/时延/队列和 CPU/SoC/Tj 验收，
        GPU 温度缺失按用户明确豁免保持未测；缓存上限/清理完成。见
        [S4b 验证](validation/GPU_RESOURCE_S4B_VALIDATION_2026-09-06.md)。
  - [ ] A1：已准入生产部署；S3/S4b 未替换服务。
- [x] S4a：Spark 与 Mamba 同时常驻但活跃推理按 `Spark -> Mamba -> Spark`
      串行的源码及隔离实机验证完成；取消先回收实际子进程再释放共享租约，实例/
      generation 和连接隔离阻止迟到结果回流。共享启动/整批锁、双方强杀恢复、
      实际 Node Planner 和原生 Mamba replay 通过，临时数据已清理。见
      [`GPU_LEASE_S4A_VALIDATION_2026-09-06.md`](validation/GPU_LEASE_S4A_VALIDATION_2026-09-06.md)。
      生产服务未替换；S4b 资源验收已按用户 GPU 温度豁免完成，所有生产调用
      统一入 gate 仍属 A1。
- [ ] 部署可回滚的生产 Worker，并在冻结的频率/增益/session 矩阵上完成 RX-only
      端到端验收；只有全部准入门通过后才报告 `recognizer_available=true`。

## 第1—3章审计依据

- [`protocol.rs`](../raspberry-pi/sdr-agent/controller/src/protocol.rs) 的
  `RecognitionSummary` 已在 S2 替换为独立的四状态 `RecognitionObservation`，
  Rust/Node 同步严格校验；S5 已完成真实 Spark 回灌，生产部署留在 A1。
- [`runner.rs`](../raspberry-pi/sdr-agent/controller/src/runner.rs) 已通过 S1 实时探测
  生成 `recognizer_available`；S5 显式工程入口已实际执行，普通生产路径仍因
  未准入而拒绝，未配置工程执行器时不伪装执行成功。
- [`policy.rs`](../raspberry-pi/sdr-agent/controller/src/policy.rs) 已对
  `RunLocalRecognition` 要求人工批准，覆盖 step/automatic 两种模式。
- [`sdr-agent.rs`](../raspberry-pi/sdr-agent/controller/src/cli/console.rs) 的交互/
  巡航路径已接 S5 工程执行器、批准/预算和联合 stop；
  [`app.js`](../raspberry-pi/sdr-agent/web-console/public/app.js) 已有 S6a 归档结果
  渲染和删除，S5/S6b 已完成原生自动回灌和实际浏览器隔离闭环；未部署。
- [`sdrd_iio.c`](../sdr-system/sdrd/src/sdrd_iio.c) 固定启用
  `voltage0,1` scan pair，并只读验证 `voltage0` 的 `rf_port_select=A_BALANCED`；
  [`sdr.rs`](../raspberry-pi/sdr-agent/controller/src/sdr.rs) 对完整 RX1 身份失败关闭。

O1a 已完成故障/fuzz、审计轮转、只读健康/本地告警及升级回滚的源码/隔离验证，
生产配置未安装；见 [O1a 验证](validation/OPERATIONS_O1A_VALIDATION_2026-09-06.md)。
独立标签、校准/准入、A1 部署及 O1b 24 小时闭环仍按各自条件推进。

## 推进顺序入口

实际推进顺序仅维护在
[`SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md`](SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md)。
当前状态和各拆分单元的勾选以
[`SDR_AGENT_PROJECT_CHECKLIST.md`](SDR_AGENT_PROJECT_CHECKLIST.md) 为准。
本文不再重复旧排期表、未完成项的旧编号或另一套 S/V 依赖顺序。

## 历史已完成里程碑

这些编号仅保留完成证据，不作为当前排期：

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
- [x] C2a：最终 checkpoint 的完整精度选择已完成，沿用冻结 FP16。
- [x] C2b：RF-v1 runtime/golden/full-logit 和有限成功/失败/取消实收已完成。

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
