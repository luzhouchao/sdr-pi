# RX1接回天线：同日停发背景对照预登记

基线e70a18d。用户按上一轮指示确认P201 RX1已换回原天线；外部N210（实际
USB B210 serial2508504）保持发射端负载和停发。只增加六次天线背景，与
刚完成的负载六次对照，不复采负载、不发射、不运行模型。

完全沿用2455MHz、2.1MS/s、BW1.5MHz、manual40dB、RX1/RX0/A_BALANCED、
settle500ms、65535 ci16_le点/次、aggregate1、capture deadline1000ms。
每次262140字节/31.207ms，总计1572840字节/187.243ms有效样本。两次之间
等待1秒；预计整轮40秒，Controller单次15秒、runner120秒外部deadline。
所有六次固定保留，不挑好结果重试。采前AGX可用809750777856字节，runner
再次保存实际空间并逐点检查余量。

AGX根`/var/tmp/sdrharness-dev/p201-antenna-return-20260909b/`，子目录
capture-00…capture-05；P201六个`/tmp/sdr-agent-dev/agx-sweep-<generation>-0`
精确路径在采集前audit.json与标准输出登记。NX无暂存；停止发SIGINT/SIGTERM
给runner，经active.json的generation调用唯一`sdr-agent --mode cancel`。
接收忙时不另开普通状态连接。沿用逐次轮询两路射频全部状态及scan/buffer
恢复、P201目录消失、最终同一daemon/hash及health核对。

采前要求一个预期sdrd、无已有接收连接、RX1已验证、buffer/scan全关；NX
前后检查hostname/user、serial、无发射进程和USB占用。沿用已安装Controller
及sdrd，不改配置。负载包25文件逐个验SHA-256，并要求两阶段Controller/
sdrd/NumPy/FIR身份一致。前段旧审计字节不改写；旧runner哈希对应e70a18d源码。

固定输出raw/FIR的128点RMS p50/p95/p99/max及旧20ADC显示线事件。先展示
全部六次和两阶段范围，再描述是否回升；不新设生产阈值、不按模型结果归因。
这是同日顺序“负载→天线”两阶段比较，没有天线前测或负载复测，时间混杂
仍存在，不能把它标记成完整的天线→负载→天线因果验收。

最小保留六份IQ、元数据、计划、报告、总审计和派生对照，登记精确文件/字节/
SHA-256及删除命令。删除本轮运行标记、空日志和scratch；不改删上一轮证据。
TX/model/warmup/locked-test均0，recognizer_available=false保持。
