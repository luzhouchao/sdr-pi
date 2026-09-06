# 同一1024源的 TX LO 偏移定位（执行前登记）

基线73bee1d；用户要求继续推进至定位问题。本单元使用已有授权的NX+B210天线
2.4 GHz发射/P201 RX1/RX0/A_BALANCED/AGX分析。无模型、训练、locked test或部署。

## 固定矩阵与界限

先一次历史+100 kHz单音（2.440 GHz、2.5 MS/s、TX BW500 kHz、RX BW1 MHz、
25000000点/10秒、TX gain70/peak0.2、RX gain40），20 dB停发对照门通过再继续。
RML顺序严格为 a0/+250000/b0/−250000/c0 Hz TX LO offset，各一次，失败不重试。
目标信号中心始终2440000000 Hz；请求物理LO分别2440000000、2440250000、
2439750000 Hz，数字频移抵消LO偏移。其他条件及天线不变。该设置也改变信号在
发射模拟滤波器内的位置，因此不能把所有幅度变化唯一归因于本振泄漏。

源仅train行102400、1024点；payload SHA256
c8e3d54629eb7dde75e6a49554090f570522e7b438d2602dce85a18cd1d771f9；原始行SHA256
3c2c5d5606a7d1a8721511afddd49ca8c2183968d59b38a4e099754646cf0922。
每次2.1 MS/s、BW1.5 MHz、gain70/peak0.2、20480完整单位、spb1024，20971520点，
FIFO167772160 bytes，名义9.98644秒/10秒预算，远端65秒硬timeout；共5次RML，
加单音最多60秒名义发射，所有目标/LO/模拟带宽边缘在2.4 GHz内。
每次停发前/中/后各65535 ci16，settle500 ms、timeout1000 ms；18次共4718520
RX bytes。每次Controller显式plan/空间/直接cancel/恢复；进程和FIFO确认停止。

AGX协调根 /var/tmp/sdrharness-dev/b210-lo-906l/；AGX/NX采集根同名
b210-lo-tone-906l、b210-lo-a0-906l、b210-lo-p250-906l、b210-lo-b0-906l、
b210-lo-m250-906l、b210-lo-c0-906l，均在 /var/tmp/sdrharness-dev/ 下。
P201仅本次generation的 /tmp/sdr-agent-dev/agx-sweep-<generation>-0。
原始IQ总量4718520 bytes；源每根8192 bytes，暂存摘要/日志/图有限，至少64 MiB
空闲再启动（构建另核对）。各次外层180秒，整个矩阵最多1200秒；保留失败记录。

## 功能依据与分析（不改变RF-v1）

NX UHD4.1.0.5-3 --help确认--lo-offset；对应上游v4.1.0.5
host/examples/tx_samples_from_file.cpp使用 tune_request_t(freq,lo_offset)。
host/lib/types/tune.cpp设rf_freq=target+offset、RF MANUAL、DSP AUTO。现有二进制
只打印请求offset/有效TX频率，不提供实际物理LO独立回读；保留此限制和程序hash，
用实收谱线移动另证行为，不把请求值伪装为实测LO。

沿用前16×1024参数区、其余固定预测、全部65535点/512段统计。每次同源相关估计
残余CFO，仍限±200 Hz于单音参考及相关/相位门。M0/M1保留源真实均值，分别拟合
源增益、源载波截距、接收固定DC；LO偏移组增加一个在预期offset+CFO±1000 Hz
内由参数区FFT峰+抛物线插值确定的单频列（M2，标为已知源诊断）。原始谱与停发
相同频带对照报告；后段不得用于重新估参。若峰落搜索边缘/无明显停发对比，不
宣称追踪到LO泄漏。零偏移组LO列与源载波截距不可辨识，不增加重合列。

若额外线跟随±250 kHz移动且停发消失，支持发射LO相关分量；若较大源载波截距
仍留在目标中心，说明移动LO未消除该差异，需要下一独立RX频位等对照。保留
三个零偏移复现，区分时间变化。背景突发和相位漂移独立报告，不把残差当准确率。
工具测试包括偏移越界/版本/哈希、双频列辨识、停发对照、后段隔离和不可辨识。

最终核对封存hash、状态恢复、精确清理全部本单元根目录（不动用户结果），保存
有界审计/图/验证、更新checklist，review diff、独立commit并立即push。未定位的
因果项保持未完成；recognizer_available=false、独立标签0、名称provisional。
