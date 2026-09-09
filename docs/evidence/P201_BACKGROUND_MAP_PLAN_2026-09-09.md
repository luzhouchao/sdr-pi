# 2.4GHz外部背景分布：连续覆盖扫描与独立复测登记

基线a9a4d73、分支codex/sdr-improvements。用户要求查清干扰分布，并确认
P201 RX1已接回原天线，N210（USB B210 serial2508504）保持负载和停发。
本轮只做有限RX/AGX分析，不启动发射、模型、Planner、训练或locked-test。

发现矩阵：70个中心为2400600000+round(i*82300000/69) Hz，i=0…69。
中心范围2400.6…2482.9MHz，相邻最大1192754Hz，小于1.5MHz带宽的80%。
按每点中心±600kHz分析区间，覆盖2400…2483.5MHz全段，无设计频率空隙。
三次独立升序扫描，每次70点，不宣称同时覆盖整个频段。

全部点使用RX1/RX0/A_BALANCED、2.1MS/s、BW1.5MHz、manual20dB、settle500ms、
65535点ci16_le、aggregate1、capture deadline1000ms。较此前40dB减少20dB
增益以保留强信号余量；所有新轮次/复测同为20dB，不直接比较旧40dB幅度，
不自动放宽削顶门或失败后自行降增益重采。

发现结束后固定选2455MHz参考，加按三轮raw128点RMS p95中位数排序的四个
活动较强中心；与已选中心至少间隔4MHz，同分优先较低频率。各点各复测三次，
按固定选择顺序重复。稀疏复测使用单点Controller调用，避免绕过多点覆盖门。
全轮上限210+15=225点，每点262140字节/31.207ms，总58981500字节IQ、
7.022秒分散有效采样。发现每次估算105秒预算，小于原300秒规则；外部调用
deadline300秒，复测调用15秒，runner整体1200秒；预计约300秒，实际耗时记录。

AGX根`/var/tmp/sdrharness-dev/p201-background-map-20260909d/`，18个调用目录
capture-00…capture-17，临时scratch限于本根。P201每个generation/point的
`/tmp/sdr-agent-dev/agx-sweep-<generation>-<index>`精确路径在各调用前
audit.json及标准输出登记。总量与实测AGX可用空间在采集前保存，每次再次
检查空间；NX没有暂存。保留旧证据不改写、不额外复制IQ。

先核对一个预期sdrd/安装哈希、RX1身份、空闲连接与scan/buffer；NX前后核对
身份、无发射进程及USB占用。SIGINT/SIGTERM直接走专用cancel，generation
见audit.active；忙时不另开HEALTH。每次调用（发现轮包含70点）结束恢复
两路全状态、scan/buffer并轮询核对，确认所有相应P201目录消失。每点原生
报告要求字节/样本/身份/健康/timeout及零已报告drop/overflow/clipping。
失败立即结束本矩阵，保留失败，不选择性重采。

AGX分析：128点RMS分布及时间序列；1024点Hann分帧谱按RATE*sum(window²)
归一成ADC²/Hz，不减DC；中央±600kHz按25kHz频带报告均值和最大帧能量。
寻找最强频率时排除中心±10kHz，避免把DC当信号；谱图明确标出该位置。
相对突发比例为观测128点块功率超过本次中位数10倍的比例，只是描述，
不是校准噪声、协议占空比或正式验收门。频率扫描的轮次/时间不可视为同时。
没有协议标签，不能只按频段把活动认成Wi-Fi/蓝牙或指向具体设备。

保留重放整个分布和复测选择所需IQ、SigMF、原生报告/计划、总审计和派生
图表，登记各文件字节/SHA-256及source/capture/request/session、删除方法。
本轮日志/scratch/运行标记清理并验证，旧三阶段证据保持。只勾选实际完成
的分布实测，不提升模型、独立标签或生产能力。
