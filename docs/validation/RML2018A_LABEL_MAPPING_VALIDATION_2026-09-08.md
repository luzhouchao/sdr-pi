# RML2018.01A 用户指定名称映射 — 2026-09-08

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
