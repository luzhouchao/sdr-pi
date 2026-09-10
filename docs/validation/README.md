# 验证记录索引

此目录按需读取：索引仅提供链接，不默认展开实验记录或原始附件。

这里保存已经执行的验证及其当时的部署、失败和清理事实，不是当前待办表。
当前状态见[权威清单](../SDR_AGENT_PROJECT_CHECKLIST.md)，下一步见[推进顺序](../SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md)。
旧命令、旧地址、当时的“未部署/下一步”仅描述原验证时点；不能直接照历史记录重跑 RF、训练或格式化操作。

按主题定位，只打开需要的一组：

- [近期射频排查](#近期射频排查2026-09-09至10)
- [Agent、控制与部署](#agent控制与部署)
- [识别软件交付](#识别软件交付)
- [数据、预处理与模型历史](#数据预处理与模型历史)
- [B210/P201 诊断](#b210p201-诊断)
- [组件目录中的历史实验](#组件目录中的历史实验)
- [文档维护](#维护记录)

## 近期射频排查（2026-09-09至10）

后续实验频段见[当前选择](../SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md#后续实验选择)。
下列为历史实测入口；通过仅指该记录中的工程门，不能把旧计划直接重跑。

- [RadioML2018A全量脚本与有限先导](RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md)

- [P201 RX1负载→天线→负载：反向三阶段背景隔离与恢复](P201_TERMINATION_BACKGROUND_VALIDATION_2026-09-09.md)
- [P201 2.4GHz背景分布：三轮全段扫描与独立复测](P201_BACKGROUND_MAP_VALIDATION_2026-09-09.md)
- [P201 5GHz Wi-Fi中心背景抽样与独立复测](P201_WIFI5_BACKGROUND_VALIDATION_2026-09-09.md)
- [Agent历史1586轮宽频记录与当前背景对照](HISTORICAL_BACKGROUND_COMPARISON_2026-09-09.md)
- [3500MHz低增益弹簧天线单音：流程完成，信号门未通过](B210_3500_TONE_VALIDATION_2026-09-10.md)
- [3500MHz双端50Ω负载背景对照](P201_3500_TERMINATION_VALIDATION_2026-09-10.md)
- [3500MHz天线接回重发](B210_3500_RETRY_VALIDATION_2026-09-10.md)
- [3500MHz发射增益矩阵](B210_3500_GAIN_VALIDATION_2026-09-10.md)
- [3500MHz历史TX70/RX50对照](B210_3500_TX70_RX50_VALIDATION_2026-09-10.md)
- [切回2440MHz原增益对照](B210_2440_RETURN_VALIDATION_2026-09-10.md)
- [2440MHz换天线后单音通过](B210_2440_ANTENNA_CHANGE_VALIDATION_2026-09-10.md)
- [433MHz天线单音与背景](B210_433920_ANTENNA_VALIDATION_2026-09-10.md)

## Agent、控制与部署

- [普通对话展示修复](HOLD_REPLY_DISPLAY_VALIDATION_2026-09-08.md)
- [首次扫描混合选参](SURVEY_PARAMETER_ASSIST_VALIDATION_2026-09-08.md)
- [本地 Planner 修复](LOCAL_PLANNER_REPAIR_VALIDATION_2026-09-08.md)
- [Web 界面重构](WEB_UI_REDESIGN_VALIDATION_2026-09-07.md)
- [新版网页日常 RX 使用验收](DAILY_RX_USE_VALIDATION_2026-09-08.md)
- [非模型运维配置部署](OPERATIONS_RX_DEPLOYMENT_VALIDATION_2026-09-08.md)
- [Web 后台升级与会话恢复验收](WEB_RECOVERY_UPGRADE_VALIDATION_2026-09-07.md)
- [AGX Agent framework validation - 2026-09-01](AGX_FRAMEWORK_VALIDATION_2026-09-01.md)
- [IIO refill 合同修复：异常长度失败关闭，尚无历史RF根因结论](IIO_REFILL_CONTRACT_VALIDATION_2026-09-07.md)
- [P201 → AGX receive-profile validation (2026-09-02)](P201_AGX_RX_PROFILE_VALIDATION_2026-09-02.md)
- [P201 → AGX bounded software-acquisition overload validation (2026-09-05)](P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md)
- [P201恢复健康检查兼容修复 — 2026-09-07](P201_RECOVERY_HEALTH_VALIDATION_2026-09-07.md)
- [P201 RX1 fixed-input identity validation — 2026-09-04](P201_RX1_INPUT_IDENTITY_VALIDATION_2026-09-04.md)
- [P201 RX-only corpus store validation — 2026-09-05](P201_RX_CORPUS_STORE_VALIDATION_2026-09-05.md)
- [P201 RX1/RX2 可选接收：源码、实收恢复与部署完成](P201_RX_PORT_SELECTION_VALIDATION_2026-09-07.md)
- [树莓派早期部署与验证合订记录](PI_BASELINE_HISTORY.md)
- [SDR Agent AGX inline-IQ results validation](SDR_AGENT_AGX_INLINE_RESULTS_VALIDATION_2026-09-01.md)
- [AGX RX ownership cutover validation — 2026-09-03](SDR_AGENT_AGX_RX_OWNERSHIP_CUTOVER_VALIDATION_2026-09-03.md)
- [Automatic `survey_band` live validation](SDR_AGENT_AUTOMATIC_SURVEY_VALIDATION_2026-09-01.md)
- [Candidate inspection and observation-restart live validation](SDR_AGENT_CANDIDATE_INSPECTION_VALIDATION_2026-09-01.md)
- [Complete-loop fault and recovery validation — 2026-09-03](SDR_AGENT_COMPLETE_LOOP_FAULT_RECOVERY_VALIDATION_2026-09-03.md)
- [SDR execution metadata and IIO-timeout validation — 2026-09-03](SDR_AGENT_EXECUTION_METADATA_TIMEOUT_VALIDATION_2026-09-03.md)
- [Initial-survey settings and fixed-gain live validation](SDR_AGENT_INITIAL_SURVEY_SETTINGS_VALIDATION_2026-09-01.md)
- [Stateless one-shot survey and inspection validation — 2026-09-03](SDR_AGENT_ONESHOT_SWEEP_INSPECTION_VALIDATION_2026-09-03.md)
- [P201 persistent Dropbear host-key validation — 2026-09-03](SDR_AGENT_P201_PERSISTENT_HOST_KEY_VALIDATION_2026-09-03.md)
- [SDR Agent visible reply and bounded-IQ compatibility validation](SDR_AGENT_REPLY_AND_CAPTURE_COMPAT_VALIDATION_2026-09-01.md)
- [P201 SDRD 30-minute reconnect and fault-recovery validation — 2026-09-03](SDR_AGENT_SDRD_LONG_RECONNECT_FAULT_RECOVERY_VALIDATION_2026-09-03.md)
- [P201 SDRD startup and recovery validation — 2026-09-03](SDR_AGENT_SDRD_STARTUP_RECOVERY_VALIDATION_2026-09-03.md)
- [SDR Agent single-operator session validation — 2026-09-03](SDR_AGENT_SINGLE_OPERATOR_SESSION_VALIDATION_2026-09-03.md)
- [SDR Agent bounded terminal-session resume validation — 2026-09-03](SDR_AGENT_TERMINAL_SESSION_RESUME_VALIDATION_2026-09-03.md)
- [SDR Agent terminal streaming-input validation — 2026-09-03](SDR_AGENT_TERMINAL_STREAMING_INPUT_VALIDATION_2026-09-03.md)
- [Spark-X2.5 AGX Planner integration validation — 2026-09-02](SPARK_X25_AGX_INTEGRATION_VALIDATION_2026-09-02.md)
- [Spark-X2.5 bounded web-search validation — 2026-09-02](SPARK_X25_WEB_SEARCH_VALIDATION_2026-09-02.md)
- [Single SDR Agent CLI — 2026-09-07](UNIFIED_CLI_VALIDATION_2026-09-07.md)

## 识别软件交付

- [S4a shared GPU lease validation — 2026-09-06](GPU_LEASE_S4A_VALIDATION_2026-09-06.md)
- [S4b 资源诊断与候选缓存修正 — 2026-09-06](GPU_RESOURCE_S4B_VALIDATION_2026-09-06.md)
- [O1a 故障、日志与运维验证 — 2026-09-06](OPERATIONS_O1A_VALIDATION_2026-09-06.md)
- [S6a recognition archive validation — 2026-09-06](RECOGNITION_ARCHIVE_S6A_VALIDATION_2026-09-06.md)
- [S2 recognition result and Planner observation — 2026-09-06](RECOGNITION_RESULT_S2_VALIDATION_2026-09-06.md)
- [Recognizer admission and approval gate (S1) — 2026-09-06](RECOGNIZER_ADMISSION_S1_VALIDATION_2026-09-06.md)
- [S5 Runner 识别执行、联合 stop 与 Spark 回灌验证](RUNNER_RECOGNITION_S5_VALIDATION_2026-09-06.md)
- [S6b 真实闭环浏览器验收 — 2026-09-06](WEB_RECOGNITION_S6B_VALIDATION_2026-09-06.md)
- [S3 Worker lifecycle validation — 2026-09-06](WORKER_SUPERVISOR_S3_VALIDATION_2026-09-06.md)

## 数据、预处理与模型历史

- [RML2018.01A 用户指定名称映射](RML2018A_LABEL_MAPPING_VALIDATION_2026-09-08.md)
- [AGX AMC-Mamba D8 离线部署与完整测试集验证 — 2026-09-04](AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md)
- [AGX Spark/Mamba resource and Planner validation — 2026-09-04](AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md)
- [AMC corpus contract validation (2026-09-05)](AMC_CORPUS_CONTRACT_VALIDATION_2026-09-05.md)
- [AMC split isolation validation — 2026-09-05](AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md)
- [P201 → AGX AMC-Mamba 实验性端到端验证 — 2026-09-04](P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md)
- [P201 → AGX seed44 四窗口联调验证 — 2026-09-04](P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md)
- [P201 Mamba 四窗口失败与取消验证 — 2026-09-05](P201_MAMBA_BATCH_FAILURE_CANCEL_VALIDATION_2026-09-05.md)
- [RF-aligned D8 checkpoint AGX validation — 2026-09-05](RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md)
- [RF preprocessing v1 validation-only selection — 2026-09-05](RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md)
- [V1a RF-v1 evidence tools and sampling validation — 2026-09-06](RF_V1_EVIDENCE_V1A_VALIDATION_2026-09-06.md)
- [RF-v1 inference precision selection — 2026-09-05](RF_V1_PRECISION_SELECTION_VALIDATION_2026-09-05.md)
- [RF-v1 runtime parity validation — 2026-09-05](RF_V1_RUNTIME_PARITY_VALIDATION_2026-09-05.md)

## B210/P201 诊断

- [单1024点源逐点对照：背景突发、载波相关分量与相位变化](B210_1024_POINTWISE_VALIDATION_2026-09-06.md)
- [2455 MHz同源对照：一组通过固定门并识别为ID0，全矩阵仍失败](B210_2455_MARGIN_VALIDATION_2026-09-07.md)
- [背景频率对照：2455 MHz较轻，但独立确认未达门槛](B210_BACKGROUND_VALIDATION_2026-09-07.md)
- [来源关联 v2 工具完成，候选判据合成验收未通过](B210_CENTERED_SOURCE_VALIDATION_2026-09-06.md)
- [失败组误差分解：简单相位/频差/时延不足以解释，宽带污染是排查重点](B210_FAILURE_DECOMPOSITION_VALIDATION_2026-09-07.md)
- [LO 偏移实收：主要载波失真定位到发射端 LO 相关泄漏](B210_LO_OFFSET_VALIDATION_2026-09-06.md)
- [本振泄漏在工程输入链路中已抑制，背景门仍失败](B210_LO_REJECTION_VALIDATION_2026-09-07.md)
- [24 类三样本 B210/P201 对照验证 — 2026-09-07](B210_MULTICLASS_VALIDATION_2026-09-07.md)
- [B210 → P201 → RF-v1 实收重放接入验证](B210_P201_RF_V1_PILOT_VALIDATION_2026-09-06.md)
- [B210/P201 40 dB 对照与同源 IQ 模型比较](B210_P201_RX40_PAIRED_VALIDATION_2026-09-06.md)
- [多类实收剩余错误、逐点 IQ 与源端基线核对 — 2026-09-07](B210_RESIDUAL_VALIDATION_2026-09-07.md)
- [新天线接回RX1：三组固定窗口源匹配通过，背景门失败，分类未测](B210_RX1_NEW_ANTENNA_VALIDATION_2026-09-07.md)
- [B210/P201 复偏置双向探索（来源门失败）](B210_RX_AFFINE_VALIDATION_2026-09-06.md)
- [RX 字节审计：未发现简单重复/补零，连续性仍不能由状态字段证明](B210_RX_BYTE_AUDIT_VALIDATION_2026-09-07.md)
- [B210/P201 实收保真度与补偿对照验证](B210_RX_FIDELITY_VALIDATION_2026-09-06.md)
- [同源 IQ 频差、相位与加噪敏感性验证](B210_SOURCE_SENSITIVITY_VALIDATION_2026-09-06.md)
- [来源关联 v3：旧错源误拒解决，窄带停发门仍未通过](B210_SOURCE_V3_VALIDATION_2026-09-06.md)
- [来源关联 v4：带宽相关停发门与独立合成验收通过](B210_SOURCE_V4_VALIDATION_2026-09-06.md)
- [B210/P201固定v4实收：出现短时扰动，来源门失败，未运行模型](B210_V4_LIVE_VALIDATION_2026-09-06.md)
- [NX B210 与 AMC-Mamba D8 资产交接](NX_B210_MAMBA_D8_ASSET_HANDOFF.md)
- [NX B210 RF A 到 P201 RX1 链路验证 — 2026-09-04](NX_B210_P201_RX1_LINK_VALIDATION_2026-09-04.md)
- [NX B210 → P201 RX1：2.440 GHz 延长回放验证](NX_B210_RML_2440_EXTENDED_VALIDATION_2026-09-06.md)
- [NX B210 RML2018A → P201 2.440 GHz 有限验证](NX_B210_RML_2440_VALIDATION_2026-09-06.md)

## 组件目录中的历史实验

保留原目录以维持源码引用与历史命令的上下文；这些是当时记录，不是当前部署或待办。

- [P201 系统基线](../../sdr-system/docs/BASELINE_2026-08-31.md)
- [SDRD shadow 验证](../../sdr-system/docs/SDRD_SHADOW_VALIDATION_2026-08-31.md)
- [SDRD controlled 接口验证](../../sdr-system/docs/SDRD_CONTROLLED_INTERFACE_VALIDATION_2026-08-31.md)
- [SDRD IIO Adapter 验证](../../sdr-system/docs/SDRD_IIO_ADAPTER_VALIDATION_2026-08-31.md)
- [早期个人部署记录](../../sdr-system/docs/SDRD_PERSONAL_DEPLOYMENT_2026-09-01.md)
- [Pi Rust/libiio 测试结果](../../raspberry-pi/p201pro-rust/TEST_RESULTS.md)
- [Pi FFT 测试结果](../../raspberry-pi/p201pro-rust/FFT_BENCH_RESULTS.md)

## 维护记录

- [CodeGraph本地初始化与CLI/MCP验收](CODEGRAPH_INITIALIZATION_2026-09-10.md)
- [文档删并、迁移和链接验证](DOCS_CONSOLIDATION_2026-09-07.md)
