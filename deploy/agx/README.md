# AGX 构建、配置与运维

当前运行组件为 Rust Controller、Planner 和 Web；P201 接收服务源码在 [src/sdrd](../../src/sdrd/README.md)。
当前部署状态以 [checklist](../../docs/SDR_AGENT_PROJECT_CHECKLIST.md) 和 [验证记录](../../docs/validation/README.md) 为准。

| 目录 | 用途 |
| --- | --- |
| [config](config) | 当前配置模板、语料规范与保留的冻结合同 |
| [scripts](scripts/README.md) | 构建、健康、恢复、发布校验和当前监测验证 |
| [systemd](systemd) | Web、Planner、健康与P201恢复服务模板 |
| [tests](tests) | 语料合同与运维工具离线测试 |

## 构建与检查

```bash
bash deploy/agx/scripts/verify-checkout.sh
bash deploy/agx/scripts/check-toolchain.sh
bash deploy/agx/scripts/build-agent-runtime.sh
```

构建入口对 Controller/Web 执行格式、测试、Clippy和release构建，并运行Planner测试。
它不启动服务或采集；发布文件暂存于 `.artifacts/sdrharness/`，不入Git。
开发构建和临时目录遵守 [AGENTS.md](../../AGENTS.md)，不要对生产Planner的node_modules链接执行npm ci。
不再构建独立C++识别Worker，不需要Torch、Mamba、h5py或论文环境。

## 实际服务

当前安装与运行目录独立于源码树：

- Controller/Web：`/home/jetson/.local/lib/sdrharness/bin/`。
- Planner：`/home/jetson/.local/lib/sdrharness/planner/current/`。
- 服务配置：`/etc/sdrharness/runtime.env` 与 `request.json`。
- Web状态和provider配置：`/var/lib/sdrharness/web-console/`，不要复制或输出其中凭证。
- Web入口：AGX的8787端口，仅用于受信任网络。
- P201：`192.168.1.10:43110`，由唯一`sdrd`拥有Linux/IIO接收。

`systemd/`是安装模板，改源码不自动修改已安装服务。部署及切回需验证独立发布目录、
单实例与健康，按[工作规则](../../AGENTS.md)执行。日常只读检查使用已安装CLI：

```bash
/home/jetson/.local/lib/sdrharness/bin/sdr-agent --mode health --sdrd 192.168.1.10:43110
```

接收忙时不能另开普通状态连接。健康/恢复脚本不构成新的RF采集授权。
Planner由Web管理provider配置，不预设本地Spark必须运行。

## Python与历史合同

当前网页单窗PSD使用NumPy/SciPy；其第三方源码说明见
[RFObserver](../../src/agent/web-console/vendor/rfobserver/README.md)。
这些轻量依赖与论文推理环境分开；本轮没有变更已安装服务的Python选择。

`config/amc/`仍有历史身份、标签和预处理合同，其中一部分被Controller/Web的历史记录解析直接引用。
它们保持冻结字节，不代表模型、数据或生产识别可用；`recognizer_available=false`。
旧独立识别服务、Spark模板、RF/模型实验脚本和配套测试已退役，历史记录通过文档索引查询。
