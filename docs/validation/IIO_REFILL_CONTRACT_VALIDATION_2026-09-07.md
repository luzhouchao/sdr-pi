# IIO refill 合同修复：异常长度失败关闭，尚无历史RF根因结论

基线 `bb8b512`，按[本单元登记](../evidence/IIO_REFILL_CONTRACT_PLAN_2026-09-07.md)完成
源码、故障注入、主机验证与ARMv7构建。**修复尚未替换P201已安装服务，也未
做新候选实收；不能宣称已修复此前宽带污染或提高识别准确率。**

## 查证与修复

当前P201 PID17136实际加载`/usr/lib/libiio.so.0.21`，88136字节，SHA-256
`96bb209b35aa22a4e48365084d92f9794adffbff9e3b643cb1f4323e761077ba`。
上游v0.21的[buffer.c](https://github.com/analogdevicesinc/libiio/blob/v0.21/buffer.c)
在refill非负时保存`data_length=read`，`buffer_end`返回起始指针加data_length。
从实际目标库提取的反汇编亦显示：refill在`0x829c`把返回值写到结构偏移16，
buffer_end在`0x8520…0x8528`读取偏移4的起始指针与偏移16的长度并相加。
源文件URL/hash、目标库hash及两段反汇编保存在[审计](../evidence/IIO_REFILL_CONTRACT_AUDIT_2026-09-07.json)。

因此，正常libiio语义下，旧代码的`end-start`已经是有效长度，不能把它说成
误读固定容量。现有封存IQ也未记录API长度不一致，故障注入不能代替历史发生证据。

但注入“refill=512字节、span=1024字节”的矛盾接口后，旧实现没有拒绝：第一
缓冲写入1024字节，第二缓冲再写176字节，合计1200字节，超过首次声明的有效
范围。旧实现测试在期望拒绝处失败，临时文件也留在测试目录。这证实接口失常
时的健壮性缺口，不证明真实libiio在历史采集中发生过该失常。

新`checked_refill`由现有raw和兼容power路径共用，在消费数据前要求：

- 非负返回值、有效跨度、配置的整缓冲大小三者一致；长度非零且4字节对齐。
- 空/逆序指针、零、短、超长、不对齐以及返回/跨度不一致均报`-EPROTO`与
  shape错误；一致短块额外保留SHORT_REFILL及缺少的样本数，不再拼接下一块。
- 底层timeout/overflow/pipe/cancel/I/O负errno保留；失败raw文件和本次目录
  被删除，活动标志释放；power不返回聚合样本/功率结果。
- 请求末尾不足一个缓冲时，仍从合法完整缓冲截取所需样本。本次成功例300点
  由256+44点组成，逐字节验证输出1200字节，无多写。

`dropped_samples`仍仅计已报告短块的缺额，不是独立ADC时间戳/连续性计数。
兼容power路径仅同步输入检查，没有新增或迁回P201聚合架构。

## 验证范围

新C测试直接替换Adapter已有libiio函数表并执行真实采集循环；生产没有注入
开关或环境变量。34组情形分别覆盖raw/power，共68次调用：矛盾返回、合法
多refill/尾段，以及首次/第二次短/零/超长/不对齐/空/逆序指针和5类负errno。
后段错误验证先前已写文件被完整清理，不会只丢弃最后坏块而留下部分结果。

- 原实现负例：按预期失败，保留退出/断言日志和1200字节合成文件的hash/形状；
  合成文件随后删除，不纳入用户诊断IQ库存。
- 修复后`make all test`通过：已有sdrd协议/身份/恢复/inline清理测试及256例
  固定种子协议变异通过；34组新refill测试通过。
- AddressSanitizer + UndefinedBehaviorSanitizer（含泄漏检查）运行相同两套测试
  通过，没有新增发现。
- 用既有`p201-sdr-workflow`固定工具链脚本构建ARMv7成功；ELF32 ARM EABI5
  动态链接、退役符号检查通过，GLIBC需求仅2.4/2.7/2.17。候选hash：
  `0c7d7aa9a0f47ac75d2316a38a6116979df3368181af19f3b513ed0e9547897c`。

未使用新候选占有真实IIO设备，未部署，未声称跨编译就是实收验收。只读查询与
目标库复制不修改P201状态，不创建P201临时目录。RF/model/warmup/dataset读取
均为0，用户没有50Ω负载，天线/负载对照仍待设备与实际连接。

## 清理与复现

精确删除`/var/tmp/sdrharness-dev/iio-refill-907r/`：正常/故障/消毒器测试产物、
ARM候选、下载的上游源码、目标库临时副本、合成IQ及临时日志全部清理。
审查时使新测试沿用原测试的TMPDIR缺省行为，最终测试源码在独立
`/var/tmp/sdrharness-dev/iio-refill-review-907r/`重跑消毒器通过，该目录亦已删除。
文件hash/字节数、清理核对和必要有界日志在审计中；没有新IQ留存，旧证据包、
应用结果和持久工具链不变。失败日志的“core dumped”来自make的退出描述；
基线命令设置`ulimit -c 0`，清理库存中没有core文件。
后续RX端口单元发现Apport仍在`/var/crash`生成了本故障测试的25253字节报告，
该文件已按精确路径补清；hash和absence记录在本审计的later_apport_cleanup。
这纠正了先前未覆盖系统自动报告目录的清理范围，不改写原测试结论。

复现测试时自行选择新的feature目录作为BUILD_DIR及TMPDIR，完成后精确删除：

```bash
TMPDIR=<feature-dir> make -C sdr-system/sdrd all test BUILD_DIR=<feature-dir>/build
TMPDIR=<feature-dir> ASAN_OPTIONS=detect_leaks=1 make -C sdr-system/sdrd test \
  BUILD_DIR=<feature-dir>/sanitized \
  CFLAGS='-std=c11 -O1 -g -Wall -Wextra -Wpedantic -Werror -fsanitize=address,undefined -fno-omit-frame-pointer'
```

下一独立单元是候选的有界RX/失败恢复实机验证及可回滚替换，届时重新登记
采样预算、停止/恢复与产物身份；不能仅凭本轮软件测试勾选。负载物理隔离仍
独立等待。生产识别保持false，epoch-10/FP16/RF-v1、原成功/失败矩阵均不变。
