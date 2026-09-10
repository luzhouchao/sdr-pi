# 3500 MHz 双端负载背景对照

用户确认 P201 RX1 和外部 N210 原发射口均换回50Ω负载，随后要求继续。
本轮只接收，NX仅只读检查，未初始化UHD、未发射、未调用模型。
六段负载背景与此前弹簧天线停发背景处于相近量级，未发现明显的天线背景抬升；
此前单音资格未通过的结论保持。不能据此证明天线适配、收发链路正常或整个3.5GHz长期无干扰。

## 有限计划和现场核对

执行基线49785c1，原runner新增显式 `termination-3500` 条件，拒绝复用已存在的
固定新目录；旧2455MHz条件继续走原校验。计划在首段采集前保存于audit。
中心3500000000Hz，一路RX1/RX0/A_BALANCED；rate2500000、BW1000000Hz、
manual gain20dB、settle500ms、65535复样本/段、六段、段间1秒。
每段采样26.214ms，合计157.284ms非连续数据；精确最大IQ1572840字节。
point deadline1000ms、每个Controller15秒、runner120秒，预计约40秒。
采前AGX可用809257545728字节。

AGX目录 `/var/tmp/sdrharness-dev/p201-3500-termination-20260910b/`；P201路径为
`/tmp/sdr-agent-dev/agx-sweep-<generation>-0`，generation1789017336737至1789017336742。
停止路径为runner的SIGINT/SIGTERM及异常时专用
`sdr-agent --mode cancel --sdrd 192.168.1.10:43110 --session-generation <generation>`。
没有普通状态连接与采集并行，没有第二个collector。

P201唯一sdrd PID5909、持久配置/启动脚本存在，唯一43110监听；Controller健康。
Controller和sdrd哈希与上一轮相同，见audit。两路RX模式/增益/端口、LO/rate/BW、
全部scan mask/buffer逐段轮询恢复，六个P201瞬时目录均消失，最终health正常。
NX身份wheeltec/wheeltec，USB serial2508504（实际UHD设备为B210克隆），前后无
匹配TX进程且USB无持有者。这是进程/设备占用证据，不是射频功率测量。

## 数值与解释

统一采用未经滤波的128点复数RMS，包含最后不足128点的块，单位ADC；不是dBm。
没有误用2455MHz/2.1MS/s旧FIR。上一轮原始证据在采前逐文件核对哈希，未复制。

| 条件 | 各段RMS中位数范围 | 各段RMS最大值范围 |
| --- | ---: | ---: |
| 本轮50Ω负载，六段 | 1.490–1.527 | 1.777–2.000 |
| 上轮弹簧天线，停发前/后两段 | 1.429–1.432 | 1.757–1.879 |
| 上轮弹簧天线，发射中一段 | 1.421 | 1.811 |

本轮六段中位数依次1.527098、1.520691、1.489547、1.524538、1.519405、1.497394。
负载没有使本来就低的天线读数明显下降；它反而略高，不能把这个跨时间的小差异
解释成负载增加干扰或已测准噪声系数。天线记录与负载记录不是同步/交错括号控制，
温度及负载/天线3.5GHz匹配未测。本轮仅3500MHz的1MHz接收窗口，不能外推整频段。

下一项收发排查宜采用已核算TX实际功率、P201最大输入和衰减量的有线衰减链路，
或重新登记天线/增益有限方案。当前两端负载不是设备间链路；不自动升增益重发。
当前证据不支持把之前收不到单音直接归咎于强背景，也不证明具体硬件故障。

## 检查、部署和清理

六段原生报告、SigMF、精确字节、身份、request/generation/sequence关联及RMS
精确重放通过；sequence1407–1412，零报告drop/overflow/clipping。
旧2455MHz termination-return六段重放、上轮3500MHz单音原生校验及重放也通过。
未新增取消/故障注入，没有Rust或生产制品改动，不部署，不恢复模型。

重放命令（只读，无RF）：

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 \
  local-assets/amc-eval/runtime/venv/bin/python -B \
  jetson-agx/sdrharness/scripts/validate-p201-termination-background.py \
  --verify --condition termination-3500
```

[证据库存](../evidence/P201_3500_TERMINATION_EVIDENCE_2026-09-10.json)登记25文件、
1608427字节，其中IQ1572840字节，用于复核六段背景；逐文件SHA-256、源/会话/
请求身份、父证据血缘及精确人工删除命令已记录。清理7文件共58字节（六个空日志和
active收据）及空scratch目录；无NX副本/新socket，P201路径全消失。
runner和其Controller子进程已退出。以前冻结证据未修改。
