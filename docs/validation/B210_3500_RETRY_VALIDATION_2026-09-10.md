# 3500MHz接回天线后重发：仍未确认单音

用户明确要求重新发射并报告已接天线，按双端接回原弹簧天线处理。
依[预登记](../evidence/B210_3500_RETRY_PLAN_2026-09-10.md)，沿用原低增益参数仅一次。
TX中心3500MHz、+100kHz SINE、rate2.5MS/s、BW500kHz、gain0dB、ampl0.2、
25000000样本/名义10秒；RX3500MHz、rate2.5MS/s、BW1MHz、manual20dB，
settle500ms，每段65535ci16样本，前/中/后三段共786420字节、78.642ms非连续数据。
没有自动升增益或追加发射。

| 阶段 | 128点RMS中位数ADC | 最大ADC |
| --- | ---: | ---: |
| 停发前 | 1.516 | 1.875 |
| 发射中 | 1.372 | 1.761 |
| 停发后 | 1.366 | 1.752 |

原+100kHz±5kHz内搜索候选位于+95330.739Hz，对两个停发同bin差值为
7.800/10.667dB，对发射中谱中位数9.944dB，均未达原20dB门，判定失败。
这不是已验证的弱单音或CFO，不证明没有任何能量到达，也不证明设备损坏。
读数不支持直接归因于强背景；实际输出功率、天线匹配、距离/方向和RF链路
尚未分离。继续链路排查应先核对端口/天线及可核算的衰减接法。

UHD实际频率/采样率/增益匹配，LO locked，正常退出；BW日志的MHz文字错误
沿用上一轮解释（500000数值单位Hz）。尾部无时间戳S保留，不能确认整10秒
连续输出或将其精确对应到RX窗口。gain0不是输出0dBm。

原runner及分析函数复用，无源码/生产制品变更，无模型/训练调用。
三个原生报告和SigMF字节/样本/身份/请求/健康/timeout及零报告drop/overflow/
clipping校验通过，数值重复计算完全一致。generation1789018278512–1789018278514，
sequence1413–1415。AGX采前可用809247936512字节。
NX前后wheeltec/wheeltec、USB2508504无持有者，TX owner/child均退出；NX空目录
已rmdir并验证消失。P201唯一PID5909、同哈希，双路gain/mode/port与LO/rate/BW、
scan/buffer逐段恢复，最终全快照一致、health正常，三个瞬时路径消失。
Controller/sdrd/UHD哈希与上轮一致，精确值见preflight/postflight。

[库存](../evidence/B210_3500_RETRY_EVIDENCE_2026-09-10.json)保留16文件/
820337字节，其中IQ786420字节。包含本轮执行wrapper用于复核前后验，
不能重跑它来覆盖证据。清理3空日志/0字节及空scratch；没有NX副本、新socket。
所有本轮采集/发射进程退出，不改旧证据，未部署、不提升recognizer_available。

只读数值重放（不会调用run.py）：

```python
import importlib.util, json
from pathlib import Path
p = Path('/home/jetson/sdrharness/jetson-agx/sdrharness/scripts/analyze-b210-3500-tone.py')
s = importlib.util.spec_from_file_location('retry_analysis', p)
m = importlib.util.module_from_spec(s)
s.loader.exec_module(m)
m.ROOT = Path('/var/tmp/sdrharness-dev/b210-3500-antenna-retry-20260910c')
assert m.prepare()[0] == json.loads((m.ROOT / 'analysis.json').read_text())
```

使用现有local-assets/amc-eval/runtime/venv/bin/python -B，设置
PYTHONDONTWRITEBYTECODE=1和OPENBLAS_NUM_THREADS=1。无需重做RF或模型实验。
