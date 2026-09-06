# B210/P201 源参考复偏置双向对照预登记

基线4bb14681154e3884449c0af228ab01999ac6e490。继续既有NX+B210天线2.4 GHz/P201
接收联调，复用有限TX、RX40、source分析、相位速率及冻结Backend。本单元只检验
已知源条件下的复偏置假设，不改变生产RF-v1、模型、准入或任何永久射频设置。

## 有限RF与数据

AGX/NX目录：/var/tmp/sdrharness-dev/b210-affine-tone-906f/ 和
/var/tmp/sdrharness-dev/b210-affine-906f/。最多两个burst、无参数重试：

- B210 serial2508504，RF A/TX-RX/channel0，LO2.440 GHz、TX gain70、peak0.2。
- tone为+100 kHz SINE、2.5 MS/s、BW500 kHz、25000000样本，名义10秒。
  P201 RX1/RX0/A_BALANCED，中心2.440 GHz、2.5 MS/s、BW1 MHz、gain40。
- RML为已有四个train行102400/102401/102403/102404，2.1 MS/s、BW1.5 MHz、
  21000000样本，名义10秒；RX同rate/BW、gain40、中心2.440 GHz。tile hash
  c95ac58c1fd91ef4da992622dbdf70a9bc5884d0941419083451473a052f534e 必须不变。
- 两种波形各启停前/中/后65535 ci16、settle500ms、timeout1000ms，每次262140
  bytes/估计1500ms，总RX1572840 bytes、TX名义20秒上限。先通过tone三对照及
  既有20 dB门再发RML；失败停止，不扩大预算。
- 每次打印计划、空间（本次IQ+8 MiB）、路径和generation stop；复用Controller
  cancel、NX owner核对后SIGINT/TERM、35/65秒远端timeout、nsamps/FIFO限量。
  每次恢复原RX状态，核对daemon、子进程/FIFO和P201 transient清除。

原始IQ保存到本单元分析结束，之后精确清理；不复制到应用库，不删除用户语料。
不读取新数据集行或locked test，不训练，不运行完整精度或标签验收实验。

## 前段估计、固定后段验证

source-only关联复用独立tone CFO、source自身99%频带、前7窗包络lag及既有
0.5/0.2/0.3对照门。只有source门通过才解释复偏置拟合；否则只保留失败和原始对照。
所有新估计仅使用前7×4096点，后8窗只用于验证；模型固定使用第8窗offset28672。

1. 估计参数时单独截取前7个原始窗，再做tone CFO补偿、FFT带限和包络lag估计，
   保留DC、不重采样，后段不能经全长FFT影响系数。完整65535点的对应变换只用于
   固定模型输入/后段验证，绝不回用于参数估计。
2. 用前7个source-reference复系数相位斜率估计剩余频差。要求各窗复相关≥0.2、
   前段相位RMSE≤0.2 rad、|剩余频差|≤200 Hz，记录512.6953125 Hz混叠周期。
   不满足则跳过依赖该估计的组；不搜索别的unwrap或阈值。
3. 将该剩余频差一次性补偿，再以前7窗同时估计`y=h*x+b`（复增益h和复常数b），
   并独立拟合无偏置`y=h0*x`基线。设计矩阵condition≤1000、|h|>1e-6且系数有限。
   这是已知源工程通道诊断，不是模型训练、通用盲补偿或生产校准。
4. 固定系数报告后8窗无偏置/仿射残差功率比、去中心化相关，以及补偿后的包络。
   残差不标为AWGN信噪比；不因某窗表现好而选窗。保留source真实非零均值，
   不用“直接减去接收均值”替代b，否则会删掉源本身的载波。

模型最多七组/28实验窗+Backend固有2warmup：
1. 带限对齐源x；2. 纯增益/相位源h*x；3. 加偏置的源h*x+b；
4. 原始实收；5. tone CFO+带限实收；6. 再补偿剩余频差的实收y；7. 去偏置实收y-b。
系数门失败时相应组明确不可用，不强行创建。所有组继续共享RMS/顺序四窗、
epoch-10、FP16 autocast+FP32权重、FP64 mean-logit，不改生产RF-v1。

保存全部准备参数及模型输入hash后才加载模型，推理前重算一致性，180秒进程上限
和私有GPU租约。即使出现“源加b变18、实收减b变0”，也只支持本源/本次capture的
双向诊断，不定位B210或P201硬件根因，不证明未知信号可以这样补偿。

不根据模型结果追加发射、改变系数或阈值；数字ID可信、名称provisional。
recognizer_available=false、独立标签0；50 dB、V1b/V2/V3/A1保持未完成。
测试/实机验证、精确清理后更新权威checklist，review diff，聚焦commit并push。


## 源关联门失败后的明确范围变更（模型输出前）

本次固定包络门实测0.339667<0.5，原始source_control_passed=false及默认三组
准备记录保留，不修改阈值或宣布源关联通过。前段各窗复相关约0.67、相位RMSE
0.0201 rad，剩余频差−83.65 Hz、复偏置拟合可计算。为继续检验假设，在首次模型
调用前另登记七组**后验探索**，覆盖上文“失败只保留原始对照”的执行范围；最大
28窗和两个burst预算不增加，不放宽射频质量、剩余频差、矩阵条件或生产门。

工具必须显式传--exploratory-source-failure，保存独立exploratory准备/结果和
原失败准备hash；source_control_passed仍为false、qualified_bidirectional_validation
仍为false。共用一次inference-started receipt，不能再执行默认三组造成额外预算。
即使双向预测或残差改善，也只能作为来源门未通过的探索结果，不勾选“合格双向验证”
或科学/生产准入。本变更不是此前预登记通过的证据，原失败不可覆盖。
