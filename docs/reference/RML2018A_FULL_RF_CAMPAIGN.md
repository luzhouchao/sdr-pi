# RadioML2018A 全量RF工程对照

[文档入口](../README.md) · [实机验证](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md) · [当前配置与论文范围](RML2018A_RF_REPRODUCTION.md)

入口为 [AGX runner](../../jetson-agx/sdrharness/scripts/rml2018a-rf-campaign.py)，
它按原 HDF5 行号读取全部 **2,555,904** 条 X/Y/Z，按计划在AGX USB（当前默认）或NX上调用
[有限 TX helper](../../jetson-agx/sdrharness/scripts/rml2018a-nx-tx.py)（历史文件名保留），再由既有
`sdr-agent --mode sweep` 控制 P201 接收，AGX 冻结模型分别识别源样本和实收样本。
用户称为N210的设备实际枚举为B210，serial `2508504`，现已迁到AGX USB。
两个主机复用已核对的UHD文件发射程序，NX仍不需要h5py/PyTorch。
设备程序/专用UHD镜像与P201接收入口分开，数据共享见[设备工作区](../../devices/README.md)。

2026-09-13最新接线已从独立负载接回B210 RF A TX/RX→原20dB衰减器及15cm同轴→P201 RX1，
B210仍停发，见[返测](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13同轴接回后的停发返测)。
用户已确认接回，后续实验沿用该接法；具体收发仍由新有限计划控制。

用户明确选择整个原始数据集，包括历史 train/validation/test 成员。本结果属于全量工程对照，
不能作为独立 locked-test 准入成绩。训练/微调暂停，生产 `recognizer_available=false`，
名称采用 server-v1 原始 24 类顺序并保持 provisional。

## 通用有限分块与无损事件归档（2026-09-13）

`event-chunk` 复用上述campaign及事件后端，计划时显式登记1–32个不同批次，
允许原始索引0–106495内任意成员及同批混合Y/Z；旧有限profile的成员约束保持。
继续固定AGX B210、2455MHz、TX60/RX50、20dB同轴、2.1MS/s、BW1.5MHz及4秒/批。
每个计划/调用都有有限边界，结束后写`chunks/<成员与命令哈希>.json`并退出，不自行调度下一块。
计划访问仍核对原始全HDF5哈希和旧成员交集；全量工程结果不因此成为独立准确率。

示例形式（`<新根>`及批次须在实际执行前登记，不能重用已封存实验）：

```text
rml2018a-rf-campaign.py plan --root <新根> --tx-level-profile event-chunk \
  --tx-host agx --tx-gain-db 60 --rx-gain-db 50 --batch-indices <1到32个明确批次>
rml2018a-rf-campaign.py run --root <同一根> --batch-indices <本次选中的登记成员>
```

`run`完成选中成员的采集、推理和统计后暂停。重复同一已完成`run`会复核凭据并跳过RF/模型。
汇总分母是完整登记成员，未执行的成员明确标记`not_attempted`，不会从分母消失。
原先`acquire/infer`分阶段操作仍可用；暂停凭据同时记录当时的推理完成状态，推荐使用`run`作为可重复的分块入口。

发送器仍先生成严格小于16,000,000字节的原始事件JSONL。成功且恢复完成的新采集使用
[无损归档模块](../../jetson-agx/sdrharness/scripts/rml2018a_event_archive.py)，以gzip level6/mtime0归档，
每份压缩结果最多2MiB；解压逐字节比较及原SHA-256通过后才移除本次原JSONL。
`event-storage.json`保留原路径/字节/哈希、压缩路径/字节/哈希及`records_removed=0`，
采集完成凭据同时绑定该归档收据。旧实验日志不压缩、不移动、不重写。
新解析器同时读原JSONL和压缩日志，拒绝超界解压、损坏CRC、截断、尾随字节/额外gzip成员。
失败尝试原日志仍保留；归档超限则保留原文件并停止，不删除异常记录或重发已完成采集来争取压缩通过。

| 存储项目 | 有限计划上限/预留 |
| --- | ---: |
| 成功事件日志 | 每批2MiB |
| 原生IQ | 每批262140字节 |
| 元数据、三路结果及失败推理记录 | 每批2MiB合并预留 |
| 额外失败采集 | 每批最多一次；每次16,000,000＋262140＋2MiB字节 |
| 同时存在的原日志及新归档 | 16,000,000＋2MiB字节 |
| 缓存/暂存预留 | 每计划256MiB |

每次新采集先检查整个有限计划的空间余量；暂停时分别校验成功元数据/IQ/归档及失败尝试保留量。
不足或超限时停止并保留证据，不能通过清理失败样本继续。默认仍继承原计划创建时的全库磁盘预检，
因此这不是为小容量磁盘实现的按剩余字节精简预检。

按106496批推算，成功保留上限为**474,593,460,224字节**；再预留8GiB失败池、
同时存在的日志/归档和256MiB暂存，合计**483,469,927,424字节（约450.27GiB）**。
这是带“每批成功归档及元数据满足上限、失败池用完即停”条件的预算，不是压缩率保证。
新程序当前只执行明确登记的1–32批，跨多个计划的8GiB失败总池尚无统一执行账本，不能宣称已经具备全库无人值守运行。
仅TX累计上限仍为425984秒（约4.93天）；采集初始化、恢复、推理和反复全源哈希还会增加总时间。

本次两个分块实测及精确保留见
[分块验证](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13通用有限分块与无损日志预算)。

## 带事件记录的分批路径（2026-09-13）

原 `rml2018a-rf-campaign.py` 新增有限 `event-boundary-pilot` 后端，仍使用同一个
Controller 接收、共享原 HDF5、冻结模型及 `plan/acquire/infer/run/summary` 命令。
该 profile 使用已验收的 `devices/b210/tx-events.cpp` 程序，记录逐次 send 与异步事件时间；
普通 `standard` 仍走历史文件/FIFO发送，默认幅度与处理不变。

本次严格限定批次 `170 4266 4437 62122`，96条源行；分别跨源Z−20/−18、28/30、
OOK/4ASK及32QAM/64QAM边界。每行分别核对原Y/Z，不能将首行标签或Z复制给全批。
RF固定2455MHz、2.1MS/s、BW1.5MHz、TX60/RX50、峰值0.632455532、LO+250kHz，
接法为20dB衰减同轴。每批最多两次采集尝试，总TX≤32秒/67,055,616复样本、
RX≤2,097,120字节；日志/暂存预留256MiB。分片推理每源批次最多两次尝试，即使改变分片组合也不能重置预算，
总模型输入≤576、warmup≤16。旧全库预算表不能直接用作事件日志及三路推理的长期空间预算。

- `batch-N/attempt-0`、`attempt-1` 保存成功/取消/失败，不移动已有IQ或覆盖失败记录。
  `--retry-failed` 仅在已记录完整恢复后使用，最多补一次；硬终止缺少恢复记录时拒绝自动重试。
- `capture-complete.json` 绑定采集计划、原生IQ、TX事件、恢复记录及真实行号。
  已完成采集逐项重验后跳过；若在采集完成与写完成标志之间中断，从已完成尝试恢复标志，避免重发。
- 推理保存在 `inference-<分片哈希>/attempt-N/`，批次 `predictions.json` 引用该凭据。
  完整推理已结束但批次凭据发布中断时，可验证并补发布，不重跑模型。
  部分失败推理保留在原尝试中，预算内重试该分片；不将部分输出冒充完成。
- `summary` 按真实逐行Z、类别及其组合统计 source/raw/guard，并保留全部96条登记分母。
  未尝试、采集失败、待推理、同步失败、SINR无效和LO拒绝分别保留；估计有效率不筛选识别分母。
  `complete` 仅指有限profile；`whole_dataset_complete` 仍为false。
- LO处理固定运行且保留原始组，不按源Z、类别或预测选择分数更高的一路。拒绝校正时保留原始输入。

本次保存根为 `/var/tmp/sdrharness-dev/b210-rml2018a-boundaries-20260913`。
最初采集软件在汇总/推理衔接处有两项已修复问题；原始 `run-plan.json`、IQ、失败日志及旧软件字节保留。
`analysis-plan-v1.json`、`analysis-plan-v2.json` 是显式版本化的处理计划，后者绑定前者哈希、
所有已完成采集及当前软件；新增RF预算为0，模型仍受原尝试总预算限制。
仅允许修订本后端、campaign入口及共享推理包装，其他DSP/运行库/模型/源文件变更继续拒绝；
不能用分析修订覆盖射频计划或开启新的采集。

可用原模型venv的Python运行以下**已有结果复核**（无新增RF或推理）：

```bash
local-assets/amc-eval/runtime/venv/bin/python -B \
  jetson-agx/sdrharness/scripts/rml2018a-rf-campaign.py verify \
  --root /var/tmp/sdrharness-dev/b210-rml2018a-boundaries-20260913 \
  --analysis-revision --batch-indices 170 4266 4437 62122
```

`--analysis-revision` 选择最新连续编号且软件/父记录匹配的处理计划，只用于 `infer/summary/verify`；
与 `acquire/run` 联用拒绝。新建处理修订用 `analysis-plan`，要求全部登记采集已封存，
不会修改旧计划或重置推理尝试数。`verify` 预检全部选中采集后走完成批次跳过路径，并复核已有预测。
上述命令会创建本单元锁和scratch目录，交付清理后再次运行者须按项目规则清理本次创建的临时项。

新RF计划必须另行登记新源行与预算；这个边界fixture不提供任意批次/多日全库许可。
实测结果、两个失败及修复、复核和保留清单见
[分批验证](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13事件发射接入campaign与边界续跑)。

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

## 已封存八类保护间隔诊断

`diagnose-rml2018a-guard-anomaly.py --prepared <八类prepared.json> --inventory <父证据清单.json>
--output /var/tmp/sdrharness-dev/rml-guard-anomaly-<唯一标识>`使用既有模型venv的Python。
脚本只读父清单哈希保护的8批记录，复核原生seal/同步/LO结果；不读取源X、不执行RF或模型。
输出192点保护半段、64点局部残差功率、Hann频带积分及导频候选拟合。
拒绝批次的候选LO残差仅作事后诊断，不能充作通过的接收处理、SINR或识别输入；门限不变。
`--plot-only --output <同一输出根>`可用已安装Matplotlib的系统Python绘制保存的统计，
不需要向模型venv安装绘图库。两种调用均使用`-B`并将缓存/TMPDIR设到本单元开发scratch。
局部频谱峰的正弦投影只描述候选峰，不是穷尽多音归因或物理干扰识别。
方法及结果见[验证](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12八类保护间隔异常的离线定位)。

## 保护间隔LO块相量验证（实验入口）

`rml2018a_guard_tone.py`提供`guard-tone-block-margin-v1`，保留原v1总残差判定作为父结果。
原v1在保护间隔存在宽带突发时可能整体拒绝相消，即使LO相量仍可预测；新方法独立验证相量，
不改变旧10dB总功率门，也不把新旧两个10dB指标视为等价。
频率和幅度仍只由v1训练半段估计，不剔除任何保护间隔、不使用源X/类别/预测、不在留出半段重拟合。
每个192点训练/留出半段下变频后，分8个连续24点块，得块均值B及均值b；
`se = sqrt(sum(|B-b|²)/(7*8))`，要求每个半段`(|b-a|+4*se)/|a| ≤ sqrt(0.1)`。
该经验余量不是任意相关干扰下的校准置信区间。原幅度/相位稳定性及导频相干度≥0.95、残余CFO≤25Hz仍检查；
无法辨识、频率搜索边界、相位跳变或余量不通过均原样返回IQ，宽带/源噪声仍计入后处理条件SINR。
不能检测仅发生在payload中的LO变化，不承诺消除宽带突发。

新有限发射profile `qam-guard-pilot`仅允许批次66422/75296/66423/75297（64/256QAM交替），
AGX TX60/RX40、峰值0.632455532、源Z30，最多96源行/16秒TX/1,048,560接收字节。
`compare-rml2018a-pilot-timing.py`复用已有prepare/infer/verify入口，根据该父profile生成
source/raw/旧LO/新guard/新guard后timing五组，最多480模型窗口加2次warmup，650秒内部/680秒外部上限。
输出根继续使用`/var/tmp/sdrharness-dev/rml-timing-multiclass-<唯一标识>`。
每个处理平面分别记录，失败/invalid均保留；新四批源输入与旧八类不重叠。
实验推理是冻结模型工程对照，`recognizer_available=false`；普通campaign预处理及生产未安装此方法。
本次时序使识别86/96→84/96，继续保留为对照，不作为识别默认。
实机与已知失败事后回放见[验证](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12保护间隔lo修复及四批qam验证)。

## QAM接收增益配对

RX增益配对使用单独的`qam-rx-gain-pilot`，只允许66440/75314/66441/75315（64/256QAM交替），
TX60、峰值0.632455532、AGX，允许RX40或RX50；旧增益/八类/保护间隔profile仍只允许RX40。
每档各建新campaign，96行/16秒TX/1,048,560接收字节；配对总计8采集、192接收行（96唯一源行）、32秒TX和2,097,120字节。
匹配源X和尺度，但两档run ID/导频不同，独立执行原同步，不称逐射频样本完全一致。
比较脚本复用`compare-rml2018a-pilot-timing.py`入口，为此profile增加固定`wide_timing`第六组，
每档576窗口+2warmup，配对1152+4，两档GPU顺序执行；普通campaign未接入这些实验处理。
组合使用原冻结500kHz系数和原时序坐标，源保真门不变，并验证组合滤波需要的真实128点两侧空间；
前级校正或空间不足时保留上一处理结果和跳过原因，不使用补零冒充有效输出。
后续实验参考及每档识别边界见[配对验证](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12rx40rx50配对实机与识别对照)。

## 其余16类高源SNR有限profile

`--tx-level-profile remaining-high-snr-pilot --tx-host agx --tx-gain-db 60 --rx-gain-db 50`
限定2455MHz、峰值0.632455532、源Z30；发包schema为`rml2018a-remaining-high-snr-pilot-v1`。
仅允许batch8790/13227/17664/30976/35414/39851/44288/48726/53163/62038/70912/79787/84224/88662/97536/106411，
对应原始类ID1/2/3/6/7/8/9/10/11/13/15/17/18/19/21/23，发射前核对标签、Z和精确源行成员。
每类24行，总384行/64秒TX/4,194,240接收字节；拒绝其他主机、增益和批次。

复用`compare-rml2018a-pilot-timing.py`的prepare/infer/verify，输出独立
`rml2018a-remaining-high-snr-comparison-v1`，仅`source/raw/guard`三组，最多1152窗口+2warmup。
保留旧LO及保护间隔相消的审计，模型只执行这三组；不执行时序或宽带滤波。
校正被拒绝时保留原始载荷、明确原因与识别分母，SINR无效不等于未收到。
该profile是有限工程入口，不改变普通campaign峰值、预处理或生产能力。
前八类RX40与本profile的RX50不得合并成同条件24类准确率；
实际结果及三批保护区拒绝见[验证](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12其余16类rx50高源snr有限覆盖)。

离线保护区诊断复用`diagnose-rml2018a-guard-anomaly.py --prepared <prepared.json> --inventory <父清单> --output /var/tmp/sdrharness-dev/rml-guard-anomaly-<唯一标识>`。
剩余16类父schema只分析17664/35414/62038/97536，并核对16批TX日志；旧八类入口仍受原批次限制。
保留原同步和校正决定，固定LO候选残差仅作描述，不输出校正IQ或新增SINR/模型预测。
192点Hann/64点hop的保护区/导频邻域谱不能把导频、载荷能量解释成背景；
局部LO相干分解也不等于接收修复。`--plot-only`从保存的统计生成图，无源数据/硬件访问。

## 固定500kHz宽带滤波对照

固定宽带滤波实验入口为`compare-rml2018a-wideband.py prepare/infer/verify --output
/var/tmp/sdrharness-dev/rml-wideband-<唯一标识>`，使用既有模型venv和该根下预登记的`plan.json`。
仅接受已封存四批QAM父比较，按父证据清单核对文件及原prepare，截止500kHz的129抽头Kaiser8低通
在整个已旋转的原生缓冲上计算，再提取载荷；组合变体复用已冻结的导频时序，不重新估计。
源保真使用真实相邻源行、TX尺度和帧保护间隔，要求96条均满足相对误差≤0.003、功率比0.995–1.005，
否则不执行模型。源滤波/source_wide、实收滤波/wide、实收滤波加时序/wide_timing共288窗口+2warmup，
650秒内部上限；外部命令使用680秒timeout，缓存/TMPDIR放本单元scratch。
原始含噪X/Z仍是条件SINR参考，各处理平面和数字滤波单列，未修改普通campaign。
此固定候选只作事后工程比较，源保真与总识别数保持不代表每类/每行无退化；新样本确认后才能考虑采用。
结果见[验证](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12固定500khz滤波与时序对照)。

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

## 有限B210事件记录与控制源

2026-09-13新增[tx-events.cpp](../../devices/b210/tx-events.cpp)与
[validate-b210-event-controls.py](../../jetson-agx/sdrharness/scripts/validate-b210-event-controls.py)。
它们是独立实验入口，不替换普通campaign helper、系统UHD或生产Controller。
固定B210 serial2508504/channel0/A:A/TX-RX、2455MHz、TX60、2.1MS/s、BW1.5MHz、LO+250kHz，
包峰值≤0.632456、26,112点×321，要求精确GO后发送，首次设备时间安排为当前设备时刻+0.2秒。
4秒有限源、6秒feed期限、10秒GO期限、外层65秒保护；逐send/异步记录分别最多20,000条。
用户取消或零进展/超时仍写失败记录，不将主机已接受样本数称实际辐射样本数。

构建仅需要与现有libuhd4.1.0.5-3匹配的开发头文件；本次从同版本arm64 deb解包到feature根，
未安装系统包。deb URL/SHA、编译器/命令参数、库与二进制哈希见
[构建与实机证据](../evidence/B210_EVENT_CONTROLS_2026-09-13.json)。编译形式为：

```text
g++ -std=c++14 -O2 -Wall -Wextra -Werror -pthread \
  -I <feature>/build/headers/usr/include devices/b210/tx-events.cpp \
  /usr/lib/aarch64-linux-gnu/libuhd.so.4.1.0 -o <feature>/build/tx-events
<feature>/build/tx-events --self-test
```

新根必须位于`/var/tmp/sdrharness-dev/b210-event-controls-<唯一标识>`，先完成构建和离线测试；
使用既有模型venv的Python和`-B`调用`validate-b210-event-controls.py plan/acquire/analyze --root <feature>`，
临时/缓存指向该根scratch，执行acquire的外层timeout430秒。
plan固定停流前、零源取消、zero1、known1、known2、zero2、停流后7个动作，
6次RX均RX50/settle500ms/65,535点，精确RX总预算1,572,840字节，5次TX总上限20秒。
known源为固定seed的合成矩形脉冲QPSK，含已知导频/保护区；没有RadioML行或模型调用。
不重用已封存根，不因失败自动重试；普通RML发射仍走原入口。

每次事件文件保存configuration、GO、设备时钟查询前后AGX时刻、send和async、最终summary。
UHD设备时间缺失时为null；各次USRP初始化后的设备时间不假定共用纪元。
`nominal_sample_from_scheduled_start`只在有设备时间时计算，允许负值/超过名义包长，
尤其不能在欠载后把它当连续发送样本索引。P201没有首样本时间戳，RX launch/return主机包络不等于硬件采样边界。
没有UHD错误事件不证明RF模拟波形无异常；ACK只按设备事件语义报告。

初版analyze的FFT-bin候选单音残差仅作粗略描述，频点量化会留下拍频，不能用于可靠噪声底。
本单元的前缀细化单音/非LO频带统计及复核脚本在证据包中另作派生，不覆盖原analysis或改变接收质量门。
停流/全零控制仍可能有LO及其他能量；known载荷的宽带功率是信号，不能当背景。


## 四类RadioML带时间事件复测

[rml2018a-event-retest.py](../../jetson-agx/sdrharness/scripts/rml2018a-event-retest.py)为本次独立有限入口，
复用事件控制的收发执行器和既有冻结模型推理/复核代码；普通campaign CLI/default不替换。
`event-retest-pilot`只接纳batch17680/35430/62054/97552，依次BPSK/32PSK/32QAM/FM，
每类24行、源Z30；本次与95份旧campaign源记录的1032个唯一行无重叠。
严格保持2455MHz、TX60/RX50、20dB同轴、峰值0.632455532、2.1MS/s、BW1.5MHz、LO+250kHz及原guard门限。
四次TX至多16秒/33,527,808个主机接受复数样本；前后停发控制加四次实收共6×65,535点，
精确原生IQ预算1,572,840字节。288个source/raw/guard单窗模型输入加2次预热；没有时序/额外滤波。

使用既有venv Python `-B`，设置`PYTHONDONTWRITEBYTECODE=1`、`OPENBLAS_NUM_THREADS=1`及feature临时/缓存路径。
新根格式为`/var/tmp/sdrharness-dev/b210-rml-event-retest-<唯一标识>`，执行顺序：

```text
rml2018a-event-retest.py plan --root <新根>
rml2018a-event-retest.py acquire --root <该根>
rml2018a-event-retest.py prepare --root <该根>
rml2018a-event-retest.py infer --root <该根>
rml2018a-event-retest.py verify --root <该根>
```

plan核验完整原HDF5 SHA、所选X/Y/Z及行级原始哈希，绑定软件、runtime、profile和既有事件二进制/构建receipt；
不再编译或复制二进制。acquire重新核验后仅一次执行，有owner锁及started排重，执行器400秒alarm/单次TX65秒外层限制。
直接停止为向`started.json`中本单元PID发送SIGINT；接收忙时仅用Controller generation cancel，随后核对完整恢复。
推理650秒alarm，建议外层680秒；使用同一GPU lease及空闲Spark暂停/恢复机制。
同步失败仍保存24条源预测和raw/guard缺失，LO拒绝保留未经该校正的载荷；不按识别结果放宽门限或重采挑样。
这里“新行”指本次相对封存campaign父记录的比较，并不授权用同一个profile反复试到成功。

事件ACK/接受样本数不等于物理连续性证明，P201未与B210样本时钟映射；条件SINR保持工程定义。
模型采用冻结epoch10、FP16 autocast/FP32权重的单1024窗工程对照，`recognizer_available=false`，名称provisional。
本次计划、源行、接收会话、288输入/预测及清理见[四类复测证据](../evidence/RML2018A_EVENT_RETEST_2026-09-13.json)，
[实际结果](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13四类新源行带事件复测)。

## 统一24类RX50有限确认

同一[rml2018a-event-retest.py](../../jetson-agx/sdrharness/scripts/rml2018a-event-retest.py)新增独立
`uniform24-high-snr-pilot`，旧四类profile仍只允许原四批。新profile按原始ID0–23顺序，每类固定24条Z30，
batch为`ceil((class_id*106496+102400+3072)/24)`，总576条；实际X/Y/Z和源行/包SHA由新plan核验。
检查既有campaign源记录及带事件实验plan中的行号交集，拒绝复用旧源行；不根据源模型预测筛选行。

```text
rml2018a-event-retest.py plan --profile uniform24-high-snr-pilot --root /var/tmp/sdrharness-dev/b210-rml-uniform24-<唯一标识>
rml2018a-event-retest.py acquire --root <该根>
rml2018a-event-retest.py prepare --root <该根>
rml2018a-event-retest.py infer --root <该根>
rml2018a-event-retest.py summary --root <该根>
```

`--profile`仅plan使用，后续从封存plan读取；使用相同venv `python -B`与feature临时/缓存路径。
参数保持2455MHz、TX60/RX50、20dB同轴、峰值0.632455532、2.1MS/s/BW1.5MHz、LO+250kHz、原guard门。
24次TX最多96秒/201,166,848主机接受复数样本；24次实收和前后停流共26次RX、6,815,640字节。
每次65,535点/settle500ms，单次TX65秒外层期限、整体采集900秒；预留512MiB覆盖有界事件日志、IQ、报告和缓存。
直接停止路径及恢复沿用四类入口；推理650秒、建议外层680秒，最多1728个单窗输入加2预热。
它是有限工程确认，不会自动接续全库或低源SNR，也不替换普通campaign/生产默认。

`summary`先确定性重放原生/同步/guard/质量及输入/预测关联，再输出逐类source/raw/guard完整分母、缺失预测、
SINR有效数/原因、质量有效性与识别的交叉计数及纠正/回退；无效SINR不会删去识别行。
`verify`可单独执行同一复核，不重跑模型；再次summary要求结果完全一致。AM的解释遵守
[指标报告边界](RML2018A_RF_REPRODUCTION.md#5-am单边带的条件sinr与识别报告2026-09-13补充)。
实际执行及逐文件保留依据通过[实验记录](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md)和[evidence索引](../evidence/README.md)按需读取。

## 四类低源SNR分层

`rml2018a-event-retest.py plan --profile four-class-snr-strata --root /var/tmp/sdrharness-dev/b210-rml-snr-strata-<唯一标识>`
登记BPSK/16QAM/64QAM/FM（ID3/12/14/21）在源Z20/10/0/−10/−20各24行，共480行。
随后使用同一入口的acquire、prepare、infer、summary；解释以源Z分组，不把条件接收SINR当分组真值。
固定Z执行顺序0/20/−20/10/−10，类别顺序随每档循环移位，具体20批顺序在plan中封存；不按结果挑选或重排。
源batch为`ceil((cid*106496+((Z+20)/2)*4096+3072)/24)`，读取时校验真实X/Y/Z与该固定单元一致。
旧Z30 profiles保持原样；新质量记录使用每行真实Z，summary增加by_source_snr及每个类别/源Z单元的统计。

沿用2455MHz、TX60/RX50、峰值0.632455532、20dB同轴、2.1MS/s/BW1.5MHz和LO+250kHz、原guard门。
20次TX最多80秒/167,639,040主机接受复数样本；加前后停流共22RX/5,767,080字节，1440模型输入加2预热。
900秒采集/650秒推理期限、单TX65秒、512MiB余量和完整停止/恢复流程同统一24类入口。
只使用原数据集不同Z的原始IQ，没有额外合成payload噪声；导频保持固定已知序列，不代表盲检测在相同低SNR下通过。
不同Z来自不同原始行，不能当作同一个干净信号的加噪配对；旧Z30单元不拼接进此次分层成绩。
低Z时条件估计中的名义源噪声项会占主导，估计接近源Z并不能单独证明链路更干净或物理SINR已校准。
本单元不完成24类×全部26个SNR档位或全库执行；以[验证记录](../validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md)和[evidence](../evidence/README.md)登记实际结果。
