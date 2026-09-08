# 首次扫描混合选参与频率显示 — 2026-09-08

基线 `a862128`，分支 `codex/recognizer-amc-offline-validation`，开始时工作区干净。
用户要求频率易读，并允许只填起止频率、其余交给上游模型；随后明确每个参数
都可自己填写，AI 只补剩余参数。实现及安装证据见
[有界审计](../evidence/SURVEY_PARAMETER_ASSIST_AUDIT_2026-09-08.json)，接口见
[扫描合同](../reference/SDR_PREPROCESSING_SWEEP_ARCHITECTURE.md#web-first-survey-parameter-suggestions-2026-09-08)。

## 行为与边界

- 步进、每点停留、固定增益各有“自己填写 / AI 选择”。起止频率始终由用户指定。
  点击“让 AI 填写待选参数”，使用已保存的上游模型生成完整具体值，预览预算后
  显式保存；保存沿用原配置格式，新会话才执行。不是每次启动自动重新询问模型。
- Worker 复用现有 provider、Spark 结构化 Adapter、超时和单推理租约。仅新增
  选参操作；原会话/动作协议不变。选参不能搜索、执行硬件、建立会话或写设置。
- 手填字段必须逐项相等；Worker 和 Rust 分别拒绝非法整数、额外字段、越界及
  超过 768 点 / 300 秒的建议。不用默认参数掩盖失败。采样率/带宽仍为 10 MHz，
  每点 4096 样本；没有把所有底层采集参数交给模型。
- 浏览器拒绝迟到建议覆盖已修改设置；修改扫描条件后保存前须有匹配建议。
  默认全频段、手动全填、关闭初扫、既有 once-only claim、停止及恢复路径复用。
- 扫频显示为 `2.4–2.4835 GHz`、步进 `8 MHz`，去掉多余零并保留整数 Hz 精度。
  原事件、诊断和 Hz 接口字节不改写。增益只是模型建议，没有现场最佳值保证。

## 实际验证

62 项 Planner、14 项前端回归通过；Rust 37 项通过、2 项既有 fixture exporter
显式忽略，fmt 与 Clippy `--all-targets -- -D warnings` 通过。覆盖混合固定字段、
越界/额外字段/总预算拒绝、迟到结果丢弃以及频率精度与原始事件不被改写。
审查中发现脚本替换误改了无关错误处理，已完整撤销并重新通过 Rust 检查；最终
Rust diff 仅新增选参接口、socket 配置与对应测试。

实际已安装 Planner 单次混合选参：固定 1 MHz 步进，返回 10 ms / 20 dB。
实际 Chromium 在已安装 Web 上再次调用，固定 1 MHz，返回 500 ms / 20 dB，
85 点 / 63.75 秒，仍在预算内；只填起止频率的全 AI 调用返回 1 MHz / 10 ms /
20 dB。这些不同返回均是实际模型输出，不宣称模型每次确定性或已优化接收质量。

实际页面检查了独立禁用/保留手填值、待生成保存阻止、建议预算、生成后保存
payload、修改频率后建议失效及 390 px 无横向溢出，JS 错误为零。保存请求仅在
该测试浏览器拦截核对 payload，以保护用户原设置；没有改写生产 provider。
最终安装页面另做用户截图原始扫频文本的 DOM 回放，确认 GHz/MHz 实际渲染；
该事件未写回服务。生产 HTTP 拒绝两个越界输入；普通 Planner 请求仍真实返回
有效 hold。没有新建会话、采 RF、训练/微调、模型精度诊断或访问 locked test。
在线网关没有验证，识别能力仍为 false。

## 部署、回滚与保护

重启现有 Planner 载入源码，Spark 不重启。Web release 实际安装为 3,323,168 bytes，
路径 `/home/jetson/.local/lib/sdrharness/bin/sdr-agent-web-console`，SHA-256
`a1bbcde69c311fd33cfbe44dcbc36f2fac1033f013efa1daf8f6b718be965cc6`。
CLI、provider 配置以及原 2 个会话、5 条结果、1 条语料均保留；两会话初扫状态
保持 complete。最终 HTTP 三份静态资源逐字节等于源码，Web/Planner 均 active。

沿用用户“不用备份”的选择，未新增备份/发布副本。复用已有
`/home/jetson/.local/lib/sdrharness/releases/20260908-rx-daily-ui-v2/sdr-agent-web-console`
（`9095a1be…`），实际执行新版 Web→旧版 Web→新版 Web，逐次核对 HTTP/健康。
这是 Web 制品回滚；Planner 的向后兼容选参扩展保持安装，普通请求另外实测。
既有回滚包登记和删除条件仍见日常 RX 验证，本次不增加或删除旧包。
必要时空闲后停止 Web，核对已有旧包哈希，原子替换 bin 并启动即可恢复旧界面。

## 精确清理

浏览器/构建进程已结束，无进程使用本单元构建制品或浏览器 profile。删除
`/var/tmp/sdrharness-dev/survey-assist-908b/`，共 **2618 文件 / 1,135,804,015 bytes**，
包括构建、测试日志、脚本及截图，目录和安装临时文件均核验不存在。
无新私有 socket、无新外部保留文件、无备份；只在 Git 留有界审计/源码/文档。
正式安装制品和用户结果、语料、已有 RF 证据及既有回滚包不参加开发清理。
