# SDR Agent project checklist

Last reviewed: 2026-09-14

This is the living source of truth for implementation status. Check an item only
after the exact wording is implemented and verified. Split partial work into a
completed item and a remaining item instead of marking an ambiguous partial
state.

Sections 1–6 are now the unified RX-only chapter plan and replace the earlier
4-to-6-only planning view. The concise chapter view is
[`CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md);
this file retains the detailed delivery and evidence ledger.

## 当前交付状态速览（2026-09-10）

以下是本文件各章节的当前交付索引；详细完成条件和证据仍见对应章节。
编号表示范围，不表示施工先后；实际顺序见
[`SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md`](SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md)。
S1/S2/V1a/S3/S4a/S6a/S5/S6b/S4b/O1a 源码、适用隔离实机验收及清理完成。2026-09-07 已单独部署统一 `sdr-agent` CLI，当前 Controller/交互代码因此在已安装制品中；本轮 Web 后台也已单独升级并实测会话恢复/回滚，归档界面进入安装制品，但 Worker、profile/准入配置未部署，不能将此计为 A1 或生产识别闭环完成。S4b 的 GPU 温度缺失由用户明确豁免，保持未测。

- [x] 固定2496验证成员频谱诊断：7488窗全保留，高源SNR源99%带宽中位256kHz，LO区占比source0.000031%/raw11.05%/guard0.144%；不支持固定1.5MHz带宽直接改+750kHz偏移。首次原source与归一source身份比较失败保留，a2按正确关系逐元素通过；4测试/150组及1872格独立核验通过，保留23文件7,517,400字节，删3文件141,572字节，无RF/模型/生产变更。见[频谱与移频边界](validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md#既有验证成员的频谱占用与lo移频几何检查2026-09-16)。
- [x] 固定TX60带时间事件复测：4份ADC/2次发送各8,381,952点，仅ACK（名义结束后0.654μs）、无报告U/S，RF/DSP独立读回通过，残余LO仍约低8dB；不同入口不能追溯旧FIFO事件。10项C++/9项Python及独立计数/功率核验通过；最终AGC瞬时增益导致严格恢复失败保留，后续原门完整相等通过。保留50文件3,885,730字节，清理179条目1,596,141字节；无模型/生产替换。见[事件复测](validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md#固定tx60单音的发送事件时间复测2026-09-16)。
- [x] 获准镜像重载后LO基线调试：6份有限实收/4次单音，等功率增益配对复现7.32/7.58dB下降；原功率条件通过，但TX尾部U/S/U/U未定位，不作为无异常链路验收。独立IQ/计数/恢复、7测试和精简skill校验通过，双路状态/USB空闲及暂存清理完成；保留62文件1,983,683字节，删35文件328,330字节，无模型/生产改动。见[设备调试](validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md#获准设备调试镜像重载后的lo功率基线2026-09-16)。
- [x] UHD校准路径审计与获准镜像重载：系统库/13批发送身份通过，创建TX流后的自动校准路径澄清，RF/DSP独立读回仍缺失；专用FX3/A7-100T加载恢复USB3、serial2508504、双回环及空闲，通过后写入N210技能。无TX/RX数据流、训练或生产变更；技能校验通过，保留16文件379,408字节，删1文件53,428字节。见[审计与实机结果](validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md#uhd校准路径只读审计与获准镜像重载2026-09-16)。
- [x] LO/50Ω历史与官方资料复核：360父文件19,907,060字节身份通过；区分TX相干泄漏与未归因背景瞬态，既有约7dB改善不重复作为新实验。下一步只读审计改版UHD校准路径；未RF/写校准/推理/训练，前置保护区草稿仅6项合成测试，真实验证暂停。删24文件4,634,714字节，保留5文件14,117字节。见[复核](validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md#lo与50ω历史复核及官方资料评估2026-09-16)。
- [x] 相消前后共用raw RMS分母：同D8 seed42/2496原val，新增2496预测，guard1341→1203（48.20%），纠正86/回退224；原相消回退救回16、原纠正丢失90，AM154→142、4ASK13→7，不启用候选。预登记数值/身份和676组独立复核通过；首轮输出字段问题在推理前修正，中断记录保留、阈值不变。删353缓存文件24,425,794字节，保留19文件1,431,486字节，无RF/训练/生产变更。见[配对与发射问题解释](validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md#相消前后共用raw-rms分母2026-09-16获准执行)。
- [x] source历史TX峰值缩放对照：同D8 seed42/2496固定val，新增预测2496，source正确1578→150（6.01%）；与guard_pilot仅61.94%逐条top-1一致，不把相近均值当作链路无损。封存函数载荷逐元素一致、675组独立复核完成；首次理论峰值1e-7诊断6行超限的中断和失败标志保留，不改阈值或删样。删353缓存文件24,425,794字节，保留19文件1,384,032字节，无RF/训练/生产变更，见[对照](validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md#source发射峰值缩放对照2026-09-16继续)。
- [x] 既有ADC离线基线与幅度诊断：原D8 seed42/2496固定val，从13主流重放，2603父文件SHA通过；raw逐元素一致、guard最大差2.38e-7，logits通过预登记容差、历史top-1一致100%。source RMS-only净退153，raw→guard纠正331/回退222（AM净退17）；导频幅度候选大幅降分、不启用。675组独立复核和最大误差样本历史64帧批量定位通过，删353缓存文件24,425,794字节、保留27文件12,649,116字节。无RF/训练/生产变更；有前序状态的同步重放，不代表整段流独立重捕获或失败成员覆盖。见[报告](validation/RML2018A_OFFLINE_BASELINE_2026-09-16.md)。
- [x] 4090模型导入与旧四窗微调权重删除：8种模型/12份权重及配置、标签/源码身份已下载，154文件逐一SHA-256一致，12份CPU安全读取/有限值检查通过；epoch-010已按用户要求精确删除，原始seed44和实收IQ/结果保留。临时2文件36,868,214字节已删除，模型及最小审计登记保留。见[验证](validation/RML2018A_MODEL_IMPORT_2026-09-14.md)。历史epoch-10验证仍为当时事实，其权重当前已不可用。
- [x] 新导入12份权重的AGX工程接入：strict load/参数/后端匹配与三域合格样本GPU先导通过，FP16数值失败保留，最终12模型采用FP32；7项筛选/行号/续跑/统计测试、原进度脚本新旧入口和独立PNG/SVG/CSV绘图验证通过。36组后台服务已实写预测块，旧Worker/profile不改绑，生产能力仍false。见[验证](validation/RML2018A_CLEAN12_EVALUATION_2026-09-14.md)。
- [x] 外接盘清洗raw/guard复制SSD：2份HDF5共43,052,129,882字节及清单，源清单/传输SHA-256/SSD读回一致，服务退出、partial无残留；原始本地RML2018A哈希复核后复用。文件保留清单及人工删除边界已登记。见[复制审计](evidence/RML2018A_CLEAN_SSD_IMPORT_2026-09-14.json)。
- [ ] 原12模型×三数据集完整识别与36张真实混淆矩阵未完成：用户随后缩至seed42并暂停，曾保留29块/475,136条CNN2 source预测，随后按用户要求删除。旧全量范围被最新选择覆盖，不继续旧计划，不把部分结果勾为完成。
- [x] 用户暂停与seed42验证划分核对：识别进程MainPID=0、运行缓存已清理，STOP及进度脚本显示暂停，已落盘块逐一哈希核验；服务器原seed42 70/15/15 NPZ取回，3,906,318字节且SHA一致，三集合无重叠/完整覆盖，val383,385条与8份seed42配置引用一致。raw/guard合格val379,662/371,108，共同369,497，未启动新推理。见[暂停与划分](validation/RML2018A_CLEAN12_EVALUATION_2026-09-14.md#用户暂停与seed42原验证集核对)。
- [x] seed42原validation的8模型从零接入及启动：直接用原NPZ val成员，RX按source_row映射后与严格质量相交，10项索引/标签/fresh/续跑测试及真实全量元数据核对通过，train/test选中0。继承已验证FP32数值依据，但预测复用0；用户指定的前两轮结果314文件467,835,397字节已精确删除，新元数据从HDF5生成。进度/收口为24组，新后台已实写val块；见[验证](validation/RML2018A_CLEAN12_EVALUATION_2026-09-14.md#seed42原验证集8模型启动)。
- [x] seed42 validation完整识别及24张真实混淆矩阵：source383,385/raw379,662/guard371,108，共9,073,240次预测，24组/图完成，耗时14,778.58秒；3,744块及7,640保留文件哈希、argmax、独立统计/共同矩阵读回通过，服务正常退出、运行缓存不存在。见[完成复核](validation/RML2018A_CLEAN12_EVALUATION_2026-09-14.md#完成核验与source到guard差距复核2026-09-15)。
- [x] source到guard差距诊断：369,497共同成员排除分母差异；固定2,496条×8模型RMS-only对照39,936次预测完成，原source复算top-1与保存结果差异0，证明幅度预处理敏感性，未将剩余差距归因为已证实硬件损失。诊断缓存清理，最小证据保留；未训练/改权重/重跑全量或RF，见同上复核。
- [x] 清洗回归核对：raw/guard各2,496条覆盖24类×26档的IQ与旧processed.h5逐元素一致；全量source_row/class/SNR映射通过，外接盘两份构建脚本哈希匹配manifest且直接复制旧IQ。没有发现抽查波形被清洗改变，未冒充全部IQ逐字节复核；历史59.07%为epoch-10结果，非本轮原始seed42同模型对照，见同上复核。
- [x] Mamba source/raw包含质量失败行接入及启动：新增显式模型/输入子集及包含质量失败选项，11项测试通过；原validation各383,385，raw含3,723条质量失败，train/test选中0，新预测预算766,770。进度默认切换、质量标志保留、共同严格合格分母另报，已有结果不改。见[启动](validation/RML2018A_CLEAN12_EVALUATION_2026-09-14.md#mamba的sourceraw包含质量失败行重跑2026-09-15)。
- [x] Mamba source/raw包含质量失败行的766,770次预测收口：两组各383,385，ACC63.3082%/49.7294%，raw3,723条质量失败全部预测；312块及644保留文件218,907,624字节哈希/统计独立核验，两图完成、服务退出、缓存不存在，耗时533.254秒。见[完成与补跑](validation/RML2018A_CLEAN12_EVALUATION_2026-09-14.md#source和raw完成及guard补跑2026-09-15)。
- [x] Mamba guard包含质量失败行单独补跑接入：11项测试含guard-only fresh范围通过，原validation383,385条、质量失败12,277条纳入、跳过0，source仅作标签核对不预测；新根独立启动并实际写出首块，进度默认切换，见同上验证。
- [x] Mamba guard383,385条补跑收口：ACC54.4607%，12,277条质量失败全部预测（7,727正确）；156块/325保留文件126,078,643字节SHA与矩阵独立核验，一张PNG/SVG及CSV完成，服务正常退出、缓存不存在，耗时295.629秒。原371,108合格行与上轮预测差异0，三组主分母相同。见[全三组完成](validation/RML2018A_CLEAN12_EVALUATION_2026-09-14.md#包含质量失败行的三组最终结果2026-09-15)。
- [x] 原始Mamba D8 seed42全量三组接入/启动：prepare-full去除split过滤并拒绝混入split参数，11项测试含全量范围通过；实际三组各2,555,904、每类每SNR4,096、原行完整，raw/guard25,314/82,406质量失败纳入、跳过0。预测复用0，后台有限脚本启动、进度默认切换，见[全量启动](validation/RML2018A_CLEAN12_EVALUATION_2026-09-14.md#原始mamba三个完整数据集启动2026-09-15)。
- [ ] 原始Mamba三个完整数据集7,667,712次预测收口：须三组全量预测/独立读回/三张矩阵/运行缓存清理完成，不将活动后台算成完整通过。
- [x] CodeGraph本地索引已初始化：180文件、5057节点、16234关系，CLI和MCP查源码/调用关系通过；索引Git忽略，实验资料仍按需读，不启动RF/模型。见[验收](validation/CODEGRAPH_INITIALIZATION_2026-09-10.md)。
- [x] B210迁移AGX及双设备工作区：B210 USB与P201网口分别提供目录/执行入口，共享同一份RadioML2018A；NX的UHD工具和A7-100T/FX3运行时8文件已隔离安装，复用相同系统libuhd。实际USB3/两次寄存器回环、P201只读健康、最终AGX计划加载及43项测试通过；精确清理6文件33,263字节，运行时及最小证据已登记。无RF流/模型/生产部署。见[迁移验证](validation/B210_AGX_MIGRATION_2026-09-11.md)。
- [x] AGX本机B210→P201有线有限收发及主动停止：用户确认50dB串联后改为30dB；低增益失败保留，30dB TX80/RX40两批48条全同步、实收45/48。首次取消残留FIFO的失败已记录并修正，新根主动取消/完整恢复通过；47测试、192模型输入哈希/质量复核及精确清理完成。见[同轴验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12同轴衰减接收幅度与主动停止)。
- [x] 20dB衰减与匹配增益对照：用户确认换成20dB，TX70/RX40与条件TX80/RX40共4批全同步，识别47/48及45/48；192输入哈希/质量/历史父记录复核、恢复及清理通过。信号与+250kHz残余功率同时随TX增益升高，未解决波形质量；无代码/生产配置变更。见[20dB对照](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-1220db衰减与匹配增益对照)。
- [x] 干净单音LO来源对照：独立有限入口复用既有TX helper/Controller，4组TX及前后停数据流控制均完成；峰随LO移动约499996Hz，数字幅度减半使有效单音降5.77dB而LO分量未降。48项测试、原生IQ/命令/频谱复核、P201恢复与精确清理通过，无数据集/模型/生产部署。见[单音对照](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12干净单音与lo跟随分量)。
- [x] 数字幅度/硬件增益配对单音验证：20dB接法下0.1/TX70与0.316227766/TX60两次A/B对照、前后停流控制共6采集，信号变化+0.10/+0.13dB且LO分量降7.39/7.28dB，均通过预登记标准；50测试、原生IQ/谱功率/恢复/清理通过，无数据集、模型或生产部署。见[配对验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12数字幅度与硬件增益配对)。
- [x] RadioML两类调制波形幅度/增益配对：同48条OOK/QPSK Z30，0.2/TX70对0.632455532/TX60，共4采集全同步；SINR中位数0.77/2.08→7.90/9.26dB，识别46/48→48/48，相关度约0.74/0.79→0.93/0.95。53测试、192模型输入哈希、恢复与精确清理通过。有限配对profile只接纳两批，普通全库峰值不变。见[调制验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12radioml调制波形的幅度增益配对)。
- [x] 保护间隔辅助LO相消离线验证：既有两类48条保持原同步，静默区拟合、留出验证及导频频率检查；后处理条件SINR中位数7.90/9.26→19.75/19.36dB，范围18.29～20.80dB，冻结识别仍48/48。55项回归及最终8项相消测试、144模型输入哈希/原生IQ/质量复核、Spark恢复及精确清理通过。无新RF或生产部署，宽搜索歧义失败保留。见[相消验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12保护间隔辅助lo相消)。
- [ ] 有线波形质量：统一RX50的24类Z30有限覆盖已完成；16QAM首保护区及零星载荷异常、AM估计/模型限制、长期稳定及低源SNR额外损失/处理回退仍未解决。局部有限验证不完成稳定全库质量、物理SINR校准或生产准入。
- [x] 相消后剩余误差/导频时序诊断：48行×9正向模型×2留出方向，源X仅作归因；QPSK时序项解释约2.31dB、OOK0.13dB，导频与payload辅助延迟估计约0.02点RMS差，组合解释后残差接近静默区残差。6项已知分量/失败测试、864fold和父seal/48输入/质量逐值复核及精确清理完成；≥3dB解释目标未全面达到，不记为接收SINR提高。无RF/模型/部署。见[剩余误差诊断](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12相消后剩余误差与导频时序诊断)。
- [x] 导频时序校正与八类新采集有限验证：独立过采样/留出/插值保真及66项回归通过；8类新192行、8批全同步和完整恢复，7批LO/时序通过、64QAM留出门拒绝并原样保留。原始/LO/时序识别133/162/162，源179/192；768实际输入/质量/预测复核及精确清理完成。实验入口已在AGX运行，生产默认未安装；不完成24类/低源SNR/物理校准。见[八类验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12导频时序校正与八类新采集)。
- [x] 八类保护间隔异常离线定位：66份父文件哈希、8份原生seal/同步/LO结果与完整派生统计复核，4项独立统计测试通过；64QAM末保护间隔后半段残差36.17counts²、第三导频残差同步升高，OOK另有训练半段突发。保留原10dB门、原始识别/SINR及失败，清理完成；无新RF/源IQ读取/模型/部署，不确认物理来源或连续性。见[诊断](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12八类保护间隔异常的离线定位)。
- [x] 保护间隔LO修复及四批QAM有限验证：新增所有保护半段的块相量经验余量准则，保留旧10dB总功率门/失败；75测试（含40次已知突发仿真）、4批新96条实收/480输入与旧64QAM回放通过。旧批SINR7.63→17.60dB，新96条原始/新LO识别11→86，追加时序84，未设为识别默认。射频/Spark恢复及精确清理完成，实验入口实际执行、生产未部署。见[修复验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12保护间隔lo修复及四批qam验证)。
- [x] 固定500kHz滤波与时序有限对照：既有96条源保真最大误差0.089%，源正确行无回退；组合SINR中位数64/256QAM22.41/22.03dB，识别合计86/96但64类净退1、256类净进1。3项独立滤波测试、288新输入/预测及96条诊断回放、Spark恢复与精确清理通过。单个固定候选，无新RF/部署；不默认启用，不完成新样本确认或稳定全库质量。见[对照](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12固定500khz滤波与时序对照)。
- [x] RX40/RX50配对有限实机验证：新96源行在两档各接收一次，8采集全同步/无削顶且完全恢复；LO后配对SINR中位提升64QAM1.92/256QAM2.88dB，识别80→90/96，10纠正/0回退。81测试、1152输入及两档源logits一致性复核、Spark恢复与精确清理通过。后续实验参考TX60/RX50+LO；滤波/时序组合总识别未进一步提高，不部署普通全库/生产。见[配对](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12rx40rx50配对实机与识别对照)。
- [x] 其余16类RX50高源SNR有限覆盖：独立profile限定AGX TX60/RX50、16批384条Z30，全同步；源/原始/LO识别369/319/350，13批应用、3批因保护区残差跳过且保留分母。84测试、1152输入哈希/质量复算、设备与Spark恢复及精确清理完成。旧八类RX40不可合并为同条件24类准确率；不完成异常归因、低SNR或全库质量。见[验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12其余16类rx50高源snr有限覆盖)。
- [x] 其余16类保护区异常离线定位：固定三失败批及BPSK对照，原生seal/同步/相消拒绝与全部诊断重放、7项统计测试、父182文件哈希和精确清理通过。失败批保护区功率起伏20–25dB且以宽带残差为主；16批S/U没有样本时间戳，不能独立确认物理来源。无新RF/模型/校正部署。见[定位](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12其余16类保护区异常的离线定位)。
- [x] 当前RF配置复现与论文范围归档：4031194版本的接线/射频/帧/处理/源行/模型/UHD与父证据已链接并版本化保存；本机8运行文件、libuhd、checkpoint、Controller/脚本哈希和文档引用核验完成。明确单窗工程、已知导频/保护区、条件SINR及同轴/空口证据边界；无RF/训练/模型/部署或临时IQ。见[复现说明](reference/RML2018A_RF_REPRODUCTION.md)与[归档验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-12配置复现归档与论文证据范围)。
- [x] B210发送事件可观测性及有限控制：独立固定参数入口记录send/异步设备时间，13项离线测试、补充单音数值验证、实机主动取消和6份RX/完整恢复/清理通过；4次完整发送仅ACK。停流/全零仍有非LO尖峰，约16ms间隔只作有限线索，不完成物理来源或跨设备时间映射。无源数据/模型/生产替换。见[事件控制](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13带时间记录的b210发送与停流全零对照)。
- [x] P201独立50Ω负载六次RX对照：用户确认断开同轴后同2455MHz/RX50采集，6次原生/恢复通过；3项数值检查、10份新旧匹配统计重算、父64文件哈希及精确清理完成。旧约16ms最大双峰模式未重现，负载2/3仍有突发；该单元不提供物理来源证明，接回返测另列。无TX/模型/部署。见[负载对照](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13p201独立50ω负载与同轴控制比较)。
- [x] 20dB同轴接回后的停发返测：用户确认接回、6次相同设置RX完成，原生/恢复/固定统计回放与精确清理通过，父50文件哈希保持。旧大尖峰及16ms最大双峰模式未恢复，较弱突发仍在；不支持接线稳定触发的确定归因，不完成物理源/全库质量。无TX/模型/部署。见[返测](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13同轴接回后的停发返测)。
- [x] 四类新源行带事件有限复测：BPSK/32PSK/32QAM/FM各24条Z30，四批同步与原guard门通过；LO后条件SINR中位21.08/18.59/22.70/25.34dB，源/原始/LO正确96/84/95，保留12纠正/1回退。98项测试、6份RX/4份事件/288输入回放、父295文件SHA、恢复与精确清理通过；旧三批拒绝未重现，停流仍有突发，不宣称物理源已修复。见[复测](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13四类新源行带事件复测)。
- [x] AM单边带指标适用性离线核对：96旧源行/4份IQ/288已存输入回放及5项解析测试通过；SSB短窗均值占比中位99.67%/99.10%，1条理想y=X仍不可辨识，26条无效SINR中21条识别正确。源/LO预测47/48一致，保留共同错误与回退；报告有效覆盖/无效原因和完整分母，原门与模型不变。父182文件及清理通过，无新RF/推理；不完成物理校准或AM混淆修复。见[核对](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13am单边带指标适用性离线复核)。
- [x] 统一24类RX50新源行有限确认：每类24条新Z30、576条全同步，26RX/24TX事件/完整恢复完成；23批LO通过，16QAM首保护区拒绝保留原始。源/原始/LO正确548/457/548，96纠正/5回退、源与LO有16条预测不同。105测试、1728输入及全部质量/汇总重放、父129文件、图表与清理通过；同条件高源SNR工程覆盖完成，不宣称长期稳定或独立/空口精度。见[统一确认](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13统一24类rx50新源行有限确认)。
- [x] 四类五档低源SNR有限分层：BPSK/16QAM/64QAM/FM×Z20/10/0/−10/−20共480新行全同步，19批LO通过、16QAM/Z−20拒绝保留原始；按Z的源/原始/LO正确93/71/92、94/76/92、56/55/53、15/13/3、5/1/2（各96）。101测试、22RX/20TX事件/1440输入及真实Z/分母重放、父291文件/图表/恢复清理通过。48纠正/22回退，不将LO设为全SNR默认，不完成24类×26档。见[分层](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13四类低源snr有限分层)。
- [x] 事件TX接入campaign及混合Y/Z边界续跑：4批96新行，主动取消/恢复/有限重试与已完成不重发通过；修复guard参考面及分片Spark目录衔接，原计划/失败/软件封存、两版零RF处理计划复用原IQ。117不同测试、4RX/5TX尝试/288输入及不重推理复核，源/raw/guard49/45/49、5纠正/1回退；恢复清理完成。仍仅有限profile，非全库或生产准入。见[边界续跑](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13事件发射接入campaign与边界续跑)。
- [x] 通用有限chunk及无损日志预算：明确登记1–32批、成功gzip/元数据与失败保留分开限额；131测试、两个48行新块及重复首块验证通过，68文件不变且无重发/重推理，日志5,405,395→530,345字节逐字节还原。源/raw/guard95/60/92、33纠正/1回退，恢复清理完成。全库条件预算483,469,927,424字节，该单元未包含跨计划失败池统一账本，不代表全库已执行。见[分块验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13通用有限分块与无损日志预算)。
- [x] 跨块总控/预算与共享源核验：只读导入96行、两批新48行；登记/完成凭据重建、重复导入、坏派生状态恢复、重复/总额度/预启动STOP门及完成块不重发不重推理通过。133测试，新增源/raw/guard47/46/47，账内144行完整提交；缓存自动清理、射频/Spark恢复与78文件保留完成。仍为有限工程验证，断电/运行中总控取消及正式全库覆盖未验收。见[总控验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13跨块总控与源核验复用)。
- [x] 全行覆盖/历史源血缘与24批有限总控：冻结106496批全域互斥去向及显式标准化重放规则；144旧行只读导入＋576新行全同步/三路推理，账内720行完整提交。139测试、重复完成跳过、24TX/24RX/1728输入、恢复及465文件精确保留/清理通过；新source/raw/guard388/331/357，68纠正/42回退。当前6批流程外推约41.4天，实际历史重放/全库/运行中总控取消仍未验收。见[覆盖验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13完整覆盖规则与24批有限总控验证)。
- [x] 接收时预处理落盘/会话内常驻模型：一个CPU进程与有界接收衔接、先完整落盘后一次加载模型；146测试、576条回放输入/top-1一致及96新行实收通过。模型阶段308.61→127.80秒；新source/raw/guard96/77/95，重复完成零新操作、恢复及192文件保留/清理完成。仅1–32批有限实验入口，生产未变。见[常驻验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13接收预处理落盘与常驻模型)。
- [x] GPU批量payload离线后端与同Z1024条映射：FP64 RMS/SINR、FP32输入输出；全库26档每档96块无重无漏。152测试通过；24/1024/4096/8192条AGX实测，源8192唯一行及重复96既有实收行，归一化字节一致、SINR最大差7.11e-15dB、状态理由一致；无新RF/模型/生产部署。清理及保留见[GPU验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13gpu批量payload预处理与1024条分块)。
- [x] 每SNR档SigMF/HDF5存储与安全重开：1024条追加、原始/处理分别保留、源Z/条件SINR/同步及背景/接收功率元数据、SHA/采样位置关联；96块合成IQ共98304条和约2.94GB真实落盘/封存/重开读回，96条模拟未同步保留。160项相关测试中159通过/1项既有GPU测试按范围跳过，最终8项存储测试通过；已提交原始块可续处理，损坏/未提交尾部保留拒绝覆盖，未验证真实断电自动修复。合成大文件清理、证据登记见[存储验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13sigmfhdf5整档存储与中断留证)，无RF/GPU/模型/生产部署。
- [x] 两个1024条块的连续收发/RAM双消费者与常驻GPU先导：原生分段流、首段IQ后TX GO、GPU预热至处理/写盘排空、全部12缓冲延迟释放实测通过；RX-only取消/断连恢复及P201回滚重上通过。最终168项Python167通过/1跳过、C/C++/Rust检查通过；算法ABBA同IQ6.464→5.276秒，全部输入/quality完全一致。清理及127文件保留见[验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13连续收发内存所有权与算法优化)。仅2048条Z30/class0先导，最终算法优化为离线验证，生产Controller未替换。
- [x] 多帧GPU保护区拟合及接收线程同步停顿修正：16/64/128帧数值门通过，64帧对应1024行，完整解码ABBA5.280→4.268秒；CUDA标量索引改gather，监测线程最长间隔117.8→1.6ms。第一次frame80失败保留；修正后2048行全部同步，两个处理块均在RX结束前提交，内存仅在处理/落盘后释放。173项中172通过/1跳过，两个新增CUDA测试实跑；清理12文件/229184字节并保留75文件，见[验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-13多帧gpu并行保护区拟合)。普通CPU调用与生产部署保持，整档/全库待验收。
- [x] 一整档及条件两档连续收发：原Z+30的98304行通过后，+30/+28的196608行一次连续TX/RX全部同步、GPU处理及封存；独立RX进程/共享RAM/有界滚动解码、跨档共用原始IQ及P201独立1GiB流限额已实现。C/C++/Rust及176项Python通过（1项既有可选跳过），P201升级/回滚/重上、完整恢复及精确清理通过；未运行模型，处理仍慢于RF。见[验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-14整档与两档连续流实验)和[保留证据](evidence/RML2018A_FULL_SNR_STREAM_2026-09-14.json)。两次+30源行重复，不累计为三个独立档。
- [x] 26档调度与恢复源码/离线验证：13对互斥源范围、旧+30/+28只读导入、完成凭据/重启补登/跳过、显式有限重试、完整RX缓存恢复和全库推理就绪门；184项回归183通过/1跳过（相关CUDA实跑），新增后台门测试及整档相关13项通过。实机验证与剩余采集由单次后台脚本按门顺序推进，实际完成另列，见[本轮记录](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-1426档后台调度与验证门)。
- [x] 26档完整实机收发与双份语料：联合停止/恢复、完整RX缓存重放及跨进程跳过通过；26档2555904行、2496处理块全部封存，旧+30/+28只读导入不重发。采集服务正常退出，射频恢复、Spark停止；新任务清理16文件3523215360字节、保留2714文件76001275437字节，旧两档另保留。见[完成及离线识别启动](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-14全26档采集完成及离线识别启动)。真实断电恢复未验证。
- [x] 8192批量识别与并行读写：复用冻结模型，以CUDA Graph和16流数值复核执行，两个CPU线程预读/校验及提交结果；10测试、24类×三Z×三组分层数值门及真实首8192行流水线复核通过。8192批量实测约1408输入/秒、53.1倍单条加速，非全链路倍数；旧严格logit门仍失败。开发清理1898文件106421051字节，保留48文件9269142字节，活动服务自行持有结果，见[验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-14大批量gpu识别与并行读写)。
- [x] 识别进度只读脚本：`rml2018a-progress.sh`默认查看当前batch1024任务，每5秒刷新已完成/未完成、百分比和档数；实际单次/交互显示及Ctrl+C退出通过，后台任务与Python源码固定哈希保持，无新增临时数据，见[切换记录](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-141024批量重跑与旧结果删除)。
- [x] 26档封存语料冻结模型识别：GPU batch1024全部2555904行、2496块及三组预测完成，独立复核全部输出哈希/唯一行号/掩码/logits混淆计数及分档汇总一致；耗时78分6秒，源/原始/校正准确率62.37%/52.48%/59.07%，无缺失预测。服务正常退出并清理380缓存文件21269694字节，结果与原RF语料保留；报告复核清理1文件123432字节、保留8文件190596字节，见[全量结果](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-14全量1024识别完成与结果)。工程完成不等同独立精度或生产准入。
- [x] 全量四窗离线模式与有限兼容验证：按帧内固定连续四条分组、重放原IQ及既有相消参数、四窗共享RMS/均值logits、组分母/成员SINR血缘及续跑校验已实现；16项测试和24类×3源SNR的GPU证明通过，验证缓存清理完成。见[四窗记录](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-14全量四窗联合识别)。
- [x] 全量四窗联合重识别完成与比较：26档、2496块、638976组/2555904唯一源行全部完成，三种输入无缺失；全部输出SHA、父索引/输入引用、四窗成员与均值logits、逐块/档/全量混淆计数独立复核一致。source/raw/guard ACC为67.60%/58.09%/61.68%，较单窗+5.23/+5.61/+2.61个百分点；服务正常退出并清理380缓存文件21271304字节。结果及报告保留见[四窗完成](evidence/RML2018A_FOUR_WINDOW_COMPLETE_2026-09-14.json)。
- [x] 2026-09-08至14日实验HTML报告：按日梳理背景/频段/天线/同轴LO归因、预处理与全量单窗四窗结果，25项原始记录链接、源SNR曲线及24类筛选数据；单文件离线、CSV下载及12页A4打印验证通过，桌面/390px移动端已目视复核。开发暂存已清理、证据保留，IQ删除暂停且64个原文件仍在。见[报告](reports/SDR_EXPERIMENT_REPORT_2026-09-08_2026-09-14.html)与[报告验证](evidence/SDR_EXPERIMENT_REPORT_2026-09-08_2026-09-14.json)。 用户后续指定单窗为主要实验基线，四窗仅列探索方式；摘要、表头、方法定位和论文表述已一致修订，数值保持，见[定位修订](evidence/SDR_REPORT_FOUR_WINDOW_EXPLORATION_2026-09-14.json)。 补充源/未相消/校正三张单窗全量混淆矩阵，统一行归一化和色标，PNG/SVG/计数CSV及报告内嵌已验证，见[矩阵证据](evidence/RML2018A_SINGLE_CONFUSION_2026-09-14.json)。
- [x] 外接硬盘IQ副本登记与首文件核验：确认USB NTFS卷及空间，独立目录注册2802文件/82.14GB；复制脚本逐文件源SHA和目标完整读回SHA校验，首Z+24 HDF5哈希及96块/98304唯一行/首末校正IQ读回通过；原AGX语料和四窗识别保留。见[复制记录](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-14外接硬盘iq副本)。
- [x] 外接硬盘全26档IQ副本完成：2802注册文件82136084528字节全部源SHA/目标完整读回SHA通过，完成标记及校验表生成；独立核对计划/逐文件凭据/校验表一致、全部目标大小及无partial残留。耗时36分46秒，服务success/exit0/MainPID0；原AGX语料保留，无临时缓存删除，审计与副本保留见[完成证据](evidence/RML2018A_EXTERNAL_IQ_COPY_COMPLETE_2026-09-14.json)。
- [ ] 与历史冷进程的严格logit数值一致：576条回放最大差0.015625，超过预登记1e-5；1728个top-1一致。新独立冷启动432输入与常驻logits完全一致，但与旧冷启动仍有差异；原严格检查失败保留，具体数值来源及长期一致性仍未确定。
- [ ] 多类校正稳定性与低源SNR覆盖：统一24类Z30及四类五档有限分层完成；低SNR源域退化、实收额外损失/LO回退、保护区突发与AM限制保留。其余类别/源Z覆盖、物理来源、长期稳定和全库结果仍未完成，不能按估计有效率或局部正确率宣布质量通过。
- [x] AGX本机B210天线有限收发：用户确认天线，显式2455MHz TX80/RX40，两批48条Z30全部同步/条件SINR有效，原始源48/48、实收45/48；96输入哈希、原生IQ/同步/质量重算、P201与Spark恢复及清理通过。UHD尾部S/U保留，不完成RF连续性、AGX主动取消、有线或全库验收。见[记录](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-11agx本机b210天线收发48条)。
- [x] RadioML2018A全量工程脚本：原始2555904行规划、NX有限TX、P201原生RX、AGX冻结模型单窗对照、同步/失败分母、取消和批次续跑已实现；12项测试、72条有限实收关联/推理、主动中断/失败重试/不重发续跑与清理通过。源72/72正确，实收0/72正确，不能称为RF质量通过；未部署生产识别。见[验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md)及[操作说明](reference/RML2018A_FULL_RF_CAMPAIGN.md)。
- [ ] RadioML2018A全量RF质量与执行：全量同轴采集、停止/恢复及2555904条三组识别已完成，见[全量结果](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-14全量1024识别完成与结果)；高源SNR校正改善、负源SNR退化及Z30回退尚待解释，不能据工程执行完成宣称全条件质量、空口部署或独立准入通过。原433MHz的72条先导不计入此次全库成绩。
- [x] 2026-09-11频段与质量记录代码：campaign v2固定2455MHz，NX发射参数和AGX readback同源，原始Z保留为source_snr_db；新增rx_sinr_db/未测原因及分组语义，拒绝以原标签/相关度冒充总SINR，旧v1计划/结果不混用，历史导频可重建。15项无硬件测试和清理完成；仅源码，无新RF/推理/生产部署。见[验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-11回到24ghz与sinr记录合同)。
- [x] 条件有效SINR实现及有限实收：固定两半窗交叉拟合新增误差，结合源Z标称功率分配；记录方法/带宽/有效性和2dB分箱，采集无需模型即可输出。23项测试、240次已知分量仿真通过；发现并修正2455MHz仍用433MHz绝对CFO范围的问题。最终新计划48条中4条估计、20条invalid、24条未同步，不能当成可靠全库质量；恢复/清理完成，无模型/生产部署。见[验证](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-11条件有效sinr实现与2455mhz有限验证)。
- [ ] 独立物理SINR校验：用干净参考/可控干扰验证源功率分配、信道与带宽假设及实际误差；当前非空rx_sinr_db为含链路失真的条件估计，measured_rows仍为0，不完成校准级SINR实测。
- [x] 2455MHz链路失败排查：复核4份既有IQ/日志、固定对齐与FIR；停发背景RX50触发削顶保护，RX40三次均见相对安静时段高33–41dB的突发。支持独立于本次RadioML发射的背景突发污染，不确认Wi-Fi身份或排除接收内部因素；固定FIR改善有限，不能据拟合失败宣称硬件增益变化。新增TX/模型0，恢复及清理通过。见[排查](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-11停发背景与实收失败排查)。
- [x] 2.4GHz离散频点比较与独立复测：8频点×3轮发现、固定2440MHz对2455MHz的6次交替确认，28次有效/2次削顶；2440MHz未通过预设安静条件，三对中两对更差，不改实验默认频道。3项选频测试、全部有效IQ统计重算、恢复及清理通过；无TX/模型，不能称全频段或长期占用测量。见[选频记录](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-11八频点背景比较与候选复测)。
- [x] 用户授权增益有限对照：核对外部B210驱动TX范围0–89.8dB，计划支持TX70/80与RX40/50，新计划默认70/40；2455MHz同48源行各发两阶段，70/40两批未同步，80/40两批同步、42条条件SINR估计/6条invalid，有效范围−4.52～+0.22dB。28项测试、4份IQ/质量重算、射频恢复及精确清理通过，无模型推理或生产部署；不完成全量质量。见[增益对照](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-11发射增益与接收增益有限对照)。
- [x] TX80/RX40既有48条固定滤波及识别对照：源保真48/48通过、相关度约0.59→0.86，但冻结模型原始源/滤波源48/48，未滤波实收41/48、滤波实收3/48；38条回退、0条纠正，不启用payload FIR。4项测试、192输入哈希与全部预测复核、Spark恢复及清理完成；无新RF/训练/生产部署，不完成全量质量。见[对照记录](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-11固定滤波与48条工程识别对照)。
- [x] 滤波误判有限归因诊断：同48条分别执行固定十组相位/CFO/偏置/尺度及八组分量对照；简单校正仅3–5/48，幅度误差/相位误差单独保留为32/48、26/48，不能提供可部署修复或确定物理来源。8项测试、864输入哈希/计数复核、基线top-1复现、Spark恢复及清理通过；新增RF0、训练0、生产变更0。见[诊断](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-11滤波误判的有限归因诊断)。
- [x] 24类高源SNR有限先导：显式批次列表支持1–32个离散批次；2455MHz TX80/RX40未滤波，各类新24行、共576行Z30，24批全同步。源543/576、实收207/576；条件SINR411估计/165invalid，全部保留分母。37项测试、1152输入哈希/质量重算、设备与Spark恢复及精确清理通过；不完成全量质量、生产部署或独立准入。见[先导](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-1124类高源snr有限先导)。
- [x] 2.4GHz历史方法与当前433MHz离线对照：核对旧原始/FIR实收30/72与56/72，确认当前仅同步滤波、模型payload未滤波；原72条保留IQ经旧175kHz FIR后相关约0.18→0.75，72条源保真条件通过。无新增RF/推理，滤波后识别尚未验证，不完成上项。见[复核](validation/RML2018A_FULL_RF_CAMPAIGN_2026-09-10.md#2026-09-10按用户要求复查24ghz历史识别方法)。
- [x] 全仓文档导航整理：172份Markdown可从入口到达，参考/验证完整索引及131份实验附件分类齐全，组件文档回链与历史状态链接化完成；原正文、封存附件和外部数据保留，无RF/模型/部署操作。见[全仓整理](validation/DOCS_CONSOLIDATION_2026-09-07.md#2026-09-10全仓文档与实验附件导航整理)。
- [x] 2026-09-10 用户选择已记录：后续实验默认433.920MHz、当前433MHz天线；规则、推进顺序和文档入口已同步，近期RF验证/证据归入专门索引，旧失败和封存字节保持。仅文档整理，无RF或生产配置部署。见[整理记录](validation/DOCS_CONSOLIDATION_2026-09-07.md#2026-09-10实验频段选择与射频记录整理)。
- [x] 普通对话去重展示：匹配 hold 回复时重复计划及对应执行器提示收进诊断，原记录/接收计划/批准/错误保留；前端回归、实际浏览器、安装及精确清理完成。见 [展示修复](validation/HOLD_REPLY_DISPLAY_VALIDATION_2026-09-08.md)。
- [x] 首次扫描混合选参与频率显示：步进/停留/增益逐项手填或 AI 补齐，双层校验、迟到隔离与具体预算预览；实际本地模型/浏览器、Web 安装及已有制品回滚、用户数据保护和精确清理通过。见 [选参验收](validation/SURVEY_PARAMETER_ASSIST_VALIDATION_2026-09-08.md)。选参本身不执行 RF，不开放识别。
- [x] 本地 Planner 恢复：恢复完整 Spark 本地选择并重新连接原会话，共享有界脱敏错误反馈；原生单次/交互及实际网页 hold 验证通过，72 项回归和精确清理完成。按用户要求不新增备份，在线网关工作暂缓。见 [本地修复](validation/LOCAL_PLANNER_REPAIR_VALIDATION_2026-09-08.md)。
- [x] 日常 RX 使用验收：新版实际 Web/Planner/P201 完成 433 MHz、2.4 GHz、5.8 GHz 有界接收、曲线/频点表、接收中停止、健康监控共存、重启保留和确认删除；修复自定义扫描与主动取消状态文案，最终安装/回滚及精确清理通过。见 [日常 RX 验收](validation/DAILY_RX_USE_VALIDATION_2026-09-08.md)。只保留未标注功率摘要，不完成 A1/O1b。
- [x] 非模型运维部署：已安装 Web/Planner 专用限额日志、30 秒只读健康和本地去重告警；实际 Planner health 兼容、停服/恢复、日志轮转、配置回滚、用户结果保留及精确清理通过。见 [运维部署](validation/OPERATIONS_RX_DEPLOYMENT_VALIDATION_2026-09-08.md)。不覆盖未部署的识别 Worker/GPU gateway，不完成 A1/O1b。
- [x] Web 界面重构：固定导航、可读对话与频谱、折叠配置/诊断、全局优先停止、完整确认/错误反馈和响应式交互已实现；原生及浏览器验证、实际部署/回滚、用户会话/结果保留和精确清理完成。见 [UI 验收](validation/WEB_UI_REDESIGN_VALIDATION_2026-09-07.md)。不部署日志/监控，不开放识别。
- [x] Web 后台升级：已核对旧制品与源码差异，补齐旧进程输出隔离，验收重启不重扫、request/session/generation 隔离、停止/断连完整恢复、浏览器结果查看/删除、原用户结果保留及实际升级/回滚；精确清理完成。见 [Web 验收](validation/WEB_RECOVERY_UPGRADE_VALIDATION_2026-09-07.md)。不开放识别，不部署日志/监控配置。
- [x] P201 RX1 有界采集/传输、停止、恢复、固定输入身份及长期重连验证完成（第3章）。
- [x] AGX 扫频/精查、结果存储和 RX 语料基础、split 隔离完成（第1/4/5章）。
- [x] RF-v1 预处理、用户训练 epoch-10 checkpoint 的 validation 和 FP16 选择完成。
- [x] 共享 RMS/四窗/full-logit/mean-logit runtime、golden 和有限实收故障清理完成。
- [x] S1：准入/health/人工批准源码、测试及隔离真实 Worker 验证完成；统一 CLI 已含 Controller 侧代码，生产 Worker/准入配置未替换，能力仍为 false。
- [x] S2：统一完整结果与 Planner 紧凑 observation、四状态/校准身份、RF-v1 batch 严格转换和真实报告 replay 完成；生产阈值未冻结，能力仍为 false。
- [x] S3：Worker 单等待位、整批 deadline、取消确认、强杀/重启清理和指标完成源码及有限真实候选验证；未部署，能力仍为 false。
- [x] S4：共享 GPU 调度与持续资源源码/隔离验收；GPU 温度缺失按用户明确豁免保持未测，生产部署另属 A1。
  - [x] S4a：共享推理租约、串行执行、取消/故障释放和隔离实机正确性完成；未部署，不代表 S4b 完成。
  - [x] S4b：96 轮/1200 秒串行候选负载下的 nvmap/PSS/队列/时延与 CPU/SoC/Tj 稳定性验证，256 MiB CPU prompt-cache 上限及精确清理完成。GPU 温度 240/240 缺失依用户明确决定不阻塞；不宣称独立 GPU 温度已验证。见 [S4b 验证](validation/GPU_RESOURCE_S4B_VALIDATION_2026-09-06.md)。
- [x] S5：Runner 工程识别执行、人工批准、预算/audit、联合 stop、自动 Spark 回灌及固定回归完成源码与有限实机验证；精确清理完成，生产能力仍为 false。见 [S5 验证](validation/RUNNER_RECOGNITION_S5_VALIDATION_2026-09-06.md)。
- [x] S6：用户识别结果源码及隔离验收交付（S6a/S6b）；Web/归档界面已随非模型单元安装，生产识别准入另属 A1。
  - [x] S6a：完整结果保存/恢复/查看/删除完成源码及隔离 replay/演示验证；复用应用 SQLite，不额外保留 IQ，归档接口已随 Web 安装。
  - [x] S6b：S5 后真实闭环、浏览器结果和 Spark 紧凑摘要验收及精确清理完成，Web 已安装但工程识别未配置。见 [S6b 验证](validation/WEB_RECOGNITION_S6B_VALIDATION_2026-09-06.md)。
- [ ] V1：RF-v1 独立数据证据准备。
  - [x] V1a：版本化派生、独立证据接入、采样/覆盖/校准与验收分组规范完成；隔离 HTTP/浏览器/删除及失败清理验证通过，Web 接口已安装，独立证据仍须 V1b。
  - [ ] V1b：获得并审核足够的独立 known-RF/OOD 标签；实际覆盖达到预注册条件。
- [ ] V2：根据 validation 和独立证据冻结校准/拒识，并完成独立验收。
- [ ] V3：标签空间与模型准入。
  - [x] V3a：按用户要求以 4090 原始标签表为准，核对源码、Adapter 的 Y.argmax 语义及报告 raw_label_id，24/24 与截图一致，冻结 server-v1 及来源哈希。映射选择/来源核对完成，生产 name_evidence 接入仍属 A1。
    - [x] 按用户 2026-09-08 截图冻结 operator-v1 的 0–23 映射，接入名称读取默认值并保留旧实验哈希；无模型/数据集操作。见 [映射记录](validation/RML2018A_LABEL_MAPPING_VALIDATION_2026-09-08.md)。
  - [ ] V3b：规则冻结后执行一次 locked test；不得用 test 反复调参。
- [ ] A1：production profile、可回滚部署、RX-only 矩阵验收和真实正向 capability。
- [ ] O1：持续运行和运维。
  - [x] O1a：固定 seed 的故障/fuzz 矩阵、8 MiB×4 audit 轮转、只读健康/本地去重告警、发布校验与私有升级/回滚演练完成源码、隔离验证及清理。原隔离验证见 [O1a 验证](validation/OPERATIONS_O1A_VALIDATION_2026-09-06.md)。
  - [ ] O1b：24 小时完整闭环 soak；不替代人工批准策略或自动触发决策。

真实候选继续 `recognizer_available=false`。软件实现、隔离验证、安装部署和
科学准入分别记账；小项完成不能使仍缺其余条件的父项被勾选。

## 1. Agent/Harness and operator interface

2026-09-07 [Web 升级](validation/WEB_RECOVERY_UPGRADE_VALIDATION_2026-09-07.md)已安装当前 Web
源码及实例隔离修正。下列 S6/V1a 原验证中的“未部署”保留历史时点；现有归档/
语料接口随 Web 制品安装，生产识别能力和已准入结果验收仍未完成。

- [x] Select Jetson AGX Orin as the primary Agent, acquisition,
      aggregation and CUDA-inference host, with clone root fixed at
      `/home/jetson/sdrharness`.
- [x] Add AGX-specific non-secret configuration, systemd templates, native build
      entry and checkout verifier without duplicating the Controller, Planner or
      Web implementations.
- [x] Preserve the Raspberry Pi release and validation evidence as the rollback
      baseline during migration.
- [x] Clone and build the repository on the real AGX and record its runtime,
      toolchain, artifact-hash and loopback-service baseline.
- [x] Verify one read-only SDRD observation from the AGX; after an explicitly
      authorized persistent `sdrd` recovery with duplicate-instance gates, the
      Controller reported online and healthy on 2026-09-01 without acquisition
      or radio/FPGA writes.
- [x] Cut SDR acquisition ownership over to AGX after proving the existing
      Spectrum collector was stopped, disabling its Web, predictor and
      reboot-resume user units, recovering exactly one retained receive-only
      `sdrd`, and verifying the deployed AGX Harness is the only enabled RX
      control path; see
      [`SDR_AGENT_AGX_RX_OWNERSHIP_CUTOVER_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_AGX_RX_OWNERSHIP_CUTOVER_VALIDATION_2026-09-03.md).

- [x] Keep Qwen inference, tokenization, and KV cache on the 4090 llama.cpp
      module for the original Pi deployment baseline; it was later stopped when
      the local AGX Spark deployment below became current.
- [x] Run a bounded `pi-agent-core` Planner Worker on the Raspberry Pi.
- [x] Use a deterministic Rust Controller as the authority for state, policy,
      capability validation, limits, approval classification, and stale-session
      rejection.
- [x] Restrict the Planner Worker to one structured `submit_plan` tool with no
      shell, filesystem, SSH, IIO, FPGA-register, or SDR authority.
- [x] Correlate proposals using request ID and Controller session generation.
- [x] Connect the Planner Worker to the existing Qwen endpoint on the 4090.
- [x] Store the Qwen token outside the repository and pass it through systemd
      credentials.
- [x] Deploy Spark-X2.5-4B BF16 outside the repository on the AGX, connect it as
      the Web-selected `spark-local` Planner, adapt its constrained JSON Schema
      response into the sole `submit_plan` tool event, and live-validate a
      greeting plus a Rust-approved real-P201 sweep with radio restoration; see
      [`SPARK_X25_AGX_INTEGRATION_VALIDATION_2026-09-02.md`](validation/SPARK_X25_AGX_INTEGRATION_VALIDATION_2026-09-02.md).
- [x] Reuse the existing AGX loopback SearXNG service as a Spark-only bounded
      host search adapter with at most two searches, eight sources, a 15-second
      timeout, a 512 KiB response limit, no redirects or arbitrary result fetch,
      untrusted-evidence prompting, Web-visible source events and unchanged
      Rust/SDR authority; live model and browser validation is recorded in
      [`SPARK_X25_WEB_SEARCH_VALIDATION_2026-09-02.md`](validation/SPARK_X25_WEB_SEARCH_VALIDATION_2026-09-02.md).
- [x] Run the Planner Worker as an enabled systemd module with memory, CPU, task,
      filesystem, privilege, and address-family restrictions.
- [x] Preserve the stateless one-shot `planner.sock` interface as a fail-closed
      fallback.
- [x] Provide an interactive `session.sock` using a persistent Pi Agent instance.
- [x] Reuse Pi Agent's public prompt, steer, follow-up, abort, queue, and event
      interfaces instead of copying its Agent loop.
- [x] Serialize one-shot and interactive inference through one global run lease.
- [x] Bound the interactive steering/follow-up queue to four messages.
- [x] Provide the static ARM64 `sdr-agent` terminal command on the Pi.
- [x] Support both interactive `sdr-agent` and one-shot `sdr-agent "..."` usage.
- [x] Provide `/status`, `/history`, `/approve`, `/reject`, `/mode manual`,
      `/auto start`, `/pause`, `/resume`, `/stop`, `/help`, and `/quit`
      terminal commands, with operator-facing state and plan output rendered as
      natural Chinese instead of raw internal fields.
- [x] Provide a Rust web console, explicitly deployed on the trusted LAN at
      `0.0.0.0:8787` because Tailscale is absent, that exposes the live terminal,
      model messages, validated plans, execution/sweep output and system errors
      without duplicating Controller policy or SDR access.
- [x] Show every web shortcut command and its Controller response in the same
      terminal stream, including stop, approve, reject, pause, resume and
      status.
- [x] Keep at most two web conversations, permit only one active interactive
      owner, and evict the least-recently-used inactive conversation before a
      third is created.
- [x] Persist root-only bounded web history and automatically compress long or
      switched conversations into a 6 KiB carry-forward context while retaining
      the 48 most recent terminal events.
- [x] Advance session generation and clear stale pending state on pause, resume,
      and stop.
- [x] Revalidate every interactive `plan_proposed` event in Rust before showing
      it as a validated plan.
- [x] Add AGX Web-managed, backend-neutral Pi AI upstream configuration for
      OpenAI-compatible Completions and Responses, with a `0600` untracked
      secret file, key redaction, strict schema/URL/permission validation and
      per-new-session reload.
- [x] Let the AGX Web Console query an authenticated OpenAI-compatible
      `{Base URL}/models` inventory and select a returned Model ID, with manual
      fallback, no key echo or process-argument exposure, one-query concurrency,
      no redirects, an 8-second timeout, and 512 KiB/512-model bounds.
- [x] Let the operator configure an 8,192–1,000,000-token upstream context
      window, adopt common bounded context metadata returned by `/models`, and
      automatically compact obsolete planning turns at a configurable 50–95%
      threshold (default 90%) while retaining the newest complete Rust-validated
      PlanningContext as authoritative.
- [x] Provide a persistent navigation settings entry that opens a separate settings
      page for model/API, context, compaction and initial-survey configuration;
      keep edits local until explicit save, warn on unsaved navigation, write
      the private file atomically as mode `0600`, and live-validate the deployed
      browser form and upstream settings readback.
- [x] Implement and unit-test AGX result persistence with SQLite summary/index
      rows, one optional per-scan `ci16_le` SigMF dataset pair, a manually saved
      raw-IQ switch, strict capture-root validation, and an operator delete path
      that removes only the indexed result and its managed files.
- [x] Implement the current-session result shortcut and persistent archive navigation to a dedicated
      aggregate-results view with saved history, a real-data SVG power trace,
      noise baseline, candidate markers/table, scan metrics and raw-IQ state;
      keep charts out of the terminal workspace and cover the backing result
      store with unit tests.
- [x] Surface the actual PlanningContext, real upstream reasoning deltas and
      Rust validation basis in the Web session state; keep reasoning collapsed
      by default, omit the whole reasoning control when no text was supplied,
      and never expose the fixed system prompt.
- [x] Deploy and live-validate the AGX result database, aggregate-results page,
      optional SigMF storage and manual deletion with a real P201 scan; see
      [`SDR_AGENT_AGX_INLINE_RESULTS_VALIDATION_2026-09-01.md`](validation/SDR_AGENT_AGX_INLINE_RESULTS_VALIDATION_2026-09-01.md).
- [x] Track automatic compaction separately from session-generation changes and
      persist one-shot initial-survey state so switching or restarting a
      completed conversation neither increments `compaction_count` nor repeats
      the survey.
- [x] Keep Planner/session sockets restricted to exact dedicated runtime
      directories, use canonical `/run/sdr-agent` on AGX, and retain exact
      `/run/sdrharness` compatibility for migration from the first installed
      template; reject nested and traversal paths.
- [x] Deploy and live-test the interactive terminal while retaining the prior
      Pi release for rollback.
- [x] Configure the local `jetson` account for passwordless sudo through a
      root-owned mode-`0440` `/etc/sudoers.d/90-jetson-nopasswd` rule, validate
      it with `visudo`, and prove non-interactive `sudo -n` succeeds.
- [x] Support concurrent terminal input while local Spark or another upstream
      model is streaming, with a four-line terminal queue, Pi-style steer and
      follow-up, priority `/stop`, asynchronous acknowledgement correlation,
      and fail-closed stale-generation handling; see
      [`SDR_AGENT_TERMINAL_STREAMING_INPUT_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_TERMINAL_STREAMING_INPUT_VALIDATION_2026-09-03.md).
- [x] Persist and resume bounded interactive terminal history after normal or
      unexpected exit and Planner restart, using atomic owner-only state,
      hard file/message/context/age limits, and conversation-only restoration
      that excludes approvals, plans, actions, queues and old generations; see
      [`SDR_AGENT_TERMINAL_SESSION_RESUME_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_TERMINAL_SESSION_RESUME_VALIDATION_2026-09-03.md).
- [x] Enforce the explicitly selected single-trusted-operator model: retain at
      most two bounded Web conversation histories for that same operator, run
      only one active interactive Controller, reject a second `session.sock`
      connection, reject commands against an inactive conversation, and keep
      the existing global inference and SDR ownership gates. Multi-user
      identity, authorization and concurrent-control isolation are not project
      requirements; see
      [`SDR_AGENT_SINGLE_OPERATOR_SESSION_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_SINGLE_OPERATOR_SESSION_VALIDATION_2026-09-03.md).
- [x] Live-test OpenCode Go `deepseek-v4-flash` through the deployed Web,
      unchanged Controller interface and real `0600` subscription credential:
      a new conversation produced a Rust-validated health-only `hold` from the
      live SDR observation, `/stop` aborted an active upstream run, and the
      authenticated `/models` query returned 33 model IDs without exposing the
      key.
- [x] Keep the saved production Planner selection on local Spark-X2.5-4B BF16
      while retaining the Web-managed OpenAI-compatible Completions/Responses
      seam for an explicit operator selection on a new conversation. Do not add
      automatic cloud failover; the provider-independent Rust policy and RX-only
      authority remain unchanged. The mode-`0600` selection, loopback endpoint
      and active/enabled service were reverified on 2026-09-04; see
      [`AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md`](validation/AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md).
- [ ] Extend the Web and terminal receive-only observation views to render
      classified/rejected/unavailable/error, numeric label identity, trusted or
      provisional name, calibrated confidence/rejection reason, source,
      model/profile identity, quality and timing without exposing IQ paths or
      tensors.
  - [x] S6a archive views: Web result-type selection and local terminal client
        show provenance, four inert demo states, candidate replay/unavailable,
        numeric/name trust, confidence calibration, source/model identity,
        quality/timing and manual deletion. Native browser/CLI and cleanup passed;
        see [`RECOGNITION_ARCHIVE_S6A_VALIDATION_2026-09-06.md`](validation/RECOGNITION_ARCHIVE_S6A_VALIDATION_2026-09-06.md).
  - [x] S5: native live receive-loop terminal observation, joined execution,
        engineering archive and automatic compact Spark feedback passed finite
        real validation and cleanup; installed services remain unchanged.
  - [x] S6b: actual browser approval/RX/Worker/Spark loop, exact result links,
        recovery without replay and manual delete passed; real unavailable/error
        and explicitly synthetic classified/rejected remain distinguished. See
        [S6b validation](validation/WEB_RECOGNITION_S6B_VALIDATION_2026-09-06.md).
  - [ ] A1: deploy and validate the admitted production result views.
- [x] Persist full bounded recognition records in the application result store
      and add a visible per-record manual-delete path without retaining IQ by
      default. S6a reuses the existing SQLite file, revalidates full S2 records,
      bounds pagination, rejects conflicting/forged imports, and verifies restart
      restoration and per-record deletion without touching capture/corpus/IQ.
      Source and isolated native acceptance only; installed services unchanged.
      See [`RECOGNITION_ARCHIVE_S6A_VALIDATION_2026-09-06.md`](validation/RECOGNITION_ARCHIVE_S6A_VALIDATION_2026-09-06.md).
- [x] S5 isolated live Spark validation: only the compact real unavailable
      observation enters one automatic feedback turn, explaining missing admission
      and producing a Rust-validated hold without claiming an unlabeled class.
      Explicit synthetic error/classified/rejected regression remains nonproduction.
      See [S5 validation](validation/RUNNER_RECOGNITION_S5_VALIDATION_2026-09-06.md).

Evidence:

- [`AGX_SDRHARNESS_MIGRATION.md`](../jetson-agx/sdrharness/README.md)
- [`AGX_FRAMEWORK_VALIDATION_2026-09-01.md`](validation/AGX_FRAMEWORK_VALIDATION_2026-09-01.md)
- [`SDR_AGENT_RUNTIME_DESIGN.md`](reference/SDR_AGENT_RUNTIME_DESIGN.md)
- [`SDR_AGENT_TERMINAL_DEPLOYMENT_2026-08-31.md`](validation/PI_BASELINE_HISTORY.md#pi-3)
- [`SDR_AGENT_EXECUTOR_DEPLOYMENT_2026-08-31.md`](validation/PI_BASELINE_HISTORY.md#pi-5)
- [`SDR_AGENT_WEB_CONSOLE_DEPLOYMENT_2026-09-01.md`](validation/PI_BASELINE_HISTORY.md#pi-7)
- [`SDR_AGENT_INITIAL_SURVEY_SETTINGS_VALIDATION_2026-09-01.md`](validation/SDR_AGENT_INITIAL_SURVEY_SETTINGS_VALIDATION_2026-09-01.md)
- [`SDR_AGENT_AUTOMATIC_SURVEY_VALIDATION_2026-09-01.md`](validation/SDR_AGENT_AUTOMATIC_SURVEY_VALIDATION_2026-09-01.md)
- [`SDR_AGENT_CANDIDATE_INSPECTION_VALIDATION_2026-09-01.md`](validation/SDR_AGENT_CANDIDATE_INSPECTION_VALIDATION_2026-09-01.md)
- [`SDR_AGENT_AGX_RX_OWNERSHIP_CUTOVER_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_AGX_RX_OWNERSHIP_CUTOVER_VALIDATION_2026-09-03.md)
- [`SDR_AGENT_TERMINAL_STREAMING_INPUT_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_TERMINAL_STREAMING_INPUT_VALIDATION_2026-09-03.md)
- [`SDR_AGENT_TERMINAL_SESSION_RESUME_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_TERMINAL_SESSION_RESUME_VALIDATION_2026-09-03.md)
- [`SDR_AGENT_SINGLE_OPERATOR_SESSION_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_SINGLE_OPERATOR_SESSION_VALIDATION_2026-09-03.md)
- [`CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md)

## 2. Receive-only planning policy and autonomous loop

- [x] Define structured actions for hold, band survey, candidate inspection,
      bounded IQ capture, local recognition, and session stop.
- [x] Reject plans that contradict live capability, state, frequency, bandwidth,
      dwell, sample, byte, candidate, or observation-age constraints.
- [x] Mark bounded IQ requests above the automatic threshold as requiring human
      approval.
- [x] Record terminal approval and rejection decisions without claiming an
      action executed.
- [x] Implement the Rust `SdrActionExecutor` interface, replay Adapter, and
      production SDRD/1 Adapter for bounded IQ execution.
- [x] Execute a validated, operator-approved SDR action and return a correlated
      observation.
- [x] Make `/stop` cancel active hardware execution directly without waiting for
      Qwen.
- [x] Implement and live-validate the bounded
      observe-plan-validate-approve-execute-observe Runner for the production
      bounded-IQ action; unsupported action kinds remain explicitly plan-only.
- [x] Add a fail-closed interactive automatic-cruise controller for production
      bounded-IQ capture and software-summary `survey_band`, with
      operator-selectable step/time budgets
      (defaults 8 steps/120 seconds; hard limits 128 steps/1,800 seconds), a
      cumulative-IQ budget, automatic execution only below the existing approval
      threshold, separate five-attempt SDR/upstream-next-step retry limits with
      a 10-second interval, and Pi Agent abort plus direct hardware cancel on
      operator stop. Isolated end-to-end fake Planner/SDRD tests covered both
      retry exhaustions and stop during an active upstream run; the AGX
      Web/terminal deployment was live-validated.
- [x] Remove the project-level fixed 64 MiB cruise ceiling while retaining a
      positive finite per-run byte budget: omitted `--mib` now derives the
      budget from step count times the PlanningContext per-action IQ limit, and
      an explicit positive MiB value is checked for integer overflow.
- [x] Supply the Planner system prompt with explicit semantics for the current
      SDR health and candidate-signal observation, total tunable frequency band,
      per-survey maximum span, per-action bandwidth, dwell, sample, byte,
      approval and freshness bounds; missing current data requires `hold` and
      never permits invented signals or capabilities.
- [x] Deploy and live-validate the revised Planner contract that supplies the
      complete bounded measured sweep as compact point pairs, states the tested
      P201/AGX fixed profile and limitations in the system prompt, and requires
      model-selected survey/inspection sample rate and RF bandwidth before Rust
      validation and SDRD execution; see
      [`P201_AGX_RX_PROFILE_VALIDATION_2026-09-02.md`](validation/P201_AGX_RX_PROFILE_VALIDATION_2026-09-02.md).
- [x] Complete automatic `survey_band` execution and feed its compact CPU sweep
      observation into the next Planner turn. The bounded AGX CPU path was
      live-validated receive-only with the real P201 SDR and OpenCode Go model,
      including fixed gain, byte/step accounting, candidate feedback, zero
      clipping and verified radio restoration; see
      [`SDR_AGENT_AUTOMATIC_SURVEY_VALIDATION_2026-09-01.md`](validation/SDR_AGENT_AUTOMATIC_SURVEY_VALIDATION_2026-09-01.md).
- [x] Execute a current `inspect_candidate` proposal through the fixed-gain,
      no-file software power-summary path in both step-approval and automatic
      dispatch modes. The real SDR/OpenCode Go manual-approval path was
      live-validated with candidate feedback, zero clipping and restoration;
      see
      [`SDR_AGENT_CANDIDATE_INSPECTION_VALIDATION_2026-09-01.md`](validation/SDR_AGENT_CANDIDATE_INSPECTION_VALIDATION_2026-09-01.md).
- [x] Render every Rust-validated proposal as a visible Agent reply, use
      language-matched `hold.reason` replies for non-hardware conversation,
      expose the manual approval gate for single surveys, and accept the
      declared SDRD `software_summary` capability in bounded-IQ execution. The
      real Web/OpenCode Go/P201 paths and exact delivery cleanup passed; see
      [`SDR_AGENT_REPLY_AND_CAPTURE_COMPAT_VALIDATION_2026-09-01.md`](validation/SDR_AGENT_REPLY_AND_CAPTURE_COMPAT_VALIDATION_2026-09-01.md).
- [x] Persist typed candidate observations independently of terminal history,
      restore them through a validated mode-`0600` runtime PlanningContext after
      Web restart, and bound textual carry-forward to one 1,024-byte terminal
      command.
- [x] Extend and deploy the stateless one-shot Runner to execute real
      `survey_band` and `inspect_candidate` actions through the existing AGX
      software `SweepEngine`, return the aggregate plus a fresh Planner
      observation, re-observe restored SDR health, and append the correlated
      proposal/validation/authorization/result JSONL audit chain; see
      [`SDR_AGENT_ONESHOT_SWEEP_INSPECTION_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_ONESHOT_SWEEP_INSPECTION_VALIDATION_2026-09-03.md).
- [x] Persist a root-only JSONL audit record joining operator input,
      model/provider, raw proposal, Rust validation, approval, execution and the
      resulting observation, including fail-closed planning attempts.
- [x] Validate reconnect, cancellation, stale-result, timeout, and partial-action
      recovery for the complete loop, including real Spark/P201 Planner and IIO
      timeouts, direct cancellation after a partial sweep, SDRD loss/recovery,
      model abort/generation invalidation, stale-result tests and daemon survival
      after a client transport timeout; see
      [`SDR_AGENT_COMPLETE_LOOP_FAULT_RECOVERY_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_COMPLETE_LOOP_FAULT_RECOVERY_VALIDATION_2026-09-03.md).
- [x] Implement S1 capability sourcing in plain Controller, one-shot Runner,
      raw execute and terminal prompt/queue/proposal/feedback/approval paths:
      replace request/template self-assertion with a bounded current Worker and
      local admission-receipt probe; fail closed on missing/stale/mismatched
      evidence, Worker restart or receipt changes in the same generation.
      Source tests and isolated real epoch-10 Worker health validation passed;
      the candidate stayed unavailable and all feature processes/data/builds
      were cleaned. See
      [`RECOGNIZER_ADMISSION_S1_VALIDATION_2026-09-06.md`](validation/RECOGNIZER_ADMISSION_S1_VALIDATION_2026-09-06.md).
- [x] Require operator approval for `RunLocalRecognition`; verify that step
      mode holds the plan, automatic cruise stops at the approval gate,
      one-shot automatic authorization fails before unsupported dispatch, and
      terminal approval rechecks current capability/generation. Positive tests
      use synthetic admitted evidence only; no production recognition executed.
- [ ] Deploy these Controller/terminal changes as part of the admitted release
      and live-validate the first production recognition profile behind manual
      approval in both step and cruise. Installed services were not replaced
      by the isolated S1 validation; this remains the A1 delivery gate.
- [ ] Execute the existing `run_local_recognition { candidate_id }` action in
      both one-shot and interactive Runners through the admitted Chapter 4
      profile and production Recognition Worker instead of returning
      `planned_only`; preserve approval, exact byte/deadline budgets, restored
      SDR health and the correlated audit chain.
  - [x] S5 explicit engineering executor now performs fresh RX and supervised
        four-window recognition in one-shot/raw-execute/terminal paths, preserving
        manual approval, original cruise budgets, audit and restored health;
        source/finite native acceptance and exact cleanup passed.
  - [ ] A1 admitted production profile, deployment and positive capability.
- [ ] Feed each classified/rejected/unavailable/error recognition observation
      into the next local Spark-X2.5-4B turn, and validate that Rust permits only
      a fresh receive-only next step: re-inspect, bounded re-capture/re-recognize,
      move to another measured candidate, survey, hold, or stop.
  - [x] S5 source integration, automatic real unavailable feedback and explicitly
        synthetic other-state Spark regression passed; no IQ/tensors/full logits
        enter Planner. Archived observations are not re-dated or reused across generations.
  - [x] S6b isolated browser loop with real unavailable/error and safe Spark hold;
        positive decisions are explicit synthetic display fixtures only.
  - [ ] A1 admitted real classified/rejected UI and deployed-loop acceptance.
- [x] Extend the priority `/stop` path to cancel the active recognition request
      as well as the already-supported Planner and SDR work, then discard every
      late Worker result whose request ID or session generation is stale and
      release the shared Spark/Mamba inference gate before later work. S5 finite
      actual RX and blocked-Worker cancellation passed; 34 lease events had no
      overlap or remaining owner. Installed services unchanged.
- [x] S5 fixed receive-only Planner regression: six-action policy/limits/status/
      stop-race tests and eight actual Spark cases passed, with every accepted
      proposal passing Rust policy. Recognition unavailable correctly yields hold;
      classified/rejected inputs are explicitly synthetic. This replaces the old
      4/5 smoke as current bounded regression evidence, not as production admission.
      See [S5 validation](validation/RUNNER_RECOGNITION_S5_VALIDATION_2026-09-06.md).

Evidence:

- [`SDR_AGENT_ONESHOT_SWEEP_INSPECTION_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_ONESHOT_SWEEP_INSPECTION_VALIDATION_2026-09-03.md)
- [`SDR_AGENT_COMPLETE_LOOP_FAULT_RECOVERY_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_COMPLETE_LOOP_FAULT_RECOVERY_VALIDATION_2026-09-03.md)
- [`CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md)

## 3. P201 Linux/IIO bounded RX control plane (`sdrd`)

- [x] Record the SDR Linux, IIO and network baseline.
- [x] Implement the C `sdrd` configuration parser, framed SDRD/1 protocol,
      request correlation, health reporting, and capability reporting.
- [x] Implement a read-only shadow mode that rejects all mutating commands.
- [x] Cross-build and temporarily validate shadow `sdrd` on the real SDR without
      changing IIO or radio state.
- [x] Implement the Rust `SdrdAdapter` for read-only shadow observation.
- [x] Define and unit-test the allowlisted SDRD/1 mutation command schema for ownership,
      retune, bounded capture, stop, restore, and execution status.
- [x] Implement the Adapter-backed connection ownership state machine and prove
      stop plus restore on explicit stop, disconnect, apply failure, and capture
      failure with a fake radio backend.
- [x] Implement and live-validate one persistent SDR-local IIO context and one
      session-owned RX buffer in the C Adapter.
- [x] Save and restore LO, sample rate, RF bandwidth, gain mode, and enabled
      channels on success, error, cancellation, and disconnect.
- [x] Live-validate the same state restoration path after an IIO timeout,
      including exact manual-gain recovery with the production IIO Adapter;
      see
      [`SDR_AGENT_EXECUTION_METADATA_TIMEOUT_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_EXECUTION_METADATA_TIMEOUT_VALIDATION_2026-09-03.md).
- [x] Live-validate restoration of LO, sample rate, RF bandwidth, gain mode, and
      scan-channel mask after success and an apply/readback error.
- [x] Implement and live-validate bounded retune, explicit settle delay, and
      quantized LO readback tolerance in `sdrd`.
- [x] Implement and live-validate bounded complex-int16 IQ capture in `sdrd`.
- [x] Implement and unit-test bounded SDRD/1 inline complex-int16 IQ transport
      for AGX aggregation, including exact shape validation and immediate
      SDR-local temporary-file cleanup after successful transfer.
- [x] Remove the retired FPGA/MMIO Adapter, configuration, source and test paths
      from `sdrd`; keep only constant false/zero SDRD/1 fields for deployed-client
      compatibility and return `retired_command` for `CAPTURE_SUMMARY`.
- [x] Deploy and live-validate the inline IQ transport on P201 without changing
      persistent radio state; see
      [`SDR_AGENT_AGX_INLINE_RESULTS_VALIDATION_2026-09-01.md`](validation/SDR_AGENT_AGX_INLINE_RESULTS_VALIDATION_2026-09-01.md).
- [x] Implement and live-validate bounded no-file `CAPTURE_POWER` summaries and
      fixed manual-gain profiles with per-point numeric gain readback, clipping
      metadata, cancellation, and saved AGC/gain restoration.
- [x] Implement and live-validate direct in-flight cancel in `sdrd`.
- [x] Implement and live-validate explicit post-action stop, buffer teardown,
      and state restoration.
- [x] Add Adapter-produced sequence, overflow, dropped-sample, timeout, health,
      request and session-generation metadata to all execution results and
      preserve failure metadata through AGX errors/audit; see
      [`SDR_AGENT_EXECUTION_METADATA_TIMEOUT_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_EXECUTION_METADATA_TIMEOUT_VALIDATION_2026-09-03.md).
- [x] Deploy controlled `sdrd` with a private-link listener, retained `/sd`
      release, tested stop path,
      bounded live capture and verified state restoration.
- [x] Maintain safe persistent `sdrd` startup after reboot and successful recovery
      health checks without modifying the boot image. Historical startup and
      host-key validations below remain valid; the 2026-09-07 recovery CLI
      incompatibility is resolved for the deployed recovery service:
  - [x] Deploy and live-validate the AGX recovery oneshot/timer, strict
        duplicate-instance gates, normal start, idle abnormal-exit recovery,
        concurrent-start rejection, current-boot persistence and rollback;
        see
        [`SDR_AGENT_SDRD_STARTUP_RECOVERY_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_SDRD_STARTUP_RECOVERY_VALIDATION_2026-09-03.md).
  - [x] Replace recovery's outdated general CLI dependency with the deployed
        read-only `sdr-agent-health` (subsequently consolidated unchanged into
        `sdr-agent --mode health`; see unified CLI validation below), reusing strict Controller Adapter parsing
        and requiring healthy verified RX1/capabilities for success. 11 test
        functions, already-running/timer-start/flock rejection, state restoration
        and exact cleanup pass. Preserve the original early-journal assertion
        and the same-recovery confirmation. General Controller/Planner/Web/model
        deployment is unchanged. See
        [recovery health validation](validation/P201_RECOVERY_HEALTH_VALIDATION_2026-09-07.md).
  - [x] Remove the manual host-key repin after a P201 reboot by explicitly
        authorized initialization of only the 917,504-byte vendor QSPI `mtd2`
        JFFS2 partition, persisting only the verified ECDSA key plus its minimal
        manifest, retaining a byte-exact root-only rollback image, and proving
        an unchanged global pin across a real reboot plus subsequent idle-daemon
        recovery; see
        [`SDR_AGENT_P201_PERSISTENT_HOST_KEY_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_P201_PERSISTENT_HOST_KEY_VALIDATION_2026-09-03.md).
- [x] Consolidate interactive Agent, scripted Controller and read-only recovery
      into the single installed `sdr-agent` CLI, preserving protocol/policy and
      admission gates. The old generic installed CLI failed `rx_input` parsing;
      Web already used a compatible interactive client. 125 tests, strict health,
      live RX/timeout/cancel, installed Web browser archive/delete/stop, actual
      deployment/rollback and recovery passed. Removed old active CLI entries;
      existing user results and session IDs preserved (normal 48-event restart
      compaction still applies). Seven exact temporary roots / 816,198,886 logical
      bytes cleaned; only inventoried release/rollback artifacts retained, no new
      IQ. Production recognition remains unavailable and A1 incomplete. See
      [unified CLI validation](validation/UNIFIED_CLI_VALIDATION_2026-09-07.md).
- [x] Complete a full 1,800-second long-duration reconnect and fault-recovery
      test on the real SDR, covering 100 bounded acquisitions, three
      profile-applied client disconnects, two idle-daemon timer recoveries,
      transport and IIO timeouts, direct partial-action cancellation,
      duplicate-start rejection, sequence/metadata/resource/thermal accounting
      and verified final restoration; see
      [`SDR_AGENT_SDRD_LONG_RECONNECT_FAULT_RECOVERY_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_SDRD_LONG_RECONNECT_FAULT_RECOVERY_VALIDATION_2026-09-03.md).
- [x] Make the fixed production physical input `RX1 / A_BALANCED` a probed,
      audited and fail-closed SDRD/1 identity, return it with profile/capture or
      health metadata, and verify that it is unchanged on every exit path
      without exposing a Planner-selectable port write. The Adapter now reads
      and strictly verifies `voltage0/rf_port_select=A_BALANCED`, correlates it
      with the software RX0 `voltage0,1` I/Q pair and front-panel RX1, and never
      writes the selector. It was deployed and live-validated with exact identity
      propagation, fail-closed mismatch tests, bounded RX, disconnect
      restoration and transient cleanup; see
      [`P201_RX1_INPUT_IDENTITY_VALIDATION_2026-09-04.md`](validation/P201_RX1_INPUT_IDENTITY_VALIDATION_2026-09-04.md).

Evidence:

- [`../sdr-system/docs/BASELINE_2026-08-31.md`](../sdr-system/docs/BASELINE_2026-08-31.md)
- [`../sdr-system/docs/SDRD_SHADOW_VALIDATION_2026-08-31.md`](../sdr-system/docs/SDRD_SHADOW_VALIDATION_2026-08-31.md)
- [`../sdr-system/docs/SDRD_CONTROLLED_INTERFACE_VALIDATION_2026-08-31.md`](../sdr-system/docs/SDRD_CONTROLLED_INTERFACE_VALIDATION_2026-08-31.md)
- [`../sdr-system/docs/SDRD_IIO_ADAPTER_VALIDATION_2026-08-31.md`](../sdr-system/docs/SDRD_IIO_ADAPTER_VALIDATION_2026-08-31.md)
- [`../sdr-system/docs/SDRD_PERSONAL_DEPLOYMENT_2026-09-01.md`](../sdr-system/docs/SDRD_PERSONAL_DEPLOYMENT_2026-09-01.md)
- [`SDR_AGENT_SDRD_OBSERVE_VALIDATION_2026-08-31.md`](validation/PI_BASELINE_HISTORY.md#pi-4)
- [`SDR_AGENT_CANCEL_VALIDATION_2026-09-01.md`](validation/PI_BASELINE_HISTORY.md#pi-6)
- [`SDR_AGENT_RUNNER_DEPLOYMENT_2026-09-01.md`](validation/PI_BASELINE_HISTORY.md#pi-8)
- [`SDR_AGENT_INITIAL_SURVEY_SETTINGS_VALIDATION_2026-09-01.md`](validation/SDR_AGENT_INITIAL_SURVEY_SETTINGS_VALIDATION_2026-09-01.md)
- [`SDR_AGENT_P201_HOST_KEY_PERSISTENCE_INVESTIGATION_2026-09-03.md`](validation/SDR_AGENT_P201_PERSISTENT_HOST_KEY_VALIDATION_2026-09-03.md#historical-investigation)
- [`SDR_AGENT_P201_PERSISTENT_HOST_KEY_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_P201_PERSISTENT_HOST_KEY_VALIDATION_2026-09-03.md)
- [`SDR_AGENT_SDRD_LONG_RECONNECT_FAULT_RECOVERY_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_SDRD_LONG_RECONNECT_FAULT_RECOVERY_VALIDATION_2026-09-03.md)
- [`P201_RX1_INPUT_IDENTITY_VALIDATION_2026-09-04.md`](validation/P201_RX1_INPUT_IDENTITY_VALIDATION_2026-09-04.md)
- [`CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md)

## 4. AGX acquisition, candidate refinement, and model input

P201 owns bounded receive-only acquisition and transport. AGX owns software
aggregation, result persistence and model-facing summaries.

- [x] Define the `SweepPlan` inputs, validation requirements, backend choices,
      result contract, and restoration requirements.
- [x] Implement the production `SweepEngine.run(plan)` module with replay and
      SDRD inline-IQ software Adapters.
- [x] Feed compact aggregate candidates into the Agent observation contract.
- [x] Implement and unit-test the AGX software-sweep Adapter that requests
      bounded inline IQ from P201, decodes and aggregates complex-int16 windows
      on AGX, computes power/clipping/noise/candidates, and reports backend
      identity `agx_iq_software_aggregate` without using `CAPTURE_POWER`.
- [x] Implement and unit-test optional one-dataset-per-scan SigMF output on AGX,
      with a single `.sigmf-data` file, a single `.sigmf-meta` file, per-window
      sample offsets/frequency/bandwidth/gain metadata, pre-write free-space
      checking, and partial-file cleanup on failure.
- [x] Live-validate a complete P201 capture → AGX aggregate → SQLite/Web result
      flow with both raw-IQ storage disabled and enabled, including exact byte
      accounting, AGX free-space evidence, SVG result readback, manual deletion,
      cancellation and verified radio-state restoration; see
      [`SDR_AGENT_AGX_INLINE_RESULTS_VALIDATION_2026-09-01.md`](validation/SDR_AGENT_AGX_INLINE_RESULTS_VALIDATION_2026-09-01.md).
- [x] Characterize the current P201/AGX bounded receive profile without raw-IQ
      retention: 2.1–30.72 MS/s profiles applied and restored, but legacy power
      processing reached only about 7 MS/s and base64 inline transport only
      about 1.87 Mb/s. Keep sustained-operation claims limited to this measured
      baseline; see
      [`P201_AGX_RX_PROFILE_VALIDATION_2026-09-02.md`](validation/P201_AGX_RX_PROFILE_VALIDATION_2026-09-02.md).
- [x] Run a configurable one-shot receive-only initial survey for each new Web
      conversation, defaulting to a 743-point 70 MHz–6 GHz plan at fixed 20 dB;
      fail on clipping or gain-readback mismatch, restore radio state, persist
      completion, and live-validate the full real-SDR to OpenCode Go hold loop
      without raw-IQ persistence or repeated scanning after Web restart.
- [x] Live-validate the independent NX B210 RF A/channel-0 to P201 physical
      RX1 path at 433.92 MHz with a bounded `+100 kHz` single-tone FFT
      comparison: the target bin rose 52.875 dB over the stopped-TX control,
      all captures had zero drops/overflow/clipping, both radios were restored,
      and transient data was removed; see
      [`NX_B210_P201_RX1_LINK_VALIDATION_2026-09-04.md`](validation/NX_B210_P201_RX1_LINK_VALIDATION_2026-09-04.md).
      Retain this only as historical RX1 port/link evidence; it is not a
      dependency, runtime component or future acceptance path for Chapters 1–6.
- [x] User-authorized independent NX/B210 finite RML2018A train playback at
      2.440 GHz to P201 RX1 demonstrated by source-specific signal matching. This 2026-09-06
      external signal-source exception does not add TX to Controller/Planner or
      change production admission, V1b labels, RF-v1 or NX inference scope.
  - [x] Finite train-only playback tools and stop/receive controls verified:
        three one-second sample streams, eight bounded RX captures with correct
        identity and restoration, exact FIFO tests and feature cleanup complete.
        Negative waveform correlation and UHD terminal S markers are preserved;
        no reception or classification success was claimed for those initial attempts. See
        [`NX_B210_RML_2440_VALIDATION_2026-09-06.md`](validation/NX_B210_RML_2440_VALIDATION_2026-09-06.md).
  - [x] User confirmed antenna ports; ten-second historical-tone and registered
        RML retries at 2.440 GHz completed, with six clean bounded RX captures,
        restoration and exact cleanup. The tone rose 44.799/34.319 dB over the
        same-bin TX-off controls; source-derived-band, fixed-lag RML correlation
        was 0.772 versus 0.009/-0.021. Original broadband failure remains recorded;
        this is exploratory engineering evidence, not independent RF labels,
        model accuracy or production admission. Eight software tests passed. See
        [`NX_B210_RML_2440_EXTENDED_VALIDATION_2026-09-06.md`](validation/NX_B210_RML_2440_EXTENDED_VALIDATION_2026-09-06.md).
- [ ] Complete the registered B210/P201 RF-v1 pilot with accepted RF controls
      and source association as well as received-result integration.
  - [x] Hash-bound received RF-v1 replay, real frozen Worker, S2/S6a archive,
        legacy/RF-v1 corpus lineage and existing delete APIs isolated-validated
        using one authorized 2.440 GHz B210/P201 pilot; tests and exact cleanup
        complete. No production deployment or independent labels. See
        [pilot validation](validation/B210_P201_RF_V1_PILOT_VALIDATION_2026-09-06.md).
  - [x] Separate RX40 engineering controls and user-requested paired source/RX
        model diagnostic completed: tone/RML TX-off checks pass fixed gates;
        original and aligned source predict ID 0, unmodified received IQ ID 18.
        NX child-query compatibility, finite stop/cleanup, 17 tests and exact
        feature cleanup verified. This is not RF-v1 50 dB acceptance or V1b.
        See [RX40 paired validation](validation/B210_P201_RX40_PAIRED_VALIDATION_2026-09-06.md).
  - [x] Offline single-source sensitivity to historical ±3.53 kHz CFO, +90°
        phase and fixed-realization added AWGN ratios 20/10 dB tested: all seven
        cases remain ID 0; both source baseline mean-logit hashes reproduce.
        Preserve this negative result, not an exclusion of actual RF impairments.
        22 tests, bounded AGX inference and exact cleanup completed. See
        [source sensitivity validation](validation/B210_SOURCE_SENSITIVITY_VALIDATION_2026-09-06.md).
  - [x] New bounded RX40 fidelity/compensation matrix completed: source controls
        pass; original/CFO/band/CFO+band received cases all remain ID 18 while
        source controls remain ID 0. Constant-phase case skipped by its gate;
        raised low-amplitude envelope and posthoc residual phase drift retained
        as hypotheses, not a fix. 29 tests, 24 model windows and exact cleanup
        verified. See [RX fidelity validation](validation/B210_RX_FIDELITY_VALIDATION_2026-09-06.md).
  - [x] Prefix-only complex gain/bias diagnostic tools and bounded RX40 posthoc
        exploration completed. Original source-envelope gate failed (0.340 < 0.5)
        and remains failed; explicit exploration produced source+b ID 0→18 and
        received-b aggregate ID 18→0, with two received windows still ID 2.
        35 tests, 28 experimental model windows, radio restoration and exact
        AGX/NX feature cleanup verified. This is known-source exploration, not
        blind compensation, hardware root-cause attribution or production repair.
        See [affine exploration validation](validation/B210_RX_AFFINE_VALIDATION_2026-09-06.md).
  - [ ] Qualify the source-reference bidirectional bias validation: the original
        source-association gate failed; exploratory improvements cannot replace
        that prerequisite. Register an appropriate independent source-association
        check before a new bounded validation; retain this run's failed gate.
    - [x] Implement and evaluate a separate centered-complex v2 numerical
          candidate with raw-prefix/heldout FFT isolation and same-spectrum
          wrong-source controls. 44 software tests and cleanup verified;
          candidate acceptance failed: 22/24 synthetic positives accepted,
          0/24 wrong sources accepted. No RF/model/dataset operations. See
          [centered-source validation](validation/B210_CENTERED_SOURCE_VALIDATION_2026-09-06.md).
    - [x] Implement v3 searched, spectrum-matched source/wrong-source contrast;
          resolve both old false rejections while preserving v2 failures. Run
          the preregistered 72-positive/72-negative matrix once: 70 positives
          accepted, no negatives accepted; full candidate acceptance still
          fails on two 32-kHz stopped-noise controls. 49 software tests and
          exact cleanup verified; see
          [source v3 validation](validation/B210_SOURCE_V3_VALIDATION_2026-09-06.md).
    - [x] Implement v4 stopped-control bounds from spectral overlap under an
          explicit independent Fourier-phase noise assumption, using per-window
          FFTs and a 16-window union bound. One preregistered independent matrix
          accepts 72/72 synthetic sources and 0/72 wrong sources; 56 software
          tests and exact cleanup pass. This qualifies only the numerical
          candidate, not live RF or production calibration; see
          [source v4 validation](validation/B210_SOURCE_V4_VALIDATION_2026-09-06.md).
    - [x] Integrate fixed v4 with sealed raw/report/SigMF/source identity and
          model preflight; execute the registered 2.440-GHz RX40 tone/RML pair.
          Six bounded captures pass native quality/identity and restoration checks, but source
          qualification fails on window 15 (coherence 0.413 < 0.6) amid short
          raw-power excursions; no model/warmup ran. 64 tests and exact AGX/NX
          cleanup complete; see
          [v4 live validation](validation/B210_V4_LIVE_VALIDATION_2026-09-06.md).
    - [x] User-requested single-1024-sample source is the new export default;
          versioned 20,480 complete-unit TX, sealed six-capture input and all
          65,535 pointwise I/Q/residual rows verified. Preserve all 512 segment
          summaries, source/carrier/DC separation, fixed-prefix scalar/FIR
          comparisons and explicitly posthoc fractional-delay diagnostics.
          76 software tests, real RX restoration and exact cleanup complete; see
          [1024 pointwise validation](validation/B210_1024_POINTWISE_VALIDATION_2026-09-06.md).
    - [x] Registered paired stopped-TX captures show short power excursions too:
          47/17 of 512 segments exceed the same exploratory 14.058-ADC-RMS line.
          This is two short captures, not background population statistics or
          evidence identifying a particular radio/interferer; see the pointwise record.
    - [x] Isolate the dominant carrier-related component with the same 1024
          source and registered TX LO offsets 0/+250 kHz/0/−250 kHz/0: the extra
          line follows both signed offsets and returns at zero, while the source-
          center bias drops about 43 dB. This supports TX LO leakage/feedthrough,
          not a damaged-component diagnosis or classifier repair. 82 tests,
          18 real captures, radio restoration and exact cleanup verified; see
          [LO-offset validation](validation/B210_LO_OFFSET_VALIDATION_2026-09-06.md).
    - [ ] Identify remaining time-varying phase and stopped/background excursions;
          LO separation does not remove these effects or establish their origin.
      - [x] Characterize retained bursts and execute a registered 30-point RX-only
            frequency comparison: discovery selects 2455 MHz once; independent
            confirmation reduces peak background versus 2440 MHz but fails all
            three absolute quiet-background checks. Preserve the failure and all
            statistics, with no protocol/hardware-cause or classification claim.
            96 tests, real restoration, precise cleanup and six inventoried
            confirmation captures (~1.6 MB) verified; see
            [background validation](validation/B210_BACKGROUND_VALIDATION_2026-09-07.md).
    - [x] Implement and live-validate an engineering +250-kHz LO / fixed 257-tap
          FIR rejection path: two captures suppress the LO band by 94.63/94.75 dB,
          preserve 99.9066% source power and show fixed-window source coherence
          0.997–0.999. Zero-offset rejection is approximately 0 dB. All three
          registered model blocks fail stopped-background gates, so model/warmup
          remain 0; this is not production RF-v1 or classification repair.
          89 tests and independent verification of 587,511 filtered samples pass.
          Non-evidence data and NX/P201 copies cleaned; per the new operator
          retention rule, 53 inventoried files (~3.3 MB) remain for sealed replay.
          See [LO rejection validation](validation/B210_LO_REJECTION_VALIDATION_2026-09-07.md)
          and [retained evidence](evidence/B210_LO_REJECTION_EVIDENCE_2026-09-07.json).
    - [x] Complete the registered 2455-MHz 1024-source amplitude ABBA comparison
          (.2/.3/.3/.2), with explicit version-4 source lineage and strict center
          binding. One fixed low1 block passes source/background controls; source,
          filtered source, raw RX and FIR RX all predict ID 0 in all four windows.
          16 experimental model windows + 2 warmups, 101 software tests, 15 real
          captures/restorations and precise cleanup verified; 67 inventoried files
          (~4.1 MB) retain the complete success/failure matrix. See
          [2455 margin validation](validation/B210_2455_MARGIN_VALIDATION_2026-09-07.md).
    - [ ] Establish repeatable source/background qualification across a fixed
          matrix: the 2455-MHz ABBA trial admits only one of four cases, so neither
          full-matrix reliability nor a benefit from increasing amplitude is
          established. Preserve failures; no retrospective gate or window changes,
          production admission, or qualified bidirectional-bias claim.
      - [x] Complete offline posthoc phase/gain/CFO/delay decomposition of all
            744 source/stopped blocks in the retained ABBA package. Broad local
            searches still leave ~95% unexplained centered energy in high2's fixed
            block and 54–64% in low2; simultaneous guard-band activity supports
            prioritizing input contamination over simple alignment corrections.
            Six synthetic tests, exact replay and temporary cleanup verified;
            no new RF/model/IQ copies and no physical-cause or repair claim. See
            [failure decomposition](validation/B210_FAILURE_DECOMPOSITION_VALIDATION_2026-09-07.md).
      - [x] Audit all 15 retained captures (983,025 samples) for byte layout,
            aligned repeats, zero fills and 4096-sample boundary artifacts:
            no full-block repeats or long constant spans found; live read-only
            IIO layout agrees with ci16_le. Six synthetic tests, 67-file seals,
            numerical replay and exact cleanup verified. This does not prove
            ADC/DMA continuity or a physical cause; see
            [RX byte audit](validation/B210_RX_BYTE_AUDIT_VALIDATION_2026-09-07.md).
      - [x] Validate IIO positive refill/span semantics against v0.21 source and
            the actual mapped target library's disassembly. Harden raw and
            compatibility power loops to reject malformed/short refills before
            consumption and clean failed output. Old-code negative reproduced;
            34 cases on both paths, existing protocol tests, ASan/UBSan, ARMv7
            ABI build and exact cleanup pass. Source delivery only; no observed
            historical RF cause or deployment claim. See
            [refill contract validation](validation/IIO_REFILL_CONTRACT_VALIDATION_2026-09-07.md).
      - [x] Live-validate the refill changes within the RX-port candidate on both
            channels: finite successful IQ, forced timeout, recovery and disconnect
            restoration pass, with a verified rollback and installed replacement.
            This does not establish historical RF-failure repair; see
            [port selection validation](validation/P201_RX_PORT_SELECTION_VALIDATION_2026-09-07.md).
      - [x] Make sdrd RX1/RX2 selectable by startup config with corresponding PHY,
            scan pair, gain snapshot/restore and truthful IQ identity. Native,
            sanitizer and bounded two-channel live tests pass; release
            `20260907-rx-port-selection-v1` is installed with default RX1 and
            retained rollback. Exact cleanup verified. Operator narrowed scope
            to these two ports after vendor source proved fixed TRX switch
            controls; no FPGA/BOOT change. Frozen Controller/profile still
            requires RX1; RX2 is an explicit diagnostic path. See the same record.
      - [x] Execute reversible three-stage antenna/50-ohm input isolation with
            actual connection evidence. Operator's 2026-09-09 connection order
            was termination/antenna/termination (reverse of the original wording).
            All 18 captures, both-channel restoration, replay and cleanup pass;
            high-background events occur in 0/6, 6/6, 0/6 captures. This completes
            physical comparison, not specific source attribution or full RF admission.
        - [x] Capture six fixed 2455-MHz terminated RX1 backgrounds with external
              TX stopped; validate native data, both-channel restoration, exact
              replay and cleanup. Retain 25 files / 1,611,184 bytes. FIR RMS
              medians 0.614–0.674 ADC are below historical antenna backgrounds,
              without a physical-cause or full-isolation claim. See
              [termination background](validation/P201_TERMINATION_BACKGROUND_VALIDATION_2026-09-09.md).
        - [x] After operator-confirmed antenna reconnection, capture six identical
              stopped backgrounds. All show short bursts (FIR maxima 45.096–167.843
              ADC versus termination 1.661–5.581); verify both-stage replay,
              restored radio, parent hashes and cleanup. No specific RF-source or
              hardware-cause claim; see the same record and
              [antenna evidence](evidence/P201_ANTENNA_RETURN_EVIDENCE_2026-09-09.json).
        - [x] Return RX1 to 50-ohm termination after operator confirmation and
              repeat six fixed captures: FIR maxima return to 1.025–3.469 ADC,
              with no original 20-ADC display-line events. Retain 25 files /
              1,612,141 bytes; see the same validation record and
              [reverse bracket](evidence/P201_REVERSE_BRACKET_COMPARISON_2026-09-09.json).
      - [x] Map ambient 2400–2483.5-MHz frequency/time distribution with 70
            overlapping centers × 3 surveys and 5 centers × 3 independent repeats,
            fixed gain20dB. All 225 points, 18 session restorations, exact replay
            and cleanup pass. Strong activity clusters near 2410–2424MHz and varies
            between windows; no protocol/source or long-term clean-channel claim.
            Retain 73 files / 64,602,034 bytes. See
            [background map](validation/P201_BACKGROUND_MAP_VALIDATION_2026-09-09.md).
      - [x] Sample 25 common 5-GHz Wi-Fi channel centers × 3 rounds plus five
            centers × 3 independent repeats at gain20dB/BW1.5MHz. All 90 native
            captures, restorations, exact replay and cleanup pass. Short activity
            recurs at 5805/5785/5745/5240MHz; sampled 5500–5720MHz centers remain
            low during these windows. This is sparse center sampling, not full-band
            coverage, protocol attribution or a permanently clean-channel claim.
            Retain 361 files / 26,038,557 bytes. See
            [5GHz background](validation/P201_WIFI5_BACKGROUND_VALIDATION_2026-09-09.md).
      - [x] Read all 1,586 archived AGX Agent 100MHz–6GHz sweeps and compare
            1MHz-subband frequency patterns with current 2.4/5GHz observations.
            Per-run overlap deduplication, daily/overall statistics, independent
            CSV checks, lineage and cleanup pass. Patterns broadly agree, with
            explicit differences near 2460–2465MHz; metrics/gain/BW are not equal
            and no same-source or protocol claim is made. See
            [historical comparison](validation/HISTORICAL_BACKGROUND_COMPARISON_2026-09-09.md).
      - [x] Implement and execute the explicitly authorized 3500-MHz spring-antenna
            tone pilot (TX gain0, RX gain20, one nominal10s TX and three controls).
            Native transport, both-channel restoration, TX stop and cleanup pass;
            tone qualification fails (17.62/12.46dB stopped contrasts,11.36dB
            spectral margin vs20dB gates). Preserve failure, no gain escalation,
            source-match/model admission or hardware-fault claim. Retain15 files /
            816,510 bytes. See
            [3500-MHz tone](validation/B210_3500_TONE_VALIDATION_2026-09-10.md).
      - [x] Compare six 3500-MHz RX1 termination captures with the retained antenna
            pilot at identical RX settings. RMS medians1.490–1.527 ADC vs antenna
            stopped1.429–1.432; no marked antenna background rise in these windows.
            Native/replay, both-channel restoration and TX-idle checks pass;
            retain25 files/1,608,427 bytes, remove7 files/58 bytes. Link tone
            qualification remains failed. See
            [3500-MHz termination](validation/P201_3500_TERMINATION_VALIDATION_2026-09-10.md).
      - [x] Execute operator-requested 3500MHz antenna reconnection retry once,
            unchanged TX0/RX20. Three native/replay and restoration checks pass;
            tone gate fails7.800/10.667dB controls and9.944dB spectral margin.
            TX stopped, evidence retained and cleanup complete. See
            [antenna retry](validation/B210_3500_RETRY_VALIDATION_2026-09-10.md).
      - [x] Execute explicitly approved3500MHz TX0/10/20dB matrix at fixedRX20:
            nine native/replay/restoration checks and15 source/bounds tests pass.
            All three tone gates fail; no confirmed gain response or hardware fault.
            TX stopped; retain52 files/2,470,747bytes, remove17 files/786,433bytes.
            No production deployment/model admission. See
            [gain matrix](validation/B210_3500_GAIN_VALIDATION_2026-09-10.md).
      - [x] Execute explicitly requested historical TX70/RX50 pair at3500MHz once.
            Three native/replay/restoration checks and16 tests pass; tone gate
            fails13.121/12.947dB controls and8.044dB spectral margin. TX stopped,
            cleanup/inventory complete; no production deployment/model admission.
            See [historical gain pair](validation/B210_3500_TX70_RX50_VALIDATION_2026-09-10.md).
      - [x] Return to2440MHz at operator request, sameTX70/RX50, one tone trial.
            Three native/replay/restoration checks pass; tone gate fails with
            23.119/10.777dB controls and17.921dB spectral margin. Strong stopped
            bursts retained, TX stopped and cleanup complete; no model admission.
            See [2440MHz return](validation/B210_2440_RETURN_VALIDATION_2026-09-10.md).
      - [x] Repeat2440MHz/TX70/RX50 once after operator antenna change:
            original tone gate passes37.037/40.902dB controls,35.889dB spectral
            margin. Three native/replay/restoration checks pass, TX stopped;
            retain18 files/823,363bytes, remove4 files/123,432bytes. No antenna
            causal-effect/modulation/model claim. See
            [antenna-change success](validation/B210_2440_ANTENNA_CHANGE_VALIDATION_2026-09-10.md).
      - [x] Test reported433MHz antenna at433.920MHz/TX70/RX50 once: original
            tone gate passes44.621/44.269dB controls and54.756dB spectral margin.
            Background steadier than recent2440MHz, not lower total RMS; no
            calibrated noise/antenna causality claim. Three native/replay and
            restoration checks plus17 tests pass; TX stopped, retain19 files/
            824,423bytes, remove12 files/909,865bytes. See
            [433MHz antenna](validation/B210_433920_ANTENNA_VALIDATION_2026-09-10.md).
      - [x] Retry RX1 with the operator's new dual-band antenna using one tone
            and three unchanged .2-amplitude 1024-source repetitions. All three
            fixed source/residual checks pass; each fails at least one original
            stopped-background margin, so classification remains unmeasured.
            31 tests, 12 live capture/restoration checks, exact replay and cleanup
            pass; retain 55 inventoried files (~3.26 MB unique). This is not an
            antenna causal-effect or recognition-accuracy claim; see
            [new antenna validation](validation/B210_RX1_NEW_ANTENNA_VALIDATION_2026-09-07.md).
      - [x] Cover all 24 numeric classes with three preselected +30 dB train
            rows each, one 1024-sample TX unit per case, interleaved across three
            rounds. All 75 tone/RML groups and 225 captures restore successfully;
            1152 diagnostic windows plus 2 warmups complete. Source/raw RX/FIR RX
            nominal agreement is 69/72, 30/72, 56/72; retain all failed gates and
            five FIR regressions. Original full diagnostic gate passes 51/72;
            five carrier-dominated sources expose the existing zero-bandwidth
            association limitation. 29 tests, retained replay, exact cleanup and
            Spark restoration pass; retain 1268 inventoried files (62,465,220
            unique-inode bytes). No independent RF accuracy, universal FIR fix,
            V1b completion or production admission claim. See
            [24-class validation](validation/B210_MULTICLASS_VALIDATION_2026-09-07.md).
      - [x] Diagnose the four qualified multiclass RX errors with all eight
            same-class successful controls, prefix-only source/channel
            counterfactuals and full fixed-block pointwise I/Q plots. 432 windows
            plus 2 warmups complete; 24 baseline logits reproduce exactly.
            Constant timing/phase/CFO/affine offsets do not recover the four
            errors; all successful controls remain successful. Check six strong
            DC sources without revising original gates, and inspect the 4090
            pre-RF D8 validation confusion matrix and operator-provided name
            reference. 17 tests, retained replay, Spark restoration and complete
            feature-root cleanup pass; no new RF, dataset reads or retained IQ.
            Hardware cause, production name mapping and general repair remain
            unresolved. See [residual validation](validation/B210_RESIDUAL_VALIDATION_2026-09-07.md).
  - [ ] This pilot's complete TX-off/source-match RF acceptance: post-TX capture
        failed with `summary_clipped`; successful received-window inference
        predicted experimental ID 18 versus source nominal ID 0. Preserve the
        failed control and ambiguous source diagnostic; no additional burst in
        this unit, and no classification-accuracy or V1b completion claim.
- [x] Feed only a selected, bounded 1,024-sample IQ window into experimental
      local recognition, with P201 inline transport, AGX-only preprocessing,
      private 8,192-byte spool, correlated CUDA/Mamba response, automatic IQ
      deletion and verified radio restoration. Keep production capability off
      because labels, RF preprocessing and rejection remain unresolved; see
      [`P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md`](validation/P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md).
- [x] Define and hash-pin the integration-only
      `rml2018a-d8-current-integration-v1` input profile and
      `legacy_adc_unit_rms_v0` preprocessing specification: fixed verified
      RX1 identity, 2.1 MS/s, 1.5 MHz, 50 dB, 4 × 1,024 samples, exact raw/model
      byte bounds, deadlines and quality gates. Both contracts remain
      `production_enabled=false`.
- [x] Compute a versioned AGX `SpectralSummary` from each inspection IQ window
      and derive a fresh `RecognitionTarget` from the same-window peak,
      spectral noise, measured SNR, center and connected-component 99% occupied
      bandwidth, together with request/session/sequence/RX identity and health.
      The 433.92-MHz live validation rejected the pre-fix over-wide target,
      then admitted the corrected bounded target without reusing a differently
      gained sweep noise estimate; see
      [`P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md`](validation/P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md).
- [x] Implement one continuous bounded 4,096-sample capture, AGX-only split into
      four exact model-ready windows, byte-reproducible golden fixtures, strict
      per-window quality/offset metadata and private spool cleanup. A real P201
      RX1 capture reached the current seed44 Worker through four sequential
      bounded offsets, returned a 3/4 integration-only vote, restored the radio
      and left no Worker, socket, spool or P201 transient data; error and direct
      cancel paths are covered by isolated tests.
- [ ] Define and version the production Chapter 4-to-6
      `RecognitionInputProfile`: candidate/source correlation, fixed initial
      sample-rate domain, separate RX gain/raw RMS/measured SNR semantics,
      capture/window/byte/deadline limits, preprocessing ID/hash and quality
      gates. Keep model-specific DSP out of Planner-controlled parameters; see
      [`CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md).
- [x] Live-validate failure during four-window Worker dispatch and direct cancel
      during the new model-ready capture, proving radio restoration and exact
      AGX/P201 temporary-data cleanup on both paths. A finite Worker exited
      after window 0 so window 1 failed explicitly and the 32-KiB spool was
      removed; an independent generation-bound cancel produced
      `capture_failed_restored`. Both paths restored verified RX1 state and left
      no transient data; see
      [`P201_MAMBA_BATCH_FAILURE_CANCEL_VALIDATION_2026-09-05.md`](validation/P201_MAMBA_BATCH_FAILURE_CANCEL_VALIDATION_2026-09-05.md).
- [x] Freeze `rf_preprocess_v1` using train/validation and versioned unknown
      P201 evidence: hardware retune, no digital shift/filter/resampling, DC
      retained, shared 4,096-sample complex RMS, four contiguous 1,024-sample
      windows and mean logits. Selection did not open test; see
      [`RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md`](validation/RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md).
- [x] Implement the independently hash-pinned integration-only RF-v1 runtime
      profile with shared-capture RMS and ordered float32 windows, reproduce the
      frozen offline golden bytes exactly, and live-validate the epoch-10 FP16
      Worker/full-logit AGX aggregation path. Success, Worker exit and direct
      capture cancel restore P201 RX1 and remove spool; all feature processes,
      ten P201 transient directories, three AGX feature roots and build staging
      were cleaned and verified. See
      [`RF_V1_RUNTIME_PARITY_VALIDATION_2026-09-05.md`](validation/RF_V1_RUNTIME_PARITY_VALIDATION_2026-09-05.md).
- [ ] Freeze independently labeled known-RF/OOD calibration and production
      acceptance thresholds before promoting the runtime profile; numerical
      RMS guards and development target gates are not calibrated acceptance.
- [x] Retire the separate sustained 5/10-MS/s aggregate acceptance gate by
      explicit operator decision on 2026-09-03. This is a scope removal, not a
      claim that inline transport and AGX aggregation were newly measured at
      those rates; the characterized P201/AGX profile above remains the measured
      baseline.
- [x] Complete the long-duration reconnect, cancellation and fault-recovery
      portion with the chapter 3 bounded 1,800-second real-SDR run; see
      [`SDR_AGENT_SDRD_LONG_RECONNECT_FAULT_RECOVERY_VALIDATION_2026-09-03.md`](validation/SDR_AGENT_SDRD_LONG_RECONNECT_FAULT_RECOVERY_VALIDATION_2026-09-03.md).
- [x] Complete bounded AGX software-acquisition overload testing: reject a
      278,528-byte point before backend/radio work, process 128 consecutive
      262,144-byte windows (32 MiB total) with continuous sequences and zero
      drop/overflow/clipping/timeout/health failures, bound AGX/P201 resources,
      and prove both IIO-deadline and client-disconnect restoration followed by
      a fresh successful generation; see
      [`P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md`](validation/P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md).

Evidence:

- [`SDR_PREPROCESSING_SWEEP_ARCHITECTURE.md`](reference/SDR_PREPROCESSING_SWEEP_ARCHITECTURE.md)
- [`../raspberry-pi/p201pro-rust/TEST_RESULTS.md`](../raspberry-pi/p201pro-rust/TEST_RESULTS.md)
- [`PI_SOFTWARE_SWEEP_FALLBACK_2026-09-01.md`](validation/PI_BASELINE_HISTORY.md#pi-9)
- [`SDR_AGENT_INITIAL_SURVEY_SETTINGS_VALIDATION_2026-09-01.md`](validation/SDR_AGENT_INITIAL_SURVEY_SETTINGS_VALIDATION_2026-09-01.md)
- [`NX_B210_P201_RX1_LINK_VALIDATION_2026-09-04.md`](validation/NX_B210_P201_RX1_LINK_VALIDATION_2026-09-04.md)
- [`P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md`](validation/P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md)
- [`P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md`](validation/P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md)
- [`P201_MAMBA_BATCH_FAILURE_CANCEL_VALIDATION_2026-09-05.md`](validation/P201_MAMBA_BATCH_FAILURE_CANCEL_VALIDATION_2026-09-05.md)
- [`P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md`](validation/P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md)
- [`CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md)

## 5. Input standardization, receive-domain alignment, and evaluation governance

The retired FPGA section is not a vacant implementation chapter. Chapter 5 now
owns the reproducible data contract between Chapter 4 reception and Chapter 6
recognition; it does not own hardware control or another runtime backend.

- [x] Retire FPGA aggregation by explicit user decision and fix production on
      P201 Linux/IIO bounded RX transport plus AGX software aggregation.
- [x] Remove the FPGA/Vivado tree, FPGA-only documents, MMIO Adapters and active
      Planner/controller snapshot capability from the working tree. Retain only
      constant false/zero SDRD/1 compatibility fields, strict acceptance of a
      legacy false Planner-health field, and the retirement decision;
      pre-cleanup evidence remains recoverable from Git history at `59cbb17`.
- [x] Define the Chapter 5 role as input standardization, receive-domain
      alignment and evaluation-data governance for the AGX-only Chapter 4-to-6
      handoff; no transmit or FPGA path is a data dependency.
- [x] Inventory the retained RML2018A/HisarMod2019 datasets, fixed splits,
      selected checkpoints, minimal inference source and exact SHA-256 values
      under the Git-ignored AGX asset root.
- [x] Distinguish dataset nominal SNR, P201 receive gain, ADC dBFS and measured
      receive SNR, and state that a field window without an independent label is
      unknown/unlabeled rather than model-generated ground truth.
- [x] Define and validate `amc_corpus_manifest_v1` plus its streamed
      `amc_corpus_record_v1` JSONL rows for labeled offline data, P201
      receive-only corpus windows and golden vectors. The contract pins content,
      profile, preprocessing, label-space, split and evidence hashes; requires
      explicit `dataset_ground_truth`, `independent_annotation` or `unknown`;
      rejects source/label misuse, provisional-name escalation, path/hash
      tampering and train/test lineage collisions; and validates the existing
      four-window golden fixture without assigning it a false class. See
      [`AMC_CORPUS_MANIFEST_V1.md`](reference/AMC_CORPUS_MANIFEST_V1.md) and
      [`AMC_CORPUS_CONTRACT_VALIDATION_2026-09-05.md`](validation/AMC_CORPUS_CONTRACT_VALIDATION_2026-09-05.md).
- [x] Build a bounded, versioned P201 receive-only corpus with session/date,
      center, rate, bandwidth, fixed RF input, gain, samples/bytes, quality and
      cleanup metadata; provide a visible manual-delete path and keep bulk IQ
      outside Git. The application-owned SQLite/package store rejects nonlocal
      writes, metadata/IQ mismatches and incomplete cleanup; a 4,096-sample
      RX1 row was live-captured, reference-validated, visibly deleted and then
      restored as an `unknown` application result; see
      [`P201_RX_CORPUS_STORE_VALIDATION_2026-09-05.md`](validation/P201_RX_CORPUS_STORE_VALIDATION_2026-09-05.md).
- [x] Prove train/validation/test isolation by source sample, capture session
      and UTC day so crops, augmentation or repeated receptions of one source
      do not cross splits. Both complete retained split files have unique,
      in-range, fully covering global-row assignments with zero pairwise
      intersections; the cross-package P201 audit enforces parent inheritance,
      all three group keys and `receive_domain` for unknown receptions. See
      [`AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md`](validation/AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md).
- [x] Pre-register and use only train statistics, complete validation groups and
      versioned `receive_domain/unknown` evidence to freeze the
      `rf_preprocess_v1` retraining contract: 2.1 MS/s without software
      resampling/frequency shift, DC retained, one RMS scale across four
      contiguous 1,024-sample windows, and mean-logit aggregation. The selection
      code never loaded the test member/result; labeled validation accuracy and
      unlabeled P201 quality/confidence remained separate. See
      [`RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md`](validation/RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md).
- [x] Receive the user-trained epoch-10 RF-aligned checkpoint, retain its full
      147-entry provenance map in an isolated ignored AGX asset directory, and
      strictly evaluate all 95,607 grouped validation examples in FP32:
      aggregate accuracy matched the 4090 exactly at `0.6705575952` and NLL
      differed by only `6.8e-8`; test remained unopened and capability false. See
      [`RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md`](validation/RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md).
- [x] Add versioned RF-v1 corpus derivation/import and independently annotated
      evidence ingestion by reusing the existing corpus contract/store. The
      deployed intake still pins the legacy profile and writes only `unknown`;
      preserve historical package hashes, bind every new profile/preprocess and
      label to source evidence, validate source/session/day grouping and retain
      manual deletion. A model prediction or an unknown-reason field is not
      an independent annotation. Source and isolated native Web/HTTP/browser
      validation passed; new roots preserve original request reports and older
      seven-file roots remain unknown-only. Parent hashes and shared IQ survive
      independent deletion, group constraints persist, and all feature data was
      cleaned. See [`RF_V1_EVIDENCE_V1A_VALIDATION_2026-09-06.md`](validation/RF_V1_EVIDENCE_V1A_VALIDATION_2026-09-06.md).
- [x] Pre-register the known-RF/OOD coverage and sampling rationale plus separate
      calibration and acceptance groups before fitting thresholds; track label
      evidence, ambiguous cases and class/name mapping without opening the
      locked test. The specification is
      [`RF_V1_KNOWN_RF_OOD_SAMPLING_V1.md`](reference/RF_V1_KNOWN_RF_OOD_SAMPLING_V1.md),
      with clustered/effective sample-size rationale and explicit coverage gaps.
      This completes the tools/specification gate only; actual independently
      reviewed coverage remains V1b, not supplied by unknown receptions.
- [ ] Use independently labeled known-RF/OOD evidence with the final checkpoint
      to freeze scalar calibration plus confidence/agreement/SNR/bandwidth
      acceptance thresholds, then perform one locked test admission. The new
      validation-only temperature candidate `1.34647` remains non-production.
- [x] Freeze the operator-designated 4090 RML2018A raw-ID/name map: AST-extracted
      RADIOML2018A_RAW_LABELS and the report raw_label_id/raw_label agree 24/24,
      with the Adapter explicitly indexing names by argmax(Y). Pin source/report
      hashes and distinguish the separate common12 canonical index. Historical
      artifacts and non-admitted runtime labels stay unchanged; production
      name_evidence integration remains A1. See [mapping decision](validation/RML2018A_LABEL_MAPPING_VALIDATION_2026-09-08.md).

Evidence:

- [`FPGA_RETIREMENT_DECISION_2026-09-02.md`](reference/FPGA_RETIREMENT_DECISION_2026-09-02.md)
- [`NX_B210_MAMBA_D8_ASSET_HANDOFF.md`](validation/NX_B210_MAMBA_D8_ASSET_HANDOFF.md)
- [`AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md`](validation/AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md)
- [`P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md`](validation/P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md)
- [`AMC_CORPUS_MANIFEST_V1.md`](reference/AMC_CORPUS_MANIFEST_V1.md)
- [`AMC_CORPUS_CONTRACT_VALIDATION_2026-09-05.md`](validation/AMC_CORPUS_CONTRACT_VALIDATION_2026-09-05.md)
- [`P201_RX_CORPUS_STORE_VALIDATION_2026-09-05.md`](validation/P201_RX_CORPUS_STORE_VALIDATION_2026-09-05.md)
- [`AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md`](validation/AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md)
- [`RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md`](validation/RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md)
- [`RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md`](validation/RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md)
- [`CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md)

## 6. Local Mamba modulation recognition

- [x] Supersede the Pi-sized production-model direction with a backend-neutral
      AGX recognizer seam and defer the production Adapter to CUDA/Mamba.
- [x] Implement the Rust `LocalRecognizer` interface.
- [x] Implement replay and Unix-socket Recognizer Adapters.
- [x] Enforce bounded, canonical spool-root IQ references and fixed planar
      float32 IQ metadata.
- [x] Correlate recognition requests and results by request ID, session
      generation, and candidate ID.
- [x] Implement the dependency-free C++20 model-backend interface and
      `ReplayBackend` tests.
- [x] Implement the bounded `ModelPackageLoader` interface, filesystem and
      replay Adapters, manifest/path/size/SHA-256/label validation, and package
      inspection command.
- [x] Inventory and verify the five D8/Shared-Bi RML2018A canonical `best.pt`
      candidates (seeds 42--46) with exact source/run metadata, byte counts and
      SHA-256 parity; after selecting seed44, remove the redundant AGX candidate
      copies while retaining the audit table and verified 4090 recovery paths.
      This does not enable recognition. See
      [`NX_B210_MAMBA_D8_ASSET_HANDOFF.md`](validation/NX_B210_MAMBA_D8_ASSET_HANDOFF.md).
- [x] Stage RML2018A seed44 and HisarMod2019 seed43 with their exact clean D8
      inference source, fixed splits and datasets under the ignored AGX-local
      asset root; strictly load both checkpoints and reproduce both complete
      FP32 test sets. Evidence:
      [`AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md`](validation/AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md).
- [x] Retain seed44 as an experimental baseline and receive the user's
      validation-selected RF-aligned epoch-10 fine-tuned checkpoint using the
      exact frozen Chapter 4 `rf_preprocess_v1`. Its source, split, preprocessing,
      numeric labels, training config and checkpoint are pinned; strict AGX FP32
      loading and complete validation parity passed without opening test.
- [x] Select and hash-pin FP16 autocast for the epoch-10 validation candidate
      after complete FP32/FP16/BF16 comparison on AGX. This precision selection
      does not promote the checkpoint or enable runtime capability; see
      [`RF_V1_PRECISION_SELECTION_VALIDATION_2026-09-05.md`](validation/RF_V1_PRECISION_SELECTION_VALIDATION_2026-09-05.md).
- [ ] Freeze calibration and acceptance thresholds before promoting epoch 10
      from a validation-only candidate to an admitted production checkpoint or
      viewing its frozen test result.
- [x] Implement and live-validate the experimental AGX CUDA/Mamba Worker behind
      the existing backend-neutral Unix Recognizer Adapter without exposing
      PyTorch, Triton or CUDA objects through the Controller interface; keep it
      explicitly production-disabled pending the remaining admission gates.
- [x] Connect the current seed44 checkpoint to the versioned four-window
      integration path: reuse one bounded private model-ready batch through four
      exact offsets, verify model/profile identity on every response, expose all
      provisional window outputs plus an explicitly uncalibrated majority-vote
      summary, and delete the batch on success or error. The real RX1 validation
      kept `production_recognizer_available=false`; see
      [`P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md`](validation/P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md).
- [x] Run the RF-aligned epoch-10 Worker with FP32 resident weights and the
      frozen FP16 autocast, return all 24 FP32 logits per ordered window, and
      aggregate them using float64 arithmetic mean followed by softmax on AGX.
      Strict request/source/capture/session/profile/preprocess/checkpoint/batch
      correlation, finite full-logit shape, replay/order rejection and bounded
      cancellation cleanup passed unit and live RX-only validation. Keep all
      probabilities uncalibrated, numeric IDs authoritative, names provisional
      and capability false; see
      [`RF_V1_RUNTIME_PARITY_VALIDATION_2026-09-05.md`](validation/RF_V1_RUNTIME_PARITY_VALIDATION_2026-09-05.md).
- [x] Numerically compare AGX FP32 with the 4090 training environment on the
      same 16 IQ rows per dataset: both argmax sets agree 16/16 and maximum
      absolute logits differences are `2.93e-5` (RML) and `1.18e-4` (Hisar).
- [x] Compare FP16 and BF16 against the frozen FP32 complete-validation result
      with preregistered accuracy, high-SNR accuracy, NLL, argmax, logit,
      probability, speed and memory gates. FP16 passed every gate and delivered
      1.2254x median throughput; BF16 was rejected for numerical divergence.
- [x] Measure offline preprocessing, host/device transfer, warm-up, inference,
      total p50/p99 latency, CUDA memory, CPU/RSS and thermal behavior for both
      complete test splits on AGX.
- [x] Run bounded short AGX co-residency and deliberate-overlap tests for local
      Spark BF16/Q8 and seed44 FP32 Mamba: BF16/Mamba fit without OOM but active
      overlap reduced both throughputs by approximately half. Also record the
      five-case Planner smoke (BF16 4/5, Q8 3/5), unavailable MTP tensors and
      unstable/no-median-gain n-gram speculation; retain BF16 as production
      default and do not count this as sustained Worker validation. See
      [`AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md`](validation/AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md).
- [ ] Measure production Worker queue drops, cancellation, concurrency and
      sustained thermal behavior.
  - [x] S3 lifecycle implementation and finite actual RF-v1 Worker validation:
        one active/four-window batch plus one waiting slot, whole-batch and
        independent queue deadlines, reserved control connections, confirmed
        cancellation, child/supervisor kill and restart fencing, exact orphan
        cleanup and bounded metrics. Rust replay/health/cancel and negative
        tests passed; feature processes and temporary data were removed. See
        [`WORKER_SUPERVISOR_S3_VALIDATION_2026-09-06.md`](validation/WORKER_SUPERVISOR_S3_VALIDATION_2026-09-06.md).
  - [x] S4b: 20-minute representative serialized replay/Planner resource evidence
        and exact cleanup passed with the explicit user exception for unavailable
        GPU temperature; CPU/SoC/Tj, memory, queue and latency gates passed. See
        [S4b validation](validation/GPU_RESOURCE_S4B_VALIDATION_2026-09-06.md).
  - [ ] A1: admitted production lifecycle deployment remains open.
- [ ] Define and live-validate the shared AGX CUDA admission policy for the
      resident Spark-X2.5-4B Planner and Mamba Worker. For production v1,
      serialize active inference, bound queue/deadline/memory/thermal use, and
      prove cancellation releases the gate before a subsequent Planner turn.
  - [x] S4a shared lease source and finite real candidate validation: inherited
        cross-process flock covers startup and whole inference; owned Spark
        gateway and S3 Mamba supervisor serialize active work, reap on cancel/
        failure before release, and fence parent death. Actual Node Planner →
        native RF-v1 Mamba → Planner, concurrent waiting, both cancellations and
        both supervisor SIGKILL/recovery passed; temporary data and processes
        were removed. See
        [`GPU_LEASE_S4A_VALIDATION_2026-09-06.md`](validation/GPU_LEASE_S4A_VALIDATION_2026-09-06.md).
  - [x] S4b: bounded candidate CPU prompt cache and representative memory/queue/
        latency/CPU-SoC-Tj thermal acceptance; GPU temperature is explicitly
        waived as unavailable, not validated.
  - [ ] A1: coordinated admitted deployment routing all production GPU callers
        through the same gate; installed endpoints remain outside the candidate.
- [x] Generate offline confusion matrices, total accuracy, macro-F1, per-class
      precision/recall/F1 and per-SNR accuracy for both complete test splits.
- [ ] Consume the Chapter 5 frozen numeric-ID/name table, then validate the RF
      input contract and rejection policy before enabling
      `recognizer_available`.
- [x] Extend recognition results beyond candidate/label/confidence with
      classified/rejected/unavailable/error status, numeric label identity,
      rejection reason, source sequence, model/profile hashes, window agreement,
      quality and timing while keeping IQ out of Planner context. S2 separates
      the full internal record from a strict 4-KiB observation, revalidates RF-v1
      batch/logits/quality/timing and rejects production decisions under the
      candidate profile. Rust/Node tests and retained live-report replay passed;
      temporary test/build data was removed. See
      [`RECOGNITION_RESULT_S2_VALIDATION_2026-09-06.md`](validation/RECOGNITION_RESULT_S2_VALIDATION_2026-09-06.md).
      The dependent Web build omission was corrected separately after V1a audit
      exposed it; 20 isolated Web tests and Clippy pass. See
      [`RECOGNITION_RESULT_S2_WEB_CORRECTION_2026-09-06.md`](validation/RECOGNITION_RESULT_S2_VALIDATION_2026-09-06.md#web-build-correction).
- [x] Define and validate `recognizer_admission_v1`, bounded six-gate evidence
      receipts and challenge-correlated `recognizer_health_v1`, including full
      model/profile/preprocess/precision identity, Worker instance and time,
      receipt hashes, 250-ms socket deadlines and no stale-success fallback.
      The real candidate reports `production_enabled=false`; two actual Worker
      instances, status-only forgery and malformed enable requests were tested.
      See [`RECOGNIZER_ADMISSION_S1_VALIDATION_2026-09-06.md`](validation/RECOGNIZER_ADMISSION_S1_VALIDATION_2026-09-06.md).
- [ ] Live-validate positive production capability from an actually admitted
      Worker and complete model/calibration/acceptance/runtime/deployment
      receipts at A1. S1 integrity checks and synthetic passing receipts do not
      validate the scientific or operational content of future gate reports.
- [ ] Live-validate the production RX-only candidate-refinement, bounded P201
      capture and AGX recognition path across a frozen frequency/gain/session
      matrix, with no forced label for noise or unlabeled field windows, radio
      restoration and exact temporary-data cleanup. Report closed-set accuracy
      only from frozen independently labeled datasets/corpora, separately from
      P201 field-domain quality, confidence and rejection behavior.
- [x] Run the experimental Recognizer Worker on AGX with listen backlog one,
      one Torch CPU thread, strict asset hashes and a finite request count for
      the delivery validation, then stop it and remove all feature data; retain
      a deliberately non-installable systemd template for repeatable bounded
      tests.
- [ ] Deploy and enable an admitted production Recognizer Worker with one
      bounded queue and explicit thread limits after labels, RF preprocessing,
      precision, rejection, concurrency and thermal gates pass.

Evidence:

- [`LOCAL_RECOGNIZER_INTERFACE.md`](reference/LOCAL_RECOGNIZER_INTERFACE.md)
- [`AGX_SDRHARNESS_MIGRATION.md`](../jetson-agx/sdrharness/README.md)
- [`NX_B210_MAMBA_D8_ASSET_HANDOFF.md`](validation/NX_B210_MAMBA_D8_ASSET_HANDOFF.md)
- [`AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md`](validation/AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md)
- [`AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md`](validation/AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md)
- [`P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md`](validation/P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md)
- [`P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md`](validation/P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md)
- [`RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md`](validation/RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md)
- [`RF_V1_PRECISION_SELECTION_VALIDATION_2026-09-05.md`](validation/RF_V1_PRECISION_SELECTION_VALIDATION_2026-09-05.md)
- [`CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md)

## 7. Emitter/radiation-source identification

2026-09-08 用户明确暂缓设备/辐射源身份识别，已将其总览项和七个子项移出当前
待办，不计入未完成条目。这是范围暂缓，不是验收完成，也不是永久退役。
原目标定义、采集/标签规范、RF 指纹数据、特征、开放集校准、鲁棒性验证及集成
条目保留在 `9dcb86e` 的 Git 历史中；只有用户明确恢复此范围后再重新评估排期。
当前继续以第1—6章 RX-only 调制识别为交付范围，模型工作暂停等既有约束不变。

本次仅调整文档范围；链接、条目数量及 diff 核对通过，无代码、部署、射频或
模型操作，无新增临时数据或保留制品。

## 8. Verification, deployment, and operations

- [x] Reorganize root `AGENTS.md` around task entry, authoritative document roles,
      shared code/CLI ownership, model and hardware boundaries, temporary versus
      retained/user data, and independent delivery. Preserve prior RX/FPGA/data
      rules and existing authorization scope; add current documentation layout,
      frozen-path handling and conditional CodeGraph use without duplicating the
      progress queue. Eight links, rule consistency and diff review verified;
      documentation-only change, no runtime activity or temporary data created.
- [x] Consolidate documentation into four current reading entries plus reference,
      validation and evidence directories. Delete four superseded guides, merge
      eleven dispersed records into three reports, preserve all 86 original
      audit/plan/figure hashes and 81 validation/handoff bodies, retain three
      frozen configuration audit paths, and update path-only consumers. Local
      links, 136 Rust and 37 Python tests, checkout and exact temporary cleanup
      pass. No runtime deployment or admission change; see
      [documentation consolidation](validation/DOCS_CONSOLIDATION_2026-09-07.md).
- [x] Pass the current Rust Controller and Recognizer interface test suite.
- [x] Pass Rust formatting and Clippy with warnings denied.
- [x] Pass the current Planner/session Node test suite.
- [x] Pass the dependency-free C++ Recognizer backend tests.
- [x] Cross-build stripped static AArch64 Controller and terminal binaries in
      WSL and verify their hashes.
- [x] Live-test interactive and one-shot Agent paths on the Pi.
- [x] Record deployed releases, hashes, resource measurements, and rollback
      locations.
- [x] Run the Rust web console as an enabled, resource-bounded systemd service
      bound only to the Pi Tailscale address, with root-only state and a retained
      independent rollback release.
- [x] Keep repository secrets, passwords, tokens, private keys, build outputs,
      dependency directories, and deployment staging files out of Git.
- [x] Remove local build intermediates and temporary upstream research clones
      after the verified deployment.
- [x] Record the user's development-only authorization for bounded receive
      sweeps, isolated per-feature data directories, hard data caps, and
      mandatory cleanup before feature completion.
- [x] 国产N210设备技能：USB B210兼容身份、专用UHD/A7-100T、有限计划/GO/停止、P201分工及证据流程；项目源码与用户技能目录同一份链接，元数据/链接/实际无RF运行时状态核验通过，见[验证](validation/B210_AGX_MIGRATION_2026-09-11.md#2026-09-13国产n210设备技能)。
- [x] Add and validate the project-local `p201-sdr-workflow` skill for bounded
      access, cross-build, deployment, duplicate-instance gating and cleanup.
- [x] O1a adds deterministic bounded mutation across application-owned protocol
      boundaries (11 targets × 256 cases), alongside actual socket malformed/
      oversized/stale/duplicate/truncated/reordered regressions. C ASan/UBSan and
      isolated native Web/Planner recovery passed; no third-party SSH/IIOD fuzz
      or exhaustive coverage claim. See [O1a validation](validation/OPERATIONS_O1A_VALIDATION_2026-09-06.md).
- [x] O1a unifies repeatable upstream/model restart, SDRD disconnect, fake-radio
      timeout, explicit transport overflow/restore, and cancellation/generation
      fault checks; these deterministic tests do not replace A1 real RF acceptance.
- [ ] Run and document a complete 24-hour autonomous-loop soak test.
- [x] O1a defines and isolated-validates current AGX logging, read-only health/
      local alert transitions, immutable candidate release verification and
      upgrade/rollback procedures. P201 follows its existing deployment workflow
      and Pi stays standby; user results are excluded from log/rollback cleanup.
  - [x] Install RX-only Web/Planner bounded journald and read-only local health,
        verify actual Planner health compatibility, fault deduplication/recovery,
        rotation, configuration rollback and user-data preservation; exact cleanup
        complete. See [deployment](validation/OPERATIONS_RX_DEPLOYMENT_VALIDATION_2026-09-08.md).
  - [ ] A1: extend monitoring/logging to the admitted coordinated recognition
        deployment and validate its rollback; current RX-only monitoring does not
        cover undeployed Mamba or GPU gateway.

## Current next milestone

The current deployment summary is at the top of this checklist. Execution order
is maintained only in [ACTUAL_DELIVERY_ORDER](SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md).
The unified CLI and the Web recovery upgrade are installed; full production
recognition remains unavailable.
Do not interpret dated evidence statements about unchanged services as current
status or restart completed S/V work.
