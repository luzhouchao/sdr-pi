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

## seed42原验证集8模型启动

用户明确“使用验证集跑这8个模型”，随后进一步要求“直接重新从头开始”“把之前的删了”。
按最终指令停止此前新validation服务，删除旧全量`clean12-single-20260914`与首次复用validation
`seed42-val-single-20260914`两根：共314文件467,835,397字节。逐路径/大小/SHA登记后删除，
核验两根不存在；权重、SSD HDF5与split保持。只保留小型计划/数值探针及删除清单作审计，
不保留旧预测副本。此前复用71,495行的尝试属于已删除历史，不进入最终结果。

最终根`/home/jetson/sdrharness/local-assets/amc-eval/results/seed42-val-fresh-20260914`，
prepare-validation --fresh从原HDF5重新生成共享metadata。启动前确认没有模型预测目录/块或reuse.json，
reused_predictions=0。原NPZ val383,385源行及排序保持；RX按source_row映射并取严格合格交集，
source/raw/guard分别383,385/379,662/371,108，共同369,497，总预算9,073,240。
实际全量metadata核对证明train/test选中0，validation_rank逐条还原原val数组。

10项合同测试通过：原val成员及RX重排映射、训练/test排除、错seed/集合交叉拒绝、
动态8模型×3输入完整收口、断点续跑与读回统计，以及不依赖旧metadata/预测的fresh准备。
相同8模型的FP32数值依据已验证，不重新挑精度或重跑GPU探针；实际加载仍校验权重、结构及真实后端。
识别预测全部新算，继承数值验证记录不等于复用预测。FP32/关闭TF32及1024批量保持。

最终服务`sdr-rml2018a-seed42-val-fresh-20260914.service`已实际启动并从0写出新val预测块。
首3个新块7,474条已核对SHA-256、原val行号、有限logits及argmax，收据不含旧预测复用字段。
24组/24张真实矩阵尚未全部完成，不能提前勾选。先导粗估约8.1小时；内部24小时期限、
服务清理余量、3GiB空间门、STOP和单实例锁保持。本轮无新RF、训练或生产配置变更。

原进度脚本默认fresh根，按计划显示真实服务、validation分母、质量跳过和24组计数。
完成后自动独立读回核验、绘制24张PNG/SVG、导出计数/比例/共同成员CSV，再生成最终完成标志。
保留清单扩展到预测、metadata、报告和图表，控制文件单列；退出finally清理该根的运行缓存。
临时测试目录自动清理，源数据没有新增IQ副本。活动结果/缓存保留至后台结束。
路径、字节、哈希、人工删除依据及实际启动快照见[验证集从零启动证据](../evidence/RML2018A_SEED42_VALIDATION_2026-09-14.json)。

## 完成核验与source到guard差距复核（2026-09-15）

用户关注guard相对source明显下降，随后要求核对是否清洗出错。本节区分完整验证集结果、
固定样本的归一化诊断和历史模型差别，原启动记录与结果字节不改写。

fresh全程完成9,073,240次预测、24模型/数据组、24张PNG/SVG矩阵及计数/比例/共同成员CSV，
耗时14,778.5777秒（约4小时6分19秒）。服务inactive/dead、MainPID=0、ExecMainStatus=0。
独立重新读取3,744预测块，检查全部logits有限/argmax、checkpoint与input绑定、24组统计和共同矩阵；
7,640保留文件、1,199,867,640字节的清单SHA全部通过。运行缓存不存在。控制文件/清单自身不计入上述保留数。

### 完整验证集的共同成员

严格共同369,497源行，以下均为同一分母，避免各组质量剔除数量不同造成误判。

| 模型 | source ACC % | raw ACC % | guard ACC % | guard−source 百分点 |
| --- | ---: | ---: | ---: | ---: |
| CNN2-stable | 54.26 | 35.23 | 46.04 | -8.22 |
| ResNet | 58.96 | 13.51 | 43.82 | -15.15 |
| GRU | 63.59 | 49.00 | 49.39 | -14.20 |
| CLDNN | 50.80 | 34.01 | 44.65 | -6.15 |
| MCLDNN | 62.88 | 49.64 | 49.35 | -13.53 |
| MCformer | 61.57 | 53.97 | 55.66 | -5.92 |
| MAMC | 47.88 | 27.32 | 37.87 | -10.00 |
| Shared-Bi / original Mamba D8 | 62.56 | 49.29 | 54.27 | -8.29 |

guard相对raw在7/8模型整体改善，MCLDNN微降0.286个百分点；这不否认guard相对source的下降。
部分模型在源Z为−8至0 dB时guard比raw下降，不能用总体平均掩盖。条件SINR改善也不等于分类ACC改善，
其估计不是独立标定的物理SINR。逐SNR、类别、翻转计数见保留analysis.json。

### 固定样本的RMS-only对照

冻结选择为24类×26源SNR×每格4条共同validation成员，共2,496条，按源行均匀取点，未按ACC选样。
8原始seed42模型分别识别原source与仅逐窗复数RMS=1的source，总39,936次新预测；
FP32、关闭TF32、batch1024、1800秒上限，实际203.016秒。IQ仅在内存，未复制或修改数据/权重。
归一化公式为sqrt(mean(I²+Q²))，float64计算标量后输出float32，未去DC、滤波、移位或I/Q交换。
同ID的raw/guard预测来自已完成全量结果。8模型原source复算与原保存top-1差异均0。

| 模型 | 原source % | 仅source RMS归一化 % | 实收guard % |
| --- | ---: | ---: | ---: |
| CNN2-stable | 54.73 | 46.43 | 46.15 |
| ResNet | 58.97 | 48.68 | 44.55 |
| GRU | 64.86 | 52.68 | 48.08 |
| CLDNN | 51.32 | 44.39 | 43.79 |
| MCLDNN | 63.78 | 52.40 | 48.68 |
| MCformer | 62.30 | 58.53 | 55.81 |
| MAMC | 48.12 | 38.82 | 37.86 |
| Shared-Bi / original Mamba D8 | 63.22 | 57.09 | 53.73 |

仅source归一化已导致3.77–12.18个百分点下降，证明这些模型对幅度预处理敏感。
固定样本中4ASK RMS中位数1.591、8ASK 1.742、AM-SSB-WC 3.122、AM-SSB-SC 2.835，
多数PSK/QAM约1；类别间幅度分布不是统一单位RMS。D8的4ASK正确数69→15/104、
AM-SSB-WC 66→33/104；BPSK为79→79、QPSK为67→67。
这些结果支持训练/推理幅度分布差异是重要因素，但不证明模型只依赖幅度或全部下降均由归一化造成。
归一化source与guard仍有差距；同步、残余LO、相位/频率、幅频响应等需独立对照后才能归因。
不能把小样本归一化下降量直接套到完整validation或拆成严格相加的物理损失。

[对照PNG](/var/tmp/sdrharness-dev/rml2018a-lo-effect-20260915/source-rms-guard-control.png) ·
[可导出PDF](/var/tmp/sdrharness-dev/rml2018a-lo-effect-20260915/source-rms-guard-control.pdf)。

### 历史成绩的模型边界

历史全量单窗source/raw/guard为62.3691/52.4792/59.0692%，采用epoch-10微调权重、
FP16 autocast；本轮为原始seed42模型、FP32，并限原validation且剔除严格质量失败行。
历史单窗profile SHA为6c1dac991b45e3738e19a6a55a9f3a1b6d3db8510ceef35ee77cdd34e2982dab，
与四窗历史记录同属已删除的epoch-10制品，不能把59.07%与当前D8的54.27%直接解释成清洗损失。
历史依据：[单窗](../evidence/RML2018A_FULL_INFERENCE_2026-09-14.json)、
[模型身份及四窗对照](../evidence/RML2018A_FOUR_WINDOW_COMPLETE_2026-09-14.json)。

### 清洗前后IQ与构建脚本复核

对本地保留的26份旧processed.h5，按source_h5_index/source_block_index/source_row定位同一批2,496条，
分别比对旧inputs/raw、inputs/guard与清洗iq；两组逐元素完全相同，变化行0、最大绝对差0。
对应原始采样起点/长度、类别、SNR一致；两份清洗文件的全2,555,904条source_row均唯一完整，
class_id/source_snr_db逐条与原数据集行结构一致。此为全量元数据检查加分层IQ抽查，不宣称全部IQ逐字节比对。

用户接回外接盘后，读取tools/build_raw_1024_h5.py与build_guard_1024_h5.py，
两份脚本SHA均与各自completed manifest一致。实现直接读取旧inputs/raw或inputs/guard，
检查已有RMS、质量和血缘后将原iq写入合并文件；没有新增归一化、去DC、I/Q交换或LO处理。
因此RMS-only诊断揭示的是已有RX输入与原始模型的适配问题，不能称为本次清洗新增归一化所致。
结合样本字节对照，当前没有发现清洗改坏波形的证据；旧模型与当前模型差异需要与数据处理区别看待。
本次没有从ADC重新推导同步/LO处理，也没有重新执行外接盘构建脚本；这一边界见cleaning-audit.json。

后续应审计训练/推理输入标度；若建立部署模型，应明确一致的幅度预处理并单独验证。
本次未取消LO处理、未改输入接入、未训练或恢复已删除权重，也未发起新的全量推理。
不要按真实类别、原始source窗的RMS或其他部署时不可得的信息补回接收幅度以提高成绩。

[本次证据和保留清单](../evidence/RML2018A_SOURCE_GUARD_REVIEW_2026-09-15.json)记录逐文件哈希、
source/model/profile血缘、有限计划、实际清理与精确人工删除命令；归一化探针保留logits和行号，不保留IQ。
本次只清理自己的Matplotlib与模型运行缓存，原完整结果、数据集和权重保留。


## Mamba的source/raw包含质量失败行重跑（2026-09-15）

用户追加要求“不忽略没通过校验的”，在Mamba上重跑source/raw。当前范围继承原服务器
seed42 validation；采用原始D8 seed42、FP32/关闭TF32、单窗1024，与历史epoch-10权重分开。
source/raw均383,385条，raw包含此前被质量标志排除的3,723条，质量跳过0；总766,770次新预测。
从HDF5重新生成元数据，无旧预测复用。保留三组8模型结果，不重跑guard、不训练、不发射、不复制IQ。

现有collection入口增加显式variants/planes/include-quality-failed选项，默认仍严格质量筛选。
包含失败行时仅改变推理选择mask，原usable/strict/quality_flags不改写；共同严格合格379,662
源行的矩阵与ACC另报，不能误称全部383,385都通过质量校验。质量失败原因和实际跳过计数分列。
原始行号、标签、数据哈希、split、输入形状/有限值/RMS和logits校验继续执行，不用伪造预测填补失败。

11项合同测试通过，覆盖RX重排后的原validation映射、质量失败纳入且train/test排除、
质量标志不被覆盖、共同合格子集、未知模型拒绝、一个模型两输入计划、fresh与动态收口/续跑。
本轮实际全量metadata逐条核对val成员相同、train/test选中0，模型/源码哈希与继承的FP32数值依据相符。
GPU沿用相同权重/计算精度验证，不再用真实ACC选择精度。首3块7,474条source新预测实际SHA、
选中行、有限logits/argmax独立读回通过；此时raw质量失败行尚未处理，未冒充已完成。

新根`/home/jetson/sdrharness/local-assets/amc-eval/results/mamba-source-raw-val-allquality-20260915`，
服务`sdr-mamba-source-raw-val-allquality-20260915.service`已active/running。
原进度脚本实际显示两组、各383,385条、质量跳过0、raw包含3,723条失败及真实计算/落盘进度；
只查看进度不会停止任务。继承数值探针粗估560.43秒，未当作完成时长。
计划内部3600秒期限、systemd最大4500秒、停止宽限60秒、1GiB输出预算、3GiB可用空间门。
启动可用空间约676GB；超时/STOP/信号退出finally清理该根专用运行缓存。

后台按用户既有要求自行执行，结束后自动全部读回核验、生成两张PNG/SVG矩阵及CSV、最终retention/COMPLETE。
此单元交付入口和实际启动，不等待所有预测，不提前勾选完整识别。服务停止路径为
`systemctl --user stop sdr-mamba-source-raw-val-allquality-20260915.service`，也可创建该结果根的STOP。
运行缓存属于仍活动任务，不在此刻删除或宣称清理。临时测试目录已自动清空并移除；
诊断脚本/元数据核对/首块证据精确保留，数据集、权重、旧结果保持。
[启动证据](../evidence/RML2018A_MAMBA_ALLQUALITY_START_2026-09-15.json)登记哈希、预算、保留/清理与精确删除路径。


## source和raw完成及guard补跑（2026-09-15）

source/raw后台已正常退出，766,770次预测、两图、完整读回与保留清单完成，实际533.254秒。
本次独立读取644保留文件218,907,624字节的SHA，312块logits/argmax、输入/模型绑定、
全量与共同质量子集矩阵重算一致；原运行缓存不存在。两组各383,385行：
source ACC63.3081628%，raw49.7293843%；raw3,723条质量失败全部预测，其中1,923条分类正确。
这与上一轮只识别合格raw的49.71%接近，不将质量失败等同于分类必错。已完成结果原样保留。

用户补充“guard忘记了”。单独准备原始Mamba D8 seed42的guard计划，沿用原validation、
FP32/关闭TF32、batch1024及单窗1024点；383,385次全新预测，包含12,277条质量失败，跳过0。
source只读用于从HDF5重新校验原标签/行号，不写source推理元数据、不重新计算source/raw。
三组主统计分母最终均383,385；guard附加合格子集371,108，与source/raw的共同合格379,662
不是同一子集，不能把这两个附加分母直接当作三组配对比较。

prepare-validation允许guard-only等已知输入子集，fresh的source标签依据从父计划中读取；
父级仍为已完成8模型三组计划，继承相同模型/输入FP32数值依据，未知或重复输入拒绝。
11项测试通过，增加单独guard计划只含原val、总次数正确、无source预测元数据、质量子集保留的检查。
全量实际元数据证明383,385个val成员全部选中、质量失败12,277纳入、train/test选中0。

新根`/home/jetson/sdrharness/local-assets/amc-eval/results/mamba-guard-val-allquality-20260915`，
服务`sdr-mamba-guard-val-allquality-20260915.service`已实际active/running。
首3块7,100条新guard预测SHA/输入模型身份/源行/有限logits/argmax读回通过，
其中1,582条质量失败已实际进入模型并落盘，证明未被第二处mask排除。
原进度脚本默认切guard，实测显示383,385、质量跳过0、失败纳入12,277与1张矩阵预算。

先导估计280.22秒；内部3600秒期限、systemd最大4500秒、停止宽限60秒、1GiB输出预算与3GiB余量门。
精确停止：`systemctl --user stop sdr-mamba-guard-val-allquality-20260915.service`，或创建新根STOP。
后台自行完成核验、一张guard矩阵与CSV、保留清单/COMPLETE；本节记录启动，不提前宣称全部完成。
测试临时目录自动清空并移除；本单元只保留核对脚本、测试日志和启动证据。活动GPU缓存由所属runner
结束时清理，不能此时删除；无RF/训练/权重或IQ改动。保留路径、哈希及精确人工删除方法见
[完成与补跑证据](../evidence/RML2018A_MAMBA_GUARD_START_2026-09-15.json)。


## 包含质量失败行的三组最终结果（2026-09-15）

guard已完成383,385次预测，正确208,794、ACC54.4606597%，质量跳过0，耗时295.629秒。
服务inactive、MainPID=0、ExecMainStatus=0，运行缓存不存在。一张真实PNG/SVG及三类CSV完整。
本次独立读取325保留文件126,078,643字节SHA，156块模型/输入身份、选中行、有限logits、argmax，
并重新计算全量/严格子集混淆矩阵；全部通过。实际查看guard图，24类标签、轴向和分母显示正确。
12,277条质量失败全部有预测，其中7,727条正确；质量估计失败不等于调制识别必错。

三组源行按source_row核对，均为完全相同383,385个原seed42 validation成员；
原始Mamba D8 seed42、FP32/关闭TF32、1024点单窗，训练/test成员不进入结果：

| 输入 | 样本数 | 正确数 | ACC | 质量跳过 |
| --- | ---: | ---: | ---: | ---: |
| source | 383,385 | 242,714 | 63.3082% | 0 |
| raw | 383,385 | 190,655 | 49.7294% | 0 |
| guard | 383,385 | 208,794 | 54.4607% | 0 |

guard比raw提高4.7313个百分点，比source低8.8475个百分点。与原8模型严格质量轮的371,108
合格guard行逐预测比较，类别变化0；这部分ACC仍54.1802%，补入质量失败后整体只提高0.2805个百分点。
因此排除质量失败行不是与历史59.07%差距的主要解释；历史成绩采用epoch-10微调权重和全量工程范围，
本轮采用原始seed42及validation，不能当成相同模型/范围下的清洗前后变化。
此前RMS-only诊断说明输入幅度适配值得研究，尚未证明剩余差距的全部机制；本次不训练或重新采集。

三张完整矩阵（PNG，旁边另存SVG/计数和百分比CSV）：

- [source](/home/jetson/sdrharness/local-assets/amc-eval/results/mamba-source-raw-val-allquality-20260915/confusion-matrices/amc_mamba_d8-seed42/source.png)
- [raw](/home/jetson/sdrharness/local-assets/amc-eval/results/mamba-source-raw-val-allquality-20260915/confusion-matrices/amc_mamba_d8-seed42/raw.png)
- [guard](/home/jetson/sdrharness/local-assets/amc-eval/results/mamba-guard-val-allquality-20260915/confusion-matrices/amc_mamba_d8-seed42/guard.png)

全三组共1,150,155次预测；source/raw的完成核验保留在上一节。本次只读回guard并核对三组汇总，
没有新推理、RF或IQ副本。新完成审计目录只保留脚本、JSON和CSV，无运行缓存或临时文件残留，
原模型/数据/结果保留。[完成证据](../evidence/RML2018A_MAMBA_ALLQUALITY_COMPLETE_2026-09-15.json)
登记路径、SHA、字节、血缘与精确人工删除命令。


## 原始Mamba三个完整数据集启动（2026-09-15）

用户明确选择同一个Mamba D8 seed42识别source/raw/guard三个完整数据集，不再只取15%validation，
并沿用包含质量失败样本要求。三组各2,555,904条，共7,667,712次全新预测；
raw25,314条、guard82,406条质量失败均纳入，质量跳过0，原质量标志保持。
全三组严格共同合格2,462,264源行另报；主ACC分母始终各2,555,904。
原始D8 seed42权重、FP32/关闭TF32、单窗1024、batch1024、CPU按16,384文件行预取保持。
source原值、RX已有逐窗RMS不改；新结果不复用任何旧validation预测，不新增IQ/权重副本。
本轮包含历史train/validation/test成员，属于用户授权的全量RF工程对照，不改写独立test或validation结果。

现有入口新增prepare-full，与prepare-validation共用元数据/模型接入；不指定split，
显式传split时拒绝，移除继承split及validation_member/rank，重新生成全量mask。
11项测试通过，覆盖一个模型三个完整输入、全量分母/零split排除、无validation字段、
显式split冲突拒绝，并保持旧validation/质量/续跑测试。之后仅CLI说明及进度默认根变更，
Bash语法与真实进度显示通过，没有为这些展示修改重复整组推理探针。

实际全量元数据独立核对：三份source_row均唯一完整覆盖0至2,555,903，
24类×26档每格均4,096条，选中mask全部为true，plan不含split，未写validation成员/rank，
质量失败纳入数、源标签/SNR、输入/模型/代码身份和预测预算一致。
新根`/home/jetson/sdrharness/local-assets/amc-eval/results/mamba-full-allquality-20260915`，
服务`sdr-mamba-full-allquality-20260915.service`已active/running；首2个完整块32,768条
source新预测SHA、模型/输入绑定、连续全行号、有限logits与argmax独立读回通过。
raw/guard此时尚未开始；首块成功不等于三组全量通过。

继承先导估计5604.32秒（约1.56小时），早期吞吐包含启动开销，实际时长以进度为准。
内部14400秒期限、systemd最大15300秒、停止宽限60秒，2GiB输出预算与3GiB可用空间门；
启动SSD可用约676GB。直接停止`systemctl --user stop sdr-mamba-full-allquality-20260915.service`，
或在新根创建STOP。原进度脚本默认显示完整数据集、三组各2,555,904、质量跳过0、
失败纳入数、计算/落盘区别及三张矩阵预算；Ctrl+C只退出查看。

后台按用户既有要求自行执行，结束后自动全部读回核验、三张混淆矩阵PNG/SVG与CSV、
最终retention/COMPLETE。此单元交付入口、实际启动与初始读回，未宣称全量完成。
测试临时目录自动清空并移除，保留最小日志/有限计划核对/首块证据；活动GPU缓存留给runner
退出finally清理，旧结果与模型/数据保持。[全量启动证据](../evidence/RML2018A_MAMBA_FULL_START_2026-09-15.json)
登记精确路径、SHA、字节、停止及人工删除命令。本次没有RF、训练或生产配置变更。
