# 5GHz Wi-Fi信道中心背景抽样预登记

基线9b82a25、codex/sdr-improvements。用户明确要求检查5GHz Wi-Fi是否也有
很强背景。沿用已确认RX1双频天线、外部N210负载停发，无需再次换线。
本轮是receive-only，既不发射也不解码归属、运行模型或训练。

固定25个常见20MHz信道中心（MHz）：5180/5200/5220/5240/5260/5280/5300/5320，
5500/5520/5540/5560/5580/5600/5620/5640/5660/5680/5700/5720，
5745/5765/5785/5805/5825。三轮按此顺序每点采一次，75次发现。每个点只
接收1.5MHz带宽，中央1.2MHz用于谱统计；信道之间有未测空隙，不称为5GHz
连续全段扫描，也不声称覆盖全部地域/扩展信道或Wi-Fi6GHz频段。

固定5180MHz参考，再选发现三轮raw128点RMS p95中位数最高的另外4点，
沿用至少4MHz间隔规则和同分低频优先；每个选点独立复测3次，共15次。
所有90次都由单点Controller调用，不能绕过原多点覆盖门。统一RX1/RX0/
A_BALANCED、2.1MS/s、BW1.5MHz、manual20dB、settle500ms、65535ci16_le点，
capture deadline1000ms；外部单次deadline15秒，runner1200秒，预计450秒。
每次262140字节/31.207ms，上限23592600字节、2.808643秒分散有效采样。
失败立即停，原门拒绝，不用降增益或重采挑结果掩盖失败。

AGX根`/var/tmp/sdrharness-dev/p201-wifi5-background-20260909e/`，90个capture
目录及scratch；初检空间809684320256字节，采前/逐次保存并复核有限余量。
P201每次精确`/tmp/sdr-agent-dev/agx-sweep-<generation>-0`在调用前audit和
标准输出登记。NX无暂存。SIGINT/SIGTERM走audit.active.generation对应
唯一CLI专用cancel，不在忙时另开HEALTH。每次核对无已有接收连接、同一
sdrd、RX1身份、两路原状态；结束轮询全部射频状态和scan/buffer恢复，
确认P201目录消失。NX前后核对wheeltec/serial2508504、无发射进程/USB占用。

复用上一轮raw128 RMS、1024 Hann PSD和25kHz频带统计及描述性相对突发比例。
软件采样率/带宽/增益与2.4GHz一致，可对比记录的ADC读数；跨频段天线增益、
接收链路响应和传播损耗未经校准，不能推成等效输入dBm/干扰源功率之比。
比较独立复测和发现分布，不把一次安静窗口认成长期无干扰，不凭信道归属
把活动全部叫Wi-Fi或接收机底噪。保留任何强弱结果。

保留完整90次IQ/元数据/计划/原生报告和总审计，登记source/capture/request/
session、字节/SHA-256、profile/预处理和严格人工删除方法；删除本轮日志/
scratch，核对进程退出和90个P201瞬时目录消失。旧2.4GHz及三阶段证据不改写。
TX/model/warmup/locked-test均0，recognizer_available=false保持。
