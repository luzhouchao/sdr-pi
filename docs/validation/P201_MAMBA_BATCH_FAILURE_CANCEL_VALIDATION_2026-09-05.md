# P201 Mamba 四窗口失败与取消验证 — 2026-09-05

## 结论

版本化 `integration_only` 四窗口链路的两个剩余实机故障路径已经完成：

1. seed44 Worker 在第一个窗口后退出，第二窗口连接显式失败；Rust RAII 删除
   32,768-byte model-ready spool，P201 在进入 Worker 前已停止并恢复。
2. 新鲜 `RecognitionTarget` 启动 model-ready capture 后，通过独立
   `CANCEL_SESSION` 精确取消 active session；capture 返回
   `capture_failed_restored`，P201 临时目录不存在且射频状态恢复。

没有发射、N210/USRP/B210、FPGA、寄存器、`BOOT.bin`、持久 SDR 配置或第二个
`sdrd` 参与。本轮不训练、不修改 checkpoint，也不打开生产 capability。

## 前置状态和有限计划

Feature ID：`ch4-batch-fault-cancel-20260905-v1`。

执行前密码文件是 regular mode-`0600`，严格 host-key SSH 和 3 秒 TCP 探测
通过。P201 只有 PID `17136` 的一个 `sdrd` 和一个
`192.168.1.10:43110` listener；部署二进制为：

```text
77d98a005305a4b7531fc3f133e9b4af521e60b065b29fcc304b4c7db80c45ae
```

AGX `/var/tmp`、`/run` 可用空间分别为 `808,838,135,808 B`、
`13,108,662,272 B`。两个用例均固定：

| 字段 | 值 |
| --- | ---: |
| 初始精查中心 | 433,920,000 Hz |
| P201 输入 | RX1 / RX0 / voltage0+1 / A_BALANCED |
| sample rate / RF bandwidth | 2,100,000 / 1,500,000 Hz |
| RX gain / settle | manual 50 dB / 100 ms |
| 精查窗口 | 4,096 complex samples / 16,384 B |
| model-ready capture | 4,096 complex samples / maximum 16,384 B |
| AGX model-ready spool | 4 × 8,192 B = maximum 32,768 B |
| capture / control deadline | 1,000 / 5,000 ms |

Worker 故障、一次只完成精查后因 target 超龄而在连接 P201 前失败的取消尝试，
以及最终取消重试，所有实际到达 P201 的操作合计上限为 `81,920 B`，实际收到
`65,536 B`。取消 capture 在读取 IQ 前结束，没有把未完成数据交给 AGX。没有
保存任何 raw IQ。

直接停止路径是 Controller `--mode cancel --session-generation N`；SDRD 只在
generation 与当前 active session 完全一致时接受。

## Worker 中途退出

实验 Worker 使用现有 seed44 manifest，配置 `max_requests=2`。第一个连接是
health probe，返回正确模型 ID、checkpoint SHA-256 和
`production_enabled=false`；第二个连接是窗口 0 的实际分类请求。Worker 随后
按上限正常退出并删除 socket，所以窗口 1 的连接确定得到：

```text
expected_failure_exit=1
controller_error=connect: No such file or directory (os error 2)
```

此前的精查 sequence 为 `6`，同窗指标为：

```text
estimated center:   433,330,913 Hz
occupied bandwidth: 1,539 Hz
peak/noise:         -60.021893 / -92.38208 dBFS
measured SNR:       32.360188 dB
```

四窗口 capture 已在 Worker 调用前成功停止并恢复 P201。失败返回后
`/run/sdr-agent/recognizer.sock` 不存在，`/run/sdr-agent/iq` 为空，确定的
`recognition-batch-20260905012-45001.f32` 不存在；P201 对应 sweep/capture
临时目录也不存在。

## Model-ready capture 直接取消

取消使用当前 16,384-byte profile，而没有为制造竞态扩大 capture。原因是
`sdrd` 的独立 cancel 线程在 session 获得所有权后设置持久取消标志；若 buffer
已经活跃则同时调用 `iio_buffer_cancel`，否则后续 capture 在开始前看到该标志
并失败关闭。

第一次生成的 target 来自 sequence `8`，但在跨工具调用期间超过 5 秒；
Controller 在连接 P201 前返回 `target_ineligible`。这证明时间门没有被测试流程
绕过。重试将精查、目标生成、capture 启动和 cancel 合并在一个有限脚本中；
精查 sequence `9` 得到：

```text
estimated center:   433,330,913 Hz
occupied bandwidth: 1,539 Hz
peak/noise:         -60.14331 / -92.611626 dBFS
measured SNR:       32.468315 dB
```

Session `20260905024` 在第 2 次 10-ms 间隔尝试时接受取消：

```json
{"session_generation":20260905024,"cancel_requested":true}
```

Capture Controller 以非零状态退出并明确返回：

```text
controller_error=remote_error: capture_failed_restored
```

这不是超时或客户端强杀；它是 SDRD 确认 capture 失败且已恢复的协议结果。

## 恢复与清理

两个用例后都核验了 P201。最终状态与前置状态一致：

```text
RX LO=2,400,000,000 Hz
sample rate=30,720,000 samples/s
RF bandwidth=18,000,000 Hz
gain mode=slow_attack
rf_port_select=A_BALANCED
RX buffer=0
scan mask voltage0..3=0000
sdrd PID/listener=17136 / exactly one 43110 listener
```

最终 Rust observe 为 online/healthy、health flags zero、IIO visible、retune/capture
true，以及 verified RX1 identity。以下路径均确认不存在或为空：

```text
/tmp/sdr-agent-dev/agx-sweep-20260905011-0
/tmp/sdr-agent-dev/agx-model-batch-20260905012-45001
/tmp/sdr-agent-dev/agx-sweep-20260905023-0
/tmp/sdr-agent-dev/agx-model-batch-20260905024-45003
/run/sdr-agent/recognizer.sock
/run/sdr-agent/iq/*
```

AGX feature 根内仅有两个 mode-`0600` target JSON 和一个小型文本日志；证据写入
本文后按精确 realpath 删除。应用结果、数据集、checkpoint 和用户数据未删除。

## 状态边界

这项证据只完成第4章四窗口失败/取消实机门。仍保持：

```text
profile admission=integration_only
production_enabled=false
production_recognizer_available=false
recognizer_available=false
```

下一项是独立的 bounded AGX software-acquisition overload 验证；
`rf_preprocess_v1`、重新训练/微调、校准和生产 Worker 仍属于后续第5、6章。
