# 4090模型导入与四窗微调权重删除（2026-09-14）

完成用户要求的4090原始模型及7种2018A基线权重导入，并按追加要求删除AGX旧四窗微调epoch-010。
型号及使用入口见[模型集合](../reference/RML2018A_MODEL_COLLECTION.md)，逐模型源路径、大小、SHA-256及删除审计见
[证据](../evidence/RML2018A_MODEL_IMPORT_2026-09-14.json)。未进行射频操作、训练、模型前向或生产替换。

## 来源与验证

- 服务器仓库`/data/lzc/mamba`，源码快照提交`3738cd3b530f3dae24783da2324170ddcd05888f`；各训练提交另记于manifest。
- Tailscale连接超时后使用既有Aliyun SSH路径，无连接配置变更；远端无暂存或文件修改。
- 154个源文件共36,687,916字节完成传输，源与AGX逐文件SHA-256一致；源文件传输前后大小/mtime不变。
- 其中12份checkpoint共35,565,796字节；配置均为2018A、1024点、24类，型号/seed/标签顺序对应。
- 12份CPU安全读取均通过：`model_state`非空、成员均为张量、浮点参数有限；CUDA未初始化。
- 原始D8 seed44与AGX旧`seed44/best.pt`完全一致。未构造模型或做strict load，不宣称GPU依赖、精度或推理通过。

## 精确删除及当前边界

仅删除`/home/jetson/sdrharness/local-assets/amc-eval/checkpoints/rml2018a/rf-v1-ft-batched-seed44/epoch-010.pt`，
1,726,724字节，SHA-256 `a3c3e41ba9732171d65b023d7d9f1d334d88b7ca28be3d939b0536878c168054`。
删除前核对真实路径、非符号链接、单硬链接、哈希和无文件持有者；旧识别服务inactive/MainPID 0。
删除后路径不存在，原始模型保留。未删除实收IQ、结果或历史profile，也未删除服务器文件。

旧epoch-10验收保留为历史事实；当前缺少其权重，旧入口不能直接复现。不恢复被删文件、不静默切换权重。
新集合仅完成导入，运行适配尚未完成；`recognizer_available=false`。阶段HTML报告仍是删除前结果快照。

## 保留与清理

为后续模型复现保留集合根
`/home/jetson/sdrharness/local-assets/amc-eval/checkpoints/rml2018a/server-models-20260914`：
157文件36,773,412字节，另加`retention.json`41,106字节。
保留模型、配置、指标、标签、源码身份及完整源/本地收据；无数据集或IQ副本。
复核本次操作所需审计位于`/var/tmp/sdrharness-dev/rml2018a-model-import-20260914`，
5文件120,709字节，另加`retention.json`1,878字节。两份retention逐文件列出大小和哈希，
其自身哈希记入Git证据；模型manifest还记录训练及预处理身份。

已删除传输暂存2文件36,868,214字节（archive与传输脚本），以及空scratch目录；
权重删除另外计数。无遗留传输/检查进程或缓存，不清理其他实验根。
不再需要时，确认无任务使用，人工只删除相应精确根：

```bash
rm -rf -- /home/jetson/sdrharness/local-assets/amc-eval/checkpoints/rml2018a/server-models-20260914
rm -rf -- /var/tmp/sdrharness-dev/rml2018a-model-import-20260914
```

上述命令为保留包的人工删除入口，本次未执行；不能扩展为删除共享checkpoint或IQ根。
