# 源码

| 目录 | 责任 | 构建/测试 |
| --- | --- | --- |
| [agent/controller](agent/controller) | 唯一硬件执行、安全门、预算与批准权威 | Cargo |
| [agent/planner-worker](agent/planner-worker) | 有界摘要、规划与模型协议 | Node.js / npm test |
| [agent/web-console](agent/web-console) | HTTP、会话、结果、网页与单窗分析 | Cargo；网页工具见组件测试说明 |
| [sdrd](sdrd/README.md) | P201 接收、传输、取消与状态恢复 | C11 / Make |

AGX 部署统一从 [deploy/agx](../deploy/agx/README.md) 进入。
`agent/web-console/frontend/` 是工作区中的前端开发目录，其未提交内容仍按原状态保留。
模块内部的测试、配置和第三方依赖与所属组件放在一起；设备快捷入口见 [devices](../devices/README.md)。

独立实验识别 Worker 已退役。Controller/Web 仍使用的协议类型、安全门与历史结果解析保持。
