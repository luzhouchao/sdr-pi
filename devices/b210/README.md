# 国产 N210（USB B210兼容）设备入口

用户设备名称为国产N210，UHD枚举为B210，serial `2508504`，A7-100T；不使用NI网口N210流程。

- `b210.py`：本机身份、运行时校验及有界probe入口。
- `transport.py`：设备所有权与有界子进程传输辅助。
- `tx-events.cpp`：有限发送及事件记录源码，使用前须登记计划；不会由Agent自动启动。
- `runtime-manifest.json` 与 `runtime/`：既有专用UHD运行时身份和Git外资源入口。

```bash
python3 -B devices/b210/b210.py status
```

状态查询不证明USB所有权或进行RF测试；初始化/probe按
[N210工作流](../../.codex/skills/n210-sdr-workflow/SKILL.md)执行。
只使用经验证的A7-100T与FX3镜像，不写EEPROM/flash，不将其与P201 FPGA/BOOT路线混用。

旧RadioML campaign快捷链接和实验脚本已退役；论文实验由独立论文项目维护。
当前B210是独立外部信号源，P201仍是唯一生产受控接收设备。既有接法和授权见
[AGENTS.md](../../AGENTS.md)，每次发送仍需有限计划和停止/恢复验证。
