# RadioML2018A 模型权重集合

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
模型结构strict load、前向及AGX GPU运行尚未验证；下载不代表识别适配或准入。

用户已明确删除`local-assets/amc-eval/checkpoints/rml2018a/rf-v1-ft-batched-seed44/epoch-010.pt`。
旧RF-v1配置仍保留历史身份，但依赖该文件的入口当前不可用，不自动恢复、回退或改绑新权重。
原始`local-assets/amc-eval/checkpoints/rml2018a/seed44/best.pt`保留，和新集合的D8 seed44哈希一致。
旧报告、识别结果及接收IQ保留；其中epoch-10结果描述删除前实验，四窗仍只列为探索方式。
训练/微调暂停，`recognizer_available=false`保持。

完整执行、清理及人工删除依据见[导入验证](../validation/RML2018A_MODEL_IMPORT_2026-09-14.md)。
