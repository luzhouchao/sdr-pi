# RadioML2018A 全量空口工程对照

[文档入口](../README.md) · [实机验证](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md)

入口为 [AGX runner](../../jetson-agx/sdrharness/scripts/rml2018a-rf-campaign.py)，
它按原 HDF5 行号读取全部 **2,555,904** 条 X/Y/Z，按计划在AGX USB（当前默认）或NX上调用
[有限 TX helper](../../jetson-agx/sdrharness/scripts/rml2018a-nx-tx.py)（历史文件名保留），再由既有
`sdr-agent --mode sweep` 控制 P201 接收，AGX 冻结模型分别识别源样本和实收样本。
用户称为N210的设备实际枚举为B210，serial `2508504`，现已迁到AGX USB。
两个主机复用已核对的UHD文件发射程序，NX仍不需要h5py/PyTorch。
设备程序/专用UHD镜像与P201接收入口分开，数据共享见[设备工作区](../../devices/README.md)。

用户明确选择整个原始数据集，包括历史 train/validation/test 成员。本结果属于全量工程对照，
不能作为独立 locked-test 准入成绩。训练/微调暂停，生产 `recognizer_available=false`，
名称采用 server-v1 原始 24 类顺序并保持 provisional。

## 帧、参数和预算

2026-09-11用户报告已换回2.4GHz；当前固定 **2455 MHz**、2.1 MS/s、TX/RX BW 1.5 MHz、TX 峰值 0.2、
TX LO offset +250 kHz；用户已确认换成2.4GHz天线（型号未报告），P201身份为 RX1/RX0/A_BALANCED。
2455MHz沿用历史实验中心，不表示本轮已扫描确认空闲；已完成有限收发，质量失败及估计边界见实机验证。
新计划默认AGX主机、TX0/RX20，作为后续低增益有线验证的起点，尚非收发通过配置。
`plan`允许登记TX0/20/40/60/70/80dB、RX20/40/50dB，执行时读取该计划，
不允许临时覆盖增益，不无衰减同轴直连。增益是设备设置值，不是发射功率dBm。
2026-09-12用户先确认B210 RF A TX/RX经30dB＋20dB串联衰减器及15cm SMA线接P201 RX1，
随后在停发后先改为30dB，又明确确认换成20dB，当前只保留20dB；
[此前质量及停止验证](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12同轴衰减接收幅度与主动停止)按需读取。
中间TX20/40/60档用于有界逐档检查；每档新计划，上一档完整恢复后才执行，默认仍为TX0/RX20。
不能直接拿天线80/40的计划用于同轴连接，也不能把条件SINR当成校准的物理SINR。
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

## 独立有线LO参考诊断

[validate-b210-cable-lo.py](../../jetson-agx/sdrharness/scripts/validate-b210-cable-lo.py)
提供`plan/acquire/analyze --root /var/tmp/sdrharness-dev/b210-cablelo-<唯一标识>`，使用AGX模型venv的Python运行。
它复用既有B210有限TX helper、AGX USB运行时和P201 Controller，不读取数据集或运行模型。
新根先生成计划，核对当前接法、软件和预算后才能`acquire`；`started.json`阻止同根重复发射，失败须保留记录。

独立schema为`b210-cable-lo-reference-v1`：固定2455MHz、2.1MS/s、BW1.5MHz、TX70/RX40、
98437.5Hz复数单音（1024点第48个FFT频点），按顺序执行`(+250kHz,0.1)`、`(-250kHz,0.1)`、
`(+250kHz,0.05)`、`(+250kHz,0.1)`，每组不超过4秒；加前后两次停数据流控制，
共6次65535点ci16接收，最大1,572,840字节。单点settle500ms、deadline1000ms、Controller外层15秒、
整体360秒，每组分量峰值须≤512计数并完整恢复才继续；源与计划须完全符合注册模板。
普通RadioML计划仍固定+250kHz、峰值0.2；不能借此schema给普通campaign任意覆盖LO/增益/幅度。

诊断前32768点估计单音及LO候选频率，后32767点统计±1kHz固定频带和拟合残差；
这是单音来源诊断，不能把拟合后误差当成已修复的调制波形SINR。停止路径沿用有界helper和Controller取消，
逐组核对P201双路状态/临时路径恢复与B210 USB空闲；USB空闲仅说明数据流/持有者状态，不证明RF能量为零。
实际结果、频谱及清理通过[实验记录](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12干净单音与lo跟随分量)按需读取。

创建计划时可显式加`--experiment gain-pair`，注册独立`b210-cable-lo-gain-pair-v1`，
顺序为停流背景、A1、B1、A2、B2、停流背景：A=幅度0.1/TX70，B=幅度0.1×√10/TX60，
LO固定+250kHz，其余RX/采样/带宽/时长/字节/恢复门与上述入口相同。
预登记要求两次配对分别满足单音功率变化绝对值≤1dB、LO频带功率下降≥6dB；这些是工程对照条件，
不是模型准入或校准SINR标准。执行/分析不能临时覆盖`--experiment`，必须使用已登记新根。
此配对只扩展严格模板允许的单音，普通RadioML发射峰值仍为0.2；
[单音实测已通过](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12数字幅度与硬件增益配对)，未据此提高全库波形幅度。

## 有限RadioML幅度增益配对

campaign的`plan`支持`--tx-level-profile standard`（默认，峰值0.2）以及严格受限的
`--tx-level-profile gain-pair-pilot --tx-host agx --tx-gain-db 60 --rx-gain-db 40`。
后者峰值为0.2×√10=0.632455532033676，payload与导频一起缩放；原同步、SINR、RMS和模型处理不变。
TX包使用独立`rml2018a-gain-pair-pilot-v1`，只允许批次4267/22016的精确24行成员，源Z须为30；
端口、中心、LO偏移、rate/BW、4秒/批预算及原生质量检查保持。错误增益/行号/峰值/普通schema拒绝发送。

配对计划固定`execution_limits`为两批、48条、8秒TX和524,280字节RX；
原`budget`仍描述全库索引空间，以支持非连续原始行号，不是允许执行全库。
`acquire/infer/run`显式使用`--batch-indices 4267 22016`或其中一批，范围外选择拒绝；
`summary`保留全库未完成状态并单列有限执行范围。执行时不能覆盖增益或`--tx-level-profile`。
源码或参数变化须新根/新计划，原始失败及结果不覆盖；标准profile仍按原峰值执行。
[两类实机配对结果](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12radioml调制波形的幅度增益配对)
不能自动推广为24类、低源SNR或全量参数准入。

## 八类新采集与导频时序校正

八类新采集的有限profile为`--tx-level-profile timing-multiclass-pilot`，固定AGX TX60/RX40、
峰值0.632455532和2455MHz，使用独立`rml2018a-timing-multiclass-pilot-v1`发包schema。
只接纳批次`4283 22032 26470 57531 66406 75280 93030 101904`，依次对应
OOK/QPSK/8PSK/16QAM/64QAM/256QAM/AM-DSB-SC/GMSK，各24行Z30，
上限8批/192行/32秒TX/2,097,120字节RX。它不扩写旧两批profile，也不改变普通全库峰值。
采集仍使用原campaign的有界Controller/有限TX/取消/恢复路径，原始audit和SINR保持。

八类对照入口为[compare-rml2018a-pilot-timing.py](../../jetson-agx/sdrharness/scripts/compare-rml2018a-pilot-timing.py)：
`prepare/infer/verify --root <八类campaign> --output /var/tmp/sdrharness-dev/rml-timing-multiclass-<唯一标识>`。
它从已完成的新采集生成source/raw/lo/timing四组工程输入，最多768个实验模型窗口及2个warmup，
明确保留每类24行、未同步、SINR无效、LO/时序拒绝及识别失败。拒绝校正时该变体使用上一阶段原样输入，
未同步时三组实收均没有预测，源预测仍保留。模型保持冻结epoch10 FP16 autocast/FP32权重，
不按识别结果挑选校正参数。源X只在接收DSP完成后用于质量/识别对照，不进入相消或时序拟合。

[导频时序模块](../../jetson-agx/sdrharness/scripts/rml2018a_pilot_timing.py)使用每个已知导频
前半段[64:448]拟合延迟及随采样时间的漂移，后半段[576:960]独立验证，不重新拟合；
至少2个导频，延迟≤0.6点、漂移≤10ppm、拟合RMS≤0.04点、验证误差≤0.08点，
导频残差比例≤0.03且正交导数比≤0.08，否则保留LO相消输出和跳过原因。
通过后采用129抽头Kaiser8窗sinc插值，保留真实64点邻域，不在行边界补零或循环拼接。
该有限插值并非严格全通；独立过采样仿真、占用带内保真及白噪声功率变化测试约束其影响。
时序后的条件估计参考面为`received_payload_after_guard_lo_and_pilot_timing_before_rms`，
记录插值器与`rx_timing_correction`，不写回原始/LO阶段SINR，也不称为物理SINR校准。

上述对照脚本是实验入口，未安装到生产接收/识别流程；普通campaign的默认预处理保持。

## 保护间隔辅助LO相消（离线实验）

[相消模块](../../jetson-agx/sdrharness/scripts/rml2018a_lo_cancellation.py)与
[有界回放入口](../../jetson-agx/sdrharness/scripts/diagnose-rml2018a-lo-cancellation.py)
独立于现有campaign接收默认值。入口提供`analyze/infer/verify --root <原配对计划>
--output /var/tmp/sdrharness-dev/rml-lo-cancel-<唯一标识>`，用既有模型venv的Python运行；
`infer`须先有通过质量检查的`prepared.json`，只接纳原配对两批4267/22016，
最多48个新模型窗口及2个warmup，复用并复核原始源/实收96个模型输入，不重复原预测。
此入口不调用RF、修改采集计划或安装生产处理；新源/软件用新的派生根，已完成推理拒绝重跑。

方法`pilot-anchored-guard-lo-cancellation-v1`保持原导频同步/CFO/相位：
将相邻重复帧的两个256点静默保护区合并，剔除首尾各64点；每区前192点拟合恒定复数单音，
后192点只验证，不重新拟合。至少两个完整保护区，频率先验为250kHz加原导频CFO，
搜索±30Hz/步长1Hz后局部细化。稀疏保护区约80.42Hz的频率歧义要求这个导频先验可信；
宽频搜索虽可拟合保护区，却会在payload内减错相位，不能使用。

留出区抑制须≥10dB、幅度跨度≤25%、相位差≤0.25rad；相消后的已知重复导频
两半相关度须≥0.95、剩余CFO须≤25Hz，频率在搜索边界或任一条件不满足则原样返回，保存原因。
相消器只接收IQ与导频坐标，不接收源X/Z、类别或模型预测；源X仅在事后评估保真与条件SINR。
它减去一个预测的加性泄漏波形，不对payload开陷波/低通，也不拟合删除payload的同频有效信号。
保护区无法保证发现只发生于payload内部的漂移，本方法尚需新采集和24类/低源SNR验证。

`raw_quality`保留原估计；`post_cancel_quality`沿用相同两半窗误差功率公式及原Z，
但参考面显式改为`received_payload_after_guard_lo_cancellation_before_rms`，并记录
`rx_interference_cancellation`及完整相消/拒绝诊断。后处理值不写回原始`rx_sinr_db`记录，
也不称为硬件原始SINR改善或物理校准。原生IQ不复制，派生张量仅保留哈希。
验证、已知失败与图表见[实验记录](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12保护间隔辅助lo相消)。

## 相消后的剩余误差归因（离线实验）

[诊断模块](../../jetson-agx/sdrharness/scripts/rml2018a_link_diagnostics.py)与
[只读入口](../../jetson-agx/sdrharness/scripts/diagnose-rml2018a-link-residual.py)提供
`analyze/verify --parent <原配对计划> --cancellation <已封存相消结果>
--output /var/tmp/sdrharness-dev/rml-link-residual-<唯一标识>`，使用既有模型venv的Python。
只接纳原两批48行Z30，先校验父库存、IQ、同步、相消输出及原质量；180秒、结果16MiB上限，
无RF、模型推理、接收参数修改或IQ副本，源/原软件改变时拒绝。

`post-guard-lo-forward-error-crossfit-v1`固定9个正向拟合模型：标量、时序导数、
线性复数时间增益、RX/TX镜像、RX DC、三次非线性、5抽头信道及组合。
每行前512点训练/后512点评价并交换；训练中心化，评价保留完整源DC。
RX镜像在原CFO校正后额外旋转−2CFO，TX镜像反射于+250kHz LO故位于+500kHz，
RX DC旋转−CFO，不能把三者都当作常量偏置或简单`conj(X)`。
列归一化后以`rcond=1e-6`解最小二乘，秩不足/条件数>10⁶保留invalid与两个fold，不删除行。
源参考保持原X的统一缩放，fc32发包仍单独核验哈希，不能用其精度变换改写基线误差。

输出是`error_reduction_db`及实际ADC计数平方残差，**不是新rx_sinr_db或接收端修复结果**。
各变体不相加为总解释量，模型改善不能唯一确定物理原因。源辅助延迟趋势以首12行预测后12行，
全24行估计另存；仅已知导频的时间估计独立执行，与payload辅助结果事后比较，未实施重采样。
静默区残差仍含预测误差/杂散，不当作校准热噪声。±175kHz只作为固定频谱统计掩码，未施加滤波。
已知分量测试、失败和48行结果见[验证](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12相消后剩余误差与导频时序诊断)。

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
"$RML_PY" -B "$RML_RUNNER" plan --root "$RML_ROOT" --tx-host agx --tx-gain-db 0 --rx-gain-db 20
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
`--tx-host`、`--tx-gain-db`和`--rx-gain-db`只用于`plan`；传给`acquire/infer/run/summary`会拒绝。
TX主机及传输代码身份写入plan；AGX还固定专用运行时manifest和UHD库/镜像哈希。
AGX模式在本机独立临时目录暂存/启动/回收B210 helper，P201连接仍由原Controller与SSH恢复流程管理。
NX模式只在显式登记`--tx-host nx`时使用；不能将旧NX计划改成AGX继续执行。
两个模式保留有限字节、精确GO、deadline、取消和恢复门。迁移单元只完成无RF探测/软件验证，
不把USB3/寄存器回环成功记成AGX发射与P201接收已通过。
更换增益必须新建根和计划；每行采集质量与summary保存实际计划TX/RX增益，所选TX主机的UHD回读及RX元数据
按相同值校验。代码支持某个增益不等于可持续发射授权，实际执行仍须明确的批次/时长/字节预算。

`--retry-failed`仅重试已证明恢复完成的失败批次：先检查所选TX主机空闲及两端瞬时目录不存在，
再把旧批次整体移动到`attempts/`，新采集有新的request/session身份。旧IQ、日志和失败结果保留。
恢复未证实、audit缺失或原始数据被修改时拒绝自动重试，先核查现场。
成功完成批次不重发；若中断前已有完整采集但尚无prediction，下次仅补推理。

前台直接Ctrl-C；后台仅向已确认的runner PID发送`kill -INT <PID>`。runner对当前generation
走专用cancel，停止已标识TX owner，核对两路RX、LO/采样率/带宽/端口/mask/buffer恢复。
先给owner发INT并等待8秒完成helper清理，超时才分级终止；helper的有界finally防止重复停止信号打断。
无进程持有后，只额外接纳名为packet.fifo的真实FIFO，并用fuser检查无持有者再清理；未知文件、符号链接继续拒绝。
TX另有55秒alarm/58秒外层timeout及有限字节上限；不要用`kill -9`代替正常停止。

## 结果和保留

每批保存 source行号/真实ID/原始SNR/缩放、有限TX/RX计划、原生SigMF、UHD readback及
停止/恢复audit、源与实收24维logits/数字ID/输入哈希/时延/相关度。原始源IQ不额外长期复制。
run-plan保存源文件、软件和模型/profile/标签身份；TX包在成功后删除，TX主机与P201的本单元暂存仅作瞬时副本。

汇总分别列出已采集、待推理、未尝试、实收预测、混淆矩阵、按源SNR分组统计及接收SINR测量状态。
`received_accuracy`只针对已有实收预测；`end_to_end_success_fraction`以已采集行为分母，
待推理和接收失败都不算成功。`complete`表示所有源行已有工程结果（允许sync_failed），
只有`all_rows_received_and_inferred=true`才表示全库每行都获得实收预测。
失败重试历史不重复进入最新汇总。

原始IQ/权重/运行制品不入Git。要删除一个campaign，先确认runner、所选TX主机及P201均已停止并恢复，
核对run-plan与根目录真实路径，再按对应保留清单逐个删除该根；不清空公共开发根，
不删除既有数据集和其他实验。验收保留包的精确路径、哈希、大小和人工删除方法见
[库存](../evidence/RML2018A_FULL_RF_CAMPAIGN_EVIDENCE_2026-09-10.json)。
