# 清洗数据SSD导入与12模型识别接入（2026-09-14）

已完成外接盘raw/guard HDF5的SSD复制、12份模型严格加载与GPU前向、筛选和进度/绘图接入，
并启动后台36组工程识别。**本记录是启动验收，不是全量结果完成报告。**
操作与结果路径见[说明](../reference/RML2018A_MODEL_COLLECTION_EVALUATION.md)，
原始证据见[复制审计](../evidence/RML2018A_CLEAN_SSD_IMPORT_2026-09-14.json)和
[接入/启动审计](../evidence/RML2018A_CLEAN12_EVALUATION_2026-09-14.json)。

## 实际数据与选择

两份HDF5各21,526,064,941字节，共43,052,129,882字节，复制约656.9秒；
源端流式SHA-256、用户清单和SSD逐文件读回一致。两个源文件及原清单仍在外接盘。
原始RML2018A复用本地21,449,148,312字节文件，完整SHA-256与原冻结身份一致。
复制服务正常退出，无partial文件残留。数据放在Git忽略的应用存储，不写入Git。

三组源行号、标签和源SNR全量对应，RX class_names与server-v1一致。
根据用户追加要求，仅对raw/guard的`usable & strict_quality_pass`行推理，已做选择的行号集合登记：

| 数据 | 推理样本 | 跳过 | 共同源行子集 |
| --- | ---: | ---: | ---: |
| 原始source | 2,555,904 | 0 | 2,462,264 |
| clean raw | 2,530,590 | 25,314 | 2,462,264 |
| clean guard | 2,473,498 | 82,406 | 2,462,264 |

raw跳过行的条件SINR状态/有限值未通过；guard有41,392行未应用相消，42,846行条件SINR状态/有限值未通过，
这些失败原因可能重叠，不能直接相加。主准确率按各组实际推理分母计算，共同源行子集另报，
未通过行不进入模型；不删除原始文件中的行或伪造预测。三份metadata.npz保留全行质量标志、源行号及选择mask。
清洗文件raw/guard均已有逐1024点窗的复数RMS归一化；读取时不重复归一化。source保留原始值。

## 代码与验证

- 独立工程入口`rml2018a_model_collection_eval.py`直接读取三份HDF5，沿用服务器结构/原权重；
  不改绑旧RF-v1 Worker，不恢复已删epoch-010，不开放生产识别。
- 12份模型CPU strict load、参数数量及实际后端完全匹配；MAMC确认为Mamba1、D8为Mamba2，没有GRU替身回退。
- 7项合同测试通过：源行重排/重复、标签错配、质量位不一致、输入非有限值与合格行筛选、共同集合按源ID对应、
  混淆矩阵方向/分母，以及连续分块→落盘读回→无重复推理续跑→身份篡改拒绝。
- 最新GPU先导只从三域各自合格集合固定取64行，每模型192行比较FP32/FP16，并执行1024大批量检查。
  12模型最终全部采用FP32，关闭TF32；最终大批量概率最大偏差约2.31e-7至4.08e-6，先导top-1批量变化均0。
  这是有界数值校验，不声称所有样本或跨平台bitwise相同。
- 原`rml2018a-progress.sh`默认改看本轮，实际`--once`已验证合格分母、跳过、已计算/已落盘；
  显式指定旧四窗root仍显示原完成进度，Ctrl+C只退出查看。
- 系统Matplotlib实际生成并检查了独立合成矩阵的PNG/SVG与CSV，轴方向、24类标签、行百分比和分母显示通过。
  推理结束后自动生成真实36张矩阵及共同子集CSV；当前尚无本轮全量真实图。

## 保留的失败与修正

初版按当时全行策略做探针，MAMC FP16出现非有限logits，未开始全库识别；
用户追加严格质量选择后，CNN2的FP16大批量概率偏差0.00755又触发门限拒绝。
没有放宽数值门或删掉难例；改为记录FP16失败并使用通过的FP32，最终12模型均通过。
这些探针是数值检查，不用于挑选更高真实ACC的精度；不读取真实标签选择计算精度。
模型venv未安装Matplotlib，首次绘图依赖检查失败；改用现有系统Python绘图，模型环境保持。
旧计划、失败、最终数值探针及独立strict-load审计均保留，最新计划记录其父级身份。

## 后台状态与保留

服务`sdr-rml2018a-clean12-eval-20260914.service`已实际进入running并写出CNN2 source预测块。
首3个实写块49,152条的SHA-256、源行索引、logits形状/有限值和argmax已独立读回检查通过。
36组总预算90,719,904次预测，GPU批量1024，CPU预取16,384个文件行并筛选后送GPU；
同一模型连续处理三数据组。原始IQ不再复制进结果根。
先导粗估计算约59.4小时，尚非稳定吞吐实测；单次有限期限设为96小时，保留3GiB磁盘余量门。
后台运行无需对话持续轮询；本次不等待数天结果、不宣称完整运行已通过。

结果根`/home/jetson/sdrharness/local-assets/amc-eval/results/clean12-single-20260914`仍活动，
plan/probe/共享metadata及每块SHA-256凭据用于续跑；最终读回核验、summary.csv、plots.json、
retention.json及COMPLETE.json由脚本在相应阶段生成。哈希/身份不符必须停止。
缓存只在该结果根对应的`/var/tmp/sdrharness-dev/rml2018a-collection-cache-172de8ace7cff7a7`，
后台退出后由finally清理；不能把活动缓存说成已清理。

SSD副本保留清单为其根下retention.json；复制审计根
`/var/tmp/sdrharness-dev/rml2018a-clean-import-20260914`保留5文件6,242字节，另加自身retention。
接入审计根`/var/tmp/sdrharness-dev/rml2018a-clean12-eval-20260914`的精确保留/删除数量、字节及哈希见
其retention.json和Git启动证据；合成绘图样例已精确删除，模型/数据及历史识别结果保留。
各根retention均给出精确人工删除命令；活动推理结果/缓存须先停止所属任务，不清理共享父目录。

## 用户暂停与seed42原验证集核对

用户随后要求仅使用seed42的8种模型，并明确“先暂停现在的识别”。已停止原服务，
MainPID=0；SIGTERM按runner的InterruptedError退出，systemd标为failed/exit1是本次人工暂停，
不是新增数据或模型失败。运行缓存已清理，源数据/权重保持；29块475,136条CNN2 source结果
逐块SHA-256复核后保留。STOP和PAUSED.json阻止旧范围自动续跑，原进度脚本明确显示暂停。
只记录下一模型选择，没有启动8模型的新识别或重跑GPU探针。

通过connect-4090-server既有Aliyun SSH只读取得
`/data/lzc/mamba/datasets/RML2018a_split_seed42_tr700_val150_te150.npz`，
保存到`/home/jetson/sdrharness/local-assets/amc-eval/splits/server-seed42-20260914/`同名文件。
3,906,318字节，源端与本地SHA-256均为
`0a7cbd3b8a4b921b7dc3d0c37473322207c6bd9fb362ea58498c851fad9dc5a3`。
文件实际seed42/比例0.7、0.15、0.15；train1,789,132、val383,385、test383,387。
已核对三个索引数组无重复、无跨集合重叠且完整覆盖原2,555,904行；8份seed42模型配置
均引用同名划分文件。无需重新随机切分，原val数组的成员与顺序可以直接复用。

按全量已核对的source_row映射及当前usable/strict质量mask，得到：

| 输入 | 原validation成员 | 可识别 | 因质量跳过 |
| --- | ---: | ---: | ---: |
| source | 383,385 | 383,385 | 0 |
| raw | 383,385 | 379,662 | 3,723 |
| guard | 383,385 | 371,108 | 12,277 |

三组共同合格369,497源行。不能在接收文件当前位置重新shuffle或按前15%取样；
复用原val成员后再按质量排除。精确索引复用不保证跨AGX/4090的浮点结果逐位一致，
更不保证经过RF链路的准确率与服务器一致。仍属validation对照，不改写原test划分。

[暂停/划分证据](../evidence/RML2018A_SEED42_PAUSE_2026-09-14.json)保存原计划保留边界、
val索引哈希、分组数量、split与审计retention；本单元无新推理/RF/训练，无临时传输包。
仅保留原NPZ和最小暂停/块收据清单，精确人工删除路径见各自retention.json。
