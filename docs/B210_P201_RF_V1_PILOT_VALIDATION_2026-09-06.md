# B210 → P201 → RF-v1 实收重放接入验证

基线 b99a85f6b83ceb75dffde98112b12bc008200a44；分支
`codex/recognizer-amc-offline-validation`。预登记见
[本轮计划](B210_P201_RF_V1_PILOT_PLAN_2026-09-06.md)，有界证据见
[审计 JSON](B210_P201_RF_V1_PILOT_AUDIT_2026-09-06.json)。

## 结论与失败边界

**实收 IQ → RF-v1 四窗推理 → S2/S6a 归档 → V1a 父包/派生 → 删除的隔离接入通过；
本轮 RF 停发对照验收失败。** 只有一次注册发射，后续 `--replay-only` 不发射、不采样。
停发后 Controller 返回 `summary_clipped` 并清理未完成采样，未保留该次 IQ/完整报告；
不重建缺失对照，不降低增益重试，不把“接入通过”写成“无线链路验收通过”。原始
pilot-summary 的失败和离线重放的成功分开保留 hash、状态及清理证据。

B210 串号 2508504，NX 上 UHD 4.1.0.5-3、RF A/TX-RX/channel 0；2.440 GHz、
2.1 MS/s、1.5 MHz、TX gain 70 dB、复数峰值 0.2。实际送入 FIFO 168000000 bytes /
21000000 样本，feed 9.965236 秒，UHD 正常退出但日志仍有末尾 `S`；不能声称无序列异常。
P201 固定 RX1/RX0/A_BALANCED，RX gain 50；计划四次 RX 上限 802804 bytes，
AGX 开始时可用 808034959360 bytes。成功保存前三次共 540664 bytes；末次失败。

| 接收用途 | sequence | 样本数 | 实际中心 Hz | 结果 |
| --- | ---: | ---: | ---: | --- |
| 停发前 | 242 | 65535 | 2440000000 | 完成、无丢样/溢出/削顶 |
| 发射中精查 | 243 | 65535 | 2440000000 | 完成、谱估计中心 2440003332 Hz |
| 发射中模型窗 | 244 | 4096 | 2440003332 | 完成、无丢样/溢出/削顶 |
| 停发后 | 无已接受报告 | 上限 65535 | 计划 2440000000 | `summary_clipped`，对照缺失 |

模型窗 IQ SHA-256：`ecd04eaf935610914c48b68f3485612f7e9879bdc11d2d32b7ac74ae7824385c`。
精查与模型窗独立 generation/sequence，原始接收时间相隔 3882 ms，符合冻结目标新鲜度。

## 来源关联与模型结果

源仍是已经查看的四个 RML2018A train 行 102400/102401/102403/102404，标称数字 ID 0。
源 tile SHA-256 为 `c95ac58c1fd91ef4da992622dbdf70a9bc5884d0941419083451473a052f534e`。
source-only 诊断先于打开模型结果：仅按已知 LO 差和源 99% 能量频带分析，不把滤波
输入交给模型，也未重新测量/校正剩余 CFO。每个4096窗取最佳循环包络相关，停发前
15 窗范围 0.1118–0.1426，发射中精查15窗 0.1304–0.3443，模型窗 0.2624。
这些探索值存在低相关及范围重叠，又缺停发后对照，不能据此宣称本轮来源匹配验收通过。
本诊断与历史采用固定 lag 的指标不同，不直接比较大小或复用历史通过结论。

冻结 epoch-10 / FP16 autocast + FP32 权重 / RF-v1 原样使用；4096原始点共享 RMS、
顺序四个1024窗，未为提高本例结果添加源滤波、重采样或 CFO 预处理。
四窗实验预测为 16/17/16/18，mean-logit top-1 为 **18**，未校准概率 0.886660，
与源标称 ID 0 不一致；agreement=0.25，累计 inference 181103 µs。
这不是分类准确率测量，也不是独立标签。完整输出转为 S2 后 observation 正确保持
`status=unavailable`、`reason=production_admission_missing`、`class=null`、无校准置信度。
内部实验数字 ID 保留、文本名称 provisional；原始 observed_at=1788687435851 ms，
没有用晚于采集的重放时间刷新它。Planner observation 没有 IQ 路径、张量或完整 logits。

## 接口与实际存储证据

新增 Controller `received_window::prepare` 和独立 example `recognize-received-window`。
输入是一个最多64 KiB 的 ReceivedWindow JSON，含精查/采样原生计划和报告、原始接收
时间、candidate/request、直接子文件名及原始 IQ hash。要求固定 RF-v1、软件聚合
backend v1、不同递增 generation/sequence、合法采样参数/固定 RX 身份；读取私有、
owned、非符号链接、单 hardlink 的16384字节文件，复算同一 IQ 的频谱/功率/削顶并比对。
复用现有 `build_model_ready_batch`、S3 Supervisor 和 S2 转换。`--validate-only` 不推理。

这是可信本地原生报告的工程重放入口；文件 hash/字段一致性不构成物理采样的密码学
证明。入口不具有生产准入或独立标注权限。S6a origin 为 `experimental_replay`，不冒充
新采样或 synthetic fixture。原始报告里的已删除 SigMF staging descriptor 在语料提交
投影中变为 null；原报告与投影各自留 hash，原始采样字段未改写。离线导入的
preflight 空间值是在接入前重新检查；采样前的空间值另存于本轮原始审计。

私有 Web/SQLite/corpus 实际运行，无 Planner 控制会话：识别归档 id=1，默认不留 IQ；
legacy 父包 `p201-b210-pilot-1788687357694-244` 与 RF-v1 子包同名加 `-rf1`，
原始 IQ SHA 相同，raw.iq 共享 inode，保留父级 manifest/IQ hash。导入后确认
receive_domain/unknown、1 unique capture、1 session/day、0 evaluation records、
分组冲突为0。通过既有 DELETE API 删除两个包及归档，列表为空。

外部 TX tile/group 与采样关联保存在有界 source-link 审计；本单元没有新增独立标注
账本或改变 V1a 包格式。重复 tile、train 来源、已经查看模型结果的本 session/day
均只用于 receive_domain；将来独立采样必须另行登记来源/盲审/分组，不能把本轮
相关、模型预测或 unknown 理由转换为标签。V1b/V3a/V2/V3b/A1 均未完成，
`recognizer_available=false`，没有读取 locked test、训练、冻结温度/拒识阈值或替换服务。

## 测试与清理

Controller 全套 118 passed、1 ignored；补充最终 received-window 测试通过，覆盖原始
字节篡改、错误 hash、过期/零时间、sequence、源/采样 RX 身份、backend、越级路径、
频谱不一致、hardlink、symlink、非私有文件拒绝。Clippy all-targets `-D warnings`、
Rust fmt、Python AST 检查通过；既有 B210 FIFO/有限发送/来源诊断8项测试通过（fake
UHD，无额外 RF 发射）。已有 live/replay 结果存在时两个入口均在接触设备前拒绝重复执行。

实机失败路径与离线成功路径均完成进程停止和无线电恢复。P201 sdrd PID 17136/hash
`77d98a005305a4b7531fc3f133e9b4af521e60b065b29fcc304b4c7db80c45ae` 不变；恢复
RX LO 5985999996 Hz、rate 30720000、BW 30000000、manual gain60、A_BALANCED，
所有 scan/buffer enable 为0。这是恢复原有 RX 状态，TX 始终只有2.440 GHz。
最终精确清理已验证，见审计 JSON 的 `final_feature_cleanup.verified=true`。
只清理 AGX/NX `/var/tmp/sdrharness-dev/b210-pilot-906a/` 和本轮四个 P201 transient
路径；未删用户结果/语料，未改变其他项目已暂停的采集状态。GPU 温度沿用用户豁免，
仍未测，本轮不新增热稳定性结论。
