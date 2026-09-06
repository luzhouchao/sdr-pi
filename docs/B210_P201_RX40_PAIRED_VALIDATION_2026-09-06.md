# B210/P201 40 dB 对照与同源 IQ 模型比较

基线 `f676e06ad9bf8be77ec8769f53dfeca4e480fab9`。按用户继续联调及“同一数据的原始
IQ与空口实收IQ都在AGX识别”要求完成本单元。预登记和用户后续范围补充见
[计划](B210_P201_RX40_CONTROL_PLAN_2026-09-06.md)，有界原始报告、哈希、结果及清理
见[审计](B210_P201_RX40_PAIRED_AUDIT_2026-09-06.json)。

## 结论

**40 dB接收的单音/RML启停对照通过预登记工程判据；成对模型比较完成，但实收
分类仍与源标称ID不一致。** 相同冻结模型、共享RMS和四窗变换下：

| 输入 | 四窗实验ID | mean-logit实验ID | 未校准概率 |
| --- | --- | ---: | ---: |
| 发射前原始tile，原四行顺序 | 0 / 0 / 0 / 0 | 0 | 0.999962 |
| 同一tile，按实收位置循环对齐 | 0 / 0 / 0 / 0 | 0 | 0.999961 |
| P201原始实收，固定第8个4096窗 | 9 / 17 / 18 / 18 | 18 | 0.970904 |

这份源IQ及它的截窗对齐版本都能得到标称ID0，差异在实收后出现；不能泛化为模型
在其他数据上正确，也不能仅由这次对照确定是噪声、干扰、频差或其他RF失真造成。
源来自已经查看的train四行，绝非独立known-RF标签或准确率验收。

源数据集标称SNR为+30 dB；实收父级65535点报告的谱峰/谱噪声估计为46.409622 dB。
后者不是同一定义的AWGN信噪比，也不是所选4096点的独立SNR标定，不能据此说
空口信号比数据集更干净。独立tone测得+3532.46 Hz频差；源/实收未去DC的
`abs(mean(I+jQ))/RMS`分别约0.3521/0.0361，也说明接收波形统计已有变化，未孤立因果。

## RF过程、失败保留与预算

NX+B210 serial2508504、RF A/TX-RX/channel0；所有TX LO均2.440 GHz，TX gain70、
幅度0.2。P201 Linux/IIO固定RX1/RX0/A_BALANCED，AGX储存和计算。
本单元诊断RX gain40，比上轮50低10 dB，未改变冻结RF-v1的50 dB要求。

第一次单音在baseline成功后，脚本尝试读取NX不支持的`/proc/PID/task/PID/children`，
返回错误并direct stop，未得到发射中/后对照。原失败报告原样保留；其中旧
`remote_tx_stopped=true`没有完整子进程证明，最终另用下面的完整检查确认，不能
仅据该旧字段判断。本次没有把该错误解释成无线链路或模型错误。

用`timeout sleep`无RF复现后，改用`ps --ppid`查询子PID，同时按精确PID/cwd/argv
及FIFO检查遗留，验证活跃进程时拒绝、停止后通过。另登记一次相同参数单音重试，
不修改RF参数或信号判据。三个burst总TX名义预算上限30秒（包含中止的第一次，
其实际RF时长未测）；有效单音/RML各10秒。总RX计划上限2359260 bytes，实际保存
7次×262140=1834980 bytes，其中6次属于完整启停对照。

| 对照 | TX样本/rate/BW | RX rate/BW | 启停结果 |
| --- | --- | --- | --- |
| 单音+100 kHz | 25000000 / 2.5 MS/s / 500 kHz | 2.5 MS/s / 1 MHz | 三次成功 |
| 四段RML train tile | 21000000 / 2.1 MS/s / 1.5 MHz | 2.1 MS/s / 1.5 MHz | 三次成功 |

每次RX为65535 ci16、settle500ms、timeout1000ms，原生Controller校验和执行。
所有7次已接受捕获均无削顶/丢样/溢出/timeout；有界计划、空间、AGX/P201目录及
stop generation在采样前打印。RML FIFO实际feed168000000 bytes，UHD退出0；
有效单音/RML日志末尾仍有`S`，不声明全程无TX序列异常。

单音发射中同bin相对两个停发对照提高47.531/46.095 dB，高于当时谱中值62.240 dB，
超过预登记20 dB门。观测峰+103532.46 Hz，独立频差+3532.46 Hz。
RML分析复用source自身99%频带和该tone频差；前7窗选择lag3152，固定应用于后8窗及
两个停发对照。发射中后8窗相关中位数0.658185，最大停发绝对中位数0.037035，差值
0.621150，分别满足≥0.5、≤0.2、≥0.3。原始相关数组保留在审计中，未事后改阈值。
这些是本单元工程来源对照，不能替代旧50 dB pilot失败或V1b独立验收。

## 成对模型实验的方法和适用范围

复用train行102400/102401/102403/102404，未读取其他数据行或locked test。
直接使用发射前fc32 tile，SHA256
`c95ac58c1fd91ef4da992622dbdf70a9bc5884d0941419083451473a052f534e`。
该tile是原四行的统一幅度缩放；共享RMS消去该整体尺度，不将TX浮点单位与ADC单位
直接比较。未额外生成或保存一份数据集IQ副本。

在看模型输出前固定选择实收offset28672、长度4096点，使用已由source-only分析
确定的lag3152生成对齐源组。不是根据预测挑选最佳窗口；三组分别只推理四窗。
使用冻结`four_window_capture_unit_rms`公式，不做DC去除、数字移频、滤波或重采样；
字节级RF-v1 golden及三个实际模型输入hash验证通过。复核时将调用研究变换集合改为
只执行该共享RMS公式，避免研究中其他DC去除分支拒绝合法常量载波；三组最终输入
字节与已推理输入完全相同，无需重跑模型。诊断分析用过的带限/CFO校正没有进入任何模型输入。

直接复用现有`RfV1Backend.classify_logits`：epoch-10，FP32权重、FP16 autocast，
四窗顺序执行，FP64 mean-logit后softmax。模型、profile、preprocess hash均与冻结
身份一致。只12个实验窗及Backend固有2次warmup，不重跑完整精度实验、不训练。
私有GPU租约覆盖加载和比较，180秒外层进程上限，实际租约持有约60.57秒，已释放。

这是**离线模型诊断**：接收gain40、中心2.440 GHz，未硬件调谐到候选中心，因而
`runtime_rx_profile_compatible=false`。没有构造虚假的50 dB CaptureMetadata，未把
输出经生产实收准入或S2/Web归档。所有概率未校准，文本名称provisional；
`recognizer_available=false`、独立标签0，V1b/V2/V3/A1均未勾选。

## 工具、验证与清理

复用现有采集、有限TX和分析工具；新增`--rx-gain-db 40`诊断参数、exclusive启动
receipt、SIGINT/TERM处理、capture timeout直接cancel、NX精确owner停止/退出检查。
分析工具支持单独tone目录，避免复制IQ，并增加固定工程对照判定；新增有界同源
比较脚本，不另建结果存储体系。

17项无RF软件测试通过：FIFO有限量/GO/篡改/-O、source lag/CFO/噪声对照、弱源或
强对照失败、缺失/非有限证据拒绝、准确RF-v1 golden hash、幅度缩放及常量载波/DC保留、
错误形状/零输入/源篡改拒绝、重复attempt/非法gain在访问设备前拒绝。Python AST和
`git diff --check`通过；NX另有sleep子进程测试和本轮真实停止/恢复验证。

P201 daemon PID17136和hash77d98a005305a4b7531fc3f133e9b4af521e60b065b29fcc304b4c7db80c45ae
不变，恢复启动前RX LO5985999996、rate30720000、BW30000000、manual gain60、
A_BALANCED及所有scan/buffer为0。这个LO只用于原RX状态恢复，TX始终在2.4 GHz。

精确清理已完成（审计`cleanup.verified=true`）：仅删除AGX/NX本单元三个精确
feature目录和已移除的P201 transient，保留有界报告/哈希/指标，不留Git IQ/tensor/
完整logits。用户语料、应用结果、已安装服务及其他项目已暂停的采集均未改动。
