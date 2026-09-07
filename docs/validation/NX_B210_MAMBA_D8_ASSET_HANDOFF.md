# NX B210 与 AMC-Mamba D8 资产交接

最后核对：2026-09-04（Asia/Shanghai）

> **历史交接记录：** 当前第1—6章不含发射端，也不以 B210/USRP 回放作为运行、
> 训练或验收依赖。本文中的 B210 配置只保留端口/接线审计价值；任何“后续发射”
> 表述均已被
> [`CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](../CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md)
> 取代。

本文是后续对话的快速入口，记录 NX 发射端硬件、P201 RX1、4090 训练仓库，
以及已落到 AGX 的数据集、D8 权重和离线运行环境。有限单音已确认 B210 到
P201 RX1 的物理链路；AGX 也已严格加载两个 checkpoint 并跑完 RML2018A 与
HisarMod2019 固定测试集。P201 RX1 的一个 1,024 点有限窗口现已通过 AGX
实验 Worker 到达 Mamba 并完成清理与射频恢复；但尚未发射 RML2018A 波形、
部署生产 Recognizer Worker 或冻结可信实收 IQ 预处理合同，因此没有打开
`recognizer_available`。

## 快速定位

| 对象 | 位置或入口 | 当前状态 |
| --- | --- | --- |
| NX SSH | AGX SSH alias `nx` | `wheeltec@wheeltec` 已验证 |
| NX B210 项目 | `/home/wheeltec/b210`（NX 本机） | USB 3.0 与双寄存器回环已通过 |
| NX B210 skill | `/home/wheeltec/b210/.codex/skills/use-b210/SKILL.md` | 项目局部 skill |
| B210 已接天线口 | 面板 `RF A / TX/RX` | UHD `channel 0`（运行时显示 `FE-TX2`），TX 灯实测点亮 |
| P201 已接天线口 | 面板 `RX1`（不是 `TRX1`） | SDRD 软件 RX0 / AD9361 `voltage0,1`，当前输入为 `A_BALANCED`；433.92 MHz 空口链路已确认 |
| 4090 SSH | AGX SSH alias `4090-via-aliyun` | `lzc@server` 已验证 |
| Mamba 仓库 | `/data/lzc/mamba`（4090 本机） | GitHub `main` 与本地一致 |
| Mamba GitHub | `git@github.com:luzhouchao/mamba.git` | 盘点时为 `d8f567d7065baed7e6a6db0b4fe050b1879fc73c` |
| 训练 checkpoint 对应源码 | 4090 commit `8bc6fb5dc58e1b83338bdebb2624824f1e6b0798` | clean；D8 推理文件与当前 `main` 无差异 |
| AGX 离线资产根 | `/home/jetson/sdrharness/local-assets/amc-eval/` | Git 忽略；数据、selected checkpoint、最小源码、venv、wheel、结果均在此 |
| AGX RML checkpoint | `checkpoints/rml2018a/seed44/best.pt` | 1,691,357 B，SHA-256 `e5a1bccd...`，完整 test 已通过 |
| AGX Hisar checkpoint | `checkpoints/hisarmod2019/seed43/best.pt` | 1,694,557 B，SHA-256 `714ac46c...`，完整 test 已通过 |
| AGX 完整结果 | `results/{rml2018a,hisarmod2019}/full-fp32-b256-v1/` | accuracy 0.638248 / 0.714564；含混淆矩阵、逐类、逐 SNR 与性能 |
| 实验实收链路 | Controller `--mode recognize-live` | P201 sequence 41 → 8,192 B 私有 spool → seed44 Worker → 删除；生产能力仍关闭 |
| 4090 候选归档 | `.../runs/rml2018a/amc_mamba_d8/d8_weight_tied_2018a_b128_seed{42..46}_nw8/` | 五个源权重仍在；AGX 重复副本已在选择 seed44 后清理 |

4090 的 Tailscale 路径在候选导入时不可用；候选与本轮 selected checkpoint、
split 和最小源码均属于小文件，按 `connect-4090-server` 约束经阿里云反向
SSH 路径传输。两份多 GB 数据集直接从 AGX 所接移动硬盘复制并逐字节校验，
没有绕 4090 重传。

### 当前射频配置速查

- B210 发射端：NX 上 `MyB210`（serial `2508504`），天线接面板
  **RF A / TX/RX**，软件必须选 `--channels 0 --ant TX/RX`；UHD 显示
  `FE-TX2` 是这块克隆板的实际映射，不要据名称改成 channel 1。
- P201 接收端：天线接面板 **RX1**，不是 `TRX1`/`RX2`；SDRD 使用软件
  RX0 和 AD9361 `voltage0,1` I/Q，当前 RF 输入读回为 `A_BALANCED`。
- 已确认配置：433.920 MHz 中心、B210 2.5 MS/s/500 kHz/70 dB/幅度
  0.2/`+100 kHz` SINE；P201 2.5 MS/s/1 MHz/手动 50 dB。该配置只用于
  有界链路验证，未来 RML2018A 发射仍需单独定义波形缩放、采样率和标签。
- 现场条件：两端均未接功放，室内约 5 米，使用标称 100 MHz--6 GHz 的
  弹簧天线；这些条件属于本次证据的一部分，不能脱离它们外推覆盖距离。
- P201 LED1/LED2 不用于判断接收成功；应检查有界 IQ、预期频点 FFT 峰、
  丢样/溢出/削顶和状态恢复。

## 当前实验端到端边界

```text
4090 训练仓库与冻结 checkpoint
                  |
                  v
AGX 外部模型资产 -> experimental CUDA/Mamba Recognizer Worker
                                         ^
                                         |
NX + B210 --未来已知标签波形--> P201 RX --有界 IQ--> AGX 第四章预处理
```

P201 仍只负责有界 RX 采集与传输。软件聚合、候选选择、DDC、重采样、
归一化、模型推理和结果持久化都留在 AGX。NX/B210 是独立测试发射端，
不得把发射能力加入 P201 或 SDR Harness Controller。

### 当前完成度一句话

`B210 RF A/channel 0 -> P201 RX1` 的单音物理链路、AGX 对原始 RML/Hisar
文件的 D8 FP32 离线推理，以及一次“P201 实收环境窗口 → 单位 RMS →
experimental Worker”的软件链路均已分别确认。最后一次没有发射且旧权重的
单位 RMS 抽样准确率下降，因此只能称为端到端接线通过，不能称为已验证空口
调制识别。完整实验记录见
[`P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md`](P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md)。

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

### 面板端口与 UHD 通道实测

2026-09-04 的现场照片和指示灯试验确认，当前天线插在 N210/B210 克隆板
面板左侧 `RF A` 分组的 `TX/RX` 口。对这块板必须使用
`--channels 0 --ant TX/RX`：UHD 把它显示为 `TX Channel: 0` / `FE-TX2`，
有限 TX 流运行时用户现场确认 RF A 指示灯点亮。此前仅按 `FE-TX1` 名称选用
`channel 1` 的假设不适用于当前物理接线；后续 RF A 发射不得沿用该假设。

P201 天线插在面板 `RX1`，不是 `TRX1`。当前 SDRD 单通道接收路径使用软件
RX0（AD9361 `voltage0,1`），RF 输入读回为 `A_BALANCED`。P201 暴露的
`led0:blue` 和 `led1:blue` 当前均使用 `heartbeat` trigger，没有证据表明它们
绑定 Linux/IIO RX buffer。因此前面板灯不亮不能用于判定 P201 没有接收。
一次 2.4465--2.4535 GHz、15 点的有界 RX1 观察扫频连续返回 sequence
13--27；每点 8,192 个复数 int16 样本，全部零丢样、零溢出、零削顶且
`health.source=iio_adapter`/`healthy=true`，证明 P201 RX 采集链路实际工作。

早期 2.450 GHz、20 dB TX/RX 对照只有 0.25967 dB 的 RMS 变化，单独看并
不足以确认链路。随后用户把接收天线换到照片确认的 P201 `RX1`，在
433.920 MHz、P201 50 dB RX gain、B210 70 dB TX gain 下做了有界 FFT
对照：发射时 sequence 39 在预期 `+100.098 kHz` 处的峰高于中值噪声
57.246 dB；停发后 sequence 40 只有 4.724 dB。目标频点功率相差
52.875 dB，噪声中值只相差 0.354 dB；两次均零丢样、零溢出、零削顶并
恢复无线电状态，NX 也无残留 TX 进程。因此物理链路现已确认是
`B210 RF A/TX-RX + UHD channel 0 -> P201 RX1`。这仍不代表 RML2018A
波形与 Mamba 识别链路已经完成。完整记录见
[`NX_B210_P201_RX1_LINK_VALIDATION_2026-09-04.md`](NX_B210_P201_RX1_LINK_VALIDATION_2026-09-04.md)。

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

### AGX 离线 checkpoint 选择

- RML2018A 在查看 test 结果前按验证集规则选择 seed44：它在 clean
  seeds 43--46 中验证 accuracy 和既定 low-SNR accuracy 最高；
- HisarMod2019 使用同一 clean 源码的 seed43，26 类；
- 这是离线实验选择，尚未等同于生产 package promotion。生产选择还要冻结
  标签、实收预处理、精度与拒识阈值。

两者都使用 `AMCMambaD8`、`d_model=64`、Mamba2 Shared-Bi、1024 点 planar
IQ。RML 为 134,798 参数，Hisar 因 26 类 head 为 135,054 参数。

## AGX 模型与数据目录

当前自包含的机器本地目录为：

```text
/home/jetson/sdrharness/local-assets/amc-eval/
  README.md
  ASSET_MANIFEST.json
  datasets/
    rml2018a/RML2018a.hdf5
    hisarmod2019/HisarMod2019.01.h5
  splits/
    RML2018a_split_seed44_tr700_val150_te150.npz
    HisarMod2019.01_split_seed43_tr700_val150_te150.npz
  checkpoints/
    rml2018a/seed44/{best.pt,config.json,evaluation_summary.json,metrics_*.json}
    hisarmod2019/seed43/{best.pt,config.json,evaluation_summary.json,metrics_*.json}
  model-source/8bc6fb5dc58e.../       # 11 个实际导入的推理依赖文件
  runtime/{venv,wheels,triton-cache}/
  results/{rml2018a,hisarmod2019}/
```

`/local-assets/` 已加入根 `.gitignore`，所以资产便于在当前 AGX 上定位，但
不会把多 GB 数据、权重、venv 或预测文件提交进 Git。小型、可审计的评测
入口和标签来源说明保留在受跟踪源码中。

五候选的指标、训练状态和 SHA-256 作为选择审计保留在下表。选择 seed44 并
确认它与新目录逐字节一致后，重复的 `/home/jetson/sdrharness-models/` 已清理；
seeds 42--46 原始制品仍在 4090 上述 run 目录，可按记录的哈希重新拉取。
`.pt` 与运行制品不得加入 Git 历史。

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

## AGX 离线验证结果

完整固定 test split、FP32、batch 256 的结果如下：

| 数据集 | Test 样本 | AGX accuracy | 4090 记录 | AGX macro-F1 | 4090 记录 |
| --- | ---: | ---: | ---: | ---: | ---: |
| RML2018A seed44 | 383,387 | 0.638248 | 0.638253 | 0.646611 | 0.646613 |
| HisarMod2019 seed43 | 117,000 | 0.714564 | 0.714547 | 0.713775 | 0.713763 |

两端另在每套 test split 上等距选择 16 条相同 IQ 比较 logits，argmax 均为
16/16 一致；RML 最大/平均绝对差为 `2.93e-5 / 3.14e-6`，Hisar 为
`1.18e-4 / 8.98e-6`。完整资源、逐类、逐 SNR、混淆矩阵、运行命令和哈希见
[`AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md`](AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md)。

## 尚未满足的生产准入项

这些候选目录不是当前 `ModelPackageLoader` 可直接接纳的生产包，也不能据此
报告识别可用：

1. RML2018A HDF5 和 checkpoint 没有保存 0--23 的调制类别名称；数据集
   `classes.txt` 已带来源和哈希暂存，但上游公开讨论质疑其与 `Y` 的对应，
   必须在生产前解决这一可信映射；
2. 必须明确 P201 捕获的采样率、DDC、抗混叠重采样、窗口对齐、去直流、
   单位 RMS 归一化和异常/静默窗口处理；
3. 当前训练输入不归一化，而 SDR Harness v1 接口要求单位 RMS planar
   float32，必须用同一 IQ corpus 验证并冻结两者之间的预处理；
4. 离线 checkpoint 与源码已选择并验证，但仍须生成受
   `ModelPackageLoader` 约束的生产模型包；
5. FP32 完整准确率和跨机 logits 已通过，仍须确定 FP16/BF16/FP32 策略、
   置信度/拒识阈值与 unknown/noise 策略；
6. 离线混淆矩阵、p50/p99、GPU/RSS/CPU 与温度已测；仍须实现有界队列为一
   的 AGX Worker，并验证排队、丢弃、取消、并发与 thermal soak；
7. 所有门禁通过前保持 `recognizer_available=false`。

## 历史：五候选导入验证

- 4090 源端与 AGX 目标端的 25 个文件逐项 SHA-256 完全一致；
- 精确总字节数为 8,735,749，文件数 25，符号链接数 0；
- 导入前 AGX `/home/jetson` 所在文件系统可用约 840.7 GB；
- 临时目录
  `/var/tmp/sdrharness-dev/mamba-d8-weight-import-20260904` 已在校验后移入
  最终资产目录，原临时路径不存在；
- 本次没有读取或保存原始 IQ，没有运行模型，没有控制现有 GPU 工作负载，
  也没有执行 RF 发射。

上面这段是五候选导入时的历史记录。本轮离线部署新增的完整证据见
`AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md`；本轮运行了模型，但
仍没有执行 RF 发射或改变 P201/NX 状态。2026-09-04 后续整理确认 4090 五个
源权重仍在且 SHA-256 不变，随后删除 AGX 的五候选重复目录，只保留当前
`local-assets/amc-eval/` 中的 RML seed44 与 Hisar seed43。
