# P201恢复健康检查兼容修复 — 2026-09-07

已部署独立的只读`sdr-agent-health`，恢复oneshot/timer重新报告成功。
复用Controller现有严格SDRD解析与RX1身份验证，没有切换通用Controller、
Planner/Web/Worker或生产识别配置。用户要求记录模型适配建议并推进模型以外工作；
建议见[暂缓记录](../reference/RF_DOMAIN_ADAPTATION_DEFERRED_2026-09-07.md)。

## 原故障与修复

安装的通用Controller hash为
`3cbad970165b9b86d8bc6441e74ddf0d8bf9740c15e54cfcd94e8786269d16c6`，
实机observe复现`response_shape: unknown field rx_input`。现有源码的SdrdAdapter
已经支持该严格字段，因此不放宽JSON规则，也不复制协议解析器。

另发现原脚本把observe的成功退出当健康：observe即使返回`healthy=false`，
仍可正常输出JSON并退出0；原脚本丢弃JSON后输出healthy。新只读二进制仅发送
HELLO/CAPABILITIES/HEALTH/QUIT，检查online/healthy/零health_flags、IIO可见、
已验证且一致的RX1/RX0/A_BALANCED身份和接收/调谐能力，不满足即非零退出。
它没有开始session、调谐、采集、推理或任意命令入口。

恢复脚本改用该入口，每次socket超时最多1000ms，另加6秒外层timeout；
systemd总启动预算从35秒改为45秒，以容纳已有25秒SSH及两次3秒TCP探测。
保留密码文件0600、严格host-key、固定IP、非阻塞flock、PID/listener零零或一一门。
RX2仍是单独诊断范围；本健康入口报告冻结RX1路径就绪，不把RX2当RF-v1 RX1。
通用CLI安装版本仍旧，其直接observe的旧字段问题留给后续独立部署兼容工作，
不能把这次恢复服务修复说成整套Controller已经升级。

## 构建、测试与部署

- 6个新CLI集成测试覆盖24个场景：合法RX1只读四请求，健康/标志/IIO/能力失败，
  缺失/未验证/不一致RX身份，错误server/schema/request/字段类型/未知字段，
  QUIT失败、无效CLI/无界超时拒绝和停滞端点超时；5个既有Adapter测试通过。
- cargo fmt、指定bin/test的clippy `-D warnings`、bash语法、systemd-analyze verify
  和git diff检查通过。systemd工具仅报告既有其他主机unit警告。
- AGX原生aarch64 release构建，529096字节，SHA256：
  `13102e3016cc2a8244cbceb99ae54dca7a26f2f025445e50e938e45e0f17138b`。
  构建入口`build-agent-runtime.sh`同步将该bin放入安装制品，避免依赖旧通用CLI。
- 安装路径：`/home/jetson/.local/lib/sdrharness/bin/sdr-agent-health`；
  脚本为同prefix的`scripts/recover-p201-sdrd.sh`。
  服务unit仍为`/etc/systemd/system/sdrharness-p201-sdrd-recovery.service`。
- 当前release：`/home/jetson/.local/lib/sdrharness/releases/20260907-recovery-health-v1`。
  保留旧脚本/unit的rollback：同级`20260907-before-recovery-health-v1`。
  两个目录共5个文件、537163字节，属于部署及回滚制品，不是未清理的临时数据；
  路径、大小和逐文件hash见[审计](../evidence/P201_RECOVERY_HEALTH_AUDIT_2026-09-07.json)。
  旧通用Controller hash验证未变，没有顺带部署其他未准入功能。

## 实机结果

整个单元最大采集字节0、TX0、模型窗口0；只查询状态和验证服务生命周期。
凭据权限、TCP3秒探测、单PID/listener和/sd持久release事先核对。

1. 初始P201 PID11547，新健康bin针对真实rx_input返回healthy=true。
   部署后oneshot走already_running，PID11547不变，Result=success、ExecMainStatus=0。
2. EXECUTION_STATUS确认active/profile_applied/restore_armed/faulted全false，
   sysfs两通道与缓冲状态保存；暂停timer后通过既有init正常停止，确认零PID/零listener。
3. 重新启用timer，由它自动走started，约16.15秒后见新PID5909；只有一个进程。
   HELLO/能力/健康通过，完整两RX通道sysfs状态与初始一致，sdrd hash不变：
   `83a661a892b8ab71de3f4e7d64064c9c65030623dc7245eb3d3a1420a696ba4f`。
4. 首个验证脚本读取journal过早，拿到此前调用日志，故原`timer-live`记录保留为
   failed assertion。随后同步journal并核对**同一次18:26:44–18:26:46调用**，
   明确出现started、healthy和Finished，timer确认记录为passed。没有再次停机重测。
5. 持有恢复flock时启动oneshot，按预期退出75且PID5909不变；释放后正常检查成功，
   timer保持enabled/active。最终service Result=success、ExecMainStatus=0。

本轮未重启P201板卡。2026-09-03已完成的真实重启/host-key持久化证据保持有效，
README同步删除过时的“仍等待初始化host-key NVM”说明；没有修改BOOT、NVM或FPGA。

## 回滚与清理

如需撤销本单元，先停timer并等待/停止oneshot，恢复rollback中的脚本和service，
移除本单元新增的健康bin，daemon-reload后恢复timer。具体为：

```bash
sudo systemctl stop sdrharness-p201-sdrd-recovery.timer sdrharness-p201-sdrd-recovery.service
sudo install -m 0755 /home/jetson/.local/lib/sdrharness/releases/20260907-before-recovery-health-v1/recover-p201-sdrd.sh /home/jetson/.local/lib/sdrharness/scripts/recover-p201-sdrd.sh
sudo install -m 0644 /home/jetson/.local/lib/sdrharness/releases/20260907-before-recovery-health-v1/sdrharness-p201-sdrd-recovery.service /etc/systemd/system/sdrharness-p201-sdrd-recovery.service
sudo rm -- /home/jetson/.local/lib/sdrharness/bin/sdr-agent-health
sudo systemctl daemon-reload
sudo systemctl start sdrharness-p201-sdrd-recovery.timer
```

这会恢复**已知有rx_input兼容故障的旧检查路径**；回滚包用于撤销新部署，
不代表旧版本健康检查成功。本轮准备并核验回滚文件，未主动恢复到该已知故障状态。
不删除既有P201 release、通用Controller或任何应用结果。

精确清理`/var/tmp/sdrharness-dev/p201-recovery-health-907w`：
**1632个文件，765,733,911逻辑字节**，整个构建/测试/临时验证根已不存在。
逻辑字节包含构建硬链接，不声称为实测物理释放量。没有新保留IQ或P201临时文件，
旧RF证据和用户语料/应用结果未删除。必要结果、原失败与后续确认、hash和状态
收录在审计JSON；模型适配继续暂缓，recognizer_available=false。
