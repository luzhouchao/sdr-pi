# Raspberry Pi 4B 上用 Rust 通过 libiio 驱动 AD9361 SDR 的可行性与性能评估

> 研究日期：2026-08-31
> 目标环境：Raspberry Pi 4B（aarch64，DietPi/Debian）→ Ethernet → `iiod` at `192.168.1.10:30431` → PUZHI PZSDR P201PRO / AD9361
> 范围：只研究方案，未在树莓派上安装、编译、修改配置或采集数据。

## 结论

**可行，而且 Rust 很适合做树莓派上的长期 SDR 采集和 DSP 程序；但“换成 Rust”不等于 SDR 到树莓派的采集通道自动变快。** Rust 程序仍通过 C `libiio` 的 network backend 访问 IIOD，因此 SDR、IIOD、TCP/千兆网和 `libiio` 的主数据路径与 Python 绑定所用的底层路径相同。Rust 的主要优势是：

- 没有 Python 解释器和 GIL，每样本 DSP、协议解析、序列化和多线程处理更可预测。
- 可以直接借用 `libiio` 采集缓冲区中的样本，在采集线程内做零额外拷贝的就地处理。
- 可构建单一可执行文件，适合 systemd 常驻、有界队列、明确的错误恢复和内存上界。

如果原 Python 程序逐 IQ 样本跑 Python 循环，Rust 可能带来很大改善；如果 Python 只调用 `libiio` 并把整块数据交给 NumPy/C 向量化处理，单纯更换语言的采集吞吐提升可能很小。必须用实测数据判断，不应在开发前承诺速率。

## 推荐的技术路线

第一版建议使用：

```toml
[dependencies]
industrial-io = "0.6.1"
```

`industrial-io` 0.6.1 是目前 crates.io 上最新的通用安全 Rust 包装，最低 Rust 版本为 1.75，默认采用 libiio 0.25 绑定。它是第三方项目，**不是 Analog Devices 官方 Rust SDK**。项目 README 自身也说仍在向 production quality 完善，CI 只在 Ubuntu x86-64 上做 build/check，由于需要 IIO 内核模块，单元测试尚未在 CI 中运行。因此它适合先做可测量的原型，但需要将重连、超时、短读、关机和长时稳定性纳入我们自己的测试。建议项目内再封装一层很窄的 `SdrRx` 接口，避免第三方 crate API 扩散到整个工程。证据见 [crate metadata](https://crates.io/crates/industrial-io/0.6.1)、[Cargo.toml](https://github.com/fpagliughi/rust-industrial-io/blob/56dec714bbfa06f5a3a2b855707f48c7e792cdec/Cargo.toml)、[README](https://github.com/fpagliughi/rust-industrial-io/blob/56dec714bbfa06f5a3a2b855707f48c7e792cdec/README.md) 和 [CI workflow](https://github.com/fpagliughi/rust-industrial-io/blob/56dec714bbfa06f5a3a2b855707f48c7e792cdec/.github/workflows/rust.yml)。

不建议第一版就直接全面使用 `libiio-sys`/`unsafe` FFI。先用安全包装实测；只有 profiling 证明 `industrial-io` 的额外分配或拷贝是瓶颈时，再在一个很小的内部模块里用 `libiio-sys` 封装可复用缓冲区。

## aarch64 和依赖可行性

- Rust 官方将 `aarch64-unknown-linux-gnu` 列为带 host tools 的 Tier 1 平台，所以 64 位 DietPi/Debian 可以原生编译 Rust 程序。见 [Rust platform support](https://doc.rust-lang.org/rustc/platform-support/aarch64-unknown-linux-gnu.html)。
- `libiio-sys` 对 Unix 按 32/64 位指针宽度选择预生成绑定，aarch64 会走 64 位文件；Linux build script 只链接系统 `libiio.so`。它不自动下载或编译 libiio，也没有 aarch64 专项 CI。见 [`libiio-sys/src/lib.rs`](https://github.com/fpagliughi/rust-industrial-io/blob/56dec714bbfa06f5a3a2b855707f48c7e792cdec/libiio-sys/src/lib.rs) 和 [`build.rs`](https://github.com/fpagliughi/rust-industrial-io/blob/56dec714bbfa06f5a3a2b855707f48c7e792cdec/libiio-sys/build.rs)。
- 原生编译时至少需要 Rust toolchain、系统 C linker 和包含开发链接名的 libiio 开发包。Debian 通常是 `build-essential` 与 `libiio-dev`；`libiio-utils` 只用于 `iio_info`/`iio_readdev` 验证，不是 Rust 程序运行的必需项。
- 如果系统没有合适的 libiio 包，Analog Devices 的 v0.25 官方构建说明给出了 CMake 构建方式。network backend 默认打开，并依赖 XML backend/libxml2。见 [libiio v0.25 build guide](https://github.com/analogdevicesinc/libiio/blob/v0.25/README_BUILD.md) 和 [CMake options](https://github.com/analogdevicesinc/libiio/blob/v0.25/CMakeLists.txt)。

`industrial-io` 0.6.1 显式提供 libiio 0.19/0.21/0.23/0.24/0.25 feature，默认为 0.25。ADI 的 libiio 0.26 与 0.25 公开 `iio.h` 没有差异，两者 SOVERSION 都是 0，因此 0.25 绑定与 0.26 存在很强的 ABI 兼容证据；但 crate 没有显式的 0.26 feature，仍应在目标机上用实际版本做编译和连接测试。比较来源：[libiio v0.25](https://github.com/analogdevicesinc/libiio/tree/v0.25)、[libiio v0.26](https://github.com/analogdevicesinc/libiio/tree/v0.26)。

## 驱动和采集方式

高层 API 路径为：

1. `Context::from_network("192.168.1.10")` 或 `Context::from_uri("ip:192.168.1.10")`。
2. 在 `ad9361-phy` 上配置 RX LO（`altvoltage0` 输出通道的 `frequency`）、RX `voltage0` 的 `sampling_frequency`/`rf_bandwidth`/`gain_control_mode`/`hardwaregain`。
3. 找到 `cf-ad9361-lpc`，开启输入 `voltage0` 和 `voltage1`（RX0 的 I/Q）。
4. `Device::create_buffer(sample_count, false)` 创建非循环 RX 缓冲区。
5. 循环调用 `Buffer::refill()`，然后处理缓冲区。

这些 API 均已存在，见 [`Context` network constructors](https://github.com/fpagliughi/rust-industrial-io/blob/56dec714bbfa06f5a3a2b855707f48c7e792cdec/src/context.rs)、[`Device::create_buffer`](https://github.com/fpagliughi/rust-industrial-io/blob/56dec714bbfa06f5a3a2b855707f48c7e792cdec/src/device.rs) 和 [`Buffer::refill`](https://github.com/fpagliughi/rust-industrial-io/blob/56dec714bbfa06f5a3a2b855707f48c7e792cdec/src/buffer.rs)。ADI 官方 AD9361 示例也使用 `ad9361-phy`、`cf-ad9361-lpc`、RX I/Q `voltage0/1` 和块缓冲采集，见 [ad9361-iiostream v0.25](https://github.com/analogdevicesinc/libiio/blob/v0.25/examples/ad9361-iiostream.c)。

建议首版在运行时检查所有设备名、通道名和 `DataFormat`，不要只凭 AGX 上的旧配置假定它们永远不变。发现的标准 AD9361 RX 扫描格式通常是 `le:S12/16>>0`，即每个 I 和 Q 均用 16 bit 容器承载有符号 12 bit 样本。ADI 官方 libiio 测试 XML 也如此描述 `cf-ad9361-lpc`，见 [fmcomms2.xml](https://github.com/analogdevicesinc/libiio/blob/98c9edc1e9ea01bb4cdf0b8b4fb7ba0b586f90b1/tests/resources/xmls/fmcomms2.xml)。

## 内存拷贝与“零拷贝”边界

需要区分三层：

1. **SDR/IIOD 到树莓派 libiio 缓冲区**：这是 TCP 传输，不可能端到端无拷贝。libiio v0.25 默认 network backend 通过 `recv` 将数据直接读入客户缓冲区，没有先读到另一个临时用户空间块再 `memcpy`。证据见 [v0.25 `buffer.c`](https://github.com/analogdevicesinc/libiio/blob/v0.25/buffer.c) 和 [v0.25 `network.c`](https://github.com/analogdevicesinc/libiio/blob/v0.25/network.c)。
2. **libiio 缓冲区到 Rust DSP**：`Buffer::channel_iter::<i16>()` 使用 `iio_buffer_first/end/step` 返回缓冲区内部样本引用，可以在同一线程、同一次 `refill` 期间就地处理，不再复制整块。
3. **解交错和转换**：`Channel::read::<i16>(&buf)` 每次会新建 `Vec<T>`，然后调用 `iio_channel_read` 把指定通道解交错、转换并拷贝进 Vec。同时读 I/Q 会生成两个 Vec 和两次通道拷贝。见 [`Channel::read`](https://github.com/fpagliughi/rust-industrial-io/blob/56dec714bbfa06f5a3a2b855707f48c7e792cdec/src/channel.rs)。

libiio v0.25 还有 `WITH_NETWORK_GET_BUFFER` 的 Linux `splice` + 临时文件 `mmap` 路径，但官方 CMake 将它标记为 **experimental zero-copy transfers** 且默认关闭。不建议为了“零拷贝”标签在第一版打开它；只有在可回滚的专项基准中证明它在树莓派上更稳定/更快，才值得考虑。见 [v0.25 build options](https://github.com/analogdevicesinc/libiio/blob/v0.25/README_BUILD.md) 和 [`network_get_buffer`](https://github.com/analogdevicesinc/libiio/blob/v0.25/network.c)。

实现建议：采集线程内如果 DSP 很轻，直接借用采集缓冲区处理；如果需要把 IQ 交给其他线程，用预分配、可循环复用的自有 IQ 块和有界队列，接受一次明确拷贝。避免每块调用两次 `Channel::read` 又再合并成第三个缓冲区。

## 线程与并发限制

`industrial-io` 的 `Context` 内部使用 `Arc`，`InnerContext` 是 `Send + Sync`，`Device` 是 `Send`；但 README 明确说 `Channel` 和 `Buffer` 目前都是 `!Send + !Sync`。`Buffer::refill()` 需要 `&mut self`，同一缓冲区不能由多个线程同时 refill。见 [Thread Safety](https://github.com/fpagliughi/rust-industrial-io/blob/56dec714bbfa06f5a3a2b855707f48c7e792cdec/README.md#thread-safety) 和 [`buffer.rs`](https://github.com/fpagliughi/rust-industrial-io/blob/56dec714bbfa06f5a3a2b855707f48c7e792cdec/src/buffer.rs)。

推荐并发模型：

```text
采集线程（拥有 Context/Channel/Buffer）
  refill → 最小化格式处理/一次拷贝 → 有界 IQ 块队列
                                                ↓
                                  DSP/录制/识别工作线程
```

队列必须有界。处理跟不上时要预先选择策略：阻塞采集、丢弃最旧块、丢弃最新块，或降低采样率；不能让内存无界增长。

crate 虽然提供 `Buffer::poll_fd()` 和 `set_blocking_mode()`，但 libiio v0.25 的 network backend 没有实现 device `get_fd`/`set_blocking_mode` backend op，这些调用对网络上下文会返回 `ENOSYS`。网络采集应使用阻塞 `refill()` + `Context::set_timeout_ms()`，并将超时和重连做成显式状态机。证据见 [v0.25 `device.c`](https://github.com/analogdevicesinc/libiio/blob/v0.25/device.c) 和 [v0.25 `network.c`](https://github.com/analogdevicesinc/libiio/blob/v0.25/network.c)。

## 吞吐上限和主要瓶颈

Raspberry Pi 4 Model B 官方规格包含 Gigabit Ethernet，见 [Raspberry Pi 4 product brief](https://pip.raspberrypi.com/categories/685-whitepapers-app-notes/documents/RP-003474-WP/Raspberry-Pi-4-Product-Brief.pdf)。单路 AD9361 RX 复数样本如果是 I16 + Q16，则线上原始 IQ 负载为 4 byte/complex-sample：

| 复数采样率 | 原始 IQ 负载 | 未计开销的比特率 |
|---:|---:|---:|
| 1 MS/s | 4 MB/s | 32 Mbit/s |
| 5 MS/s | 20 MB/s | 160 Mbit/s |
| 10 MS/s | 40 MB/s | 320 Mbit/s |
| 20 MS/s | 80 MB/s | 640 Mbit/s |
| 25 MS/s | 100 MB/s | 800 Mbit/s |
| 30.72 MS/s | 122.88 MB/s | 983.04 Mbit/s |
| 61.44 MS/s | 245.76 MB/s | 1.966 Gbit/s |

因此 1 Gbit/s 的绝对数学上限是 31.25 MS/s，而实际 TCP/IP/Ethernet/IIOD 有必然开销，可持续采样上限必然低于该数。30.72 MS/s 的原始 IQ 已经占用 983.04 Mbit/s，加上协议开销后无法在 1 Gbit/s 链路上完整承载；61.44 MS/s 更不可能。如果同时开启两路 RF（四个 I/Q scan element），同一采样率的负载翻倍。

这些是传输层上限，不是实测性能。具体 P201PRO 的 FPGA/IIOD 实现、以太网 MAC/PHY、TCP 窗口、缓冲大小、树莓派温度/降频和后续 DSP 都可能先成为瓶颈。Rust 不会改变这个网络上限。

## 实施前必做的验证

以下是后续获得授权后的实施/基准计划，本次没有执行：

1. 记录树莓派实际 `aarch64`/Debian 版本、Rust 版本、`libiio.so` 版本和 SDR 端 IIOD 版本；确认 `iio_info -u ip:192.168.1.10` 能完整枚举。
2. 用最小 Rust 程序只建立 context，验证 `ad9361-phy`/`cf-ad9361-lpc`/`voltage0`/`voltage1` 及它们的数据格式。
3. 暂不做 DSP，对 1、5、10、15、20、25 MS/s 进行纯 refill 吞吐测试；对每个采样率测 16 KiS、64 KiS、256 KiS、1 MiS 缓冲。
4. 每秒记录 refill bytes/s、最大/平均/高分位 refill 耗时、超时/短读次数、CPU 占用、RSS、网口实际吞吐、温度和降频。
5. 分别比较：（a）采集线程内原地扫描；（b）两次 `Channel::read` 分配 Vec；（c）一次拷贝到复用 IQ 块再交给 DSP 线程。
6. 连续运行至少数小时，模拟网络短断和 IIOD 重启，确认超时、context/buffer 重建和 systemd 退出都可控。

“高性能”的验收标准应写成可测数字，例如：指定采样率下连续 N 小时无 refill 错误，p99 refill 时间低于一块样本的采集时长，RSS 无持续增长，处理队列不积压。

## 最终建议

1. **选 Rust，但理由应是可预测的长期服务、DSP 效率、线程模型和部署，不是认为 Rust 能让 libiio/TCP 本身变快。**
2. 首版固定 `industrial-io = 0.6.1` 并优先固定 libiio v0.25；若系统已是 v0.26，先做编译、链接和长时采集验证再接受，不直接跟随 libiio main/v1 的新 API。
3. 将采集缓冲区固定在单独线程；轻 DSP 原地处理，重 DSP 通过可复用块 + 有界队列分发。
4. 先用 5–10 MS/s 建立稳定基线，再逐步上探；对 20 MS/s 以上不作事先承诺，由实测决定。
5. 只有 profiling 证明 Rust safe wrapper 的分配/解交错是瓶颈后，才引入小范围 `libiio-sys` unsafe 封装；不在第一版启用 libiio 实验性 network zero-copy。

## 一手资料索引

- Rust 官方：[`aarch64-unknown-linux-gnu` platform support](https://doc.rust-lang.org/rustc/platform-support/aarch64-unknown-linux-gnu.html)
- crates.io：[`industrial-io` 0.6.1](https://crates.io/crates/industrial-io/0.6.1)、[`libiio-sys` 0.4.1](https://crates.io/crates/libiio-sys/0.4.1)
- Rust binding 官方源码库：[`fpagliughi/rust-industrial-io` at `56dec714`](https://github.com/fpagliughi/rust-industrial-io/tree/56dec714bbfa06f5a3a2b855707f48c7e792cdec)
- Analog Devices libiio：[v0.25 source](https://github.com/analogdevicesinc/libiio/tree/v0.25)、[v0.26 source](https://github.com/analogdevicesinc/libiio/tree/v0.26)、[v0.25 AD9361 streaming example](https://github.com/analogdevicesinc/libiio/blob/v0.25/examples/ad9361-iiostream.c)
- Raspberry Pi 官方：[Raspberry Pi 4 Product Brief](https://pip.raspberrypi.com/categories/685-whitepapers-app-notes/documents/RP-003474-WP/Raspberry-Pi-4-Product-Brief.pdf)
