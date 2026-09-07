# 同源 IQ 频差、相位与加噪敏感性预登记

基线3743c3b25edfd00ac53fbf844b881746e1666565；本独立单元只在AGX离线执行，TX/RX
次数均为0，不连接或改变NX/B210/P201。目标是定位上轮“源ID0、实收ID18”差异的
可能机制；上轮实收IQ已按规则清理，本轮没有实收补偿的因果证明。

复用已有导出器，只读train.npy成员和原四行102400/102401/102403/102404的X/Y/Z，
不新增行、不读locked test、不训练。导出tile须匹配
c95ac58c1fd91ef4da992622dbdf70a9bc5884d0941419083451473a052f534e。
上轮审计SHA256为1d3c01a3f26e3661295b2a72facd87d3d72d1510bb279e1afd3344fbbc84b432；
从其读取lag3152及单音频差+3532.4635690852447 Hz。频差没有在本轮实收重新测量。
两个未扰动组的模型输入bytes必须复现该审计中的原始/对齐源hash。

在打开本轮模型输出前固定七组，每组4096点/四个顺序1024窗：

1. source_original：原四行顺序。
2. source_aligned：循环roll3152，与上轮源对齐组相同。
3. aligned_cfo_positive：在对齐源上乘exp(+j2πfn/Fs)。
4. aligned_cfo_negative：在对齐源上乘exp(-j2πfn/Fs)，作为符号对照。
5. aligned_phase90：仅乘j，保持幅度包络。
6. aligned_awgn20：对齐源加复高斯噪声，源总功率/新增噪声功率为20 dB。
7. aligned_awgn10：与上组同一个噪声实现，只改变尺度，比率为10 dB。

Fs=2100000，f取上述独立历史tone值，n=0..4095连续跨四窗，不在窗边界复位。
初相为0只是受控设定，不冒充实收未知初相。高斯噪声使用NumPy PCG64 seed20260906，
生成4096×2单位正态并按实测complex RMS归一化，同一噪声向量用于两个加噪组。
源自身数据集标称SNR+30 dB；这里20/10 dB仅指“新增噪声分量”相对源总功率，
不是数据集重新标注的SNR，也不是前轮46.41 dB谱峰/噪声估计的复现。

所有扰动先作用于原始source，然后复用已通过golden的共享RMS/四窗normalize。
复用现有RfV1Backend、冻结epoch-10/FP16 autocast/FP32权重、FP64 mean-logit。
最多28个实验窗，加Backend固有2个warmup；GPU租约覆盖加载和推理，外层180秒
timeout及SIGINT/TERM退出。无参数搜索、无结果驱动扩充案例、无温度/拒识拟合。

本轮对照结论只描述这四个已训练样本对单独变化的敏感性；不把合成组称为实收，
不宣称重现了实际RF通道，不输出生产classified，不改RF-v1频移/滤波/校准配置。
即使某频差组也输出18，实收CFO补偿仍是下一独立验证；未证明噪声不存在。

精确AGX目录/所有缓存：/var/tmp/sdrharness-dev/b210-source-sensitivity-906d/。
只保留一份32768-byte导出tile；七组变换和229376-byte模型输入总量仅在内存中。
检查可用空间≥8 MiB，保存有界结果、源/案例/模型/脚本hash、参考logit对比、时间、
测试与清理。结束后停止feature进程，清理精确目录；不删除应用结果或用户原始语料。
V1b/V2/V3/A1与生产capability均保持原状态，recognizer_available=false。
