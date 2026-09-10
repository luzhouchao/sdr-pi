# CodeGraph本地初始化与查询验收

用户明确同意在当前仓库初始化索引。基线83ac400，分支codex/sdr-improvements，工作区初始干净。
已安装CodeGraph1.2.0，复用现有CLI与MCP，不重新安装。执行
`codegraph init /home/jetson/sdrharness`成功，约4.1秒完成180文件索引，5057节点、16234关系。
索引语言C/C++/JavaScript/Python/Rust/YAML，backend=node-sqlite，journal=wal，extraction version24。
这是支持语言的代码索引数量，不是全仓文档数量或完整调用覆盖证明。

## 验收与使用边界

- CLI `codegraph explore validate_rf_case`返回正确文件、当前行号源码及调用关系。
- 已连接MCP用projectPath=/home/jetson/sdrharness同查询成功，现有会话无需重启。
- `codegraph sync --quiet /home/jetson/sdrharness`成功；status显示pending新增/修改/删除均0，
  worktreeMismatch=null、reindexRecommended=false。
- 文件列表未包含local-assets；未读模型权重、IQ或locked test，也未执行实验代码。
- root `.gitignore`加入`/.codegraph/`，Git check-ignore确认数据库及本地内部.gitignore均忽略；
  无索引二进制进入提交。原AGENTS已要求有索引时优先CodeGraph，保留其规则，无需生成重复指令。

本次查询中CodeGraph未关联到validate_rf_case的动态导入测试，尽管仓库已有对应测试。
因此其“no covering tests found”只能作为索引发现结果，不等于没有测试；实际测试仍需按任务核对。
查询原始代码不执行TX/RX；实验文档仍依项目规则通过链接按需读取。

## 本地数据和交付范围

持久可重建索引位于`/home/jetson/sdrharness/.codegraph/`，不是封存RF证据。
初始化/同步CLI均已退出；现有MCP连接可保留SQLite运行文件供后续查询。
记录时四文件共19591397字节：数据库19558400、内部.gitignore229、shm32768、wal0。
运行期间SQLite边车文件可变化，以上是观察时点，不是不可变保留清单。

数据库观察哈希`c7bb876e0d43b00a0ee05213e729204b20992dc480bbe8b54f7a5f615c103064`；
内部.gitignore哈希`47c0dacebca9f56c9020b68584470dfc51f07650a3719904e98f4b447a5dd003`。
后续sync会合理改变数据库，不应拿旧哈希当作冻结门。用途仅本仓库代码导航，无capture/request/model身份。
人工需要移除时运行`codegraph uninit /home/jetson/sdrharness`；不删除全局安装或其他项目索引。

本单元未创建开发暂存目录、构建或模型缓存，删除0文件/0字节；保留上述用户请求的本地索引。
仅提交忽略规则、使用入口和本记录/checklist；无产品源码、服务配置、生产部署、发射或识别操作。
