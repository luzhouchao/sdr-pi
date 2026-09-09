# P201 RX1 50Ω负载：停发背景有界采集预登记

基线 `5e558f1`。用户已确认 P201 RX1 和此前外部发射端都接 50Ω负载，
并明确同意先执行停发、P201负载背景采集。本单元只完成负载阶段；以后更换
接法才能补全同会话对照，不用历史天线数据冒充本轮天线→负载→天线。

固定六次单点 RX：2455MHz、2.1MS/s、BW1.5MHz、manual gain40dB、
RX1/RX0/A_BALANCED、settle500ms、65535 ci16_le 点/次、aggregate1、
capture deadline1000ms。每次262140字节、31.207142857ms有效样本；总计
393210点、1572840字节。两次之间额外等待1秒，预期约15秒，Controller每次
最多15秒，runner整轮120秒deadline，错误立即停止，不挑好结果重采。

AGX根 `/var/tmp/sdrharness-dev/p201-termination-20260909a/`，六个子目录
`capture-00`…`capture-05`。P201按已保存generation使用
`/tmp/sdr-agent-dev/agx-sweep-<generation>-0`，确切六个路径在采集前由
`audit.json`及标准输出登记。NX无暂存。AGX已检查约809753403392字节可用，
runner在实际采集前再次保存精确空间，并为每次采集保留8MiB以上额外余量。

使用已安装唯一CLI `sdr-agent --mode sweep --sigmf-directory ...`，不改软件、
服务或射频持久配置。要求一个预期sdrd、无现有43110/30431接收连接、空闲
scan mask/buffer、已验证RX1身份。NX只读核对wheeltec身份、USB serial2508504、
无UHD/B210/发射进程及USB占用；这不是测得外部设备RF输出为零。

停止：对runner发送SIGINT/SIGTERM，runner调用专用
`sdr-agent --mode cancel --sdrd 192.168.1.10:43110 --session-generation <active.json中的generation>`。
不在接收忙时另开普通HEALTH。每次结束轮询比对LO、采样率、带宽、两路
gain/mode/port、全部scan mask及buffer，确认P201临时目录消失；最终核对
同一daemon/hash和健康。保留任何失败，恢复失败不得宣称完成。

复用既有背景统计：全长128点RMS分段，raw及固定257-tap/175kHz/Kaiser8 FIR
的p50/p95/p99/max，事件显示线20 ADC RMS保持。原始数据不减DC、不换滤波器、
不改变旧验收门。用既有同参数停发证据做明确标注的历史描述；负载下异常
是否仍存在须据实际结果表述，不由单次低背景宣布故障已修复。

仅保留六份IQ、SigMF元数据、计划、原生报告、总审计及最小复核图表；登记
精确文件/字节/SHA-256及人工删除方法。删除本单元日志、scratch、运行标记，
保留原历史证据不动。TX/model/warmup/locked-test操作均0；生产识别仍关闭。
