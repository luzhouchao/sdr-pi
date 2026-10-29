# 文档清理与合并验证 — 2026-09-07

整理基线：`7115b50`，分支 `codex/recognizer-amc-offline-validation`。
用户要求审计 docs、删除过时说明、合并重复文档。本单元只整理文档及其资源读取
路径，没有部署程序、访问 SDR/NX/4090、读取数据集/locked test 或调用模型。

## 当前结构

原来 docs 根目录平铺 190 个文件；整理后根目录为 **7 个文件**：4 份日常入口与
3 份被冻结配置按原路径引用的审计 JSON。其余按 reference / validation /
evidence 分类，并有主题索引。docs 总文件数由 **190 减为 180**，并非删除了全部
移出根目录的文件。完整入口见 [README](../README.md)。

- `reference`：当前架构、接口、规范和决策，不重复维护下一步列表。
- `validation`：已执行的记录和回滚依据，历史待办不作为当前指令。
- `evidence`：原始审计、保留文件清单、预登记和图表，不改写哈希或原始路径字段。

## 删除和合并

| 原文档 | 处理与替代来源 |
| --- | --- |
| `ROADMAP.md` | 删除。它仍把已完成语料/预处理/Worker/O1a 列作下一步；顺序统一到 [DELIVERY_ORDER](../SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md) |
| `CHAPTER_4_6_INTEGRATION_PLAN.md` | 删除。该文件已明确被取代，仍包含 seed44、重新训练和旧 A–H 排期；当前范围用 [第1—6章规划](../CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md)，输入及数据治理已有独立合同 |
| `ITERATION_WORKFLOW.md` | 删除。分支规则和流程过时且与 [AGENTS.md](../../AGENTS.md) 重复；保留 AGENTS 为唯一开发规则入口 |
| `AGX_SDRHARNESS_MIGRATION.md` | 删除。迁移已完成，旧“仍需低精度/队列”等待办失效；当前布局用 [AGX README](../../deploy/agx/README.md)，历史实机证据仍在 AGX framework / RX ownership 验证 |
| 九份早期 Pi MVP/安装/终端/observe/executor/cancel/Web/Runner/软件扫频记录 | 完整合入 [Pi 历史合订记录](PI_BASELINE_HISTORY.md)，原单文件删除；每份正文有独立锚点、原文件名和原始 SHA-256 |
| `RECOGNITION_RESULT_S2_WEB_CORRECTION_2026-09-06.md` | 完整并入 [S2 验证附录](RECOGNITION_RESULT_S2_VALIDATION_2026-09-06.md#web-build-correction)，保留曾遗漏 Web 构建的失败事实 |
| `SDR_AGENT_P201_HOST_KEY_PERSISTENCE_INVESTIGATION_2026-09-03.md` | 完整并入 [持久化验证附录](SDR_AGENT_P201_PERSISTENT_HOST_KEY_VALIDATION_2026-09-03.md#historical-investigation)，明确其中待批准/待实施步骤已属历史，不得重做格式化 |

删除了 4 份过时说明；11 份分散证据并入 3 份报告。没有删掉独特的验证结果、
失败记录、制品哈希或清理证据。81 份原验证/交接记录均核验正文保留（只忽略
Markdown 链接目标的迁移差异）。原始文件还可从 `7115b50` 查询：

```bash
git show 7115b50:docs/ROADMAP.md
```

## 消除失效待办

实际推进文档从逐次实验日志改为单一当前队列：先审计并推进新版 Web 会话恢复
上线，再独立处理非模型运维配置。S/V 已完成项不重做；模型工作暂停、V1b/V2/V3
及 A1/O1b 的依赖仍保留。历史 RF 每次成功/失败的详细结论继续在验证记录及
权威 checklist 中，不再在排期文件重复“下次修旧 CLI”。

修正根 README、架构文档和 checklist 末尾的过时状态：RX1 身份已验证，S3/S4a/
S4b/S5/S6 已有实现及相应隔离验证，统一 CLI 已安装；完整识别系统仍未生产准入。
这次文档修正不新增部署或科学验收，`recognizer_available=false` 保持。

## 冻结证据与消费路径

**45 份 JSON、18 张 PNG、23 份预登记 Markdown，共 86 个原始附件 SHA-256
全部不变。** 其中三份 JSON 留在根目录：split、预处理选择、RF-aligned checkpoint
审计被冻结配置直接引用。其余移入 evidence；不为目录整理改写配置或配置哈希，
不留重复副本或兼容软链接。

历史记录内部的旧路径和源码哈希仍对应原提交。[证据目录说明](../evidence/README.md)
给出当前位置规则。17 个 Python 文件、1 个 checkout 脚本、2 个 Rust 测试夹具
消费者仅改资源路径；通过从 Git 基线机械替换路径再逐字比较，确认算法和运行
逻辑无变化。Rust 改动只在测试夹具读取位置，不需要安装新二进制。

## 验证与清理

- Controller：101 个库测试通过；1 个显式合成夹具导出测试保持忽略。
- Web：35 个测试通过；2 个显式夹具导出测试保持忽略。
- Python：37 个相关测试通过，包括旧 RF 判定回归与冻结 FP16 计划/证据合同；未执行精度实验。
- 两个 Rust crate 格式检查、checkout 验证、变更 Python AST、资源路径存在检查通过。
- Markdown 本地链接检查及合并锚点验证通过；原始附件哈希、合订正文、冻结配置路径和路径改动范围均核对。
- 原来第1—6章文档指向已移除的 `controller/src/bin/sdr-agent.rs`，已改为当前 `controller/src/cli/console.rs`。

临时构建、测试日志和清理脚本只在 `/var/tmp/sdrharness-dev/docs-cleanup-907y/`。
实际移除数量和最终检查计数在下方记录；未触及既有用户结果、语料、外部 IQ 或
任何保留的 RF 诊断包。本单元无新增保留数据。

最终清理：**1,603 个文件 / 876,198,394 逻辑字节**，上述唯一临时根已验证不存在；
无本单元进程或新增保留数据。最终检查覆盖 139 份 Markdown、
522 个本地链接（无失效链接；不豁免预登记链接）。

## 2026-09-10：实验频段选择与射频记录整理

用户在433MHz试验后明确“以后都用433”，随后要求记录并整理文档。基线88dbbf7。
用户追加要求实验资料只提供链接、需要时再读。AGENTS及入口明确默认仅读入口/当前选择/checklist速览，
实验正文、图表、计划和证据按当前任务需要打开，不递归展开索引。
AGENTS记录后续实验默认433.920MHz、当前433MHz天线；推进顺序集中维护单音参考参数和
后续有限非模型单元边界，删除逐轮过程重复及已过期的“当前接法”。docs入口增加当前实验链接，
验证索引集中近期负载/背景/天线/增益记录，证据索引把新附件移出“冻结路径例外”章节。
checklist更新日期和本次文档交付，历史已完成条目及失败记录不重写。

检查修改Markdown链接与锚点、索引原链接无丢失、diff及封存附件Git差异；无源码、生产配置、
RF、模型或部署操作。本单元未创建开发临时目录，无新增保留数据，删除0文件/0字节；
以前IQ与证据全部保持。旧runner默认/profile/生产扫描范围没有因此改变，下一次执行按登记计划显式选433.920MHz。

## 2026-09-10：全仓文档与实验附件导航整理

用户要求整理所有文档、实验记录等资料，沿用“仅链接、按需读”的规则。基线2c8518c。
本轮对Git跟踪的172份Markdown及docs/evidence的131份附件做文件/标题/链接级盘点，
不读取原始IQ或运行实验。15份参考文档与92份中央验证记录原已有索引；附件原缺104条直接入口。

附件索引现完整列出35份Markdown预登记、68份JSON及28张PNG，按计划、保留包、审计、
派生统计和图表分类。三个冻结根路径例外维持原位。reference集中组件操作、安全与许可文档链接；
validation补入组件目录中七份历史系统/Pi记录，移除重复“近期入口”，所有旧链接目标保持。
根README和AGX部署入口中过时状态改为指向checklist，五个组件入口增加回链和历史定位。
没有迁移、复制或删改实验正文/JSON/PNG，组件技术合同和旧命令不重写。

全仓Markdown本地文件链接检查、修改索引的锚点检查、旧索引目标不丢失检查及从docs/README
出发的文档可达性检查通过：172份Markdown、809个本地文件链接有效，全部文档可达，reference/validation/evidence目录均无
未索引文件；修正新图表分类链接中的标点锚点。检查diff确保封存实验与原始附件字节保持。
本轮仅文档导航与状态来源整理，不改变433.920MHz选择、源码、配置或部署，不运行RF/模型。
无临时目录、新证据包或额外数据副本；清理0文件/0字节，原保留数据不动。

## 论文拆分后的入口收敛（2026-10-29）

本轮基线 `148fe61`。文档首页移除重复实验成绩和历史排期，详细结果仍由
checklist、validation、evidence 维护。移除两个只用于旧批次的独立离线脚本，
共 8665 字节；Git 跟踪文件中未找到脚本名引用。共享模块、设备控制和生产代码保留。

| 原脚本（`jetson-agx/sdrharness/scripts/`） | 字节 | SHA-256 |
| --- | ---: | --- |
| `diagnose-rml2018a-campaign-sinr.py` | 3351 | `9a5f3c2515245840a2e1ffaaf5dea3bfc3e90eac7c81b2f7534b9ff99386c3dc` |
| `plot-p201-background-map.py` | 5314 | `70ad870052022bfdc1ec609525447f5ae2326beac7ca8119b1a5e7172781bbe0` |

删除前与本仓库 `148fe61` 原文件逐字节一致，可通过 `git show 148fe61:原路径` 恢复。
检查期间论文工作区同名副本被其他操作移除，因此不以该副本作为保留依据。
验证：跟踪文件引用检查、首页本地链接、删除后路径缺失及 diff 检查。
本轮无 RF、推理、部署或临时制品，临时/新增保留制品均为0。
原有论文迁出与前端改动保持；除首页收敛外不纳入本轮提交。

## 源码目录分类与旧 Pi 退役（2026-10-29）

基线 `eac1d8c`。用户明确选择实际重排源码，并删除旧 Pi 代码，以当前 AGX 为准。
当前工作区移动356个原有文件/链接；未提交的论文迁出与前端改动随相应目录保留，
提交中隔离这些既有改动。目录入口统一到仓库 README；AGX 脚本增加按用途的完整索引。

| 原位置 | 新位置/处理 |
| --- | --- |
| `raspberry-pi/sdr-agent/` | `src/agent/`：仍用于 AGX 的 Controller、Planner、Web、识别接口 |
| `jetson-agx/sdrharness/` | `deploy/agx/`：构建、配置、服务模板、运维及测试 |
| `sdr-system/sdrd/` | `src/sdrd/`：P201 C11 服务 |
| `sdr-system/docs/` | 架构放 `docs/reference/`，历史验证放 `docs/validation/p201-system/` |
| `sdr-system/private/` | `deploy/p201/private/`，仅凭证存放规则，未迁移秘密 |
| `raspberry-pi/p201pro-rust/`、`raspberry-pi/config/` | 删除旧独立 libiio 采集、Pi 网络配置；独有测试记录另存验证目录 |
| Pi Planner/Web systemd 模板及旧 provider 示例 | 删除；当前 AGX 模板由 `deploy/agx/systemd/` 维护 |

合计退役17文件、82,826字节，原内容可从 `eac1d8c` 查询。
独有历史测试保留于 `PI_LIBIIO_TEST_RESULTS.md`、`PI_FFT_BENCH_RESULTS.md`；
封存审计 JSON、图表、冻结预处理规范及原始 profile 均保持原字节。

路径迁移导致两个运行 profile 的 `preprocess.spec_path` 失效；新增 `.layout-v2.json`
派生版本，仅改变路径。RF-v1 分别固定原始与派生身份，篡改哈希仍拒绝；历史记录读取
继续使用原始嵌入 profile，未改写旧结果哈希或放宽数值/准入门。新版规范与派生说明见
[配置说明](../../deploy/agx/config/amc/README.md)。

验证：checkout、169份Python语法、JSON/bash语法、当前文档链接及设备源码链接检查通过；
Controller 159测试通过/1忽略，Web 41通过/2忽略，Rust格式与Clippy通过；
Planner 102通过/1跳过，P201 C测试及两份C++识别接口测试通过。
首次 Controller 测试13项路径失败、后续原/新profile身份冲突均已修正，最终原门通过。
Python旧数据合同/传输测试曾因系统环境缺h5py失败，未作为本轮通过项。
用户随后要求专注目录整理，不追加论文测试依赖或模型运行。

只读核对系统服务：AGX Planner/Web均active，ExecStart/WorkingDirectory不引用旧源码路径。
本轮无服务重启、硬件操作、模型推理或生产部署。

用户曾要求新建venv，现仅保留NumPy 2.2.6、SciPy 1.15.3及基础pip/setuptools，
已撤销额外h5py/pytest等依赖；论文环境未删除。保留目录
`/home/jetson/sdrharness/local-assets/python/venv`，5172普通文件、208,866,695字节；
逐文件SHA清单 `local-assets/python/venv-files.sha256` 的SHA-256为
`4bc3933dd93d096014203ffd37213a87f85f4e58903a70de3785abd722cc0e71`，用途与删除方法见同目录上级 `ENVIRONMENT.json`。
人工删除为 `rm -rf -- /home/jetson/sdrharness/local-assets/python`。该环境未切换生产服务。
单窗合成PSD在系统Python和新venv输出16×256，最大差1.53e-5 dB（门限1e-4），无实收数据访问。

本轮构建、日志、差异基线与临时索引目录 `/var/tmp/sdrharness-dev/layout-20261029/` 已完整清除：4724普通文件、2,255,869,985字节、0链接；目录不存在复核通过。未清理其他任务的缓存或证据。
