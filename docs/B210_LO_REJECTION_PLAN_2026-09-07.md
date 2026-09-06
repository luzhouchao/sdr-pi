# 本振泄漏修复：固定分离与滤波，执行前计划

基线f7171ae。使用p201-sdr-workflow/connect-nx已核验流程；继续同一1024点train
行102400，原始hash3c2c5d5606a7d1a8721511afddd49ca8c2183968d59b38a4e099754646cf0922，
payload c8e3d54629eb7dde75e6a49554090f570522e7b438d2602dce85a18cd1d771f9。
只修复已确认的LO相关污染；背景/相位问题不假定已解决，不改变生产RF-v1。

## 工程修复及冻结判据

TX采用已经验证的+250 kHz LO offset，目标2440 MHz。AGX使用固定257-tap实系数
对称FIR：2.1 MS/s、cutoff175 kHz、Kaiser beta8、系数和归一为1。有效样本舍去
两端各128点，标记原始sample offset；不去均值、不重采样、不使用已知源b扣除。
设计验证：|f|≤140 kHz幅度偏差≤0.001，|f|≥210 kHz衰减≥80 dB；该源经相同
FIR保留功率≥99%，否则本候选不执行RF。这个窄带工程模式不适用于任意未知带宽，
不能冒充生产RF-v1。2.4GHz LO偏移本身不能从当前1.5MHz RX带中消除泄漏。

实收前16384点仅用于既有单1024源alignment/M0估计，拟合仍基于原始IQ、保留源
均值并分离源增益/载波截距/RX DC。滤波不使用这些系数；它们只构造对照预测。
固定评估块从17408开始每4096点共11块；模型仅考虑offset32768的固定4096点，
不因结果挑换窗口。滤波通过有限卷积读取各端128点halo，不跨参数区估参。
全部有效65279点和所有统计段保留；参数估计从不使用后段滤波数据。

修复门：偏移组在预期LO附近±500 Hz的前段Hann谱功率下降≥40 dB（区间去掉
两端128，报告窗函数泄漏限制）；源保留功率≥99%；三组均完成native质量/身份/
停发恢复。零偏移负对照的源中心泄漏不应被低通消除。
来源/背景模型门按**每次预先固定的4096点块**单独判定：四个1024点的中心化
源相关均≥0.9；仅复增益/已估CFO预测的归一化残差功率≤0.2；同offset滤波后
停发前/后功率均比during低≥10dB；source alignment可用，偏移组另需修复门通过。
这些是本次已知源工程诊断门，不是校准准确率/拒识；所有组含失败与跳过均报告，
不能以通过子集声称全矩阵/长期可靠。全段11块保留相同指标但不选取模型窗。

## 有限实机与模型

一次历史单音控制，随后RML顺序zero(0)/fix1(+250k)/fix2(+250k)，各一次不重试。
单音固定25000000点/10秒、2.5MS/s、TX BW500k/RX BW1M、+100k tone。
RML每次20480×1024=20971520点、FIFO167772160 bytes、约9.98644秒/10秒预算；
TX gain70、peak0.2、BW1.5M、spb1024、B210 serial2508504、A/TX-RX/channel0。
P201全部RX1/RX0/A_BALANCED、gain40；中心2440MHz、RML2.1MS/s/BW1.5M。
每次停发前/中/后各65535 ci16、settle500ms/timeout1000ms，12次3145680 bytes。
NX65秒/单音35秒timeout，单次runner180秒、总矩阵800秒；至少64MiB空间并每次
打印计划/字节/目录；Controller直接cancel、NX身份核验stop、P201状态逐次恢复。

AGX协调根 /var/tmp/sdrharness-dev/b210-reject-907m/；AGX/NX采集根分别
b210-reject-tone-907m、b210-reject-zero-907m、b210-reject-fix1-907m、
b210-reject-fix2-907m，全部位于 /var/tmp/sdrharness-dev/ 下。
P201仅本次generation目录。旧根和旧实收均已清理，不复用旧数据假称本次实收。

通过本次固定模型窗门的case才加载冻结epoch-10 FP16 autocast/FP32权重模型：
每个case固定4种输入（对齐原始源、同滤波源、RX原始、RX滤波），各4窗mean logits；
最多48实验窗+一次2窗warmup，300秒外层timeout。使用现有GpuLease、RF-v1共享
RMS/四窗/权重，保留完整logits、输入hash、ID/名称provisional，拒绝生产classified。
源的alignment/增益/频率仅作评估预测，模型源输入只循环对齐，不借助RX去偏置；
全部结果为单源工程对照，不代表独立标签或总体准确率。若所有模型窗门失败，
模型/warmup为0；仍记录滤波性能与失败原因，不偷换阈值。

## 验证和交付

测试固定DC/频带保真、分离LO抑制与零偏移负例、FIR边界/局部依赖/非法输入、
固定窗门和sealed输入拒绝篡改；复用有限TX/捕获/identity回归。工具不建新结果库。
适用实机/模型验证后封存有界审计/图/源与IQhash，精确清理本单元IQ/缓存/构建和
NX/P201残留，不动用户结果。checklist如实拆分泄漏修复与背景/相位/分类结果，
review diff、聚焦commit并立即push。独立标签0、recognizer_available=false保持。
