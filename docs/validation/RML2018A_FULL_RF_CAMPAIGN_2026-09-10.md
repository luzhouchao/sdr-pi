# RadioML2018A 全量脚本：有限先导与未通过的接收质量

[入口](../README.md) · [操作说明](../reference/RML2018A_FULL_RF_CAMPAIGN.md) ·
[保留与清理清单](../evidence/RML2018A_FULL_RF_CAMPAIGN_EVIDENCE_2026-09-10.json)

2026-09-10，分支`codex/sdr-improvements`，基线`02e5cdc`。用户明确要求全部原始
RadioML2018A样本，恢复此范围的冻结模型工程推理，训练/微调仍暂停。
交付边界是全量迭代脚本、有限空口先导、结果关联、取消/续跑和证据；**未执行全库，
接收识别质量未通过**。未部署生产Worker/profile，`recognizer_available=false`。

## 实现与源码检查

新增AGX campaign、NX有限文件TX helper、纯帧/同步合同及12项单元测试。
全库2,555,904行按24条/批覆盖106496批，每行保留原始ID、Y.argmax和Z，
不按类别/低SNR筛掉失败样本。全HDF5字节数、SHA-256及X/Y/Z形状均在plan中核对。
旧test成员只按本任务授权作工程源访问，不重写旧split或独立审计。

实际运行环境没有SciPy、NX没有h5py/Python UHD。实现改用NumPy FFT相关，
NX通过FIFO喂给已安装UHD程序，未新增系统依赖。
发射程序必须收到精确GO；payload哈希/幅度/设备/频率/有限字节不匹配时在UHD前拒绝。
推理每32批使用新的spawn进程，避免Torch线程池二次初始化并在分片后释放CUDA。

12项测试通过：全量/尾批覆盖、峰值与波形保真、篡改和越界拒绝、未知时刻/相位/CFO恢复、
错批/静音/截断拒绝、强带外tone下仅同步滤波且payload不变、尾部标记定位前一完整帧、
RMS保留恒定载波、FIFO有限实际字节流/EOF、GO前断连不送payload、汇总分母、已完成续跑
校验IQ且不重发。尾部标记新增测试先发现滤波边界影响CFO，改为半标记内部取样后通过。
最后命令为运行环境Python `-B -m unittest discover -s jetson-agx/sdrharness/tests
-p test_rml2018a_campaign.py`，TMPDIR为本单元开发scratch；没有Rust/前端修改。

## 真实参数与设备

NX hostname/user均为wheeltec；用户称为N210的设备UHD实际枚举B210，serial2508504，
USB3、A:A/channel0/FE-TX2、TX/RX。P201仅RX1/RX0/A_BALANCED。
沿用用户当前433MHz天线；天线产品型号及具体更换端未另作推定。

中心433.920MHz，TX/RX rate2.1MS/s、BW1.5MHz，TX70/RX50，峰值0.2、TX LO offset+250kHz。
每批TX最多4秒，完整24条帧重复321次，8381952个复数样本。
RX settle500ms、point deadline1000ms、65535个ci16复数样本，最大262140字节。
调用的batch数量、外层deadline见下表；每批audit保存执行前可用空间（约809GB）、
AGX/NX/P201精确路径、两路RX状态及直接停止方法。

P201 sdrd PID5909，实际哈希`83a661a892b8ab71de3f4e7d64064c9c65030623dc7245eb3d3a1420a696ba4f`；
Controller哈希`24b8340dd5c56bcf643a44e1eadbd11450e3b5e528d2ec72dc26103e9f23e25f`；
NX UHD文件TX程序哈希`fe3aebc556c16a5065d63d4e6ef8f02ef277ac01dcf250a35dec58b84eceb5cf`。
未修改已安装二进制、P201持久配置/启动链或生产TX能力。

## 先导结果及失败沿革

各根完整路径均为`/var/tmp/sdrharness-dev/b210-rml2018a-pilot-20260910{a,b,c}`，
原始run-plan、audit和哈希封存于原处，具体文件见库存。

| 根/操作 | batch与源行 | 调用范围/deadline | 结果 |
| --- | --- | --- | --- |
| a acquire | 4267，102408–102431 | 1批/180秒 | 原同步检测失败0.323595；采集及恢复通过；未推理 |
| b run | 同一批/源行，新run标记 | 1批/650秒 | 仅同步检测加固定低通，仍失败0.418432；源24/24正确，实收预测为空 |
| c run | 4267–4268，102408–102455 | 2批/650秒 | 48条全部同步并推理；源48/48正确，实收0/48正确 |
| c 中断acquire | 22016，528384–528407 | 1批/180秒；batch_plan后4.8秒SIGINT | 已TX start，中断退出1；未形成完整capture receipt；NX/P201恢复通过 |
| c retry/run | 22016，同一源行 | 1批/650秒，retry-failed | 旧失败整体移入attempts，新的request/session完成24条；源24/24正确，实收0/24正确 |
| c 重复run | 4267–4268 | 2批/180秒 | 4.171秒结束，9个原批次receipt/audit/prediction哈希不变，无新TX或推理事件 |

根a原始IQ中基带约−589.17kHz窄带分量占主导。根b还存在时变带内分量，早期标记受干扰，
最清晰标记在采集末尾，原实现因后面没有完整payload而排除它。
最终检测采用固定129-tap Hamming 500kHz低通，仅用于标记，不滤payload；从全窗口找标记，
必要时用已知26112点重复间隔取前一完整帧。CFO估计排除FIR边缘瞬态，未降低原质量门。
根a/b只作版本化离线同步复核，得分0.788831/0.692524，记录在c根
`offline-sync-recheck-v1.json`；没有把原始失败改写为成功，也未再推理这些旧RX。

最终c根三批标记得分为0.756716、0.741393、0.720123，估计CFO约657.50、514.35、594.76Hz。
前两批使用尾部标记定位前一完整payload，第三批标记后直接有完整payload。
三批源/实收平均相关度分别0.189643、0.165355、0.189147。
源类别为48条OOK(raw ID0)和24条QPSK(raw ID4)，均为原数据集Z=+30dB；
Z不是空口实收SNR。三批源72/72正确，实收72条全被判为ID17或18，**实收0/72正确**。
这只是2类高SNR小先导，不能外推全库正确率，也不能把同步成功等同于波形保真或准入成功。
−589kHz分量的物理来源仍未确认，不能因先前2.4/5GHz排查而把433MHz当前问题直接称为Wi-Fi。

UHD readback频率/rate/gain/BW/LO锁定通过；日志尾部有`S`，它不是时间戳化的连续发射证明。
实际marker及原生RX元数据提供批次关联，无法证明每次重复发射都无间断。
推理单次平均约37ms；首次新缓存加载/推理隔离窗口约67秒，后续单批窗口约15秒，
Spark都恢复且watchdog停止。没有在同一进程重复构造Torch backend。

## 预算与当前扩量边界

全量RX原生IQ 27,916,861,440字节，加13,958,643,712字节元数据/预测预留，共约39GiB；
累计TX上限425984秒（4.93天）。该TX时间不是整个实验耗时。
最终三批capture audit耗时11.88–12.45秒，尚不含前置检查；相邻批次实际开始相隔约15.38秒。
加上推理/模型分片开销，**全量约三周量级**，仅为小先导外推，未作全库长时验证，
代码初始10秒/批的字段明确标记unvalidated，不能当成已测承诺。

脚本可以按全量行范围执行、停止和批次续跑，但目前质量门不支持有意义的全量RF模型比较。
尚未执行2,555,904行全库，也未执行32批连续推理分片/多日soak；当前只验证了2批及1批真实分片。
下一步应先定位带内/带外分量与接收失真、用有限样本确认波形保真改善，再扩量。
不通过改模型、放宽同步门或把失败样本排除出分母获得成功。

## 停止、恢复与精确清理

正常、失败和主动中断均核对唯一接收所有者、同一sdrd哈希/PID、LO、rate、BW、
两路RX增益模式/增益/端口、全部scan mask和buffer恢复。六次尝试的NX/P201瞬时目录
最后再次核对不存在，NX无TX进程/USB持有者，P201 healthy=true，Spark状态S。
最终只读现场检查在c根`postflight.json`。

NX共删除42个暂存文件、1,347,331字节，每批audit有逐文件清单；P201目录已不存在。
AGX最终清理708个cache/lock/冗余packet文件，共40,492,354字节，三个scratch和本单元dev根已移除。
正常批次的208896字节TX源包由runner随批删除，不另存源IQ。
测试TemporaryDirectory自行清理，早期测试瞬时字节未逐项记账，因此不把最终清理数字说成
涵盖所有历史测试临时写入的精确总数。

保留74个证据文件、1,580,090字节，包括原失败/成功/取消的IQ或占位文件、原生元数据、
版本化离线复核、模型预测和恢复/续跑凭据；无权重/原始源IQ副本入Git。
每文件路径、大小、SHA-256、run/source/request/session、模型/profile/preprocess身份与
人工删除根见库存。清理完成不意味着这些必要证据被删除。

## 2026-09-10：按用户要求复查2.4GHz历史识别方法

本次只读历史文档/源码及已保留IQ，**新增RF采集0、模型推理0**。上一节0/72及旧审计保持。
基线8c51c0d；[离线复核脚本](../../jetson-agx/sdrharness/scripts/diagnose-rml2018a-campaign-filter.py)
输出[版本化逐行统计](../evidence/RML2018A_HISTORICAL_FILTER_COMPARISON_2026-09-10.json)。

先前“波形失真”描述过于笼统：现已量化一个主要问题是**额外窄带分量进入模型输入**。
三份当前实收Hann频谱的最大峰均在基带−589.160kHz，该峰±2kHz占各自全段谱功率
81.92%–83.72%。这是基带频率和窗内谱功率比例，不是Wi-Fi识别、绝对dBm或已测SNR。
分量物理来源仍未定位，也不能据此认定天线故障或ADC削顶。

历史不是“2.4GHz所有样本都成功”：

- [2440MHz早期保真度实验](B210_RX_FIDELITY_VALIDATION_2026-09-06.md)中，源ID0、
  实收ID18；仅CFO/带限均未修复。后来通过[TX LO正负偏移对照](B210_LO_OFFSET_VALIDATION_2026-09-06.md)
  证明当时有随TX LO移动的额外载波，符合LO泄漏/载波馈通。
- [固定泄漏抑制](B210_LO_REJECTION_VALIDATION_2026-09-07.md)使用TX LO+250kHz，
  AGX再用257-tap、175kHz cutoff、Kaiser beta8 FIR滤模型输入，保留DC、丢弃边缘halo；
  该次来源相关显著改善，但背景门失败，模型没有运行。
- [2455MHz 24类×3样本](B210_MULTICLASS_VALIDATION_2026-09-07.md)实际源69/72正确、
  原始实收30/72、固定FIR实收56/72；不是72/72。每条发一个1024点源并循环约10秒，
  RX40dB，固定4096点四窗共享RMS/mean-logit。滤波前验证每条源功率保留≥99%、
  归一化失真≤1%；失败/预测回退也纳入分母。

当前campaign沿用了TX LO+250kHz、TX70及2.1MS/s/BW1.5MHz，但RX50dB，
每批拼接24个不同1024点源、重复约4秒、使用pilot对齐和单窗推理；
**仅同步检测有500kHz FIR，实际模型payload没有175kHz FIR**。因此遗漏了历史有效的
模型输入滤波对照；这不是已经证实的频段或天线单因素失败。

离线复用旧`repair-b210-lo-leakage.py`的同一FIR系数（SHA-256
`d0e12014bedae088b71366497299adc3a1be0a45cf622e9cbb346d4ea0c8c8be`），
固定原audit的payload位置/CFO/相位，不重新找窗、拟合增益或根据预测调参数。
RX使用两端完整128点halo；源保真使用实际24条拼接帧及其邻居/保护区，
而非假装每条在当前TX中独自周期重复。

| 当前batch | 原始复相关均值 | 旧FIR后复相关均值 | payload接收功率被滤除 |
| --- | ---: | ---: | ---: |
| 4267 | 0.189643 | 0.758439 | 93.762% |
| 4268 | 0.165355 | 0.717607 | 94.698% |
| 22016 | 0.189147 | 0.759007 | 93.811% |

72/72源样本达到旧FIR的源保真条件：最小功率保留99.5609%、最大失真功率0.3629%。
复相关是逐1024点的非中心化复相关幅值，与旧记录的中心化四窗来源门不是同一统计量。
滤波使当前约0.18相关提高到约0.75，直接支持额外频带分量是主要污染；
仍不证明余下差异全部来自背景或滤波后分类必然正确。没有为本次滤波结果运行模型。
不能将本先导72条通过源保真推广到全库，特别是不同SNR/带宽及拼接边界。

检查包括父级audit/IQ/source行/TX帧哈希、固定行号与FIFO帧重建、旧FIR系数哈希、
独立FFT卷积对坐标/数值验证（误差小于1e−9），以及旧汇总的69/30/56计数复核。
所有计算在内存完成，无新增IQ/张量/缓存副本或硬件进程，没有开发临时目录需删除；
只增加Git中的脚本与派生统计。原保留清单74份文件全部哈希仍匹配。

复核命令只打印JSON，不更改campaign及旧证据：

```bash
cd /home/jetson/sdrharness
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 \
  local-assets/amc-eval/runtime/venv/bin/python -B \
  jetson-agx/sdrharness/scripts/diagnose-rml2018a-campaign-filter.py \
  --root /var/tmp/sdrharness-dev/b210-rml2018a-pilot-20260910c
```
