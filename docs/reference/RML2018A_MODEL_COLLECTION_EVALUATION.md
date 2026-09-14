# 12份权重与三份数据的单窗工程识别

当前已按用户要求暂停，原36组未完成，475,136条CNN2 source预测保留；旧计划STOP不得自动移除。
后续只保留seed42的8个模型。服务器原seed42验证集383,385条已经取回核对，raw/guard合格成员
379,662/371,108，共同369,497；新范围尚未接入或启动。见[暂停与原始划分](../validation/RML2018A_CLEAN12_EVALUATION_2026-09-14.md#用户暂停与seed42原验证集核对)。
以下36组命令/预算描述暂停前的运行，不能照旧计划续跑。


用户2026-09-14明确授权36组对照：每份权重分别识别原始RML2018A、外接盘清洗raw和guard，
每份文件2,555,904条，每条独立1024点；按用户最新要求跳过raw/guard未通过严格校验的行，
共90,719,904次预测。不做四窗聚合或训练。
权重身份见[模型集合](RML2018A_MODEL_COLLECTION.md)，实际启动/验证见
[验证记录](../validation/RML2018A_CLEAN12_EVALUATION_2026-09-14.md)。

## 数据与预处理

AGX本地SSD数据根：`/home/jetson/sdrharness/local-assets/amc-eval/datasets/rml2018a/`。

| 分组 | 根下路径 | 模型输入 |
| --- | --- | --- |
| source | `RML2018a.hdf5` | 原始`X [N,1024,2]`转置为`[N,2,1024]`，原值保留 |
| raw | `rx-clean-20260914/RadioML2018A_RX_raw_1024_per_window_RMS_v1.h5` | 直接读`iq [N,2,1024]` |
| guard | `rx-clean-20260914/RadioML2018A_RX_guard_1024_per_window_RMS_v1.h5` | 直接读`iq [N,2,1024]` |

两份RX文件已经逐窗复数RMS归一化，不重复归一化。raw已同步并校正CFO/相位；
guard使用保护间隔LO相消后的载荷，拒绝相消的帧保留原载荷并带标志。这里的raw不是未处理ADC字节。
文件保留全部源行，是带血缘和质量标志的整理格式；不因“clean”名称就删去失败或低质量样本。
实际仅推理usable与strict_quality_pass同时为true的行：raw 2,530,590条（跳过25,314），
guard 2,473,498条（跳过82,406）；文件保留全部行，不删除IQ。原始source仍2,555,904条全量。

入口核对`source_row`为完整唯一行号集合，并逐行核对原始Y/Z与`class_id/source_snr_db`，
保留raw/guard SINR、质量标志和guard_applied。分组用源SNR，不把条件SINR当作真值。
三组结果均可按source_row对应；RX顺序可能与原始HDF5顺序不同。
主分母各用实际通过校验的样本数，跳过原因/数量单列；
额外按共同通过校验的2,462,264个source_row报告三组可比结果。原始/RX幅度预处理不同，结果含预处理和RF链路影响，
不能把准确率差全部归于硬件；此比较包含历史训练成员，不作为独立测试集成绩。

## 操作与输出

使用既有`local-assets/amc-eval/runtime/venv/bin/python -B`运行
`jetson-agx/sdrharness/scripts/rml2018a_model_collection_eval.py`：

- `prepare --root <新结果根>`：核验模型代码/权重/数据哈希、标签及血缘，保存有限计划与共享元数据。
- `probe --root <结果根>`：12模型strict load与真实后端校验，仅在三域符合选择条件的固定样本上比较FP16/FP32，验证1024批量。
- `run --root <结果根>`：按照探针记录的精度执行36组；有有效凭据的块校验后跳过，单模型驻留。
- `verify --root <结果根>`：只读回预测文件，核对哈希、argmax、完整分母及独立重算混淆矩阵。

实际结果根：`/home/jetson/sdrharness/local-assets/amc-eval/results/clean12-single-20260914`。
每模型数据组保存合格行的完整FP32 logits、数据集行号和类别，按16,384个文件行扫描写块、GPU每批1024条；预取下一块。
不重复存IQ，源行号/真实类别/SNR/SINR/质量信息在三个共享metadata.npz中。
`*-summary.json`记录实际合格分母及共同通过校验的子集、26档混淆矩阵与每档准确率。
预测完成后自动生成`summary.csv`、`verification.json`及36张混淆矩阵（PNG/SVG、计数/比例CSV）；
共同通过校验的样本另有common-counts CSV，最后才生成`COMPLETE.json`。仅存在部分文件不表示全量完成。

查看进度：

```bash
/home/jetson/sdrharness/jetson-agx/sdrharness/scripts/rml2018a-progress.sh
```

直接停止：`systemctl --user stop sdr-rml2018a-clean12-eval-20260914.service`，
或在精确结果根建立`STOP`文件。当前进程有限96小时，检查磁盘至少余3GiB，进程锁拒绝同根双开。
原进度脚本默认查看本轮，可用`--once`只看一次；显式`--root`仍能查看旧单窗/四窗历史。
它展示合格总量、跳过数量、共同子集、已计算/已落盘、36组完成数及绘图进度。
这轮最终12模型全部使用FP32，TF32关闭；先导粗估约59.4小时，未当作已验证全库耗时。
系统Python负责绘图，模型venv不新增绘图库。
探针和运行均不修改旧Worker/profile或生产识别状态。实际执行精度、版本和时间存于probe/plan。
后续续跑前核对停止原因，不能绕过哈希、标签、数值或预算失败。

删除入口：确认无任务使用后，仅删除精确`clean12-single-20260914`结果目录；
这不会删除共享权重和数据。SSD副本另有`rx-clean-20260914/retention.json`，
其源外接盘及原始RML2018A均保留，不能扩大删除到共享父目录。
