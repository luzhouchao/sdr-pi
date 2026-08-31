# Raspberry Pi 4B GPU FFT/PSD 可行性研究

研究日期：2026-08-31
目标平台：Raspberry Pi 4B，AArch64，VideoCore VI / V3D 4.2
范围：工程研究和后续基准设计；本轮未安装软件、未修改启动配置、未重启设备、未部署代码

## 结论

GPU 应纳入 SDR 性能方案，但不应直接替换当前 RustFFT 路径。推荐把它定位为一个可选的
**批量 FFT/PSD 加速器**：Pi 4 的 Mesa V3DV 可以通过 Vulkan 使用 V3D GPU，VkFFT 官方也明确
列出 Raspberry Pi 4 GPU 支持。技术路线成立，当前设备状态却还不能运行它，而且没有任何一手
资料能证明单个 2048 点 FFT 在 Pi 4 GPU 上会快过 Cortex-A72 NEON。

建议的优先级是：

1. 继续把 RustFFT 作为生产基线和 GPU 故障回退路径。
2. 在维护窗口内启用并验证 `vc4-kms-v3d` + Mesa V3DV；这一步涉及启动配置和重启，不能在线热切换。
3. 用 VkFFT Vulkan FP32 做相同输入的 1/2/4/8/16/32 帧批处理交叉测试。
4. GPU 内融合 `packed i16 IQ -> Hann -> FFT -> power/PSD -> accumulation/reduction`，只读回小结果。
5. 只有 GPU 在完整端到端路径中显著释放 CPU、没有造成采集丢帧且满足延迟门槛，才进入默认路径。

OpenCL 不作为主路线。Mesa 当前 Rusticl 文档列出的受支持和实验驱动都不包含 `v3d`；即使手动
设置 `RUSTICL_ENABLE=v3d` 能暴露某种设备，也属于未受支持的实验，不适合作为 SDR 部署基础。

## 当前设备基线

此前的只读检查得到：

| 项目 | 当前状态 | 含义 |
| --- | --- | --- |
| CPU 架构 | `aarch64` | 可运行 Pi 4 的 V3DV/Vulkan 用户态栈 |
| DRM 设备 | `/dev/dri` 不存在 | 当前没有可供 V3DV 打开的 V3D DRM render node |
| 内核模块 | `v3d`、`vc4` 未加载 | GPU DRM 路径当前未启用 |
| Vulkan 工具 | 无 `vulkaninfo`，未发现相关包 | 尚不能枚举 Vulkan API、队列、内存类型和限制 |
| OpenCL 工具 | 无 `clinfo`，未发现相关包 | 尚不能枚举 OpenCL 平台；也没有证据存在 V3D OpenCL 驱动 |
| CPU FFT | 2048 点完整流水线 p50 `46.352 us`、p99 `51.408 us` | GPU 必须以此为端到端基准，而不是只比较 kernel 时间 |

Mesa 官方说明 V3D 栈包含用于 Pi 4/5 的 V3DV Vulkan 驱动，Pi 4 对应 V3D 4.2；Mesa 通过内核
V3D DRM 驱动调度 GPU 命令。因此，当前缺少 `/dev/dri` 且未加载 V3D DRM 时，安装一个 Rust
crate 或 VkFFT 头文件本身不能让 GPU 工作。见 [Mesa V3D/V3DV 文档][mesa-v3d]。

Raspberry Pi 官方已经宣布 Pi 4 的 V3DV 获得 Vulkan 1.2 一致性认证。这证明现代软件栈在
Pi 4 上能提供合规 Vulkan，而不是证明当前这个系统镜像已经具备相同版本；仍必须在目标机用
`vulkaninfo` 实测。见 [Raspberry Pi Vulkan 1.2 公告][pi-vulkan12]。

## 为什么不能假定 GPU 单帧更快

当前 CPU 数字包含：

```text
interleaved i16 IQ -> Hann -> Complex32 FFT -> power sum/max
```

GPU 端到端时间必须包含：

```text
CPU/采集缓冲交接
-> 写入或刷新映射的 Vulkan buffer
-> queue submit
-> GPU IQ 转换/加窗/FFT/PSD/归约
-> fence 完成通知
-> 必要的 cache invalidate
-> CPU 读取结果
```

Vulkan 把命令记录到 command buffer 后提交给 queue，fence 用于把设备完成状态通知主机；GPU
读写之间还需要正确的 memory dependency/barrier。持久映射也不等于自动一致：只有
`HOST_COHERENT` memory 才不需要显式 flush/invalidate，实际 memory type 必须从目标 V3DV 设备
查询。见 [Vulkan queue submission][vk-queues]、[同步语义][vk-sync]、[内存语义][vk-memory]。

VkFFT 可以把 FFT 附加到用户 command buffer，使用用户分配的 storage buffer，计算阶段除 planning
外不占 CPU；FP32 Vulkan 后端只要求 Vulkan 1.0。它也明确列出 Raspberry Pi 4 GPU 支持。
但是 VkFFT README 展示的短 FFT 吞吐测试会把变换批到总数据量 `500 MB–1 GB` 后取平均，而且
使用的是 A100/MI250 等 GPU。这种大批量吞吐结果不能外推到 Pi 4 的单个 2048 点实时延迟。
见固定版本的 [VkFFT README][vkfft-readme]。

所以这里有两种不同的“赢”：

- **单帧低延迟赢**：GPU 完整 p99 必须低于 CPU 的 `51.408 us`。逐帧 submit + wait 很可能很难达到，
  但必须实测，不能凭经验定论。
- **批量吞吐/释放 CPU 赢**：GPU 每帧摊销时间满足到达速率，并把 ARM 核留给采集、分类和控制；
  可以接受一定聚批延迟。这是更现实的目标。

## 收益门槛

对 `N=2048`、50% overlap，hop 为 1024 sample：

| Fs | 帧间隔 `H/Fs` | CPU p99 核时/单 RX | GPU 稳态硬上限 |
| ---: | ---: | ---: | ---: |
| 10 MS/s | 102.40 us | 0.502 core | 摊销时间必须 `<102.40 us/frame` |
| 20 MS/s | 51.20 us | 1.004 core | 摊销时间必须 `<51.20 us/frame` |
| 25 MS/s | 40.96 us | 1.255 core | 摊销时间必须 `<40.96 us/frame` |

“能跟上”不等于“值得替换”。本项目建议 GPU 候选至少同时满足：

- 数值结果与 RustFFT 参考在预先定义的 FP32 容差内，峰值 bin/幅度和 PSD 积累一致；
- live IIOD 采集无新增 short read、drop、队列持续增长或 p99 refill 恶化；
- 在目标采样率下，批次 p99 除以 batch size 不超过帧间隔的 70%，保留 30% 抖动余量；
- 与相同 live workload 的 RustFFT 相比，DSP CPU 核时至少降低 50%，或在 20 MS/s 下稳定释放
  至少约 0.5 个 ARM 核给调制识别；
- 端到端 p99 满足业务延迟预算，并且长时运行无 GPU fault、温度降频或系统 throttle。

70% 是本项目的生产准入策略，不是 Vulkan 或硬件规格。若 GPU 只在 kernel timestamp 上更快，
但 queue/fence、cache、准备和读回后的 wall time 没有改善，判定为未通过。

## 批处理的延迟代价

假设第一帧已经就绪，再等待一个 batch 的其余帧，最老一帧新增的聚批延迟下界为：

```text
Tfill_oldest = (B - 1) * H / Fs
batch cadence = B * H / Fs
```

对 `N=2048`、50% overlap：

| Batch | 10 MS/s 新增延迟 | 20 MS/s 新增延迟 | 25 MS/s 新增延迟 |
| ---: | ---: | ---: | ---: |
| 1 | 0 us | 0 us | 0 us |
| 2 | 102.40 us | 51.20 us | 40.96 us |
| 4 | 307.20 us | 153.60 us | 122.88 us |
| 8 | 716.80 us | 358.40 us | 286.72 us |
| 16 | 1.536 ms | 768.00 us | 614.40 us |
| 32 | 3.174 ms | 1.587 ms | 1.270 ms |

因此频谱显示、慢速统计和调制识别可以试 `B=8–32`，严格事件检测先试 `B=1–4`。batch size
不能只按最高吞吐选择；必须把“最老样本到结果”的 age 一起报告。

## 推荐的 Vulkan 数据通路

```text
libiio acquisition (CPU)
  -> 预分配 hop/block ring
  -> persistently-mapped Vulkan input slot
  -> compute shader: packed i16 IQ -> f32 complex + Hann
  -> barrier
  -> VkFFT FP32 C2C, numberBatches=B
  -> barrier
  -> compute shader: |x|^2 + PSD accumulate + band/top-k reduction
  -> fence per ring slot
  -> read back compact result only
```

实现原则：

- 创建一次 Vulkan instance/device/compute queue、VkFFT application、pipeline、descriptor、command
  pool 和 buffer ring；VkFFT 会运行时编译 kernel，planning/compile 绝不能进入热路径。
- 使用 2–3 个 batch slot。只在复用一个 slot 前等待其 fence；不要每个 FFT 调一次
  `vkQueueWaitIdle`，也不要让多个 Rust 线程并发操作同一 queue。Vulkan 规定 host 对 queue 的访问
  需要外部同步。
- 一个 command buffer 完成预处理、FFT、PSD 和归约；stage 之间放正确的 compute barrier。
- 首版使用 packed `u32` 承载一对 `i16 I/Q`，在 shader 中符号扩展，避免一开始依赖 16-bit
  storage feature；VkFFT 本身使用 FP32 C2C。
- 查询而不是假设 `HOST_VISIBLE`、`HOST_COHERENT`、`DEVICE_LOCAL` 组合；非 coherent 路径按
  `nonCoherentAtomSize` 对齐 flush/invalidate。
- 生产模式只回传积累 PSD、bandpower、top-k、噪声底和质量指标。完整 complex FFT 或逐帧完整
  PSD 只用于验证/调试。
- 保留 RustFFT worker。Vulkan 初始化失败、`VK_ERROR_DEVICE_LOST`、输出校验失败或队列超时时，
  自动降级到 CPU，而不是停止采集。

### 避免 overlap 重复搬运

2048 点一帧的 packed i16 IQ 是 8 KiB；转换为 complex f32 后是 16 KiB；完整 f32 PSD 是 8 KiB。
10 MS/s、50% overlap 时，如果每帧都重复上传完整 packed 窗口，仅输入就约 80 MB/s；上传 f32
窗口约 160 MB/s，再逐帧读回完整 PSD又约 80 MB/s。虽然 Pi 没有独立显卡的 PCIe 往返，这些
内存访问、cache 维护和 GPU DRAM 流量仍会与 ARM 和网络采集竞争。

正式实现应让输入 ring 只接收每 hop 新到的 4 KiB packed IQ，再由 GPU gather/window shader
组帧；或至少先分别测试“完整帧复制”和“hop ring”两种路径。VkFFT kernel 快但重复搬运过多时，
整个系统仍可能输给 CPU NEON。

## Rust 集成边界

VkFFT 是 C header-only 库，Vulkan 后端还需要 Vulkan loader 和 glslang 编译支持。Rust 程序建议
通过一个很窄的 C ABI shim 管理 VkFFT/Vulkan opaque handles，而不是在业务层暴露大量 `unsafe`：

```text
Rust acquisition/queue/metrics
    -> C ABI: gpu_fft_create / submit / poll / destroy
        -> Vulkan + VkFFT
```

这类产物依赖目标机的 AArch64 GNU 用户态 GPU 驱动和 `libvulkan.so`，应走 ARM64 GNU/native-library
交叉构建与 ELF 依赖检查，不应把它当作可完全静态链接的 musl 二进制。VkFFT application 和 shader
编译在启动阶段创建一次；启动耗时也要记录，但不混进 steady-state FFT 延迟。

## OpenCL/Rusticl 判断

Mesa 官方把 Rusticl 定义为构建在 Gallium drivers 之上的 OpenCL 实现，并且默认不广告任何设备，
需要通过 `RUSTICL_ENABLE` 明确启用。更关键的是，当前官方环境变量文档列出的受支持驱动为
`iris`、`llvmpipe`、`nouveau`、`panfrost`、`radeonsi`，实验驱动只有 `r600`；列表中没有 `v3d`。
见 [Rusticl 文档][rusticl] 和 [Rusticl 支持驱动列表][rusticl-env]。

因此：

- VkFFT 虽然有 OpenCL backend，但目标 Pi 当前没有受支持的 V3D OpenCL runtime。
- `llvmpipe` 是 CPU 软件路径，不是 VideoCore GPU 加速，不能拿它证明 GPU FFT 可行。
- 不把 `RUSTICL_ENABLE=v3d`、clvk 或其他兼容层放入主计划；它们只可作为隔离实验，且必须
  明确标注 unsupported。
- 当前可信主路线是 `V3D DRM -> Mesa V3DV -> Vulkan -> VkFFT`。

## 启用驱动、重启和回滚边界

Raspberry Pi 的 `config.txt` 在 Linux 启动前读取，修改仅在重启后生效。现代 Raspberry Pi OS
通常位于 `/boot/firmware/config.txt`，但实施前必须通过挂载点和系统版本确认实际文件，不凭路径
猜测。官方示例使用 `dtoverlay=vc4-kms-v3d`；overlay README 说明它启用 kernel DRM
VC4 HDMI/HVS/V3D driver，并提供不同 CMA 参数。见 [config.txt 官方源码文档][pi-config] 和
[官方 overlay README][pi-overlay]。

未来维护窗口的可回滚步骤应是：

1. 只读保存 OS/kernel/Mesa、boot config、已安装包、`dmesg`、显示/SSH状态；定位真实 config 文件。
2. 对启动分区和 config 做可恢复备份，确认可通过本机挂载 SD 卡恢复；不要只依赖下一次 SSH。
3. 准备匹配当前 OS/架构的 Mesa Vulkan driver、Vulkan loader、`vulkaninfo` 和构建/运行依赖；
   离线环境先在本机保存准确版本的软件包及校验和。
4. 只改 GPU overlay 这一项，记录 diff，然后重启。不要同一轮同时调 CMA、CPU governor 或网络。
5. 重启后验证 `v3d`/`vc4`、`/dev/dri/renderD*`、render 组权限、`vulkaninfo --summary`、compute
   queue、memory types、workgroup/shared-memory limits，并运行最小 compute smoke test。
6. 若启动、显示、网络、IIOD 或 CPU FFT 基线异常，恢复原 config 后再重启；安装的用户态包可以
   留存但不得进入生产服务。

本研究不授权执行上述变更。尤其不能把“安装包无需重启”和“Device Tree overlay 需要重启”混为一谈。

## 可回滚 benchmark matrix

所有 GPU 测试都使用同一份固定 IQ 输入和 RustFFT 参考输出；CPU 与 GPU 不能分别生成随机输入。
先 synthetic，后 live。每项记录 warm-up、至少 60 秒统计，最终候选再做 30 分钟热稳定性测试。

| 阶段 | Backend/路径 | NFFT | Batch | 输出 | 目的 |
| --- | --- | --- | --- | --- | --- |
| 0A | RustFFT 当前配置 | 1024/2048/4096/8192 | 1 | power + peak | 变更前基线 |
| 0B | RustFFT，启用 V3D 后但 GPU idle | 同上 | 1 | 同上 | 检查驱动/内存争用是否影响 CPU |
| 1 | VkFFT，预装 f32 input，FFT only | 同上 | 1/2/4/8/16/32 | complex | GPU 计算上限 |
| 2 | mapped packed i16 + window + VkFFT | 2048/4096 | 1/2/4/8/16/32 | full PSD | 完整但高读回成本 |
| 3 | 同上 + PSD accumulate/reduction | 2048/4096 | 1/2/4/8/16/32 | top-k/bands | 推荐融合路径 |
| 4 | live IIOD + CPU RustFFT | 2048 | 1 | compact | 10/20/25 MS/s 对照 |
| 5 | live IIOD + GPU fused | 2048 | 1/4/8/16 | compact | 真正 go/no-go |

每个点至少采集：

- startup/planning/shader compile 时间；
- CPU wall：input handoff、map/write/flush、submit、poll/wait、invalidate/read；
- GPU timestamp（若 compute queue 的 `timestampValidBits` 支持）和 batch execution；
- 每帧摊销 p50/p95/p99/max、最老样本端到端 age、batch queue 深度；
- 采集 samples/s、refill p99、short read/drop、softnet/网卡 counter；
- 每核 CPU、GPU/CPU 温度、频率、RSS、throttle/GPU fault/dmesg；
- 与 RustFFT 的 complex/PSD 最大误差、RMS 误差、peak-bin 一致率和积累误差。

严格按以下回滚次序隔离变量：

```text
CPU before -> enable V3D/reboot -> CPU with GPU idle
-> synthetic GPU -> live GPU -> stop GPU service -> CPU after
-> 如有回归则恢复 config/reboot -> CPU restored
```

不能把安装驱动、performance governor、CPU affinity、CMA、网络参数和 GPU 算法一次性修改；否则
无法知道收益或回归来自哪里。

## 最终建议

- **现在**：RustFFT 继续承担 10 MS/s 主路径；GPU 尚未启用，不能算作现有算力。
- **近期实验**：维护窗口启用 V3DV，做 VkFFT FP32 batched benchmark。先测 2048 点、`B=1/4/8/16`。
- **适合 GPU**：20–25 MS/s 单 RX且后续调制识别需要释放 ARM 核；或者谱图/统计允许
  `0.3–3 ms` 聚批延迟，并且只需压缩结果。
- **不适合 GPU**：单帧硬延迟接近 50 us、每帧完整结果都要立刻回 CPU、或 GPU 路径导致采集
  内存/调度争用。
- **更高负载**：双 RX 20–25 MS/s 的原始 IQ 本身已超千兆链路预算，GPU 在 Pi 端无法补救网络
  瓶颈；这时应优先让 SDR FPGA 输出 PSD/top-k/bandpower 摘要。

最终架构不是 CPU、GPU、FPGA 三选一，而是：

```text
低延迟/回退：RustFFT NEON
批量频谱/识别：Pi V3DV + VkFFT
高采样率/双通道/压缩：SDR FPGA 预处理与摘要
```

## 一手资料

- [Mesa V3D/V3DV driver stack][mesa-v3d]
- [Raspberry Pi：Pi 4 Vulkan 1.2 conformance][pi-vulkan12]
- [Raspberry Pi `config.txt` 官方源码文档][pi-config]
- [Raspberry Pi firmware overlay README（固定提交）][pi-overlay]
- [Linux kernel V3D driver documentation][linux-v3d]
- [VkFFT README（固定提交）][vkfft-readme]
- [VkFFT API guide source][vkfft-api]
- [VkFFT MIT license（固定提交）][vkfft-license]
- [Vulkan command/queue submission][vk-queues]
- [Vulkan synchronization][vk-sync]
- [Vulkan memory mapping/coherency][vk-memory]
- [Vulkan synchronization examples][vk-sync-examples]
- [Mesa Rusticl][rusticl]
- [Mesa Rusticl supported-driver list][rusticl-env]

[mesa-v3d]: https://docs.mesa3d.org/drivers/v3d.html
[pi-vulkan12]: https://www.raspberrypi.com/news/vulkan-update-version-1-2-conformance-for-raspberry-pi-4/
[pi-config]: https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/config_txt/what_is_config_txt.adoc
[pi-overlay]: https://github.com/raspberrypi/firmware/blob/eef9c230a0e70e23a54be98f90d5237ab6e0b0fd/boot/overlays/README
[linux-v3d]: https://docs.kernel.org/gpu/v3d.html
[vkfft-readme]: https://github.com/DTolm/VkFFT/blob/066a17c17068c0f11c9298d848c2976c71fad1c1/README.md
[vkfft-api]: https://github.com/DTolm/VkFFT/blob/066a17c17068c0f11c9298d848c2976c71fad1c1/documentation/VkFFT_API_guide.tex
[vkfft-license]: https://github.com/DTolm/VkFFT/blob/066a17c17068c0f11c9298d848c2976c71fad1c1/LICENSE
[vk-queues]: https://docs.vulkan.org/spec/latest/chapters/devsandqueues.html#devsandqueues-submission
[vk-sync]: https://docs.vulkan.org/spec/latest/chapters/synchronization.html
[vk-memory]: https://docs.vulkan.org/spec/latest/chapters/memory.html#memory-device
[vk-sync-examples]: https://docs.vulkan.org/guide/latest/synchronization_examples.html
[rusticl]: https://docs.mesa3d.org/rusticl.html
[rusticl-env]: https://docs.mesa3d.org/envvars.html#envvar-RUSTICL_ENABLE
