# RadioML2018A 模型权重集合

## 当前统一库（2026-09-26）

用户确认数据保留范围为四个开源数据集各自的source、接收原始IQ、raw、guard，共16套数据版本；模型独立管理。
四数据集×八模型的32份权重统一放在`/home/jetson/models/amc/<dataset>/<variant>/best.pt`。
数据集为rml2016a、rml2016b、rml2018a、hisarmod2019；模型为CNN2-stable、ResNet、GRU、CLDNN、MCLDNN、MCformer、MAMC、D10。
用户2026-09-26明确训练来源：四套D10来自**沙盘4090 WSL**（`ssh shapan4090`，luzhouchao@192.168.50.46:2222）；七种baseline来自**原4090 Linux**（既有4090-via-aliyun路由）。AGX库位置及转存位置不能代替训练来源。
沙盘连接技能已安装至`/home/jetson/.codex/skills/connect-shapan4090/SKILL.md`；两别名免密/严格主机检查及四份D10源权重SHA核对通过，见[连接与身份审计](../evidence/SHAPAN4090_CONNECTION_SKILL_2026-09-26.json)。
三套新数据集补入21份baseline seed42；原2018A七份及四份D10迁入，原路径保留符号链接，不复制权重。
用户2026-09-26随后明确四套D10全部固定seed42：已从沙盘4090取回正式best.pt，四份严格加载通过，新三套CUDA批量/逐条数值门及top-1一致通过；2018A权重SHA未变。当前32模型全部seed42，旧非42三包移至`/home/jetson/models/archive/d10-before-seed42-20260926`作替换回滚，旧seed别名指向旧包，不冒充seed42。见[seed42导入审计](../evidence/D10_ALL_SEED42_IMPORT_2026-09-26.json)。此前不同seed的选样与D10数值记录已被本次选择覆盖。
2016A/B保留128点，2018A/Hisar保留1024点。各数据集标签顺序见统一库class-order.json。
独立D8包已经按用户要求删除，下面导入表仅是2026-09-14历史事实，不代表D8仍可用；D10内部d8命名依赖不能删除。
本次统一库验证和保留清单见[导入审计](../evidence/AMC_32_MODEL_COLLECTION_2026-09-26.json)。新三套D10 CUDA数值门通过，实收识别尚未验证，生产recognizer_available=false。

## 历史导入（2026-09-14）

2026-09-14按用户要求从4090导入AGX，共8种模型、12份正式`best.pt`。
权重根为`/home/jetson/sdrharness/local-assets/amc-eval/checkpoints/rml2018a/server-models-20260914`，
各权重路径为`<根>/<variant>/seed<seed>/best.pt`，模型文件不入Git。

| 模型 | variant | seed |
| --- | --- | --- |
| CNN2-stable | `baseline_cnn2_stable` | 42 |
| ResNet | `baseline_resnet` | 42 |
| GRU | `baseline_gru` | 42 |
| CLDNN | `baseline_cldnn` | 42 |
| MCLDNN | `baseline_mcldnn` | 42 |
| MCformer | `baseline_mcformer` | 42 |
| MAMC（Mamba1） | `baseline_mamc` | 42 |
| Shared-Bi／原始Mamba D8（Mamba2） | `amc_mamba_d8` | 42、43、44、45、46 |

每个seed目录同时保存配置、validation/test指标及评估摘要。指标为服务器归档成绩，
不是本次AGX实测；不同seed的划分和初始化须独立核对。MAMC与Shared-Bi为不同模型。
集合内`manifest.json`记录源路径、训练提交、源码快照身份和SHA-256，
`source/`仅存依赖源码快照，未安装或激活；`class-order.json`与server-v1原24类顺序一致。

全部权重已通过源/本地哈希及CPU `torch.load(..., map_location="cpu", weights_only=True)`检查，
参数字典键为`model_state`。原评估输入为float32、1024点，`[N,1024,2]`转置为`[N,2,1024]`，
无额外外部归一化、去DC、滤波或去噪。不得直接套用旧RF-v1单位/四窗共享RMS作为原始模型基线。
导入时仅做CPU参数检查；随后用户授权的12模型strict load与GPU先导已通过，
全量识别已启动，操作与边界见[三数据集识别](RML2018A_MODEL_COLLECTION_EVALUATION.md)。
工程推理不代表生产准入。

用户已明确删除`local-assets/amc-eval/checkpoints/rml2018a/rf-v1-ft-batched-seed44/epoch-010.pt`。
旧RF-v1配置仍保留历史身份，但依赖该文件的入口当前不可用，不自动恢复、回退或改绑新权重。
原始`local-assets/amc-eval/checkpoints/rml2018a/seed44/best.pt`保留，和新集合的D8 seed44哈希一致。
旧报告、识别结果及接收IQ保留；其中epoch-10结果描述删除前实验，四窗仍只列为探索方式。
训练/微调暂停，`recognizer_available=false`保持。

完整执行、清理及人工删除依据见[导入验证](../validation/RML2018A_MODEL_IMPORT_2026-09-14.md)。
