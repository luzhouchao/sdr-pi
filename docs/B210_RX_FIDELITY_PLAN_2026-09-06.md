# B210/P201 实收保真度与补偿对照预登记

基线cf03ed696c5f53eab025af353ba973019f830c7e。用户继续授权既有NX+B210天线/
2.4 GHz/P201联调。沿用连接skill、原生有界RX、已有有限TX/source分析/模型Backend。
本单元仅工程诊断，不改变冻结epoch-10、FP16/FP32权重、生产RF-v1及准入状态。

## 有限RF预算

两端目录各为 /var/tmp/sdrharness-dev/b210-fidelity-tone-906e/ 和
/var/tmp/sdrharness-dev/b210-fidelity-906e/。最多两个burst，不追加参数重试：

- 单音：B210 serial2508504、RF A/TX-RX/channel0、LO2.440 GHz、+100 kHz SINE，
  rate2.5 MS/s、BW500 kHz、gain70、amplitude0.2、25000000样本（名义10秒）。
  P201 RX1/RX0/A_BALANCED，中心2.440 GHz、rate2.5 MS/s、BW1 MHz、gain40。
- RML：同一B210/LO/gain，复用train四行102400/102401/102403/102404（ID0、标称
  SNR+30 dB），tile SHA c95ac58c1fd91ef4da992622dbdf70a9bc5884d0941419083451473a052f534e；
  rate2.1 MS/s、BW1.5 MHz、复数peak0.2、21000000样本（名义10秒）。RX同rate/BW、gain40。

每种波形停发前/中/后各65535 ci16，settle500ms、point timeout1000ms，每次最大
262140 bytes/估计1500ms，总6次RX上限1572840 bytes、TX名义20秒。每次记录计划、
空间（至少本次IQ+8 MiB）、目录和generation stop。单音三个捕获与原20 dB启停门
通过后才进行RML；失败停止，不扩大功率、时长或样本数。

复用直接Controller cancel与按精确cwd/argv核对的NX owner PID stop；远端tone/
RML timeout35/65秒和nsamps/FIFO feed双重有限，最终验证子进程/FIFO消失。每次恢复
实际开始前RX状态、sdrd PID/hash不变，P201 transient在AGX收到后清除。

## 在模型输出前固定的分析

1. 独立tone估计CFO，source自身99%功率定义对称频带（复用既有方法）。RML前7个
   4096窗固定包络lag；后8窗与停发对照使用同一lag，沿用0.5/0.2/0.3工程对照门。
   门未通过也保留原数据和失败；其后离线结果只能按来源关联不足解释，不据模型挑窗。
2. 本轮所有模型组固定使用第8个4096窗（offset28672），原始IQ/hash留到分析结束。
   对完整65535点做实验变换，再截取这个中部窗，避免每1024点重置移频/滤波边界。
3. 预定义四种实收路径：raw、仅CFO补偿、仅source频带理想FFT带限、CFO后带限。
   FFT带限保留DC，不重采样；属于离线实验，不能进入现有生产RF-v1。
4. 以对应raw/带限源的重复序列，分别对direct和conjugate模型做复标量最小二乘
   y=h*x；只用前7窗拟合h。报告前段复相干度、后8窗每窗复相干度和固定h残差比。
   残差包含噪声、干扰、模型失配和剩余频差，不能叫独立SNR或识别准确率。
5. 仅当CFO+带限路径的direct前段相干度≥0.2，才由该h的arg得到一项固定相位
   补偿；否则明确跳过该模型组。不根据模型结果、conjugate拟合或后8窗选相位。
   报告接收功率在source频带内/外的比例；不凭占比给外部信号贴类型标签。

模型输入最多七组：对齐源、带限对齐源、实收raw、CFO、带限、CFO+带限、可选的
CFO+带限+固定相位。最多28实验窗+Backend固有2warmup，共享RMS/四窗公式不变，
FP64 mean-logit后softmax。先保存source-only准备记录及所有模型输入hash；推理前
重算并严格比对，再加载冻结Backend，180秒进程上限，私有GPU租约覆盖加载/推理。
所有变换明确标记，不冒充未变换实收或50 dB运行profile，不写生产DTO/应用结果库。

不因raw已经变成ID0或补偿无效而重新发射。结果只说明本组数据；若某补偿得到0，
也不据此直接发布生产预处理。train/已查看session/day均不能计入V1b独立标签。

源码、测试、bounded审计/图表/hash保留；IQ、派生数组及模型tensor仅在本单元私有
目录/内存使用。测试和适用实机验证后停止feature进程、精确清理两端目录、更新
权威checklist、review diff、聚焦commit并push。用户原语料和应用结果不清理。


## 结果后的只读补充说明

六个预登记模型组均已执行（固定相位组因前段相干度<0.2跳过），结果后发现“单窗
复相关较高、跨七窗固定相位拟合很低”。补充只读source-referenced相位速率诊断：
按每4096窗估计一个复系数，只对前7窗相位unwrap并拟合直线，报告后8窗相位预测
误差及512.6953125 Hz的相位速率混叠周期。另报告固定第8窗的归一化包络分位数并
绘图。这些是明确后验统计，不修改原准备记录、原模型输入或判据，不追加模型调用
或发射。相位速率只作为后续假设，不能宣称已测得通用LO误差或已验证补偿成功。
