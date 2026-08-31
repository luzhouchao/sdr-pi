# P201 Pro SDR + Raspberry Pi 4B 性能优化研究

研究日期：2026-08-31
适用基线：Raspberry Pi 4B（64-bit）经直连千兆以太网访问 `192.168.1.10:30431` 的 P201 Pro/AD9361
范围：工程研究与离线 FFT 基准；未修改树莓派、SDR、IIOD、内核、网络或 FPGA 配置

## 结论

目前配置的 `10 MS/s` 采集目标已经基本跑满：单路复数 `I16 + Q16` 的理论载荷是
`10,000,000 × 4 = 40 MB/s`，实测纯 `refill` 为 `9.988 MS/s / 38.102 MiB/s`
（约 `39.95 MB/s`），没有超时或短读。现阶段没有证据表明 libiio、TCP 或 Rust FFI
限制了 10 MS/s；这不表示千兆链路本身已经饱和。基线见
[`TEST_RESULTS.md`](../raspberry-pi/p201pro-rust/TEST_RESULTS.md) 和
[`BASELINE_2026-08-31.md`](../sdr-system/docs/BASELINE_2026-08-31.md)。

当前最有收益的路线是：

1. 让一个线程只负责阻塞 `refill` 和一次最小化的块复制，不再同步执行逐样本分析。
2. 使用预分配、有界、可循环复用的 IQ 块池，把 window/FFT/PSD/reduction 分给 Pi 的两个 DSP 核。
3. 复用 FFT plan、Hann 系数、输入、scratch、PSD 和 top-k 工作区；不在热路径分配内存或记录逐样本日志。
4. 先用实测定位 IRQ、softirq、page fault 或频率波动，再分别 A/B affinity、RPS、内存锁定和 governor；不套用“万能 sysctl”。
5. 只有在 Pi 的完整 DSP 流水线超过核时预算，或者原始 IQ 接近千兆网硬上限时，才把能**减少上传数据量**的整段处理卸载到 FPGA。

Rust 是合适的实现语言，但它的主要价值是可预测的内存、线程和部署模型，不是让同一个
libiio/TCP 数据路径凭空变快。

## 已确认的性能边界

### 原始 IQ 与千兆网

Raspberry Pi 4B 官方规格为四核 Cortex-A72 和 Gigabit Ethernet，见
[Raspberry Pi 4 Product Brief](https://pip.raspberrypi.com/categories/685-whitepapers-app-notes/documents/RP-003474-WP/Raspberry-Pi-4-Product-Brief.pdf)。
千兆网的线速上限是 `125 MB/s`，实际 TCP/IPv4/Ethernet/IIOD 可用吞吐必然更低。

单个独立复数流为 4 byte/sample 时：

| 复数采样率 | 原始 IQ | 未计协议开销 | 判断 |
| ---: | ---: | ---: | --- |
| 10 MS/s | 40 MB/s | 320 Mbit/s | 当前实测已满足 |
| 20 MS/s | 80 MB/s | 640 Mbit/s | 应实测，不预先承诺 |
| 25 MS/s | 100 MB/s | 800 Mbit/s | 已逼近工程上限 |
| 30.72 MS/s | 122.88 MB/s | 983.04 Mbit/s | 加上开销后无法完整承载 |

双 RX、每路独立 I/Q 时载荷翻倍。Rust、CPU affinity 和更大的 socket buffer 都不能突破这个物理边界。

### libiio 的真实读路径

libiio v0.21 的 `iio_buffer_refill()` 将已有 buffer 传给 backend；network backend 发出
`READBUF <device> <length>` 后，通过 read/recv 将数据直接填入目标地址。对同一 device 的
network read 受锁保护，所以多个线程同时 refill 同一设备不能把一条流拆成并行读取。见
[v0.21 `buffer.c`](https://github.com/analogdevicesinc/libiio/blob/v0.21/buffer.c#L133-L154)、
[v0.21 `network.c`](https://github.com/analogdevicesinc/libiio/blob/v0.21/network.c#L685-L697) 和
[v0.21 `iiod-client.c`](https://github.com/analogdevicesinc/libiio/blob/v0.21/iiod-client.c#L606-L659)。
network socket 已设置 `TCP_NODELAY`，见
[`network.c`](https://github.com/analogdevicesinc/libiio/blob/v0.21/network.c#L566-L588)。

由此得到三个直接结论：

- context、channel 和 buffer 必须会话级复用，不能每帧或每个 FFT 重建。
- `refill` 线程应保持单一所有权；并行发生在块到达后的 DSP 阶段。
- buffer 越大，`READBUF` 命令和唤醒频率越低，但等待一块填满的延迟越高；必须按吞吐与延迟一起选择。

当前 `65,536` complex-sample buffer 是 `256 KiB`，在 10 MS/s 下代表约 `6.554 ms`
的样本时间。建议以后只做有控制的 `16 KiS / 64 KiS / 256 KiS / 1 MiS` 扫描，记录吞吐、
p50/p99/max refill、系统 CPU、网口 drop 和 DSP 队列深度，而不是仅追求最大的 buffer。

IIOD 当前命令中的 `-n 3` 是 USB pipes 数量选项，不是网络线程数；把它调大不能优化当前
Ethernet 路径，见 [IIOD v0.21 参数源码](https://github.com/analogdevicesinc/libiio/blob/v0.21/iiod/iiod.c#L89-L110)。

## FFT 算力预算

### 可计算模型

对每个独立复数通道，定义：

```text
Fs       = sample_rate，complex samples/s
N        = NFFT
O        = overlap，0 <= O < 1
H        = hop = N * (1 - O)
C        = 独立复数通道数；单 RX 为 1，双 RX 独立 FFT 为 2
W        = DSP worker 数
Tstage   = 一帧完整流水线时间，不只是 FFT

frames/s/channel = Fs / H
total_frames/s   = C * Fs / H
frame_period     = H / Fs
required_cores   = total_frames/s * Tstage
```

`frame_period` 是新帧到达间隔。若要求每帧在下一帧到达前完成，它也是单帧硬截止时间；若允许
跨 `W` 个 worker 排队，吞吐可以利用多核，但必须单独限制端到端队列延迟。生产准入不能只用
平均时间，应至少以 `Tstage p99` 估算，并给分类、输出、OS 和温度变化留出余量。

10 MS/s 下的到达预算如下：

| NFFT | overlap | FFTs/s/channel | 新帧间隔/截止时间 |
| ---: | ---: | ---: | ---: |
| 1024 | 0% / 50% / 75% | 9,766 / 19,531 / 39,063 | 102.4 / 51.2 / 25.6 us |
| 2048 | 0% / 50% / 75% | 4,883 / 9,766 / 19,531 | 204.8 / 102.4 / 51.2 us |
| 4096 | 0% / 50% / 75% | 2,441 / 4,883 / 9,766 | 409.6 / 204.8 / 102.4 us |
| 8192 | 0% / 50% / 75% | 1,221 / 2,441 / 4,883 | 819.2 / 409.6 / 204.8 us |

重叠率是最强的算力旋钮：50% overlap 使帧数和大部分逐样本工作翻倍，75% overlap 使其变为
四倍。不要在没有检测收益证据时默认使用 75%。

### Raspberry Pi 4B 实测

已在目标 Pi 上运行 RustFFT 6.4.1 AArch64 NEON 单线程基准。测量包括
`interleaved i16 IQ -> Hann -> Complex32 -> in-place FFT -> power sum/max`，不是只计 FFT。
Pi 的最高频率为 1.5 GHz、governor 为 `schedutil`，温度 `37.4 -> 39.9 °C`，前后 `throttled=0x0`。

| NFFT | prepare p50 | FFT p50 | reduce p50 | full p50 | full p99 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1024 | 2.926 us | 15.444 us | 2.982 us | 24.074 us | 32.778 us |
| 2048 | 5.370 us | 32.889 us | 5.315 us | 46.352 us | 51.408 us |
| 4096 | 10.222 us | 82.518 us | 9.852 us | 105.389 us | 110.648 us |
| 8192 | 18.315 us | 173.630 us | 18.352 us | 213.204 us | 221.166 us |
| 16384 | 36.426 us | 389.278 us | 37.445 us | 466.074 us | 482.834 us |
| 32768 | 77.815 us | 887.166 us | 79.592 us | 1,048.259 us | 1,081.630 us |

完整数据、环境和复现命令见
[`FFT_BENCH_RESULTS.md`](../raspberry-pi/p201pro-rust/FFT_BENCH_RESULTS.md)。RustFFT 官方说明
AArch64 默认启用 NEON，`FftPlanner` 会选择可用 SIMD；planner 应复用，见
[RustFFT README](https://github.com/ejmahler/RustFFT#simd-acceleration) 和
[`FftPlanner` 源码说明](https://github.com/ejmahler/RustFFT/blob/master/src/plan.rs#L28-L58)。
`Fft::process()` 会为 scratch 新建 `Vec`，持续处理必须预分配并调用
`process_with_scratch()`，见
[`Fft` trait](https://github.com/ejmahler/RustFFT/blob/master/src/lib.rs#L179-L211)。

以 2048 点的 full p99 `51.408 us` 计算一个 RX 的核时：

| Fs | overlap | FFTs/s | p99 所需核数 | 判断 |
| ---: | ---: | ---: | ---: | --- |
| 10 MS/s | 0% | 4,883 | 0.251 | 一个 DSP 核很宽松 |
| 10 MS/s | 50% | 9,766 | 0.502 | 一个核可跑，生产建议分给两个 worker 留余量 |
| 10 MS/s | 75% | 19,531 | 1.004 | 单核已到边缘，使用两个 worker |
| 20 MS/s | 50% | 19,531 | 1.004 | 需要两个 worker |
| 25 MS/s | 50% | 24,414 | 1.255 | 计算可放进两个核，但网络也已接近上限 |
| 20 MS/s | 75% | 39,063 | 2.008 | 已吃满两个核，尚未计后处理 |
| 25 MS/s | 75% | 48,828 | 2.510 | 超过计划的两核 DSP 预算 |

双 RX 独立 FFT 将上述核时翻倍。实测尚未包含 `fftshift`、对数 PSD、噪声底估计、top-k、
bandpower、写盘、UI 编码和调制识别，所以不能把“FFT bench 能跑”误当成完整应用已经满足。

## 推荐的 Pi 软件架构

```text
CPU0: OS + Ethernet IRQ/softirq + 轻量结果输出
CPU1: libiio acquisition（唯一拥有 Context/Channel/Buffer）
      refill -> 融合解交错/拷贝 -> 预分配有界块池
                                  |                |
CPU2: FFT worker A <--------------+                |
CPU3: FFT worker B <-------------------------------+
      每个 worker 独占 plan/scratch/window/frame/PSD/top-k 工作区
```

这是起始 A/B 布局，不是未经测量的永久配置。先比较不绑核的 baseline，再比较上述布局；若实际
Ethernet IRQ 已在其他核或 irqbalance 会重写 affinity，应以 `/proc/interrupts` 为准。

实现要求：

- 块池在启动时一次性分配和预触碰，固定容量，绝不无界增长。
- 采集线程只做保证下游可消费所需的一次拷贝；把 i16->f32、Hann 和 Complex32 写入融合成一遍。
- 每个 FFT worker 单线程处理完整帧；2048 点 FFT 不应再在单帧内部创建线程，而应跨帧并行。
- overlap tail 由 frame assembler 在预分配内存中维护，不重复拷贝整个窗口。
- 明确定义过载策略：严格连续采集则报警/降采样；监测型业务可选择丢最旧块并记录 gap。
- 每秒记录接收样本数、块池高水位、丢块、每阶段 p50/p95/p99/max、每核利用率和温度。

建议将两个 DSP 核的**持续生产准入线**设为总核时不超过 `1.4 core`（70% × 2）。这是本项目
为给分类、输出和系统抖动留余量的工程策略，不是硬件规格。超过后依次减少 overlap、降低
Fs/做抽取、减少通道、减少每帧输出，最后才进入 FPGA 卸载评审。

## Rust/FFI 与内存边界

Rust 的 `extern "C"` 按 C ABI 调用；opaque C 对象应继续用指针，只有确实跨 ABI 的自定义结构
才使用 `#[repr(C)]`。见 Rust 官方
[FFI 指南](https://doc.rust-lang.org/nomicon/ffi.html) 和
[`repr(C)` 布局规则](https://doc.rust-lang.org/reference/type-layout.html#the-c-representation)。

`industrial-io` 的 `Buffer::refill()` 只包装一次 `iio_buffer_refill` 调用并转换返回值，没有额外
整块复制；`channel_iter` 初始化时取 first/end/step，随后在 Rust 中做指针步进，见
[`industrial-io` 0.6.1 buffer 源码](https://docs.rs/crate/industrial-io/0.6.1/source/src/buffer.rs)。
因此“每块一次 FFI”不是当前瓶颈。不能笼统保证所有安全抽象都零成本：应通过 release profile
和 profile 验证生成路径，只有 iterator/解交错明确成为热点后，才在一个很窄的内部模块中借用
raw buffer。

若使用 `slice::from_raw_parts`，必须同时证明非空/对齐、单一 allocation、合法长度、初始化状态
和生命周期，并保证下一次 refill/destroy 前不再持有 slice；见
[Rust 官方安全条件](https://doc.rust-lang.org/std/slice/fn.from_raw_parts.html)。优先保留安全 wrapper，
不要为了“零拷贝”扩大 `unsafe` 面。

构建保持 release、LTO 和单 codegen unit。可单独 A/B `-C target-cpu=cortex-a72`，但交叉编译时
不能使用构建机的 `target-cpu=native`；Rust 官方说明见
[`target-cpu`](https://doc.rust-lang.org/rustc/codegen-options/index.html#target-cpu)。任何定向优化产物
都要与 generic aarch64 产物做相同输入/校验和与性能对比。

## CPU、IRQ、网络与实时调度

### 只在证据出现后调 RPS/IRQ

Linux 官方说明 RPS 是软件 RSS：它在中断之后按 flow 选择协议处理 CPU；`rps_cpus=0` 时关闭。
单队列网卡可能受益，多队列已覆盖所有 CPU 时 RPS 可能多余。见
[Linux networking scaling](https://docs.kernel.org/networking/scaling.html)。IIOD 样本通常是单个 TCP
flow，RPS 不会把这一条 flow 拆成四核并行；它只可能把该 flow 的 softirq 移到另一个核。

测试顺序：

1. 读取 `ethtool eth0`、`ethtool -l/-k/-S eth0`、`/proc/interrupts`、`/proc/net/softnet_stat`、
   `ip -s link` 和每核 softirq。
2. 保留默认 affinity/RPS 跑长时 baseline。
3. 只改一个变量，比较 IRQ affinity、RPS 或 RFS 对 p99 refill、softnet drop、总核时和 DSP 队列的影响。
4. 仅保留可重复改善；否则恢复默认。

IRQ 的允许 CPU 通过 `/proc/irq/<IRQ>/smp_affinity[_list]` 控制，内核官方说明见
[SMP IRQ affinity](https://docs.kernel.org/core-api/irq/irq-affinity.html)。

### 不先调 TCP 大缓冲或 Jumbo Frame

Linux TCP receive auto-tuning 默认会在 `tcp_rmem[2]` 上限内调节接收缓冲，见
[Linux IP sysctl](https://docs.kernel.org/networking/ip-sysctl.html#tcp-variables)。直连低 RTT 链路的
带宽时延积很小；当前 10 MS/s 已完整接收且 error/drop 为零，没有证据支持先扩大全局 socket
buffer。Jumbo Frame 需要 Pi、SDR MAC/驱动和中间路径全部支持，也不应作为第一步。

libiio 的 `WITH_NETWORK_GET_BUFFER` 使用 splice/mmap，但 v0.21 和 v0.26 均标为实验性且默认关闭，
见 [v0.21 CMake](https://github.com/analogdevicesinc/libiio/blob/v0.21/CMakeLists.txt#L281) 和
[实现](https://github.com/analogdevicesinc/libiio/blob/v0.21/network.c#L846-L1010)。只能作为独立、
可回滚的客户端 A/B，必须验证断网、超时、destroy 和长时样本连续性；不能直接替换稳定路径。

### governor、内存锁定和实时优先级

- `performance` governor 请求 policy 允许的最高频率，可用于固定条件的 A/B；定义见
  [Linux CPUFreq](https://docs.kernel.org/admin-guide/pm/cpufreq.html)。当前 `schedutil` 下 FFT 已有明确基线，
  所以切 governor 的价值是降低尾延迟，不能假定提高平均吞吐。
- 只有 profile 出现 major/minor page fault 导致的尾延迟时，才使用
  `mlockall(MCL_CURRENT | MCL_FUTURE)`，并预触碰栈和块池；它受 `RLIMIT_MEMLOCK` 约束，见
  [`mlockall(2)`](https://man7.org/linux/man-pages/man2/mlockall.2.html)。
- 先用普通调度 + affinity。`SCHED_FIFO/RR` 只在 p99 仍受调度干扰时试验，错误的高优先级忙循环
  会饿死 softirq 和系统线程；Linux 实时策略语义见
  [`sched(7)`](https://man7.org/linux/man-pages/man7/sched.7.html)。
- 长时记录 `scaling_cur_freq`、温度和 `vcgencmd get_throttled`。当前温度与 throttle 正常，不需要
  超频；供电/散热问题出现前不把它当瓶颈。

## 何时卸载到 FPGA

FPGA 的价值不在于“FFT 比 CPU 快”，而在于让上传 Pi 的数据从原始 IQ 变为显著更小的结果。
如果 FPGA 做完 FFT 仍把每帧完整 float PSD 经网络传回，0% overlap 时 `N × 4 byte` 的频谱与
`N × 4 byte` 的 I16+Q16 原始帧大小相当；有 overlap 时甚至会发更多。真正有效的 offload 必须
把 window、FFT、功率、积累/平均、bandpower、top-k/阈值/事件触发中的足够多阶段放在 SDR 端，
只传压缩摘要，或仅在事件触发时回传原始窗口。

### FPGA GO 条件

满足任一性能问题，并且摘要协议已定义，才进入实现评审：

- 原始 IQ 需求达到约 20–25 MS/s 单 RX或双 RX相应载荷，长时实测证明 Gigabit/IIOD 已成为瓶颈。
- 按 `required_cores = C × Fs/H × Tstage_p99` 计算，完整生产流水线超过两个 DSP 核的 70% 准入线，
  且降低 overlap/抽取/减少输出不能满足业务。
- p99 队列延迟持续错过产品截止时间，且已排除分配、调度、温度和不必要后处理。
- 业务只需要 bandpower、峰值、占用、Goertzel/相关统计或低速摘要，原始 IQ 仅用于偶发调试。

### FPGA NO-GO 条件

- Pi 还需要完整 IQ 做可变算法、录制、标定或模型开发。
- 只节省几十微秒 FFT，却仍要上传完整 IQ 或完整逐帧频谱。
- 需要用 AXI-Lite 逐 bin 读完整向量，或没有 DMA/ring-buffer、backpressure、帧号和丢帧语义。
- 当前 bitstream 身份、时钟、资源、时序或 golden rollback 尚未确认。

当前加载的 `/sd/BOOT.bin` 不匹配已记录的 V8L1/V10S0，历史 summary 地址也不可访问；在重新完成
boot-chain/FPGA identity 审计前，不能假设已有 summary/FFT 能力。见
[`BASELINE_2026-08-31.md`](../sdr-system/docs/BASELINE_2026-08-31.md)。现有工程也明确认为 FPGA
只有在移除整段 raw capture/PSD 成本时才值得进入主路径，见
[`P201PRO_PROJECT_LEVEL_BAND_SCAN_OPTIMIZATION_PLAN.md`](../fpga/docs/P201PRO_PROJECT_LEVEL_BAND_SCAN_OPTIMIZATION_PLAN.md)。

若进入 FPGA 阶段，建议先做固定 `N=2048` 的 shadow path：

```text
AD9361 IQ -> frame/overlap -> window -> FFT -> |x|^2
           -> time/frequency accumulation -> bandpower/top-k/threshold
           -> 小型带版本和帧号的结果 ring/DMA -> IIOD/控制面 -> Pi
```

AMD FFT IP 支持不同架构、数据格式和缩放配置，但仍需项目自己解决 window、帧缓存、缩放策略、
时钟域、backpressure、DMA/结果协议、验证向量与 timing closure；见
[AMD Fast Fourier Transform Product Guide PG109](https://docs.amd.com/v/u/en-US/pg109-xfft)。

## 实施顺序与验收门槛

### P0：保持设备不变，完成软件流水线

- 将当前同步 `refill -> observe_iq` 改为 acquisition + 预分配块池 + 两个 worker。
- 集成 2048 点 RustFFT，固定输入重放先验证每帧 checksum/PSD 容差。
- 指标：10 MS/s、50% overlap、单 RX，长时无 refill error/short read，队列不持续增长，
  DSP 两核总利用率低于 1.4 core，记录端到端 p99。

### P1：受控上探

- 对 10/15/20/25 MS/s、0/50/75% overlap、单/双 RX 建立矩阵。
- 对每点测 buffer size、完整 stage timing、网口、softirq、温度、丢块和结果延迟。
- 当前 2048/10 MS/s/50% overlap 的计算有明显余量；优先证明它可长时稳定。

### P2：只对已证明的瓶颈调系统

- 依次 A/B affinity、governor、RPS/RFS、mlockall；每次只改一个变量并保留回滚值。
- TCP buffer、Jumbo、实验性 network zero-copy 放在最后，并要求显著、可重复改善。

### P3：FPGA 决策门

- 用真实业务输出定义压缩比：`raw bytes in / result bytes out`。
- 只有满足 FPGA GO 条件、能减少整段数据移动，并完成 bitstream identity/golden rollback 后，
  才进入 Vivado shadow 实现；否则继续使用 Pi 的 NEON FFT 路径。

## 建议的最终形态

```text
默认/开发模式：P201 raw IQ -> Gigabit/IIOD -> Pi Rust -> NEON FFT/DSP
高负载摘要模式：P201 FPGA window/FFT/积累/特征 -> 小结果 -> Pi Rust
触发调试模式：FPGA 摘要持续运行，事件时才抓取有限 raw IQ 窗口
```

这三种模式比“一刀切把所有 FFT 都搬进 FPGA”更能同时保留开发灵活性、10 MS/s 现有性能和未来
高采样率余量。
