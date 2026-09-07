# P201 RX1/RX2 可选接收：源码、实收恢复与部署完成

基线5a79664。用户先要求四口，提供厂家资料后明确收敛为**只做RX1/RX2可选**。
本单元按[计划](P201_RX_PORT_SELECTION_PLAN_2026-09-07.md)完成，详见
[有界审计](P201_RX_PORT_SELECTION_AUDIT_2026-09-07.json)。

## 使用与实际范围

P201上的`/sd/sdr-agent/current/sdrd.conf`支持以下二选一设置，停止会话并重启
daemon后生效。缺省RX1；不运行两个daemon，也不能通过编辑文件改变活动会话。

```ini
rx_input=RX1
```

改为`rx_input=RX2`即可选择第二个接收口。配置错误、TRX1/TRX2及未知口均拒绝。
选择不是改一个名称：PHY读写、scan mask、gain快照/恢复和每份IQ身份一起切换。

| 面板 | 软件逻辑 | PHY | I/Q扫描 | RF选择 |
| --- | --- | --- | --- | --- |
| RX1 | RX0 | voltage0 | voltage0/voltage1 | A_BALANCED |
| RX2 | RX1 | voltage1 | voltage2/voltage3 | A_BALANCED |

一次仍为一个复数通道、ci16_le、4字节/点。另一PHY的gain/mode不改写，公共
LO/rate/BW和原scan mask在停止、失败、断连时恢复；不写rf_port_select或TX。
所有成功IQ响应携带所选身份，混合身份或与启动配置不符的Adapter被拒绝。

**安装后默认仍为RX1，以兼容现有AGX Controller。** 冻结RF-v1/Controller的
RX1身份检查未放宽；RX2已通过原生协议实收，但不能送入旧RX1模型profile或
旧语料包，也没有本轮Web/Planner端口选择功能。兼容CAPTURE_POWER字段名为
rx0，因此RX2禁用该命令及software_summary能力；原始IQ→AGX处理仍可用。

## 厂家硬件证据

资料盘位置为`/media/jetson/陆周超的移动硬盘/SDR P201P`，只读读取。硬件说明
第2.13.1节和原理图PDF第14页（图纸页16）显示两组PE42553B-Z外部射频开关，
RX1/TRX1与RX2/TRX2分别共用各自AD9361 A输入，B/C不能当作面板口名。

厂家`pzsdr-fw.7z`内`hdl/projects/pzp201pro/system_top.v`将四条控制线固定为
0/0/1/1；原理图真值表CTRL=0选RF2、CTRL=1选RF1，固定配置对应两专用RX口。
配套XDC记录四条控制引脚。未把它们连到GPIO的软件能力写成可用，也未生成或
替换FPGA/BOOT。只读GPIO清单与厂家成员/PDF的路径、大小、SHA-256见审计；
不声称仅凭厂家源码已经逐字证明当前加载的bitstream。原资料盘没有改写。

用户确认更换2.4/5GHz双频天线并接在RX2。本轮RX1没有同一副天线作对照，
故结果不能用于评价两通道优劣、天线改善量或解释此前宽带污染。

## 测试和有限实机

原协议/身份/恢复/inline清理测试、256例固定变异和新增配置/身份混淆负例通过。
36组refill情形分别跑raw/power内部循环，保留原34组并增加RX2成功和后续坏块
清理。独立双PHY测试验证选中通道的scan/gain读写、另一通道不变、成功和增益
写失败后的恢复、错误RF输入拒绝，以及RX2不暴露兼容power。ASan/UBSan通过。
新测试最初把错误RF输入的返回值误期望为0，改为既有的-EPROTO行为后通过。

固定工具链构建ARMv7动态EABI5产物，GLIBC仅2.4/2.7/2.17，无退役符号。
候选及最终安装hash一致：
`83a661a892b8ab71de3f4e7d64064c9c65030623dc7245eb3d3a1420a696ba4f`。

实机均2455MHz、2.1MS/s、BW1.5MHz、40dB、settle500ms。每口65535点成功、
65535点/1ms强制超时、4096点恢复采集，以及apply后断开连接。六次采集最大
预算1,081,328字节，四次成功返回合计557,048字节，仅内存统计/hash后释放。

| 口 | 65535点成功 | 强制超时 | 4096点恢复 | 断连恢复 |
| --- | --- | --- | --- | --- |
| RX1 | 33.616ms；RMS1.562；范围[-7,7] | 3.798ms，capture_failed_restored | 3.739ms；RMS2.580 | 通过 |
| RX2 | 33.591ms；RMS8.917；范围[-26,27] | 3.826ms，capture_failed_restored | 3.767ms；RMS3.661 | 通过 |

成功采集身份、字节数、health/overflow/短块状态与实际scan位均符合选择。采集
期间选中gain40dB、另一gain60dB；每次退出均逐项核对两路gain/mode/port及
公共LO/rate/BW和scan/buffer完全恢复。数值只是本次未标注背景，不是收到的
信噪比、分类准确率或独立标签。

首次验证在创建buffer前检查sysfs scan位而提前失败，尚未执行采集；完整恢复
原服务并清理远端后，改在实际buffer创建后的成功采集阶段检查，通过完整矩阵。
这次调整没有修改RF参数或分类门，失败日志仍保留在审计。

## 安装、回滚与发现的既有兼容问题

新release：`/sd/sdr-agent/releases/20260907-rx-port-selection-v1`。
回滚release：`/sd/sdr-agent/releases/20260907-before-rx-port-selection-v1`。
两目录分别保留sdrd/config/init三个文件，大小和hash登记在审计；它们是部署和
回滚产物，不是未清理的开发数据。旧sdrd hash为
`77d98a005305a4b7531fc3f133e9b4af521e60b065b29fcc304b4c7db80c45ae`。

先停止旧进程并确认无PID/监听，再替换启动；最终PID11547、单监听43110，
原生HELLO/CAPABILITIES/HEALTH通过，radio状态与原值一致，默认RX1。
独立候选验证时暂停的AGX恢复timer已恢复原active状态。

部署第一次检查本机`~/.local/lib/sdrharness/bin/sdr-agent-controller`发现其拒绝
`rx_input`未知字段，脚本自动回滚到旧产物；旧sdrd随后也原样复现该错误。
新旧默认HELLO、能力和health三个JSON对象逐字段完全相同，证明这不是端口
改造的报文回归。按原生实收、恢复及默认协议等价证据重新完成安装；旧CLI的
错误没有被改写为通过，也没有把recovery.service称为健康。该既有部署兼容
问题已在checklist单列下一独立修复，本轮不替换AGX Controller/Web/Worker。

人工回滚应暂停恢复timer，停止并确认无sdrd/监听，从回滚目录恢复相应文件，
启动后核对旧hash、单实例与radio/health，再恢复timer。确认不再需要某个历史
release后才能人工删除其三个已登记文件和目录；不要删除current正在使用的文件。

## 清理与后续

所有P201采集目录及本次stage目录均已删除。AGX feature根
`/var/tmp/sdrharness-dev/rx-port-select-907s/`的构建、测试、日志副本、网页、PDF
文本/图片裁剪、p7zip临时解包工具和仅供阅读的两个厂家成员已删除；库存字节
与absence核对见审计cleanup。没有解包整个4.8GB资料包，没有新IQ留存，原附件、
资料盘、旧诊断IQ和应用结果不动。
另精确删除Apport生成的本轮测试报告24226字节和上轮refill测试报告25253字节，
记录在审计apport_cleanup；已补记上轮清理范围，未删除已有UHD用户报告。

复现源码测试使用独立feature目录作为TMPDIR/BUILD_DIR；有界实机脚本为
`jetson-agx/sdrharness/scripts/validate-sdrd-rx-ports.py`，需新目录和经过技能ABI
检查的候选binary。它固定两口预算、校验身份/恢复，并恢复其运行前的已安装
daemon，不负责替换release。计划/profile未经准入不能启用生产识别。

后续先修复既有恢复CLI兼容性，再考虑AGX端口选择与诊断对照。模型/warmup/
独立标签均0，recognizer_available=false，冻结epoch-10/FP16/RF-v1及文本名称
provisional保持；本次可选端口交付不等于识别问题已修复。
