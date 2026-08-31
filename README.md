# sdr-pi

P201 Pro SDR、Raspberry Pi 4B Rust 采集端和 Zynq-7020 FPGA 加速的统一工程仓库。

仓库只保存继续开发和复现所需的源码、配置样例、构建脚本、版本路线与测试证据。Vivado 安装包、厂商原始工程、综合缓存、私钥、密码以及可重新生成的大型二进制不会提交。

## 当前状态

- Raspberry Pi 4B 已通过 Rust + libiio 驱动 P201 Pro。
- `10 MS/s` 纯采集实测约 `9.988 MS/s / 38.102 MiB/s`，未出现超时或短读。
- 树莓派只需要 libiio 运行库；Rust 在本机交叉编译，不需要安装到树莓派。
- FPGA 历史主线以 V8L1 为最高硬件验证基线；当前 SDR 实际加载镜像必须重新读取身份后才能引用这些能力。
- 当前优化方向是端到端扫描会话、SDR 本机传输和可复用 FPGA 摘要内核，而不是孤立追求 FFT 单项速度。

## 目录

| 目录 | 内容 |
| --- | --- |
| [`raspberry-pi/`](raspberry-pi/) | Rust/libiio 客户端、树莓派网络配置与实测报告 |
| [`sdr-system/`](sdr-system/) | P201 Pro 内嵌 Buildroot/IIOD 系统基线与后续系统优化 |
| [`fpga/`](fpga/) | 精简后的 FPGA HDL、Vivado 脚本、版本路线和硬件证据 |
| [`docs/`](docs/) | 跨层架构、路线和迭代工作流 |

## 快速开始

本机 WSL/Docker 构建 ARM64 Rust 客户端：

```bash
cd raspberry-pi/p201pro-rust
docker build -t p201pro-rust-cross:1.98 -f Dockerfile.cross .
docker run --rm -v "$PWD:/work" -w /work p201pro-rust-cross:1.98 \
  bash -c 'cargo test --all-targets && \
    CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc \
    cargo build --release --target aarch64-unknown-linux-gnu'
```

树莓派端只读探测：

```bash
./p201pro-test probe
```

默认安全配置短采样：

```bash
./p201pro-test capture --seconds 3
```

## 安全边界

- 不提交密码、私钥、访问令牌或带凭据的日志。
- 不覆盖厂商原始 `BOOT.bin` 或原始 SD 备份。
- 未通过时序、路由、Bootgen、哈希和物理断电重启验证的 FPGA 镜像，不得标记为硬件验证通过。
- FPGA/BOOT 大文件只在通过门禁后作为 GitHub Release artifact 发布，不进入 Git 历史。
- 修改 SDR 系统或 FPGA 前必须保存当前状态、提供回滚镜像，并在测试后验证 AD9361/IIO 健康。

迭代规则见 [`docs/ITERATION_WORKFLOW.md`](docs/ITERATION_WORKFLOW.md)。
