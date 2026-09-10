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

固定 433.920 MHz、2.1 MS/s、TX/RX BW 1.5 MHz、TX70/RX50、TX 峰值 0.2、
TX LO offset +250 kHz；使用已报告的433MHz天线，P201身份为 RX1/RX0/A_BALANCED。
不支持在命令行任意改频率/增益，不无衰减同轴直连。

每批最多24个独立1024点样本，各自按复数峰值缩放，前面加入由 run/batch 派生的1024点
QPSK同步标记，两端各256点零保护。完整帧26112点；重复321次，总发射8381952点，
约3.9914秒，有限上限4秒。重复用于覆盖异步RX启动，**不是每个原始样本只发一次**。
P201每批接收65535个复数ci16样本（262140字节），500ms settle、1000ms点超时。

同步只使用标记，先固定129-tap Hamming、500kHz低通检测，再估计时刻/CFO/公共相位。
该滤波器仅用于检测，**送入模型的payload不做此低通或自适应陷波**；不使用真实类别、
模型输出寻找对齐，也不减去DC。同步门未过的批次不产生实收预测。
若最清晰标记位于接收尾部、后续payload不完整，使用已知重复帧长度定位前一完整payload；
报告同时保存锚点标记与payload前标记的位置/得分，不将受干扰标记的得分冒充通过。
单个源/实收1024点窗口均做复数RMS归一化，沿用冻结epoch-10、FP16 autocast/FP32权重。
这是工程单窗比较，区别于生产RF-v1四窗/mean-logit准入。
Z仅为原始数据集的标称SNR，不是当前空口接收SNR。

| 项目 | 全库预算 |
| --- | ---: |
| 批次 | 106496 |
| 原生实收IQ | 27,916,861,440字节（约26GiB） |
| 元数据和预测预留 | 13,958,643,712字节（约13GiB） |
| 单批源包瞬时副本 | 208896字节 |
| 累计TX上限 | 425984秒（约4.93天） |

总输出预留约39GiB，另留缓存和失败重试空间；重试保留旧证据，会增加占用。
初始代码的10秒/批估计尚未验证，实际耗时以验证记录为准，不能用空口样本时长代替SSH、
设备初始化、恢复与推理耗时。全量属于多日运行，此工具尚无全库长期稳定性验收。

## 在AGX执行

使用已有运行环境，所有路径绝对化。以下 `plan` 仅读取/校验约21.45GB源文件，不发射。
结果根必须为开发根下一个新的 `b210-rml2018a-` 开头目录，名称仅字母、数字和连字符。

```bash
cd /home/jetson/sdrharness
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1
RML_PY=/home/jetson/sdrharness/local-assets/amc-eval/runtime/venv/bin/python
RML_RUNNER=/home/jetson/sdrharness/jetson-agx/sdrharness/scripts/rml2018a-rf-campaign.py
RML_ROOT=/var/tmp/sdrharness-dev/b210-rml2018a-full-20260910
"$RML_PY" -B "$RML_RUNNER" plan --root "$RML_ROOT"
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

汇总分别列出已采集、待推理、未尝试、实收预测、混淆矩阵及按源SNR分组统计。
`received_accuracy`只针对已有实收预测；`end_to_end_success_fraction`以已采集行为分母，
待推理和接收失败都不算成功。`complete`表示所有源行已有工程结果（允许sync_failed），
只有`all_rows_received_and_inferred=true`才表示全库每行都获得实收预测。
失败重试历史不重复进入最新汇总。

原始IQ/权重/运行制品不入Git。要删除一个campaign，先确认runner/NX/P201均已停止并恢复，
核对run-plan与根目录真实路径，再按对应保留清单逐个删除该根；不清空公共开发根，
不删除既有数据集和其他实验。验收保留包的精确路径、哈希、大小和人工删除方法见
[库存](../evidence/RML2018A_FULL_RF_CAMPAIGN_EVIDENCE_2026-09-10.json)。
