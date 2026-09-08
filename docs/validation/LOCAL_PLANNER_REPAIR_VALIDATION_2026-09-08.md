# 本地 Planner 恢复 — 2026-09-08

基线 `a5f9157`。用户报告本地/在线请求失败，随后明确暂停在线网关排查，只修复
本地模型，并要求“不用备份”。最终交付仅恢复本地 Spark 配置及共享错误反馈。
[审计](../evidence/LOCAL_PLANNER_REPAIR_AUDIT_2026-09-08.json)记录实际调用、来源哈希及清理。

## 实际修复与验证

现场保存的是 Responses 在线网关、`gpt-5.6-luna`、500000 上下文；当前会话继续
使用其打开时选定的 provider。独立只读规划验证确认本地 Spark 本身可以正常
提交 hold，不能据用户看到的统一报错认定本地权重损坏。

已直接恢复 `/var/lib/sdrharness/web-console/provider.json` 为：

- API `openai-completions`，Base URL `http://127.0.0.1:8010/v1`。
- Provider **`spark-local`**，Model `spark-x2.5-4b`；此 Provider 选择既有 Spark
  JSON→submit_plan Adapter，不能只改 URL 却保留另一 provider/protocol。
- 32768 上下文，与实际 llama-server 配置一致；压缩阈值 90%。
- 使用既有 Spark 私有 key，文件保持 0600；不输出密钥。
- 初扫参数和 IQ 保存选择保留。先 stop 确认，再停 Web/Planner、更新配置、重启
  Planner/Web，让原当前会话立即采用本地配置；没有新建会话或重复初扫。

当前本地独立单次及交互两条原生路径均返回 hold。实际 Chromium 在原会话
`session-1788840575092` 发送“你好，你是谁？请只回复身份并保持等待，不操作硬件。”，
约 4.7 秒显示正常本地回复，Rust 明确校验 request=1/generation=1788841690347
及 hold；没有硬件执行。页面 JS 错误 0，原 2 个会话、5 条结果、1 条语料保留。
Spark 一直是 PID 1150，未重启或重新加载权重；Web/CLI 二进制哈希不变。

交互层原来把 SDK 中的连接/服务错误统称为“生成结束但没有提交计划”。现在
单次/交互共用错误说明：真实 provider 错误、输出长度耗尽、中止和正常生成却
缺少工具调用分开呈现；显式脱敏当前 key、Bearer 和 URL，限制长度。错误仍
失败关闭，不合成 hold，不绕过 submit_plan/人工批准或放宽 Rust 校验。

最终 60 项 Planner +12 项前端回归全部通过，包含错误区别、秘密脱敏、失败后
租约释放及不产生计划。没有改动 Rust/前端源码，不需要重建二进制。

## 在线排查的停止边界

初始只读定位到 Node 证书信任、网关 Responses 消息类型/工具选择兼容问题和
格式错误的 SSE 错误消息。用户要求先不处理后，停止所有相关私有进程；临时
Responses 改动、其测试和 systemd CA 参数全部撤回，没有部署网关修复，不能
宣称在线入口已经修好。本地没有自动云端切换。

## 清理与当前状态

按用户明确要求，未新增配置/源码/制品备份或回滚包，也不复制原在线密钥。
源码原版仍在既有 Git 历史；不承诺能从本单元备份恢复旧私密配置。当前本地
配置是正式运行配置，用户如要重新配置在线服务，仍需自己提供相应有效设置。

确认没有私有进程引用 feature 根，两条允许路径的测试 socket 均不存在。
删除 `/var/tmp/sdrharness-dev/planner-fix-908a/`，共 **96 个文件 / 1,112,890 bytes**，
核验目录不存在；含测试记录、脱敏网关 trace、临时脚本和浏览器截图/缓存。
没有新外部保留包；Git 仅保留源码、文档和有界审计。用户结果及既有 RF 证据
未删除。未采 RF、未训练/微调、未读取 locked test、未运行 Mamba 诊断，
recognizer_available=false；本地 Planner 的功能修复不改变识别准入。
