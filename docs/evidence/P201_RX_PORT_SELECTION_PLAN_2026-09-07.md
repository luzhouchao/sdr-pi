# P201 面板接收口选择改造

基线5a79664。用户明确要求sdrd可选择四个面板口，并确认新2.4/5GHz双频天线
接在RX2；这一指令覆盖旧固定RX1对本次接收诊断的限制，不授权P201发射或
恢复已退役FPGA路线。新天线身份与旧空口采集分开，不把换天线的差异归因于代码。

先审计硬件：现有证据只确认RX1/RX0/voltage0+1/A_BALANCED；设备还暴露PHY
voltage1与scan voltage2+3。公开厂家产品页确认P201Pro/AD9361，但没有面板
TRX开关控制表。A/B/C是芯片输入，不等同于四个外部插座。不得推测GPIO/寄存器
或把TRX名称直接映射到B/C，也不把接收口选择实现成TX。

先完成可独立验证的接收通道配置：`rx_input=RX1|RX2`，默认RX1保持旧报文。
RX2使用第二个复数通道，配置、实读身份、scan mask、增益控制、快照与恢复
均选择对应通道；一次一个通道。所有IQ响应输出真实选择身份，不能只改名称。
TRX1/TRX2保留明确unsupported错误，待厂家映射与实机输入对照后才开放；
用户随后明确收敛为只做RX1/RX2，TRX不属于本轮交付。配置在daemon启动时生效，活动session不能
通过改文件偷偷换口。生产RF-v1/Controller仍校验RX1，不把RX2实验IQ塞进旧profile。

验证配置负例、身份串改、第二通道scan/gain/恢复及实际IQ字节路径、原RX1
协议和refill故障矩阵；ARMv7固定工具链构建。实机优先只读通道probe，新的
有界采集/射频输入证明另记录有限计划和结果；未做真实口关联就不宣称已完成。
全部四口能接收须硬件证据成立，软件无法补出未知的射频连接。

资料盘接入AGX后，厂家原理图与pzp201pro/system_top.v已确认外部开关的控制
输出为常量0/0/1/1，RX1/RX2连到各自A输入，TRX切换未接到GPIO。只读考证，
不构建/部署厂家固件。按用户最终决定，仅交付RX1/RX2。

有限实机计划：2455MHz、2.1MS/s、1.5MHz、40dB、settle500ms。每口65535点
成功、65535点1ms强制超时、4096点恢复采集，以及一次apply后断开连接验证；
共6次采集，最大1,081,328字节（含超时最坏预算），预估60秒。新天线保持RX2，
TX/model均0。复用已有daemon协议，候选分别以两份配置独占设备；暂停恢复
timer，停止旧daemon后才启动候选。每次检查两路gain/mode/port及公共频率/
采样率/带宽/scan/buffer恢复，finally恢复旧daemon与timer；明确SIGINT/SIGTERM
和STOP_SESSION停止路径。IQ仅内存统计/hash，不留副本。AGX空间由脚本预检。

临时根`/var/tmp/sdrharness-dev/rx-port-select-907s/`；只保留代码、测试、bounded
audit、来源URL/hash与结果说明；清理构建/网页/图片裁剪/测试数据。原附件与
用户结果、旧IQ证据不删除。每独立交付更新checklist、review、commit并push。
