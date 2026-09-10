# 换天线后2440MHz同参数单次复测预登记

用户明确“现在重新试一下，我换了天线”。记录为天线已换，具体更换端/型号未报告，沿用原收发口；
不把当前新天线推定为之前的弹簧型号。原室内有限发射条件沿用。
TX2440MHz、+100kHz SINE、gain70dB、ampl0.2、rate2.5MS/s、BW500kHz，B2102508504 RF A/TX-RX channel0。
只发一次25000000样本/名义10秒，timeout35秒+2秒强停。
P201仅RX1/RX0/A_BALANCED、2440MHz、manual50dB、rate2.5MS/s、BW1MHz、settle500ms。
停发前/中/后三段各65535ci16点，最大786420字节、78.642ms非连续采样。
point1000ms、Controller15秒、runner120秒，预计40秒。停止为runner信号、专用generation cancel和具名TX owner INT。
AGX/NX目录 /var/tmp/sdrharness-dev/b210-2440-antenna-change-20260910g/，NX仅空目录；AGX scratch隔离缓存。
初检AGX可用809240899584字节，逐段复查；P201三条agx-sweep-<generation>-0执行前登记。
预检身份/哈希/唯一sdrd/空闲RX/NX USB；后验双路完整恢复、health、TX退出与瞬时目录消失。
复用原runner/分析，无源码改动；+100kHz±5kHz候选与两个停发同bin及谱中位数各≥20dB原门不变。
不重试/升增益、不降低门；仅一次跨时间换天线比较，不足以独立归因天线。
最小证据逐文件库存及人工删除，清理空日志/缓存/NX空目录，不部署/运行模型/训练。
