# seed42原验证集：8模型与三数据集识别

## 当前追加：Mamba三组包含质量失败行重跑

用户随后补充guard。source/raw已完成766,770次预测、两张矩阵和独立读回核验，
两组各383,385条，ACC为63.3082%/49.7294%，raw的3,723条质量失败均已有预测。
guard单独补跑383,385条，包含12,277条质量失败，跳过0；同一原始D8 seed42、FP32、
单窗1024、同一原validation。全三组共同的主要分母均383,385，不重新计算已完成source/raw。

当前guard根`local-assets/amc-eval/results/mamba-guard-val-allquality-20260915`，
服务`sdr-mamba-guard-val-allquality-20260915.service`，进度默认指向guard。
`prepare-validation --variants amc_mamba_d8 --planes guard --include-quality-failed --fresh`
支持单独补跑；source仅用于只读核验标签/行号，不进入这次预测。
guard完成后自动核验并生成自己的混淆矩阵与保留清单；source/raw图表留在下面原根。
停止：`systemctl --user stop sdr-mamba-guard-val-allquality-20260915.service`。
预计280秒，内部3600秒期限和systemd最大4500秒保持。见[补跑验证](../validation/RML2018A_CLEAN12_EVALUATION_2026-09-14.md#source和raw完成及guard补跑2026-09-15)。

### 已完成的source/raw

2026-09-15用户要求不忽略未通过质量校验的行，重新识别source和raw。
沿用原始Mamba D8 seed42、单窗1024、FP32/关闭TF32及服务器原validation成员，
source/raw各383,385条，共766,770次新预测；raw包含此前排除的3,723条，质量跳过0。
未改IQ或归一化，质量标志原样保留；共同严格合格379,662源行另报对照。
本阶段仅这一个模型和两种输入，随后guard补跑见上方；既有8模型三组结果保留。历史59.07%来自已删除的epoch-10微调模型。

新根`local-assets/amc-eval/results/mamba-source-raw-val-allquality-20260915`，
服务`sdr-mamba-source-raw-val-allquality-20260915.service`已退出；可通过进度脚本`--root`查看此根。
有限计划内部期限3600秒、systemd最大4500秒，磁盘3GiB余量门保持；先导约560秒，实际以进度为准。
已完成独立核验、两张混淆矩阵及CSV、保留清单，实际533.254秒。
停止命令：`systemctl --user stop sdr-mamba-source-raw-val-allquality-20260915.service`。

现有`prepare-validation`增加`--variants amc_mamba_d8 --planes source raw --include-quality-failed`，
配合`--fresh`从HDF5生成元数据、在全新结果根从零运行；父级为已停止或已完成计划。
不指定这些选项时保持既有8模型/三组/严格质量策略。包含质量失败是采样范围选择，
并不忽略行号、标签、原划分、哈希、有限IQ和输出校验。见[启动验证](../validation/RML2018A_CLEAN12_EVALUATION_2026-09-14.md#mamba的sourceraw包含质量失败行重跑2026-09-15)。

## 已完成的8模型三组对照

上一轮授权为8种模型各自的seed42权重，使用4090原70/15/15划分中的validation，
逐1024点窗识别source/raw/guard。用户已要求删除前两轮结果并从零运行；fresh任务已完成，9,073,240次预测及24张混淆矩阵已独立读回核验，运行缓存已清理。
实际状态见[checklist](../SDR_AGENT_PROJECT_CHECKLIST.md)，启动依据见
[验证](../validation/RML2018A_CLEAN12_EVALUATION_2026-09-14.md#seed42原验证集8模型启动)。

## 固定数据与选择

原索引文件位于`local-assets/amc-eval/splits/server-seed42-20260914/RML2018a_split_seed42_tr700_val150_te150.npz`，
SHA-256为`0a7cbd3b8a4b921b7dc3d0c37473322207c6bd9fb362ea58498c851fad9dc5a3`。
直接复用`val`数组的383,385个原始行号，不重新随机切分、不按RX文件位置取15%。
每份RX文件通过`source_row`映射回原始成员，再与`usable & strict_quality_pass`相交。

| 输入 | validation成员 | 实际识别 | 质量跳过 |
| --- | ---: | ---: | ---: |
| 原始source | 383,385 | 383,385 | 0 |
| clean raw | 383,385 | 379,662 | 3,723 |
| clean guard | 383,385 | 371,108 | 12,277 |

三组共同合格369,497源行，另报相同成员上的准确率及混淆计数。
总预测数9,073,240。训练和测试成员不送入本轮模型；质量失败行保留标志，但不生成预测。
metadata保存`validation_member`及`validation_rank`，可恢复原val顺序；source本身按原排序索引，
RX按存储顺序读取后用源ID对应，不声称跨批量/设备浮点结果逐位一致。

数据直接复用AGX SSD的`local-assets/amc-eval/datasets/rml2018a/`：

- source：`RML2018a.hdf5`，原`X [N,1024,2]`仅转置为`[N,2,1024]`，保持原值。
- raw：`rx-clean-20260914/RadioML2018A_RX_raw_1024_per_window_RMS_v1.h5`。
- guard：`rx-clean-20260914/RadioML2018A_RX_guard_1024_per_window_RMS_v1.h5`。

raw/guard的`iq [N,2,1024]`已逐窗复数RMS归一化，读取时不再归一化。
raw已同步并校正CFO/相位，guard包含保护间隔LO相消；其区别不能简化为未处理ADC与处理ADC。
三组幅度预处理不同，差值不能全部归因于RF链路；这是已有模型的validation工程对照，
不训练、不改test划分、不作为独立生产准入。

2026-09-15固定2,496条共同validation样本的有界对照已证明：仅将source逐窗归一化到RMS=1，
8模型ACC下降3.77–12.18个百分点；不能将source与guard差距全部解释为LO或硬件损失。
这是幅度预处理敏感性的诊断，不是全验证集归一化后的成绩，也没有改写现有结果或模型输入。
完整共同成员与固定样本三方对照见[复核](../validation/RML2018A_CLEAN12_EVALUATION_2026-09-14.md#完成核验与source到guard差距复核2026-09-15)。

模型是CNN2-stable、ResNet、GRU、CLDNN、MCLDNN、MCformer、MAMC和Shared-Bi/D8，均seed42。
权重/结构见[集合](RML2018A_MODEL_COLLECTION.md)。沿用先前通过的8模型FP32数值依据，关闭TF32，
不重新挑精度。所有9,073,240次预测重新计算，旧预测复用数0。用户指定的旧全量与首次复用validation结果均已删除，
仅保留删除清单、模型数值验证等小型审计；不保留旧预测缓存。Mamba seeds43–46不运行。

## 执行、进度和停止

上一轮8模型结果根：`/home/jetson/sdrharness/local-assets/amc-eval/results/seed42-val-fresh-20260914`。
服务：`sdr-rml2018a-seed42-val-fresh-20260914.service`。已正常退出，实际总耗时14,778.58秒（约4小时6分19秒），单次内部期限24小时；
运行时磁盘保持至少3GiB余量。GPU每批1024条、CPU按16,384个文件行预取并筛选。
各模型驻留处理完三组后再加载下一个。

查看进度仍运行原脚本，默认已切到上方Mamba追加重跑：

```bash
/home/jetson/sdrharness/jetson-agx/sdrharness/scripts/rml2018a-progress.sh
```

加`--once`只显示一次；加`--root <历史根>`可查看已完成8模型任务。进度区分计算/落盘、验证集大小、
质量跳过、共同子集、24组完成数和绘图。Ctrl+C只退出查看。
直接停止：`systemctl --user stop sdr-rml2018a-seed42-val-fresh-20260914.service`，
或在新结果根创建`STOP`。旧`clean12-single-20260914`和`seed42-val-single-20260914`根已删除，不恢复旧范围。

代码入口`rml2018a_model_collection_eval.py`使用既有模型venv Python `-B`：
`prepare-validation --fresh --root <新根> --parent-root <已封存的小型计划/数值审计目录> --split <原NPZ>`
从HDF5重新构建metadata，只继承既有数值/输入哈希依据，不读取旧预测或metadata缓存；
`run --root <根>`执行；`verify`只读回验证；`render`调用已有系统Python/Matplotlib绘图。
计划冻结源码、权重、split、输入和metadata身份；不一致拒绝继续，不静默重切或放宽质量门。

## 输出与保留

每模型/数据组保存合格行的完整logits、类别和`dataset_row`，用共享metadata还原source_row、
validation_rank、源SNR、SINR和质量标志。原始IQ不再复制到结果根。
summary记录26档源SNR的准确率/混淆矩阵、质量跳过及共同成员结果。
全部识别后生成`summary.csv`，读回所有结果哈希、argmax和独立重算统计，再生成24张矩阵：
`confusion-matrices/<variant>-seed42/<source|raw|guard>.png/.svg`，另有计数、行百分比及共同成员计数CSV。
最终保留清单包含预测、metadata、汇总、图表和哈希；运行控制文件单独列出。
仅最终核验/绘图通过才写`COMPLETE.json`，不能把启动、部分summary或某张图当成全部完成。

缓存放在新根对应的`/var/tmp/sdrharness-dev/rml2018a-collection-cache-<标识>`，由退出finally清理。
活动任务不做开发清理。以后人工删除先确认无任务使用，再只删除精确结果根；
SSD数据、模型、split及旧实验分别有保留清单，不扩大删除到共享父目录。
原12模型全量启动与暂停记录保留在[历史验证](../validation/RML2018A_CLEAN12_EVALUATION_2026-09-14.md)，
不是当前启动指令。
