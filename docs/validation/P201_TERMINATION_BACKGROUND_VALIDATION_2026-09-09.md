# P201 RX1接50Ω负载：六次低背景实收，完整天线隔离尚未完成

用户确认P201 RX1及此前外部发射端均已接50Ω负载，并授权先做停发背景采集。
按[预登记](../evidence/P201_TERMINATION_BACKGROUND_PLAN_2026-09-09.md)，六次全部
成功且逐次恢复；本轮固定滤波后的128点RMS中位数为0.614–0.674 ADC。
此前新天线停发记录为11.737–13.609 ADC。本轮背景明显更低，但跨日历史
比较不能单独证明天线因果，也未定位具体干扰源或证明接收机无故障。

## 连接、参数与实际范围

连接证据来自本对话用户确认：P201 RX1接50Ω负载，外部设备原发射端接50Ω
负载。NX实际hostname/user均wheeltec，USB枚举为B210、serial2508504，与旧
记录一致；保留用户口称“N210”，不据外壳名称改变设备身份。采集前后均未
发现UHD/B210/发射进程，sudo只读fuser确认USB节点无占用；没有启动UHD或
发射。这个停发依据不是用功率计验证RF输出为零。

六次都是2455MHz、2.1MS/s、BW1.5MHz、gain40dB、RX1/RX0/A_BALANCED，
settle500ms、65535点ci16_le、单帧、capture deadline1000ms。共393210点、
1572840字节，只有187.243ms有效采样，不能解释为连续监测33秒。
六次Controller调用跨度33.445秒，每次约3.99–4.01秒，超过登记的15秒整轮
预估，但每次15秒及整轮120秒外部deadline均未超限。保存的采样timeout未触发。
AGX采集前可用809753030656字节。确切计划、generation、路径、状态和哈希
位于[25文件库存](../evidence/P201_TERMINATION_BACKGROUND_EVIDENCE_2026-09-09.json)
指向的总审计与六份原生报告。

## 背景结果

沿用已有257-tap、175kHz、Kaiser8工程FIR；系数SHA-256为
`d0e12014bedae088b71366497299adc3a1be0a45cf622e9cbb346d4ea0c8c8be`。
完整128点分段统计包含不足128点的末段，不减DC、不换窗、不挑结果重采。
数字单位为ADC RMS，未校准成dBm。

| 负载采集 | 原始p50 | 原始最大 | FIR p50 | FIR p95 | FIR最大 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 1.521 | 18.153 | 0.624 | 0.870 | 5.197 |
| 2 | 1.508 | 18.467 | 0.614 | 0.873 | 5.581 |
| 3 | 1.518 | 7.397 | 0.617 | 0.922 | 3.382 |
| 4 | 1.561 | 17.791 | 0.674 | 1.022 | 4.161 |
| 5 | 1.536 | 3.665 | 0.645 | 1.446 | 2.485 |
| 6 | 1.566 | 2.771 | 0.664 | 1.003 | 1.661 |

六次原始128点RMS均未超过旧统计使用的20 ADC事件显示线，但仍存在短时
起伏。该线只是显示规则，不是故障、噪声或生产准入门。
[9月7日新天线停发六份数据](B210_RX1_NEW_ANTENNA_VALIDATION_2026-09-07.md)的
原始p50为26.071–30.546 ADC，FIR p50为11.737–13.609，FIR最大为28.605–61.163。
当时和本轮接收参数及sdrd哈希相同，但日期、环境及外部设备负载状态不同。
本轮没有取得同会话天线样本，完整“天线→负载→天线”条目保持未完成。

## 软件、恢复与验证

源码基线`5e558f1`；使用原已安装`sdr-agent`，实际SHA-256在总审计登记。
P201前后均为唯一PID5909、`/sd/sdr-agent/current/sdrd`，哈希均为
`83a661a892b8ab71de3f4e7d64064c9c65030623dc7245eb3d3a1420a696ba4f`。
采集前无43110/30431已有接收连接，scan mask/buffer全零；原Web交互进程
保持空闲，未另启第二个接收所有者。

每次原生报告的样本/字节、RX身份、generation/request/sequence、健康、
timeout、零已报告drop/overflow/clipping均通过校验。六次逐次轮询确认LO、
采样率、带宽、两路gain/mode/port、全部scan mask/buffer与原状态逐字一致。
最终恢复到原LO5985999996Hz、30.72MS/s、BW30MHz，两路manual60dB及
A_BALANCED，全部scan/buffer关闭；这是恢复原值，不是本轮采样参数。
最终只读health通过。六个P201瞬时目录均消失。成功路径实测通过；本轮
没有新增故障注入或取消实测，不把已有取消实现称为本轮重新验证。

脚本语法检查、六份原始SigMF/元数据/原生报告/计划关联校验、NumPy1.26.4
逐项统计精确重放通过。重放只读现有IQ，未导入Torch或运行模型。
没有Rust、生产接口或部署变更，因此没有构建、Clippy或部署/回滚操作。
TX/model/warmup/locked-test均0；`recognizer_available=false`保持，独立标签0。

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 \
  local-assets/amc-eval/runtime/venv/bin/python -B \
  jetson-agx/sdrharness/scripts/validate-p201-termination-background.py --verify
```

## 保留与清理

保留根`/var/tmp/sdrharness-dev/p201-termination-20260909a/`中的25文件、
1611184字节，其中六份IQ共1572840字节；其余是SigMF元数据、计划、原生报告
及总审计，用于后续天线对照和全部结果复核。没有新增IQ副本，旧证据不动。
库存逐文件登记source/capture/request/session、字节、SHA-256、预处理身份
及先核对路径/哈希再逐文件删除的完整人工命令。

runner已退出。删除7个非证据文件共58字节（运行标记及六个空stderr日志），
空scratch目录已删除，逐一确认不存在。本轮没有NX暂存、构建产物或新socket；
六个P201瞬时目录全部确认不存在。保留包没有被称为已清理。
