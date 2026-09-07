# AGX AMC-Mamba D8 离线部署与完整测试集验证 — 2026-09-04

## 结论

AMC-Mamba D8 已在 Jetson AGX Orin 上以独立 Python `venv`、Jetson CUDA
PyTorch 和本机编译的 ARM64 CUDA 扩展成功加载。RML2018A seed44 与
HisarMod2019 seed43 checkpoint 均按冻结源码严格加载，两个固定 test split
均已逐条跑完；AGX FP32 结果与 4090 训练端记录只相差少数边界样本。

这次完成的是**离线模型部署与数据集验证**，不是生产 Recognizer Worker，也
不是空口 RML2018A 端到端识别。P201 原始 ADC IQ 到训练分布的 DDC、重采样、
幅度标定、窗口策略和 unknown/noise 拒识仍未冻结，因此
`recognizer_available` 必须继续为 `false`。

## 范围与安全边界

- 只读取移动硬盘复制到 AGX 的两个 HDF5 数据集和 4090 复制来的模型制品；
- 没有读取完整训练工程，只冻结 D8 实际导入的 11 个模型文件；
- 没有控制 P201、NX/B210 或执行任何 RF 发射；
- 没有停止现有 Spark `llama-server`。性能数据是在该进程约 2.56 GiB RSS、
  GPU layers 常驻的正常 AGX 服务环境中测得；
- 数据集、checkpoint、venv、wheel、预测记录与结果均位于 Git 忽略的
  `/home/jetson/sdrharness/local-assets/amc-eval/`。

## 固定资产

| 资产 | 字节 | SHA-256 |
| --- | ---: | --- |
| `datasets/rml2018a/RML2018a.hdf5` | 21,449,148,312 | `e3dd0bef66a3426959ee66a1709a8c0a95d4f8395d18aaf6f1214bdbc763bd38` |
| `datasets/hisarmod2019/HisarMod2019.01.h5` | 6,399,126,728 | `b4b2d2dcde17691b09e3d6b1aa91a9fbadd096980d5103a47af18f93ae1b596f` |
| RML2018A seed44 `best.pt` | 1,691,357 | `e5a1bccdaf4b0290f41b26cb05b8b98565df9d5b07147727d79bbf43f6cb42dd` |
| HisarMod2019 seed43 `best.pt` | 1,694,557 | `714ac46cfbdb014350bb2f89f18938c612f27a28d0b3e5d1160bd21dd8386191` |
| RML2018A seed44 split | 3,906,249 | `5b8ccdc0183455445d5beab20f2ed7e553ff616da76a31114f700929607d0792` |
| HisarMod2019 seed43 split | 1,193,298 | `fd79c0ba607b3504180fc0fe4d3cf2bbc367f0a2d4f3cf86691b04d33e518b0a` |

两份多 GB HDF5 在复制后已与移动硬盘源文件逐字节比较；完整评测又重新计算
了 AGX 副本 SHA-256，均与表中值一致。checkpoint 和 split 经阿里云反向
SSH 从 4090 传输，目标端 SHA-256 与源端一致。

模型定义固定到 4090 Mamba 工程 clean commit
`8bc6fb5dc58e1b83338bdebb2624824f1e6b0798`。本地只保存：

```text
models/d8/{__init__.py,model.py,sequence.py}
models/d3_4/{__init__.py,model.py}
models/d3_3/{__init__.py,model.py}
models/d2/{__init__.py,model.py,sequence.py}
utils/model_defaults.py
```

评测入口建立仅包含上述冻结推理文件的 namespace package，避免把上游顶层
package init、训练 registry、数据增强和训练依赖带入 AGX。首次验证时一并
复制但从未执行的 `models/__init__.py` 与 `utils/__init__.py` 已在整理时删除。
首次完整结果的 `summary.json` 仍保留当时 13 个文件的哈希作为历史证据；
当前入口只校验仍实际使用的 11 个文件。

## AGX 运行环境

| 项目 | 值 |
| --- | --- |
| AGX OS | JetPack 6.2.1 / L4T R36.4.4 / Linux 5.15.148-tegra |
| GPU | Jetson AGX Orin，CUDA capability 8.7 |
| Python | 3.10.12，独立 `venv` |
| PyTorch | 2.8.0 Jetson CUDA wheel，CUDA 12.6，cuDNN 9.3.0 |
| NumPy / h5py | 1.26.4 / 3.14.0 |
| Mamba runtime | `mamba-ssm` 2.3.1、`causal-conv1d` 1.6.1、Triton 3.4.0 |
| import dependencies | Transformers 5.3.0、huggingface-hub 1.8.0 |

选择 `venv` 而不是在 AGX 再建 Conda 环境，是为了直接保持 JetPack 的系统
CUDA、Jetson PyTorch wheel 和 Python 3.10 ABI；4090 训练端继续使用原 Conda
环境。两端不要求完全相同的 CUDA/PyTorch build，而由固定源码、固定权重和
同 IQ logits 数值对照验证移植一致性。

现成的旧 ARM64 extension 与 PyTorch 2.8 ABI 不兼容，因此两个扩展均针对
Orin `sm_87` 从源码重编译：

| Wheel | 源码 tag / commit | 字节 | SHA-256 |
| --- | --- | ---: | --- |
| `causal_conv1d-1.6.1-cp310-cp310-linux_aarch64.whl` | v1.6.1.post4 / `9e4ace0b1d53ede275308abf25f64a1fc04c5fd4` | 29,680,711 | `fb0d8c4a3d75a3b542e385f0a9d8566ff9b8537fb777fdc5518120a6317b86cc` |
| `mamba_ssm-2.3.1-cp310-cp310-linux_aarch64.whl` | v2.3.1 / `c5afbdf3bda1a09d68f65181ae3a43ec71079820` | 46,491,101 | `7b3eb559eb4dd86a4c4c292199a5745d531d195e3f087064f2dd5cefc8c83b94` |

Mamba2 的 FP32、FP16 和 BF16 随机张量 CUDA smoke 均输出有限值；正式完整
准确率与 4090 parity 本轮固定使用 FP32。低精度全测试集和阈值选择仍是
后续准入项。

## 数据与标签合同

RML2018A：

- `X (2555904,1024,2) float32`，评测时只转置为 `[B,2,1024]`；
- `Y (2555904,24) int64` one-hot，转为 `argmax` 数字类别；
- `Z (2555904,1) int64` 为 SNR；
- test split 为 seed44 固定的 383,387 条；
- 不做归一化、去直流、去噪、augmentation、裁剪或重采样。

RML2018A HDF5 不含类别名。本仓库保存了数据集附带 `classes.txt` 的 24 项
顺序及来源，但 radioML 上游公开 issue #25 对该顺序是否和 `Y` 一致存在
争议。因此本轮总准确率、数字类别混淆矩阵和数字类别 recall 是可信的，
调制名称只能作为**临时显示名**，不能据此开放生产识别或生成带名称的空口
结论。

HisarMod2019：

- `X (780000,2,1024) float32`，无需转置；
- `Y` 的 26 个原始值为
  `0,1,2,3,4,10,11,12,13,14,20,21,22,23,24,30,31,32,34,40,41,44,50,51,54,61`；
- 与冻结训练加载器一致，按原始值升序映射到 `0..25`；
- 类别名称直接读取 HDF5 `classes`；
- test split 为 seed43 固定的 117,000 条；同样不做额外预处理。

Hisar 第一次 smoke 暴露了非连续 raw label；评测脚本随后加入冻结映射与送入
GPU 前的范围检查，避免 CUDA loss 内核异步失败。修正后完整结果与训练参考
一致。

## 完整测试集结果

| 数据集 / checkpoint | 样本数 | AGX accuracy | 4090 记录 | 差值 | AGX macro-F1 | 4090 记录 | 差值 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RML2018A seed44 | 383,387 | 0.638248037 | 0.638253253 | -0.000005217（-2 条） | 0.646611427 | 0.646613191 | -0.000001763 |
| HisarMod2019 seed43 | 117,000 | 0.714564103 | 0.714547009 | +0.000017094（+2 条） | 0.713774683 | 0.713762750 | +0.000011933 |

RML2018A 的逐 SNR accuracy 从 -20 dB 的 0.044050 上升到 10 dB 的
0.978218，12--30 dB 保持约 0.982--0.985。Hisar 从 -20 dB 的 0.487092
上升到 10 dB 的 0.937887、18 dB 的 0.972452。完整逐类 precision/recall/F1、
逐 SNR、混淆矩阵和 top confusions 均在结果目录中。

## 4090 与 AGX 同 IQ logits 对照

从每个固定 test split 首尾之间等距选择 16 个全局样本 ID，4090 使用
PyTorch 2.6.0+cu124，AGX 使用 PyTorch 2.8.0 / CUDA 12.6；两端均为冻结
源码、同一 checkpoint、FP32、关闭 TF32：

| 数据集 | logits 元素 | 最大绝对误差 | 平均绝对误差 | 最大相对误差 | argmax 一致率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| RML2018A | 384 | 2.93255e-5 | 3.13805e-6 | 2.17824e-4 | 16/16 |
| HisarMod2019 | 416 | 1.18256e-4 | 8.97816e-6 | 2.03101e-3 | 16/16 |

这比只比较汇总 accuracy 更直接地证明了跨架构移植的数值一致性；完整测试集
的正确样本总数与训练记录各只相差 2，不能据此推断完整逐样本预测也只差 2 条。

## AGX 性能与资源

完整评测均为 batch 256，排除前 5 个 warm-up batch；单样本延迟另做 10 次
warm-up 后 100 次测量。

| 指标 | RML2018A | HisarMod2019 |
| --- | ---: | ---: |
| 完整评测 wall time | 190.364 s | 62.617 s |
| 端到端吞吐 | 2,013.96 sample/s | 1,868.51 sample/s |
| 纯模型吞吐 | 2,340.13 sample/s | 2,335.81 sample/s |
| batch 总时延 p50 / p99 | 110.829 / 111.735 ms | 110.836 / 111.748 ms |
| H2D p50 / p99 | 1.194 / 1.330 ms | 1.191 / 1.371 ms |
| 模型推理 p50 / p99 | 109.379 / 110.170 ms | 109.402 / 110.156 ms |
| 单样本模型推理 p50 / p99 | 33.507 / 34.636 ms | 33.953 / 35.682 ms |
| CUDA peak allocated / reserved | 581,596,672 / 792,723,456 B | 581,597,696 / 792,723,456 B |
| 进程最大 RSS | 1,293,217,792 B | 1,272,688,640 B |
| GPU 温度，前 / 后 | 45.656 / 50.156 °C | 43.937 / 46.781 °C |

RML 的 HDF5 顺序读取为 10.342 s、输入转置/选择为 1.484 s；Hisar 分别为
3.136 s 和 0.229 s。这里没有 Worker 队列，因此 drop 指标不适用；队列丢弃、
并发、持续负载和 thermal soak 必须在生产 Worker 阶段另测。

## 复现入口与结果

评测脚本：
`jetson-agx/sdrharness/scripts/evaluate-amc-mamba.py`，本轮内容 SHA-256 为
`446ced21f5077ab425d3977c08a87b67ec89f2d41975643fa88a845f2223d453`。

```bash
local-assets/amc-eval/runtime/venv/bin/python \
  jetson-agx/sdrharness/scripts/evaluate-amc-mamba.py \
  --dataset rml2018a --precision fp32 --batch-size 256 \
  --warmup-batches 5 --single-sample-repeats 100 \
  --hash-dataset --save-predictions --progress-every 100 \
  --output-dir local-assets/amc-eval/results/rml2018a/full-fp32-b256-v1

local-assets/amc-eval/runtime/venv/bin/python \
  jetson-agx/sdrharness/scripts/evaluate-amc-mamba.py \
  --dataset hisarmod2019 --precision fp32 --batch-size 256 \
  --warmup-batches 5 --single-sample-repeats 100 \
  --hash-dataset --save-predictions --progress-every 50 \
  --output-dir local-assets/amc-eval/results/hisarmod2019/full-fp32-b256-v1
```

关键结果摘要 SHA-256：

- RML `summary.json`：
  `075ae052af659e95d1a51bb4f4026b7b3fd382e9ab9de38c057bd2106596b004`；
- Hisar `summary.json`：
  `eb52502dd05bd9be5e9015588baed1953ee511179d8f536d89f6999096fec562`。

每个结果目录另含 `confusion-matrix.csv`、`per-class.csv`、`per-snr.csv`、
`top-confusions.csv` 和带 sample ID/SNR/confidence 的 `predictions.npz`。

## 清理与保留

完整结果确认后，两个 extension `build/` 与生成的 `*.egg-info`、失败/抽样
smoke 结果、两个依赖源码 checkout、空的 `cache/`/`reports/`、未执行的两个
package init，以及重复的五候选 AGX 目录均已按精确路径清理。4090 上的五个
候选源权重已在删除前重新核对存在与哈希；依赖源码可由表中的 tag/commit
恢复，selected checkpoint 和两个 wheel 均有本地校验副本。

仅本任务产生的回收站条目随后被定向永久删除，共释放 1,291,473,759 字节；
这些本地副本已不能从回收站恢复，但可从上述 4090 路径、上游 commit 或保留
wheel 重建。没有清空整个回收站，也没有删除其中既有的其他用户项目。

另按下载时间和 wheel 内容确认并删除本轮 venv 安装产生的 63 个 pip
`http-v2` 条目及其 self-check（127 个文件、24,814,801 字节）；2026-09-01
及更早的 49,674,075 字节用户缓存保持不动。两部分累计永久清理
1,316,288,560 字节。

两个完整结果、两套数据集、selected checkpoint、split、11 个最小模型文件、
可运行 venv 和两个自编译 wheel 均保留。本轮产生的 86,592,320 字节 Triton
JIT cache 从共享的 `~/.triton/cache` 归入
`local-assets/amc-eval/runtime/triton-cache/`；评测入口默认固定到该可再生目录，
不会再污染用户级缓存。迁移时将 115 个含旧绝对路径的生成型索引改写到新
目录，并验证 161 个索引中的 1,127 个子文件引用全部存在且未逃逸目录；两套
16 条严格加载烟测通过，第二次暖缓存复测前后均为 1,298 文件、86,888,880
字节，索引集合 SHA-256 均为
`6ae8502c43f8d667a17600e8591213dedfaa55eaaaf17f52c0ec16bc64461676`。
烟测输出与新增 `__pycache__` 随后已删除。

`local-assets/amc-eval/` 下没有残留 `RUNNING` marker，也没有触碰现有 Spark
服务或用户其他回收站项目。

## 尚未满足的生产门禁

1. 解决 RML2018A `Y` 与调制名称的可信映射；
2. 固定 P201 捕获到模型输入的采样率、DDC、抗混叠重采样、窗口、DC 与幅度合同；
3. 在相同完整 test split 上决定 FP16/BF16/FP32，并冻结数值误差与准确率阈值；
4. 定义静默、噪声、分布外信号与低置信度的拒识策略；
5. 实现 bounded queue=1 的 AGX Worker、Unix socket Adapter、取消和丢弃计数；
6. 做 P201 实收 RML 波形、并发/故障、长时间 thermal soak 和端到端验证；
7. 上述门禁通过前不得打开 `recognizer_available`。
