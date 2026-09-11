# RadioML2018A 全量空口工程对照

[文档入口](../README.md) · [实机验证](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md)

入口为 [AGX runner](../../jetson-agx/sdrharness/scripts/rml2018a-rf-campaign.py)，
它按原 HDF5 行号读取全部 **2,555,904** 条 X/Y/Z，在 NX 上调用
[有限 TX helper](../../jetson-agx/sdrharness/scripts/rml2018a-nx-tx.py)，再由既有
`sdr-agent --mode sweep` 控制 P201 接收，AGX 冻结模型分别识别源样本和实收样本。
NX 上用户称为 N210 的设备实际枚举为 B210，serial `2508504`。
NX 不需要安装 h5py、PyTorch 或 Python UHD；复用已核对的 UHD 文件发射程序。

用户明确选择整个原始数据集，包括历史 train/validation/test 成员。本结果属于全量工程对照，
不能作为独立 locked-test 准入成绩。训练/微调暂停，生产 `recognizer_available=false`，
名称采用 server-v1 原始 24 类顺序并保持 provisional。

## 帧、参数和预算

2026-09-11用户报告已换回2.4GHz；当前固定 **2455 MHz**、2.1 MS/s、TX/RX BW 1.5 MHz、TX 峰值 0.2、
TX LO offset +250 kHz；用户已确认换成2.4GHz天线（型号未报告），P201身份为 RX1/RX0/A_BALANCED。
2455MHz沿用历史实验中心，不表示本轮已扫描确认空闲；已完成有限收发，质量失败及估计边界见实机验证。
新计划默认TX70/RX40；`plan`仅允许登记TX70或80dB、RX40或50dB，执行时读取该计划，
不允许临时覆盖增益，不无衰减同轴直连。增益是设备设置值，不是发射功率dBm。
本次有限70/40与80/40对照中，80/40两批均同步，但条件SINR仍低，不能据此认定全量参数合格；
见[增益对照](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-11发射增益与接收增益有限对照)。

每批最多24个独立1024点样本，各自按复数峰值缩放，前面加入由 run/batch 派生的1024点
QPSK同步标记，两端各256点零保护。完整帧26112点；重复321次，总发射8381952点，
约3.9914秒，有限上限4秒。重复用于覆盖异步RX启动，**不是每个原始样本只发一次**。
P201每批接收65535个复数ci16样本（262140字节），500ms settle、1000ms点超时。

同步只使用标记，先固定129-tap Hamming、500kHz低通检测，再估计时刻/CFO/公共相位。
该滤波器仅用于检测，**送入模型的payload不做此低通或自适应陷波**；不使用真实类别、
模型输出寻找对齐，也不减去DC。同步门未过的批次不产生实收预测。
CFO搜索按原433.920MHz的相对频偏容限缩放：2455MHz时搜索±14.5kHz、步长500Hz，
细化后绝对上限17kHz；初始/最终标记质量门仍为0.55/0.65。搜索参数写入新run-plan。
若最清晰标记位于接收尾部、后续payload不完整，使用已知重复帧长度定位前一完整payload；
报告同时保存锚点标记与payload前标记的位置/得分，不将受干扰标记的得分冒充通过。
单个源/实收1024点窗口均做复数RMS归一化，沿用冻结epoch-10、FP16 autocast/FP32权重。
这是工程单窗比较，区别于生产RF-v1四窗/mean-logit准入。
Z仅为原始数据集的标称SNR，不是当前空口接收SNR/SINR。

| 项目 | 全库预算 |
| --- | ---: |
| 批次 | 106496 |
| 原生实收IQ | 27,916,861,440字节（约26GiB） |
| 元数据和预测预留 | 27,917,287,424字节（约26GiB） |
| 单批源包瞬时副本 | 208896字节 |
| 累计TX上限 | 425984秒（约4.93天） |

总输出预留约52GiB，另留缓存和失败重试空间；重试保留旧证据，会增加占用。
初始代码的10秒/批估计尚未验证，实际耗时以验证记录为准，不能用空口样本时长代替SSH、
设备初始化、恢复与推理耗时。全量属于多日运行，此工具尚无全库长期稳定性验收。

## 源SNR与条件有效SINR估计（v3）

`rml2018a-all-row-rf-v3`保留原始Z为`source_snr_db`。原始X本身已有噪声/信道损伤；
实收相对X的误差仅反映新增链路误差，不能单独称为总SINR。本版本在明确假设下组合两者，
输出`rx_sinr_status=estimated`的**条件有效SINR**，不称为独立测得的总RF SINR。

估计器见[receive_quality](../../jetson-agx/sdrharness/scripts/rml2018a_campaign.py)。
对pilot固定对齐后的每个1024点窗口，以前512点拟合复数标量增益、在后512点评估，再交换。
拟合时对X/Y中心化以免额外DC被吸入增益；评估用完整X/Y，保留有效信号DC，也将额外DC计入误差。
不寻找更有利的窗口，不用真实类别/模型预测，不对模型输入额外滤波或均衡。

令两个测试半窗平均的预测X功率为A、残差功率为E，源标签线性比值为γ=10^(Z/10)：

- 标称有效信号功率：A × γ/(γ+1)。
- 标称源噪声功率：A/(γ+1)。
- 条件有效SINR：10 log10[(A × γ/(γ+1)) / (A/(γ+1) + E)]。

没有直接相加dB，也没有把已含噪X整体当成干净信号；结果不会超过源Z。
E包含新增干扰、接收噪声、未建模的信道/硬件失真及有限样本的拟合误差。
必须假设Z能描述本窗口的标称源功率分配、源信号和源噪声经历同一增益、
链路在窗口内近似标量线性且新增干扰与X不相关。稳定多径/非线性仍可能进入E；
相关干扰可能偏置增益。这些假设不能仅凭实收自证，故不是校准仪器级SINR或每条源的精确SNR。

固定有效性条件：两个增益相对差≤0.25，两个残差功率比≤4，参考/残差比≥−10dB，
各训练半窗中心化参考能量占比≥1e−4。同步失败记`not_measured`，能量不足/增益不稳/
突发残差等记`invalid`并保留原因，`rx_sinr_db=null`；无效行继续进入采集和识别分母。
门限只限定这个估计器的工作范围，不是模型拒识阈值；通过也不证明所有假设成立。

测量位置为`received_payload_before_rms`，数字滤波`none`；积分覆盖完整采样复基带
[−Fs/2, Fs/2)，记录带宽2.1MHz，已经经过1.5MHz模拟RX滤波，不把模拟带宽当成精确ENBW。
各功率以接收窗口总功率归一化，另存ADC平方单位总功率，不输出未校准dBm。
`rx_sinr_diagnostics`保留两半窗功率、增益一致性、标称源噪声和新增误差，方法版本和假设写入run-plan。

采集audit就保存逐行估计；`acquire`也生成汇总，无需启动模型。推理从已封存audit沿用同一估计，
并校验源Z/行号/功率关系；汇总拒绝prediction与audit的质量记录不一致。
`by_source_snr_db`仍按源Z分组；接收指标单列`rx_sinr.estimated/invalid/not_measured`及
固定2dB左闭右开分箱`by_estimated_rx_sinr_db`，包含每箱采集/实收推理/正确数。
`measured_rows=0`强调没有独立仪器测量；未同步及无效原因单列，不塞入0dB分箱。

继续以RadioML作源数据/空口工程对照，先高源SNR基线再扩档。严格物理SINR曲线仍需要干净参考/
可控干扰及独立校验，不需要因此更换训练数据集。旧v1/v2计划/审计保持原字节，源码变化必须新campaign；
导频生成仍固定v1种子以便离线重建历史帧。仿真/实机边界见[验证](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md)。

## 在AGX执行

已封存实收的固定滤波对照使用[离线诊断脚本](../../jetson-agx/sdrharness/scripts/diagnose-rml2018a-campaign-filter.py)。
默认只输出保真JSON，无射频/模型操作；`--batches`显式限定1–3个不重复的完整批次。
指定`--infer-output`才在新派生根执行原始源、滤波源、原始实收、滤波实收四组工程推理：
所有登记源行均须满足功率保留≥99%及失真≤1%，否则整组跳过模型，不选择有利行。
保留原同步位置/CFO/相位及全部SINR invalid行，使用相同单窗复数RMS和冻结模型。
最多288个实验窗口加2个warmup，650秒deadline，复用空闲Spark暂停/恢复与GPU租约；
父campaign和原始IQ只读，结果及清理单独登记。

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 \
  local-assets/amc-eval/runtime/venv/bin/python -B \
  jetson-agx/sdrharness/scripts/diagnose-rml2018a-campaign-filter.py \
  --root /var/tmp/sdrharness-dev/b210-rml2018a-tx80rx40-20260911 \
  --batches 4267 22016
```

需要推理时另指定尚不存在的`/var/tmp/sdrharness-dev/rml-filter-<唯一标识>`派生根。
2026-09-11这48条的固定175kHz FIR使实收识别从41/48降至3/48，**当前不接入campaign payload**。
滤波后源噪声分配改变，`filtered_rx_sinr_db=null`；原条件SINR只作为未滤波输入的父级记录。
参见[滤波及识别对照](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-11固定滤波与48条工程识别对照)。

同一脚本的互斥`--diagnose-output`用于固定十组相位/CFO/偏置/尺度诊断，
`--components-output`用于固定八组FIR互补成分及幅度/相位替换诊断；都必须指定新的派生根。
两者使用已知源波形拟合或替换部分输入，**只能解释工程误判，不是未知信号可用的接收校正**。
各自最多3批、720或576个实验窗口，加2warmup，650秒deadline；执行前保存固定变体/预算。
尺度对照明确保留非单位RMS，其他输入沿用单窗复数RMS；不能把尺度对照当成新的生产预处理。
CFO诊断固定8个128点仿射拟合，按源能量加权拟合相位斜率，超±5kHz记录无效并保持原输入，
不搜索模型正确率。实际两轮48条诊断没有发现可直接修复回退的简单校正，
结论及限制见[回退排查](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-11滤波误判的有限归因诊断)。

背景选频使用[链路诊断脚本](../../jetson-agx/sdrharness/scripts/diagnose-rml2018a-link-quality.py)的
`survey`子命令：固定8个2.4GHz频点三轮比较、选定候选后与2455MHz交替确认，共最多30次接收，
RX40、2.1MS/s、BW1.5MHz、每点65535复数，总IQ预算7,864,200字节，无TX/模型。
按三轮最差175kHz FIR峰值排名，同时保留原始带宽结果；削顶点不参与候选排名。
确认条件仅针对背景，不是接收SINR或模型准入。脚本固定唯一日期根，根已存在时拒绝重跑；
不为重复实验删除旧证据。2026-09-11候选2440MHz未通过独立确认，实验默认频道保持2455MHz。
详情见[验证](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-11八频点背景比较与候选复测)。

使用已有运行环境，所有路径绝对化。以下 `plan` 仅读取/校验约21.45GB源文件，不发射。
结果根必须为开发根下一个新的 `b210-rml2018a-` 开头目录，名称仅字母、数字和连字符。

```bash
cd /home/jetson/sdrharness
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1
RML_PY=/home/jetson/sdrharness/local-assets/amc-eval/runtime/venv/bin/python
RML_RUNNER=/home/jetson/sdrharness/jetson-agx/sdrharness/scripts/rml2018a-rf-campaign.py
RML_ROOT=/var/tmp/sdrharness-dev/b210-rml2018a-2455-20260911
"$RML_PY" -B "$RML_RUNNER" plan --root "$RML_ROOT" --tx-gain-db 70 --rx-gain-db 40
"$RML_PY" -B "$RML_RUNNER" run --root "$RML_ROOT" --start-batch 0 --max-batches 32 --deadline-seconds 1800
```

先运行有限批次并检查 `summary.json`、每批 audit 和预测。每个推理分片最多32批，独立进程
退出释放CUDA；仅在Spark空闲时暂挂其已核对进程，设独立恢复watchdog，并记录恢复。
Spark忙会拒绝，已采集批次仍保留，可在空闲后续跑。此工程路径使用feature私有GPU租约，
不是生产共享GPU调度部署；运行期间不要另启模型诊断或其他射频任务。

全量命令（最多30天deadline，终端需保持）：

```bash
"$RML_PY" -B "$RML_RUNNER" run --root "$RML_ROOT" --start-batch 0 --max-batches 106496 --deadline-seconds 2592000
```

重复同一命令自动校验并跳过已完成采集/推理；断点单位为批次。若只采集或只推理，使用
`acquire` 或 `infer`；`summary`只读既有批次并写汇总，不调用RF/模型。
源码/依赖、profile或数据身份变化会拒绝复用旧计划，须创建新campaign，不能改写旧plan哈希。
离散类先导可用`--batch-indices <批次...>`显式选择1–32个不重复批次，按给定顺序执行，
替代连续范围；不能与非默认`--start-batch/--max-batches`混用，也不能传给`plan`。
有限先导的行号、类别、SNR、射频/模型预算和失败策略须另行预登记；列表选取不是全库执行。
`acquire`完成后可对同一列表运行`infer`，合为一个有界GPU分片，避免逐类反复加载模型。
同步失败仍可保存源预测并进入分母；硬件/原生完整性/恢复失败按原门停止，不自动重试。
`--tx-gain-db`和`--rx-gain-db`只用于`plan`；传给`acquire/infer/run/summary`会拒绝。
更换增益必须新建根和计划；每行采集质量与summary保存实际计划TX/RX增益，NX UHD回读及RX元数据
按相同值校验。代码支持某个增益不等于可持续发射授权，实际执行仍须明确的批次/时长/字节预算。

`--retry-failed`仅重试已证明恢复完成的失败批次：先检查NX空闲及两端瞬时目录不存在，
再把旧批次整体移动到`attempts/`，新采集有新的request/session身份。旧IQ、日志和失败结果保留。
恢复未证实、audit缺失或原始数据被修改时拒绝自动重试，先核查现场。
成功完成批次不重发；若中断前已有完整采集但尚无prediction，下次仅补推理。

前台直接Ctrl-C；后台仅向已确认的runner PID发送`kill -INT <PID>`。runner对当前generation
走专用cancel，停止已标识NX owner，核对两路RX、LO/采样率/带宽/端口/mask/buffer恢复。
NX另有55秒alarm/58秒外层timeout及有限字节上限；不要用`kill -9`代替正常停止。

## 结果和保留

每批保存 source行号/真实ID/原始SNR/缩放、有限TX/RX计划、原生SigMF、UHD readback及
停止/恢复audit、源与实收24维logits/数字ID/输入哈希/时延/相关度。原始源IQ不额外长期复制。
run-plan保存源文件、软件和模型/profile/标签身份；TX包在成功后删除，NX与P201只留瞬时副本。

汇总分别列出已采集、待推理、未尝试、实收预测、混淆矩阵、按源SNR分组统计及接收SINR测量状态。
`received_accuracy`只针对已有实收预测；`end_to_end_success_fraction`以已采集行为分母，
待推理和接收失败都不算成功。`complete`表示所有源行已有工程结果（允许sync_failed），
只有`all_rows_received_and_inferred=true`才表示全库每行都获得实收预测。
失败重试历史不重复进入最新汇总。

原始IQ/权重/运行制品不入Git。要删除一个campaign，先确认runner/NX/P201均已停止并恢复，
核对run-plan与根目录真实路径，再按对应保留清单逐个删除该根；不清空公共开发根，
不删除既有数据集和其他实验。验收保留包的精确路径、哈希、大小和人工删除方法见
[库存](../evidence/RML2018A_FULL_RF_CAMPAIGN_EVIDENCE_2026-09-10.json)。
