# 再接50Ω负载：负载→天线→负载反向三阶段对照登记

基线e3ef811。用户确认P201 RX1已再次换回50Ω，外部N210（USB B210
serial2508504）保持负载及停发。只追加固定六次负载背景，不重做前两阶段。
此次顺序为负载→天线→负载，检查天线阶段强突发能否随反向换线消失；
如全部实施并验证，可记录反向三阶段物理对照完成，不冒称原先天线→负载→
天线的字面顺序，不因此认定具体信号来源或完整硬件无故障。

完全沿用2455MHz、2.1MS/s、BW1.5MHz、manual40dB、RX1/RX0/A_BALANCED、
settle500ms、每次65535点ci16_le、aggregate1、capture deadline1000ms。
每次262140字节/31.207ms，总1572840字节/187.243ms有效采样；间隔额外1秒，
预计40秒，Controller每次15秒、整轮120秒外部deadline。失败不挑窗重试。
AGX初检809748606976字节可用；采前保存精确可用空间，逐点检查余量。

本轮AGX根`/var/tmp/sdrharness-dev/p201-termination-return-20260909c/`，
capture-00…capture-05与scratch按本轮隔离。P201精确六个
`/tmp/sdr-agent-dev/agx-sweep-<generation>-0`路径在实际采集前audit.json和
标准输出登记；NX无暂存。停止对runner发SIGINT/SIGTERM，走active.json
generation对应的唯一CLI专用cancel；忙时不另开HEALTH。前后只读检查NX
身份/无发射进程/无USB占用、唯一sdrd、RX1身份与空闲scan/buffer；逐次轮询
两路全部射频状态/scan/buffer恢复、远端目录消失，最后核对同一daemon/hash
和health。保持原安装，不部署或改配置。

父级为封存天线阶段库存/审计，采前逐文件SHA-256校验并要求Controller、
sdrd、NumPy及FIR身份一致。保留全部六次原始及既有128点raw/FIR统计，
沿用20ADC事件显示线，不新设验收阈值或用模型诊断替代物理对照。
新派生三阶段比较绑定各原审计哈希，旧证据不改写或复制。

仅保留六份IQ、元数据、计划、原生报告、总审计及必要派生比较；登记精确
路径/字节/SHA-256/血缘/人工删除命令，删除本轮运行标记、空日志和scratch，
确认runner退出与远端瞬时目录消失。TX/model/warmup/locked-test均0，
recognizer_available=false不变。
