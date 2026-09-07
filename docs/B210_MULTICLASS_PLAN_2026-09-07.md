# 24 类 × 3 行实发实收诊断预注册

按用户要求覆盖全部数字类别，每类三条不同训练行，先固定清单再采集/推理。
当前 P201 RX1 接用户的新 2.4/5 GHz 天线；NX B210 2508504 channel 0
TX/RX 经独立天线发射。仅外部有界工程源，P201 保持 RX-only。

- 只解压 split 的 `train.npy`，验证既有 train hash。每类 +30 dB block
  内按 SHA256(`b210-multiclass-907u:row:<row>`) 排序取前三；先验证训练成员，
  再读取仅这 72 行 X/Y/Z。验证 one-hot 数字 ID 和 SNR。绝不读 locked test，
  不重新扫描/哈希整个 HDF5；整库身份引用既有固定 hash 并核验尺寸。
- 三轮各 24 类，轮内按 SHA256(`b210-multiclass-907u:order:<round>:<id>`)
  排序，样本选择不看模型结果。每条保留原始 1024 点；缩放到 complex peak .2，
  只循环这一条 20480 次。不给不同样本拼接成一个发射单元。
- 2455 MHz，B210 LO +250 kHz、gain 70 dB、2.1 MS/s、BW 1.5 MHz；
  P201 RX1/RX0/A_BALANCED、gain 40 dB、settle 500 ms。
  40 dB 是诊断条件，不能冒充生产 profile 的 50 dB。
- 每轮先做历史有界 100 kHz tone，2.5 MS/s，25,000,000 点；tone 门失败
  停止矩阵并保留未执行项，不自动补发失败样本。每组停发前/发射中/停发后
  各 65,535 ci16 点，单次 timeout 1000 ms，Controller 总 deadline 15 s。
- 最多 75 组 / 225 captures / **58,981,500 RX bytes**；
  TX 最多 1,584,949,440 点、750 nominal seconds。外层总 deadline 7200 s，
  每组 180 s（另留 20 s stop）；NX 独立 timeout 和有限 FIFO 防止失联无限发射。
  开始前记录空闲空间，要求 RX 上限另加 1 GiB 开销。每组直接 stop 和恢复校验，
  额外核验两 RX 通道状态、单 daemon 和部署 hash。SIGINT/SIGTERM 触发清理。
- 固定模型块为接收 offset 32768 开始连续 4096 点；源是原始行重复四次。
  两者均走 RF-v1 共享 RMS / 四窗、冻结 epoch-10 FP16 autocast + FP32 weights，
  保存完整 logits / mean logits，不作数值校准或生产 classified。
- 主要对照 **原始源 / raw RX**。另登记固定 175 kHz FIR 对照：只对源功率
  保留 >= .99 且归一化失真 <= .01 的样本运行 source-FIR / RX-FIR；
  不适用者保留原始比较，不能删掉宽带调制。源谱检查在任何推理前完成。
- 原有来源相关/残差/背景门保持原数值，单列合格与否；有限且完整的 IQ 可以
  诊断推理，不因背景门失败就消失。来源拟合退化记 unavailable，不能伪造相关性。
  保留 UHD untimed U/S 标记，不能据此证明空口连续或归因具体坏窗。
- 最多 1152 实验窗口 + 2 warmup，不训练、不做完整精度实验。
  报告全部 72 分母、原始源标称一致、RX 标称一致、source→RX 变化和缺失，
  附各类三条结果。训练样本的小规模重复播放不是独立 RF 测试准确率；
  数字 ID 可信、名称 provisional，V1b/V2/生产准入保持未完成和 false。
- AGX 根 `/var/tmp/sdrharness-dev/b210-multiclass-907u`，各组为同父目录下
  `b210-multi-{tone0..tone2|r0c00..r2c23}-907u`。组内复用 SigMF 存储；
  NX 同名组目录和 P201 plan-derived 临时路径在接收/校验后删除。
  保留最小源/接收证据支持逐类复核（上限约 60 MB），登记精确路径、字节、
  SHA256、source/request/session 与手动删除方法；build/test/cache/复制中间件
  全部删除。不得触碰任何旧诊断包或用户应用结果。
