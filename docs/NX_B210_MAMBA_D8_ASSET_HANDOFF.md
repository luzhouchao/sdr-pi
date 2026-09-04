# NX B210 与 AMC-Mamba D8 资产交接

最后核对：2026-09-04（Asia/Shanghai）

本文是后续对话的快速入口，记录 NX 发射端硬件、4090 训练仓库和已
落到 AGX 的 RML2018A D8 候选权重。当前状态仅为资产盘点与候选制品
落盘：没有执行 RF 发射，没有部署生产 Recognizer Worker，也没有打开
`recognizer_available`。

## 快速定位

| 对象 | 位置或入口 | 当前状态 |
| --- | --- | --- |
| NX SSH | AGX SSH alias `nx` | `wheeltec@wheeltec` 已验证 |
| NX B210 项目 | `/home/wheeltec/b210`（NX 本机） | USB 3.0 与双寄存器回环已通过 |
| NX B210 skill | `/home/wheeltec/b210/.codex/skills/use-b210/SKILL.md` | 项目局部 skill |
| 4090 SSH | AGX SSH alias `4090-via-aliyun` | `lzc@server` 已验证 |
| Mamba 仓库 | `/data/lzc/mamba`（4090 本机） | GitHub `main` 与本地一致 |
| Mamba GitHub | `git@github.com:luzhouchao/mamba.git` | 盘点时为 `d8f567d7065baed7e6a6db0b4fe050b1879fc73c` |
| AGX 候选权重 | `/home/jetson/sdrharness-models/amc_mamba_d8/rml2018a/shared-bi-pr02-seeds42-46` | 5 个 seed、25 个源制品（另有 2 个本地说明/校验文件）、8,735,749 源字节 |

4090 的 Tailscale 路径在本次导入时不可用；这些约 8.7 MB 的小文件按
`connect-4090-server` 约束经阿里云反向 SSH 路径传输。

## 预期端到端边界

```text
4090 训练仓库与冻结 checkpoint
                  |
                  v
AGX 外部模型资产 -> 未来 CUDA/Mamba Recognizer Worker
                                      ^
                                      |
NX + B210 --受控测试信号--> P201 RX --有界 IQ--> AGX 第四章预处理
```

P201 仍只负责有界 RX 采集与传输。软件聚合、候选选择、DDC、重采样、
归一化、模型推理和结果持久化都留在 AGX。NX/B210 是独立测试发射端，
不得把发射能力加入 P201 或 SDR Harness Controller。

## NX B210

已核对的硬件与运行时：

- UHD 识别名 `MyB210`，serial `2508504`，`type=b200`，product `B210`；
- USB ID `2500:0020`，实际运行于 USB 3.0；
- FPGA 变体固定为 A7-100T，UHD `4.1.0.5-3`；
- RX/TX 前端范围由 UHD 报告为 50 MHz--6 GHz；
- 两次 register-loopback 均通过；
- skill SHA-256：
  `74c3f60d82d0a92b7676925e782d99e550ea20208148bd2ce4a67c351b9461b4`；
- 激活脚本 SHA-256：
  `d2daefa09e6e6c0c2aa763595393b624129ecbf5eae6a3b937438c47e5b1bdca`；
- A7-100T 源镜像与当前 UHD 安装镜像均为 2,898,992 字节，SHA-256 均为
  `ee03a9e38c83a1f6f327e7b560522c2a96629e7de574196092c1b830d05fcf9b`。

操作约束来自 NX 项目局部 `use-b210` skill：

- 激活脚本必须从交互终端运行，`sudo` 密码不得进入命令或文件；
- A7-200T 镜像在该板上曾以 `fx3 is in state 5` 失败，正常操作禁止加载；
- 不写 EEPROM 或 flash；
- `--benchmark` 只覆盖 10 秒、双通道、5 MS/s 的接收测试；
- RF 发射必须另有明确的频率、采样率、带宽、增益、持续时间、端口/负载、
  物理衰减和合法工作条件。未给出这些参数时不得发射。

## Mamba 模型身份

更新后的 Mamba 仓库明确区分两个身份：

- `amc_mamba_d3_4` 是冻结的代码主线锚点和 Untied-Bi 核心对照；
- `amc_mamba_d8` 是论文主模型 Shared-Bi，也是本次搬运的候选模型；
- D9 方向低秩适配保留为 rejected evidence；
- D5/Mamba3 已退役，不应恢复为部署候选。

D8 保持 D3.4 的信号路径，但正反向扫描共享同一组 Mamba2 mixer 参数。
RML2018A 模型配置为：

- 输入 float32 planar IQ，张量形状 `[B, 2, 1024]`；
- 输出 24 类 logits；
- `d_model=64`、`d_state=16`、`d_conv=4`、`expand=2`、`headdim=16`；
- 134,798 参数，1024 点 profile 约 31.068 M MACs；
- 真实后端身份
  `real_mamba2_weight_tied_bidirectional_d8_length_conditioned_shared_coarse`；
- 训练环境记录为 Python 3.11、PyTorch 2.6、CUDA 12.4、
  `mamba-ssm` 2.3.x；
- 训练配置未启用去噪或 IQ augmentation。

训练数据加载器只把 `[T,2]` 转成 `[2,T]` float32，并在需要时居中裁剪或
补零；它没有做单位 RMS 归一化、去直流、重采样或载波同步。因此不能把
P201 原始 ADC IQ 直接送入该模型并声称与训练分布一致。

## AGX 权重目录

目录布局如下：

```text
/home/jetson/sdrharness-models/amc_mamba_d8/rml2018a/shared-bi-pr02-seeds42-46/
  README.md                 # 本地资产提示（导入后补充）
  SHA256SUMS                # 本地全量文件校验（导入后补充）
  seed42/
    best.pt
    config.json
    evaluation_summary.json
    metrics_val.json
    metrics_test.json
  seed43/ ... seed46/       # 同一结构
```

目录权限为 `0750`，已搬运的模型与 JSON 文件权限为 `0640`。`.pt` 与运行
制品位于 Git 仓库之外，不得提交到 `sdrharness`。

### 候选 checkpoint

| Seed | `best.pt` 字节 | SHA-256 | 训练源码状态 |
| ---: | ---: | --- | --- |
| 42 | 1,691,293 | `6f984a78639a8e8e15403a1257b264839c6057165b3ae9ac8640ecc056f78143` | commit `82cfbc2b...`，dirty |
| 43 | 1,691,357 | `5e00b5eef2a01323da374700f658472ad990027ec2a95e99998ee963a0cbb33a` | commit `8bc6fb5d...`，clean |
| 44 | 1,691,357 | `e5a1bccdaf4b0290f41b26cb05b8b98565df9d5b07147727d79bbf43f6cb42dd` | commit `8bc6fb5d...`，clean |
| 45 | 1,691,357 | `794f94ff8e1df81f9e9da6ed95e1201daa9a06876c53efe136bf58ce0a7479c4` | commit `8bc6fb5d...`，clean |
| 46 | 1,691,357 | `b998125611730cdb83e1f8bb5d4562ec9bff7bcd4430481d8c44547f011993c6` | commit `8bc6fb5d...`，clean |

### 已记录的 RML2018A 指标

| Seed | Val accuracy | Val macro-F1 | Val `[-8,0] dB` accuracy | Test accuracy |
| ---: | ---: | ---: | ---: | ---: |
| 42 | 0.633076 | 0.659477 | 0.378550 | 0.633209 |
| 43 | 0.626736 | 0.638534 | 0.372007 | 0.626179 |
| 44 | 0.637852 | 0.646249 | 0.381778 | 0.638253 |
| 45 | 0.627578 | 0.638577 | 0.376953 | 0.627191 |
| 46 | 0.632458 | 0.644956 | 0.380411 | 0.631712 |

seed44 的验证准确率与既定 low-SNR 指标最高；seed42 的验证 macro-F1
最高，但其训练源码状态是 dirty。该事实只用于后续选择，不等同于已经
指定生产 checkpoint。选择规则必须先固定在验证集指标上，不能按测试集
结果事后挑 seed。

## 尚未满足的生产准入项

这些候选目录不是当前 `ModelPackageLoader` 可直接接纳的生产包，也不能据此
报告识别可用：

1. RML2018A HDF5 和当前制品没有保存 0--23 的调制类别名称，必须从可信
   数据集定义冻结标签顺序并生成带哈希的 `labels` 文件；
2. 必须明确 P201 捕获的采样率、DDC、抗混叠重采样、窗口对齐、去直流、
   单位 RMS 归一化和异常/静默窗口处理；
3. 当前训练输入不归一化，而 SDR Harness v1 接口要求单位 RMS planar
   float32，必须用同一 IQ corpus 验证并冻结两者之间的预处理；
4. 必须选择一个生产 checkpoint，锁定对应源码，并生成 AGX 可验证的模型包；
5. 必须确定 FP16/BF16/FP32 策略、置信度/拒识阈值与 unknown/noise 策略；
6. 必须实现有界队列为一的 AGX Worker，并完成同 IQ 数值比较、混淆矩阵、
   p50/p99、GPU/RSS/CPU、丢弃与温度验证；
7. 所有门禁通过前保持 `recognizer_available=false`。

## 本次导入验证

- 4090 源端与 AGX 目标端的 25 个文件逐项 SHA-256 完全一致；
- 精确总字节数为 8,735,749，文件数 25，符号链接数 0；
- 导入前 AGX `/home/jetson` 所在文件系统可用约 840.7 GB；
- 临时目录
  `/var/tmp/sdrharness-dev/mamba-d8-weight-import-20260904` 已在校验后移入
  最终资产目录，原临时路径不存在；
- 本次没有读取或保存原始 IQ，没有运行模型，没有控制现有 GPU 工作负载，
  也没有执行 RF 发射。
