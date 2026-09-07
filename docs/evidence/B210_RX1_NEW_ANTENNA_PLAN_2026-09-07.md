# 新双频天线接回RX1：有限同源重试登记

基线b23fe92。用户确认把新2.4/5GHz双频天线从RX2移回RX1，并要求重试。
本轮优先级按此新指令前移；旧恢复CLI兼容性仍单列，不混入本提交。
沿用既有授权NX+B210天线发射、P201 Linux/IIO RX1/RX0/A_BALANCED、AGX处理。

只做一次预先固定矩阵：一个tone参考，随后r1/r2/r3三个相同RML源发射，每次
都有停发前/发射中/停发后三次65535点采集。中心2455MHz，RX gain40dB、
settle500ms、timeout1000ms；tone用2.5MS/s、RX BW1MHz、100kHz单音、TX BW500kHz、
幅度.2、TX gain70、25,000,000点（10秒）。
RML用2.1MS/s、BW1.5MHz、TX gain70、同一train row102400，数字幅度.2，
单个1024点为发送单位，20480次重复，共20,971,520点（约9.986秒）。
RML TX LO偏移+250kHz（请求2455.25MHz），不提高幅度、不换频、不调整门槛。
NX仍只作外部信号源，不做推理；型号/通道沿用UHD验证的B210 serial2508504、
channel0、TX/RX。不因外壳标签猜测型号。

最大12次RX，共3,145,680字节；最大4次有限TX、87,914,560点、名义40秒。
协议/SSH时间预算复用已有单组180秒timeout和finally停止/恢复，整矩阵上限
4×205秒。AGX先检查空间；所有计划/实际路径在每次capture前输出。
协调目录`/var/tmp/sdrharness-dev/b210-antenna-907t/`，四组为同父目录的
`b210-antenna-tone-907t`、`b210-antenna-r1-907t`、`...-r2-907t`、`...-r3-907t`。
NX暂存使用同名路径；P201临时采集为计划generation生成的agx-sweep目录。
停止走现有runner的SIGTERM、generation cancel与NX所有者PID/FIFO回收；每次
要求radio恢复、远端TX退出、SDR瞬时文件消失。结束后核对第二路gain未被改动。

复用已保留的.2源payload/计划（hash c8e3d546…），不打开数据集、locked test或
重训。RF-v1/epoch-10/FP16维持冻结。固定257-tap/175kHz/Kaiser8工程FIR和
offset32768起的4096点评估块保持；四窗相关≥.9、残差≤.2、两次停发余量≥10dB、
LO抑制≥40dB、源保留≥99%，全部通过才产生模型输入。失败组不挑窗重试。
每合格组只比较原始源/FIR源/原始RX/FIR RX四种输入，三组最多48实验窗+2 warmup，
GPU租约按既有实现取得/释放；模型输出依旧uncalibrated实验结果、名称provisional。

背景统计复用128点RMS分段，保留全部组的raw/FIR p50/p95/p99/max及事件区间，
与旧2455同参数包作历史描述。天线、时间和sdrd版本均有变化，不能把差异全部
归因于天线，也不是RX1/RX2同天线对照，不据此宣布准确率或生产准入。

仅保留复现本矩阵必要的最小sealed IQ/元数据/发射来源、完整hash与有界分析，
采用既有feature证据机制；源payload尽量硬链接复用，不另建存储。清理构建、
测试、缓存、NX/P201副本和重复日志，记录保留/删除的确切路径、字节、用途及
人工删除方法。更新checklist、review diff、聚焦commit后立即push。
