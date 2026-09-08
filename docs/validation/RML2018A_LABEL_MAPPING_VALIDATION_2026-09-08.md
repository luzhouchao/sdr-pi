# RML2018.01A 用户指定名称映射 — 2026-09-08

当前采用本文末节核对的 **4090 server-v1**；下面首先保留本日较早的截图指定
记录，operator-v1 内容未追溯修改。

基线 `21c14d8`，用户明确要求“2018的数字标签就这么映射”，并提供 24 类截图。
项目后续数字 ID→名称解释采用下表，不再自行换回旧 classes.txt 的排列。
机器可读唯一新映射为
[`rml2018a-labels.operator-v1.json`](../../jetson-agx/sdrharness/config/amc/rml2018a-labels.operator-v1.json)，
SHA-256 `3ca235c692b37cea23675625a102a91602cf0a573c2ffac3949b61857d4a893f`。
数组索引就是原 one-hot Y 的 argmax，数字 ID、logits 顺序、权重和标签数组不重排。

| ID | 名称 | 中文说明 |
| --- | --- | --- |
| 0 | OOK | 开关键控 |
| 1 | 4ASK | 四进制幅移键控 |
| 2 | 8ASK | 八进制幅移键控 |
| 3 | BPSK | 二进制相移键控 |
| 4 | QPSK | 四相相移键控 |
| 5 | 8PSK | 八进制相移键控 |
| 6 | 16PSK | 十六进制相移键控 |
| 7 | 32PSK | 三十二进制相移键控 |
| 8 | 16APSK | 十六进制幅相键控 |
| 9 | 32APSK | 三十二进制幅相键控 |
| 10 | 64APSK | 六十四进制幅相键控 |
| 11 | 128APSK | 一百二十八进制幅相键控 |
| 12 | 16QAM | 十六进制正交幅度调制 |
| 13 | 32QAM | 三十二进制正交幅度调制 |
| 14 | 64QAM | 六十四进制正交幅度调制 |
| 15 | 128QAM | 一百二十八进制正交幅度调制 |
| 16 | 256QAM | 二百五十六进制正交幅度调制 |
| 17 | AM-SSB-WC | 带载波单边带调幅 |
| 18 | AM-SSB-SC | 抑制载波单边带调幅 |
| 19 | AM-DSB-WC | 带载波双边带调幅 |
| 20 | AM-DSB-SC | 抑制载波双边带调幅 |
| 21 | FM | 调频 |
| 22 | GMSK | 高斯最小频移键控 |
| 23 | OQPSK | 偏移四相相移键控 |

## 接入与历史边界

`evaluate-amc-mamba.py` 的 RML2018A 名称文件默认值改为新版，既有 load_labels
返回新顺序、provenance 和 SHA-256。仅改变后续名称解释，没有执行评测；HDF5
自身若有 classes 元数据，原读取优先级未改。当前已知 RML2018A 文件没有名称元数据。

旧 `rml2018a-labels.json` 被 seed44 experimental manifest 按 SHA-256 固定引用，
继续保留原字节。历史 profile、报告、语料、已归档名称及 manifest 不追溯改写；
既有冻结实验继续按原 hash 解释。RF-v1 Worker 当前仍使用数字身份和 provisional
wire 标签，没有借此部署 Worker、修改运行结果或把 `name_status` 强行设为 verified。

新来源明确标记 `operator_specified`，含本次原附件路径/大小/SHA-256 和旧映射
引用。这已落实用户的项目命名选择；独立 RF 标签、名称生产准入证据和原映射
争议的科学验证是另一个事实，不从截图推断其已通过。V3a 的映射选择子项完成，
生产证据/接入仍未验收；其他模型门保持原状，不再把“选择哪张表”当作当前待定。

## 验证与清理

逐项核对 0–23 全部名称、24 项唯一性和中文说明；以 AST 隔离执行真实 load_labels
函数，用内存 one-hot 形状替身验证新 JSON 输出、来源和哈希，不导入评测器的
Torch/HDF5 依赖，不读取任何数据集。核验旧标签 SHA-256 与冻结 manifest 仍一致，
Python AST、文档链接和 diff 检查通过。

无服务/模型/射频操作，无训练、诊断或 locked test 访问；recognizer_available=false。
未创建构建、缓存、临时文件或制品，开发清理数量 0/0 bytes。用户原附件不复制、
不删除，机器映射只记录其来源 receipt；无新增外部保留包。源码/映射与文档提交
到 Git，不修改以前封存的证据。


## 后续：以 4090 原始表为准

用户进一步明确“你看我4090服务器上的表，以那个为准”。AGX 基线 `f34129f`。
通过既有 `4090-via-aliyun` 严格主机校验只读核查，找到实际来源：

| 4090 路径 | 字节 | SHA-256 |
| --- | --- | --- |
| `/home/lzc/sdrharness/source/sdr_amc/labels.py` | 1793 | `30b233ad3f57c28caf52adab36ef4baeba8a361e75bd154b6aa6d71ceb331a91` |
| `/home/lzc/sdrharness/reports/canonical-label-map.json` | 11981 | `61839847402fb1492e75d3872ca85ab1b838f01da24ce76ad90612eaf06aa60b` |
| `/home/lzc/sdrharness/source/sdr_amc/adapters.py` | 7356 | `679eb7b401cf9550eddf3ea1cc2f01a48355cac95d52d63cf5849f3687e50a78` |
| `/home/lzc/sdrharness/source/sdr_amc/audit.py` | 24259 | `928abe150092dcde2d0a3a2ec92e390a56682bf1da9db2ee64a7f0f4847da4b7` |

该仓库 HEAD 为 `988e9e22468eaa7c87453218d4a73a20806fd267`；上述四个文件与
HEAD 无差异，其他 README/删除模型产物等用户改动未触碰。名称顺序从源码
`RADIOML2018A_RAW_LABELS` 用 AST literal 读取，与报告 source=RadioML2018.01A
条目的 raw_label_id/raw_label 按 ID 排序逐项比较，**24/24 与截图/operator-v1 一致**。
Adapter 源码明确 `raw_id = argmax(one_hot)`、`raw_label = RADIOML2018A_RAW_LABELS[raw_id]`，
报告生成器也按原始 ID 枚举该表；此次只读源码，没有执行 Adapter 或读取 HDF5。

注意该服务器项目另有 `sdr_amc_common12_v1`：那是跨数据集筛选后的 12 类输出
编号，例如 BPSK 的 canonical_index=0，但其 RadioML 原始 raw_label_id=3。
本项目采用原始 24 类 ID；不能用这套 12 类编号去解释当前 24-logit checkpoint。

当前机器映射改用
[`rml2018a-labels.server-v1.json`](../../jetson-agx/sdrharness/config/amc/rml2018a-labels.server-v1.json)，
SHA-256 `859f74d4776bb58dd5dd54106e168b47f5c4053c5170b13275ed59b15a30bac3`。
它记录服务器路径、commit、四份哈希、Adapter 语义及 operator-v1 父级引用；中文
说明仍来自用户截图。后续名称读取默认值指向 server-v1。operator-v1 和旧
classes.txt 映射的原字节/hash 均保留，不复制远端源码或重写历史证据。

另核对 `/data/lzc/rf-aligned-batched-20260905/labels.json` 与 preflight 同名文件：
两者 SHA-256 为 `6010b4d39a98c57b5b2f47bcdf8ab9e849dd90190443b00e2916af91198d4e57`，
只有 0–23 数字及 `display_names=provisional_not_used`，并非另一张名称表。
训练仓库 `/data/lzc/mamba` 的数据读取源码将 one-hot 用 argmax 转成整数；本次未
读取 checkpoint、训练/测试数组、评测结果或 locked test，也未控制任何远端进程。

V3a 的项目映射选择与来源核对据此完成；这证明用户指定的服务器表、代码解释和
报告一致，不把它当成 V1b 独立实收标签或模型准确率证据。生产 name_evidence
引用及已准入 Worker 部署仍属于 A1，现有非准入运行标签保持 provisional。
AGENTS、章节规划、权威 checklist 和推进顺序同步此边界。

检查包括：24 项顺序/唯一性、源码/报告一致性、原始与 common12 编号分离、真实
名称加载函数的隔离测试、前两版映射哈希不变、Python AST、链接与 diff。
服务器缺少 rg，改用 git grep/受限文件名查找定位；没有安装工具或生成缓存。
无临时文件、复制制品或新保留包，清理 0 文件/0 bytes。只有本地新增版本化
映射/文档与读取默认路径进入提交，服务和模型准入不变。
