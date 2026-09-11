# B210迁移AGX与双设备工作区

[文档入口](../README.md) · [设备入口](../../devices/README.md)

基线`efb1e4d`。用户要求将NX上的B210程序/UHD/FPGA运行时迁到AGX，并把B210与P201
放在不同目录、共享同一份RadioML2018A。当前单元只迁移软件/运行时、验证USB初始化和网口健康，
未执行TX/RX流、模型、EEPROM/flash写入或P201部署/FPGA/BOOT操作。

## 实际目录与迁移范围

- `devices/b210/`：本机状态/有界初始化程序、AGX/NX传输后端、UHD运行时manifest、有限TX和campaign程序入口。
- `devices/p201/`：原Controller只读健康入口、sdrd/Controller源码及AGX配置入口，固定网口RX。
- 两个`dataset/`符号链接均解析到`local-assets/amc-eval/datasets/rml2018a/RML2018a.hdf5`，
  已核对相同设备号/inode47739861、大小21,449,148,312字节，计划生成再次通过完整SHA-256。
  没有复制NX的RadioML2018A或HisarMod，也没有新建训练数据副本。
- 程序入口链接到既有唯一实现；现有Controller安装路径、P201 `/sd/sdr-agent/current/`、
  共享Worker/profile及原始实验记录不移动、不复制、不重写。

NX和AGX都为aarch64/Ubuntu22.04，UHD均为4.1.0.5-3；三个UHD工具、文件TX程序与
`libuhd.so.4.1.0`逐字节SHA-256一致。AGX已有相同系统库/依赖/udev权限，复用安装，未重装或覆盖全局库。
从NX直接复制三个UHD工具、文件TX程序、两份所需镜像、原skill/激活脚本共8份文件，
总3,878,444字节，放入Git外的版本目录
`local-assets/devices/b210/uhd-4.1.0.5-3-a7-100t/`。
它经`devices/b210/runtime`链接访问；完整大小/哈希记录在[运行时manifest](../../devices/b210/runtime-manifest.json)。
旧NX激活脚本仅存为只读迁移来源，不执行其NX绝对路径、全局镜像安装或USB reset步骤。
NX原安装/数据保留作为历史及回退依据，本次未在NX创建暂存文件或删除其已有文件。

## B210镜像及实机边界

本板为`MyB210`、serial2508504、A7-100T；专用FPGA镜像2,898,992字节，SHA-256
`ee03a9e38c83a1f6f327e7b560522c2a96629e7de574196092c1b830d05fcf9b`；
FX3 `usrp_b200_fw.hex`为514,346字节，SHA-256
`cc8e4bc968d91d1a67c63871ce5b2c1613c49676fe363bf2f6e336059899ae5c`。
这不是普通B210镜像；A7-200T和官方备用镜像均不迁入活动目录。
设备入口同时硬编码校验这两个已验证哈希、manifest、固定路径和系统UHD库身份。
`UHD_IMAGES_DIR`仅进入B210子进程，文件TX程序也固定到独立版本目录并校验原UHD二进制哈希，
不修改`/usr/share/uhd/images`，不将B210镜像放入P201目录。

初始AGX USB枚举VID:PID2500:0020、boot serial0000000004BE、480Mb/s。
确认唯一B210且USB无持有进程后，有界discover（35秒）加载FX3，随后probe（70秒）
使用指定serial加载A7-100T；实际重新枚举到serial2508504、5000Mb/s，UHD显示USB3，
两次寄存器回环通过。初始化没有开启RF流，无需USB reset或写EEPROM/flash。
最终USB节点`/dev/bus/usb/002/004`空闲；节点编号可能随重插改变，后端按sysfs身份动态解析。
P201健康入口独立返回healthy、RX1/RX0/A_BALANCED，没有导入UHD或操作USB。

## 本机收发编排与验证

campaign新plan默认`tx_host=agx`、TX0/RX20；可显式指定NX历史主机及既有70/80、40/50档。
host/增益只能在plan登记；host传输代码、设备入口及AGX运行时manifest身份一并固定，变更必须新campaign。
AGX后端使用本机暂存/进程管道/文件回收，NX后端才使用SSH/SCP；P201连接、原生数据验证、
取消和射频状态恢复仍由原Controller及P201帮助程序负责。audit标注tx_host及对应主机的postflight。
有限TX保留字节/时长/峰值、精确GO、子进程停止与日志哈希门；未验证的UHD二进制在启动前拒绝。

入口验证发现原代码使用`Path(__file__).name`时把链接名campaign.py当作源码名，
首次plan生成在软件身份阶段失败，无射频、没有完整plan。已改为解析真实路径，补齐共享模块搜索路径，
并增加符号链接入口及GPU租约模块定位回归。失败日志保留，空失败目录逐项移除，未放宽哈希门。
修正期间的中间plan不作为可执行最终计划；最终计划另用新根保存，不改写旧plan软件哈希。

43项相关测试通过：新增AGX本地文件往返/子进程路径不调用NX、设备主机边界、共享数据链接、
符号链接源码身份与依赖定位、TX0有限FIFO和UHD替换文件拒绝；原同步/预算/SINR等测试保持通过。
实际探测、P201健康、UHD版本/镜像路径和最终AGX plan加载均通过。
本轮无实际B210发射、无P201新IQ，不能称AGX本机TX→P201有线收发已验收；
生产recognizer_available保持false。下一步仍需确认30dB＋20dB衰减器和15cm SMA线的实际接法，
再登记低增益有限验证，不默认沿用此前空口80/40。

## 保留、清理与回退

逐文件路径、大小、SHA-256、来源和精确人工删除命令见
[迁移证据清单](../evidence/B210_AGX_MIGRATION_2026-09-11.json)。
保留安装运行时8文件3,878,444字节；无RF探测/失败诊断/最终测试与校验6文件15,506字节；
最终未执行计划1文件4,989字节，位于`/var/tmp/sdrharness-dev/b210-rml2018a-agx-ready-20260911/run-plan.json`。
该计划加载通过，固定AGX、TX0/RX20，尚不构成有线试验的接线确认或批次预登记。

已删除本单元冗余日志和未使用中间plan共6文件33,263字节，两个非保留根已核对不存在；
此前首次失败的空目录也已移除。无新增socket、NX/P201暂存或遗留本单元进程，USB无持有者。
没有新增IQ、权重或数据集副本，原实验保留包不参与本次清理。
NX原安装保留；回退须将B210接回NX并创建显式NX新计划，不改旧计划身份。
AGX全局UHD与P201安装未替换；删除本单元专用运行时只会使B210入口校验拒绝，不能删除共享数据集。
