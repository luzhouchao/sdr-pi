# SDR Agent project checklist

Last reviewed: 2026-09-06

This is the living source of truth for implementation status. Check an item only
after the exact wording is implemented and verified. Split partial work into a
completed item and a remaining item instead of marking an ambiguous partial
state.

Sections 1–6 are now the unified RX-only chapter plan and replace the earlier
4-to-6-only planning view. The concise chapter view is
[`CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md);
this file retains the detailed delivery and evidence ledger.

## 当前交付状态速览（2026-09-06）

以下是本文件各章节的当前交付索引；详细完成条件和证据仍见对应章节。
编号表示范围，不表示施工先后；实际顺序见
[`SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md`](SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md)。
S1/S2/V1a/S3/S4a/S6a/S5/S6b/S4b/O1a 源码、适用隔离实机验收及清理完成，生产服务未替换。S4b 的 GPU 温度缺失由用户明确豁免，保持未测。

- [x] P201 RX1 有界采集/传输、停止、恢复、固定输入身份及长期重连验证完成（第3章）。
- [x] AGX 扫频/精查、结果存储和 RX 语料基础、split 隔离完成（第1/4/5章）。
- [x] RF-v1 预处理、用户训练 epoch-10 checkpoint 的 validation 和 FP16 选择完成。
- [x] 共享 RMS/四窗/full-logit/mean-logit runtime、golden 和有限实收故障清理完成。
- [x] S1：准入/health/人工批准源码、测试及隔离真实 Worker 验证完成；生产服务未替换。
- [x] S2：统一完整结果与 Planner 紧凑 observation、四状态/校准身份、RF-v1 batch 严格转换和真实报告 replay 完成；生产阈值未冻结，能力仍为 false。
- [x] S3：Worker 单等待位、整批 deadline、取消确认、强杀/重启清理和指标完成源码及有限真实候选验证；未部署，能力仍为 false。
- [x] S4：共享 GPU 调度与持续资源源码/隔离验收；GPU 温度缺失按用户明确豁免保持未测，生产部署另属 A1。
  - [x] S4a：共享推理租约、串行执行、取消/故障释放和隔离实机正确性完成；未部署，不代表 S4b 完成。
  - [x] S4b：96 轮/1200 秒串行候选负载下的 nvmap/PSS/队列/时延与 CPU/SoC/Tj 稳定性验证，256 MiB CPU prompt-cache 上限及精确清理完成。GPU 温度 240/240 缺失依用户明确决定不阻塞；不宣称独立 GPU 温度已验证。见 [S4b 验证](GPU_RESOURCE_S4B_VALIDATION_2026-09-06.md)。
- [x] S5：Runner 工程识别执行、人工批准、预算/audit、联合 stop、自动 Spark 回灌及固定回归完成源码与有限实机验证；精确清理完成，生产能力仍为 false。见 [S5 验证](RUNNER_RECOGNITION_S5_VALIDATION_2026-09-06.md)。
- [x] S6：用户识别结果源码及隔离验收交付（S6a/S6b）；生产部署另属 A1。
  - [x] S6a：完整结果保存/恢复/查看/删除完成源码及隔离 replay/演示验证；复用应用 SQLite，不额外保留 IQ，未部署。
  - [x] S6b：S5 后真实闭环、浏览器结果和 Spark 紧凑摘要验收及精确清理完成，未部署。见 [S6b 验证](WEB_RECOGNITION_S6B_VALIDATION_2026-09-06.md)。
- [ ] V1：RF-v1 独立数据证据准备。
  - [x] V1a：版本化派生、独立证据接入、采样/覆盖/校准与验收分组规范完成；隔离 HTTP/浏览器/删除及失败清理验证通过，未部署。
  - [ ] V1b：获得并审核足够的独立 known-RF/OOD 标签；实际覆盖达到预注册条件。
- [ ] V2：根据 validation 和独立证据冻结校准/拒识，并完成独立验收。
- [ ] V3：标签空间与模型准入。
  - [ ] V3a：解决数字 ID/文本名称映射证据问题；解决前文本仍 provisional。
  - [ ] V3b：规则冻结后执行一次 locked test；不得用 test 反复调参。
- [ ] A1：production profile、可回滚部署、RX-only 矩阵验收和真实正向 capability。
- [ ] O1：持续运行和运维。
  - [x] O1a：固定 seed 的故障/fuzz 矩阵、8 MiB×4 audit 轮转、只读健康/本地去重告警、发布校验与私有升级/回滚演练完成源码、隔离验证及清理。生产配置未安装；见 [O1a 验证](OPERATIONS_O1A_VALIDATION_2026-09-06.md)。
  - [ ] O1b：24 小时完整闭环 soak；不替代人工批准策略或自动触发决策。
- [ ] 第7章设备/辐射源身份识别：后续独立范围，不计入当前调制识别交付。

真实候选继续 `recognizer_available=false`。软件实现、隔离验证、安装部署和
科学准入分别记账；小项完成不能使仍缺其余条件的父项被勾选。

## 1. Agent/Harness and operator interface

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
      [`SDR_AGENT_AGX_RX_OWNERSHIP_CUTOVER_VALIDATION_2026-09-03.md`](SDR_AGENT_AGX_RX_OWNERSHIP_CUTOVER_VALIDATION_2026-09-03.md).

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
      [`SPARK_X25_AGX_INTEGRATION_VALIDATION_2026-09-02.md`](SPARK_X25_AGX_INTEGRATION_VALIDATION_2026-09-02.md).
- [x] Reuse the existing AGX loopback SearXNG service as a Spark-only bounded
      host search adapter with at most two searches, eight sources, a 15-second
      timeout, a 512 KiB response limit, no redirects or arbitrary result fetch,
      untrusted-evidence prompting, Web-visible source events and unchanged
      Rust/SDR authority; live model and browser validation is recorded in
      [`SPARK_X25_WEB_SEARCH_VALIDATION_2026-09-02.md`](SPARK_X25_WEB_SEARCH_VALIDATION_2026-09-02.md).
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
- [x] Provide a top-bar gear beside LAN status that opens a separate settings
      page for model/API, context, compaction and initial-survey configuration;
      keep edits local until explicit save, warn on unsaved navigation, write
      the private file atomically as mode `0600`, and live-validate the deployed
      browser form and upstream settings readback.
- [x] Implement and unit-test AGX result persistence with SQLite summary/index
      rows, one optional per-scan `ci16_le` SigMF dataset pair, a manually saved
      raw-IQ switch, strict capture-root validation, and an operator delete path
      that removes only the indexed result and its managed files.
- [x] Implement the top-level current-sweep card as an entry to a dedicated
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
      [`SDR_AGENT_AGX_INLINE_RESULTS_VALIDATION_2026-09-01.md`](SDR_AGENT_AGX_INLINE_RESULTS_VALIDATION_2026-09-01.md).
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
      [`SDR_AGENT_TERMINAL_STREAMING_INPUT_VALIDATION_2026-09-03.md`](SDR_AGENT_TERMINAL_STREAMING_INPUT_VALIDATION_2026-09-03.md).
- [x] Persist and resume bounded interactive terminal history after normal or
      unexpected exit and Planner restart, using atomic owner-only state,
      hard file/message/context/age limits, and conversation-only restoration
      that excludes approvals, plans, actions, queues and old generations; see
      [`SDR_AGENT_TERMINAL_SESSION_RESUME_VALIDATION_2026-09-03.md`](SDR_AGENT_TERMINAL_SESSION_RESUME_VALIDATION_2026-09-03.md).
- [x] Enforce the explicitly selected single-trusted-operator model: retain at
      most two bounded Web conversation histories for that same operator, run
      only one active interactive Controller, reject a second `session.sock`
      connection, reject commands against an inactive conversation, and keep
      the existing global inference and SDR ownership gates. Multi-user
      identity, authorization and concurrent-control isolation are not project
      requirements; see
      [`SDR_AGENT_SINGLE_OPERATOR_SESSION_VALIDATION_2026-09-03.md`](SDR_AGENT_SINGLE_OPERATOR_SESSION_VALIDATION_2026-09-03.md).
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
      [`AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md`](AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md).
- [ ] Extend the Web and terminal receive-only observation views to render
      classified/rejected/unavailable/error, numeric label identity, trusted or
      provisional name, calibrated confidence/rejection reason, source,
      model/profile identity, quality and timing without exposing IQ paths or
      tensors.
  - [x] S6a archive views: Web result-type selection and local terminal client
        show provenance, four inert demo states, candidate replay/unavailable,
        numeric/name trust, confidence calibration, source/model identity,
        quality/timing and manual deletion. Native browser/CLI and cleanup passed;
        see [`RECOGNITION_ARCHIVE_S6A_VALIDATION_2026-09-06.md`](RECOGNITION_ARCHIVE_S6A_VALIDATION_2026-09-06.md).
  - [x] S5: native live receive-loop terminal observation, joined execution,
        engineering archive and automatic compact Spark feedback passed finite
        real validation and cleanup; installed services remain unchanged.
  - [x] S6b: actual browser approval/RX/Worker/Spark loop, exact result links,
        recovery without replay and manual delete passed; real unavailable/error
        and explicitly synthetic classified/rejected remain distinguished. See
        [S6b validation](WEB_RECOGNITION_S6B_VALIDATION_2026-09-06.md).
  - [ ] A1: deploy and validate the admitted production result views.
- [x] Persist full bounded recognition records in the application result store
      and add a visible per-record manual-delete path without retaining IQ by
      default. S6a reuses the existing SQLite file, revalidates full S2 records,
      bounds pagination, rejects conflicting/forged imports, and verifies restart
      restoration and per-record deletion without touching capture/corpus/IQ.
      Source and isolated native acceptance only; installed services unchanged.
      See [`RECOGNITION_ARCHIVE_S6A_VALIDATION_2026-09-06.md`](RECOGNITION_ARCHIVE_S6A_VALIDATION_2026-09-06.md).
- [x] S5 isolated live Spark validation: only the compact real unavailable
      observation enters one automatic feedback turn, explaining missing admission
      and producing a Rust-validated hold without claiming an unlabeled class.
      Explicit synthetic error/classified/rejected regression remains nonproduction.
      See [S5 validation](RUNNER_RECOGNITION_S5_VALIDATION_2026-09-06.md).

Evidence:

- [`AGX_SDRHARNESS_MIGRATION.md`](AGX_SDRHARNESS_MIGRATION.md)
- [`AGX_FRAMEWORK_VALIDATION_2026-09-01.md`](AGX_FRAMEWORK_VALIDATION_2026-09-01.md)
- [`SDR_AGENT_RUNTIME_DESIGN.md`](SDR_AGENT_RUNTIME_DESIGN.md)
- [`SDR_AGENT_TERMINAL_DEPLOYMENT_2026-08-31.md`](SDR_AGENT_TERMINAL_DEPLOYMENT_2026-08-31.md)
- [`SDR_AGENT_EXECUTOR_DEPLOYMENT_2026-08-31.md`](SDR_AGENT_EXECUTOR_DEPLOYMENT_2026-08-31.md)
- [`SDR_AGENT_WEB_CONSOLE_DEPLOYMENT_2026-09-01.md`](SDR_AGENT_WEB_CONSOLE_DEPLOYMENT_2026-09-01.md)
- [`SDR_AGENT_INITIAL_SURVEY_SETTINGS_VALIDATION_2026-09-01.md`](SDR_AGENT_INITIAL_SURVEY_SETTINGS_VALIDATION_2026-09-01.md)
- [`SDR_AGENT_AUTOMATIC_SURVEY_VALIDATION_2026-09-01.md`](SDR_AGENT_AUTOMATIC_SURVEY_VALIDATION_2026-09-01.md)
- [`SDR_AGENT_CANDIDATE_INSPECTION_VALIDATION_2026-09-01.md`](SDR_AGENT_CANDIDATE_INSPECTION_VALIDATION_2026-09-01.md)
- [`SDR_AGENT_AGX_RX_OWNERSHIP_CUTOVER_VALIDATION_2026-09-03.md`](SDR_AGENT_AGX_RX_OWNERSHIP_CUTOVER_VALIDATION_2026-09-03.md)
- [`SDR_AGENT_TERMINAL_STREAMING_INPUT_VALIDATION_2026-09-03.md`](SDR_AGENT_TERMINAL_STREAMING_INPUT_VALIDATION_2026-09-03.md)
- [`SDR_AGENT_TERMINAL_SESSION_RESUME_VALIDATION_2026-09-03.md`](SDR_AGENT_TERMINAL_SESSION_RESUME_VALIDATION_2026-09-03.md)
- [`SDR_AGENT_SINGLE_OPERATOR_SESSION_VALIDATION_2026-09-03.md`](SDR_AGENT_SINGLE_OPERATOR_SESSION_VALIDATION_2026-09-03.md)
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
      [`P201_AGX_RX_PROFILE_VALIDATION_2026-09-02.md`](P201_AGX_RX_PROFILE_VALIDATION_2026-09-02.md).
- [x] Complete automatic `survey_band` execution and feed its compact CPU sweep
      observation into the next Planner turn. The bounded AGX CPU path was
      live-validated receive-only with the real P201 SDR and OpenCode Go model,
      including fixed gain, byte/step accounting, candidate feedback, zero
      clipping and verified radio restoration; see
      [`SDR_AGENT_AUTOMATIC_SURVEY_VALIDATION_2026-09-01.md`](SDR_AGENT_AUTOMATIC_SURVEY_VALIDATION_2026-09-01.md).
- [x] Execute a current `inspect_candidate` proposal through the fixed-gain,
      no-file software power-summary path in both step-approval and automatic
      dispatch modes. The real SDR/OpenCode Go manual-approval path was
      live-validated with candidate feedback, zero clipping and restoration;
      see
      [`SDR_AGENT_CANDIDATE_INSPECTION_VALIDATION_2026-09-01.md`](SDR_AGENT_CANDIDATE_INSPECTION_VALIDATION_2026-09-01.md).
- [x] Render every Rust-validated proposal as a visible Agent reply, use
      language-matched `hold.reason` replies for non-hardware conversation,
      expose the manual approval gate for single surveys, and accept the
      declared SDRD `software_summary` capability in bounded-IQ execution. The
      real Web/OpenCode Go/P201 paths and exact delivery cleanup passed; see
      [`SDR_AGENT_REPLY_AND_CAPTURE_COMPAT_VALIDATION_2026-09-01.md`](SDR_AGENT_REPLY_AND_CAPTURE_COMPAT_VALIDATION_2026-09-01.md).
- [x] Persist typed candidate observations independently of terminal history,
      restore them through a validated mode-`0600` runtime PlanningContext after
      Web restart, and bound textual carry-forward to one 1,024-byte terminal
      command.
- [x] Extend and deploy the stateless one-shot Runner to execute real
      `survey_band` and `inspect_candidate` actions through the existing AGX
      software `SweepEngine`, return the aggregate plus a fresh Planner
      observation, re-observe restored SDR health, and append the correlated
      proposal/validation/authorization/result JSONL audit chain; see
      [`SDR_AGENT_ONESHOT_SWEEP_INSPECTION_VALIDATION_2026-09-03.md`](SDR_AGENT_ONESHOT_SWEEP_INSPECTION_VALIDATION_2026-09-03.md).
- [x] Persist a root-only JSONL audit record joining operator input,
      model/provider, raw proposal, Rust validation, approval, execution and the
      resulting observation, including fail-closed planning attempts.
- [x] Validate reconnect, cancellation, stale-result, timeout, and partial-action
      recovery for the complete loop, including real Spark/P201 Planner and IIO
      timeouts, direct cancellation after a partial sweep, SDRD loss/recovery,
      model abort/generation invalidation, stale-result tests and daemon survival
      after a client transport timeout; see
      [`SDR_AGENT_COMPLETE_LOOP_FAULT_RECOVERY_VALIDATION_2026-09-03.md`](SDR_AGENT_COMPLETE_LOOP_FAULT_RECOVERY_VALIDATION_2026-09-03.md).
- [x] Implement S1 capability sourcing in plain Controller, one-shot Runner,
      raw execute and terminal prompt/queue/proposal/feedback/approval paths:
      replace request/template self-assertion with a bounded current Worker and
      local admission-receipt probe; fail closed on missing/stale/mismatched
      evidence, Worker restart or receipt changes in the same generation.
      Source tests and isolated real epoch-10 Worker health validation passed;
      the candidate stayed unavailable and all feature processes/data/builds
      were cleaned. See
      [`RECOGNIZER_ADMISSION_S1_VALIDATION_2026-09-06.md`](RECOGNIZER_ADMISSION_S1_VALIDATION_2026-09-06.md).
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
      See [S5 validation](RUNNER_RECOGNITION_S5_VALIDATION_2026-09-06.md).

Evidence:

- [`SDR_AGENT_ONESHOT_SWEEP_INSPECTION_VALIDATION_2026-09-03.md`](SDR_AGENT_ONESHOT_SWEEP_INSPECTION_VALIDATION_2026-09-03.md)
- [`SDR_AGENT_COMPLETE_LOOP_FAULT_RECOVERY_VALIDATION_2026-09-03.md`](SDR_AGENT_COMPLETE_LOOP_FAULT_RECOVERY_VALIDATION_2026-09-03.md)
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
      [`SDR_AGENT_EXECUTION_METADATA_TIMEOUT_VALIDATION_2026-09-03.md`](SDR_AGENT_EXECUTION_METADATA_TIMEOUT_VALIDATION_2026-09-03.md).
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
      [`SDR_AGENT_AGX_INLINE_RESULTS_VALIDATION_2026-09-01.md`](SDR_AGENT_AGX_INLINE_RESULTS_VALIDATION_2026-09-01.md).
- [x] Implement and live-validate bounded no-file `CAPTURE_POWER` summaries and
      fixed manual-gain profiles with per-point numeric gain readback, clipping
      metadata, cancellation, and saved AGC/gain restoration.
- [x] Implement and live-validate direct in-flight cancel in `sdrd`.
- [x] Implement and live-validate explicit post-action stop, buffer teardown,
      and state restoration.
- [x] Add Adapter-produced sequence, overflow, dropped-sample, timeout, health,
      request and session-generation metadata to all execution results and
      preserve failure metadata through AGX errors/audit; see
      [`SDR_AGENT_EXECUTION_METADATA_TIMEOUT_VALIDATION_2026-09-03.md`](SDR_AGENT_EXECUTION_METADATA_TIMEOUT_VALIDATION_2026-09-03.md).
- [x] Deploy controlled `sdrd` with a private-link listener, retained `/sd`
      release, tested stop path,
      bounded live capture and verified state restoration.
- [x] Design and validate safe persistent `sdrd` startup after reboot without
      modifying the boot image:
  - [x] Deploy and live-validate the AGX recovery oneshot/timer, strict
        duplicate-instance gates, normal start, idle abnormal-exit recovery,
        concurrent-start rejection, current-boot persistence and rollback;
        see
        [`SDR_AGENT_SDRD_STARTUP_RECOVERY_VALIDATION_2026-09-03.md`](SDR_AGENT_SDRD_STARTUP_RECOVERY_VALIDATION_2026-09-03.md).
  - [x] Remove the manual host-key repin after a P201 reboot by explicitly
        authorized initialization of only the 917,504-byte vendor QSPI `mtd2`
        JFFS2 partition, persisting only the verified ECDSA key plus its minimal
        manifest, retaining a byte-exact root-only rollback image, and proving
        an unchanged global pin across a real reboot plus subsequent idle-daemon
        recovery; see
        [`SDR_AGENT_P201_PERSISTENT_HOST_KEY_VALIDATION_2026-09-03.md`](SDR_AGENT_P201_PERSISTENT_HOST_KEY_VALIDATION_2026-09-03.md).
- [x] Complete a full 1,800-second long-duration reconnect and fault-recovery
      test on the real SDR, covering 100 bounded acquisitions, three
      profile-applied client disconnects, two idle-daemon timer recoveries,
      transport and IIO timeouts, direct partial-action cancellation,
      duplicate-start rejection, sequence/metadata/resource/thermal accounting
      and verified final restoration; see
      [`SDR_AGENT_SDRD_LONG_RECONNECT_FAULT_RECOVERY_VALIDATION_2026-09-03.md`](SDR_AGENT_SDRD_LONG_RECONNECT_FAULT_RECOVERY_VALIDATION_2026-09-03.md).
- [x] Make the fixed production physical input `RX1 / A_BALANCED` a probed,
      audited and fail-closed SDRD/1 identity, return it with profile/capture or
      health metadata, and verify that it is unchanged on every exit path
      without exposing a Planner-selectable port write. The Adapter now reads
      and strictly verifies `voltage0/rf_port_select=A_BALANCED`, correlates it
      with the software RX0 `voltage0,1` I/Q pair and front-panel RX1, and never
      writes the selector. It was deployed and live-validated with exact identity
      propagation, fail-closed mismatch tests, bounded RX, disconnect
      restoration and transient cleanup; see
      [`P201_RX1_INPUT_IDENTITY_VALIDATION_2026-09-04.md`](P201_RX1_INPUT_IDENTITY_VALIDATION_2026-09-04.md).

Evidence:

- [`../sdr-system/docs/BASELINE_2026-08-31.md`](../sdr-system/docs/BASELINE_2026-08-31.md)
- [`../sdr-system/docs/SDRD_SHADOW_VALIDATION_2026-08-31.md`](../sdr-system/docs/SDRD_SHADOW_VALIDATION_2026-08-31.md)
- [`../sdr-system/docs/SDRD_CONTROLLED_INTERFACE_VALIDATION_2026-08-31.md`](../sdr-system/docs/SDRD_CONTROLLED_INTERFACE_VALIDATION_2026-08-31.md)
- [`../sdr-system/docs/SDRD_IIO_ADAPTER_VALIDATION_2026-08-31.md`](../sdr-system/docs/SDRD_IIO_ADAPTER_VALIDATION_2026-08-31.md)
- [`../sdr-system/docs/SDRD_PERSONAL_DEPLOYMENT_2026-09-01.md`](../sdr-system/docs/SDRD_PERSONAL_DEPLOYMENT_2026-09-01.md)
- [`SDR_AGENT_SDRD_OBSERVE_VALIDATION_2026-08-31.md`](SDR_AGENT_SDRD_OBSERVE_VALIDATION_2026-08-31.md)
- [`SDR_AGENT_CANCEL_VALIDATION_2026-09-01.md`](SDR_AGENT_CANCEL_VALIDATION_2026-09-01.md)
- [`SDR_AGENT_RUNNER_DEPLOYMENT_2026-09-01.md`](SDR_AGENT_RUNNER_DEPLOYMENT_2026-09-01.md)
- [`SDR_AGENT_INITIAL_SURVEY_SETTINGS_VALIDATION_2026-09-01.md`](SDR_AGENT_INITIAL_SURVEY_SETTINGS_VALIDATION_2026-09-01.md)
- [`SDR_AGENT_P201_HOST_KEY_PERSISTENCE_INVESTIGATION_2026-09-03.md`](SDR_AGENT_P201_HOST_KEY_PERSISTENCE_INVESTIGATION_2026-09-03.md)
- [`SDR_AGENT_P201_PERSISTENT_HOST_KEY_VALIDATION_2026-09-03.md`](SDR_AGENT_P201_PERSISTENT_HOST_KEY_VALIDATION_2026-09-03.md)
- [`SDR_AGENT_SDRD_LONG_RECONNECT_FAULT_RECOVERY_VALIDATION_2026-09-03.md`](SDR_AGENT_SDRD_LONG_RECONNECT_FAULT_RECOVERY_VALIDATION_2026-09-03.md)
- [`P201_RX1_INPUT_IDENTITY_VALIDATION_2026-09-04.md`](P201_RX1_INPUT_IDENTITY_VALIDATION_2026-09-04.md)
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
      [`SDR_AGENT_AGX_INLINE_RESULTS_VALIDATION_2026-09-01.md`](SDR_AGENT_AGX_INLINE_RESULTS_VALIDATION_2026-09-01.md).
- [x] Characterize the current P201/AGX bounded receive profile without raw-IQ
      retention: 2.1–30.72 MS/s profiles applied and restored, but legacy power
      processing reached only about 7 MS/s and base64 inline transport only
      about 1.87 Mb/s. Keep sustained-operation claims limited to this measured
      baseline; see
      [`P201_AGX_RX_PROFILE_VALIDATION_2026-09-02.md`](P201_AGX_RX_PROFILE_VALIDATION_2026-09-02.md).
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
      [`NX_B210_P201_RX1_LINK_VALIDATION_2026-09-04.md`](NX_B210_P201_RX1_LINK_VALIDATION_2026-09-04.md).
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
        [`NX_B210_RML_2440_VALIDATION_2026-09-06.md`](NX_B210_RML_2440_VALIDATION_2026-09-06.md).
  - [x] User confirmed antenna ports; ten-second historical-tone and registered
        RML retries at 2.440 GHz completed, with six clean bounded RX captures,
        restoration and exact cleanup. The tone rose 44.799/34.319 dB over the
        same-bin TX-off controls; source-derived-band, fixed-lag RML correlation
        was 0.772 versus 0.009/-0.021. Original broadband failure remains recorded;
        this is exploratory engineering evidence, not independent RF labels,
        model accuracy or production admission. Eight software tests passed. See
        [`NX_B210_RML_2440_EXTENDED_VALIDATION_2026-09-06.md`](NX_B210_RML_2440_EXTENDED_VALIDATION_2026-09-06.md).
- [ ] Complete the registered B210/P201 RF-v1 pilot with accepted RF controls
      and source association as well as received-result integration.
  - [x] Hash-bound received RF-v1 replay, real frozen Worker, S2/S6a archive,
        legacy/RF-v1 corpus lineage and existing delete APIs isolated-validated
        using one authorized 2.440 GHz B210/P201 pilot; tests and exact cleanup
        complete. No production deployment or independent labels. See
        [pilot validation](B210_P201_RF_V1_PILOT_VALIDATION_2026-09-06.md).
  - [x] Separate RX40 engineering controls and user-requested paired source/RX
        model diagnostic completed: tone/RML TX-off checks pass fixed gates;
        original and aligned source predict ID 0, unmodified received IQ ID 18.
        NX child-query compatibility, finite stop/cleanup, 17 tests and exact
        feature cleanup verified. This is not RF-v1 50 dB acceptance or V1b.
        See [RX40 paired validation](B210_P201_RX40_PAIRED_VALIDATION_2026-09-06.md).
  - [x] Offline single-source sensitivity to historical ±3.53 kHz CFO, +90°
        phase and fixed-realization added AWGN ratios 20/10 dB tested: all seven
        cases remain ID 0; both source baseline mean-logit hashes reproduce.
        Preserve this negative result, not an exclusion of actual RF impairments.
        22 tests, bounded AGX inference and exact cleanup completed. See
        [source sensitivity validation](B210_SOURCE_SENSITIVITY_VALIDATION_2026-09-06.md).
  - [x] New bounded RX40 fidelity/compensation matrix completed: source controls
        pass; original/CFO/band/CFO+band received cases all remain ID 18 while
        source controls remain ID 0. Constant-phase case skipped by its gate;
        raised low-amplitude envelope and posthoc residual phase drift retained
        as hypotheses, not a fix. 29 tests, 24 model windows and exact cleanup
        verified. See [RX fidelity validation](B210_RX_FIDELITY_VALIDATION_2026-09-06.md).
  - [x] Prefix-only complex gain/bias diagnostic tools and bounded RX40 posthoc
        exploration completed. Original source-envelope gate failed (0.340 < 0.5)
        and remains failed; explicit exploration produced source+b ID 0→18 and
        received-b aggregate ID 18→0, with two received windows still ID 2.
        35 tests, 28 experimental model windows, radio restoration and exact
        AGX/NX feature cleanup verified. This is known-source exploration, not
        blind compensation, hardware root-cause attribution or production repair.
        See [affine exploration validation](B210_RX_AFFINE_VALIDATION_2026-09-06.md).
  - [ ] Qualify the source-reference bidirectional bias validation: the original
        source-association gate failed; exploratory improvements cannot replace
        that prerequisite. Register an appropriate independent source-association
        check before a new bounded validation; retain this run's failed gate.
    - [x] Implement and evaluate a separate centered-complex v2 numerical
          candidate with raw-prefix/heldout FFT isolation and same-spectrum
          wrong-source controls. 44 software tests and cleanup verified;
          candidate acceptance failed: 22/24 synthetic positives accepted,
          0/24 wrong sources accepted. No RF/model/dataset operations. See
          [centered-source validation](B210_CENTERED_SOURCE_VALIDATION_2026-09-06.md).
    - [x] Implement v3 searched, spectrum-matched source/wrong-source contrast;
          resolve both old false rejections while preserving v2 failures. Run
          the preregistered 72-positive/72-negative matrix once: 70 positives
          accepted, no negatives accepted; full candidate acceptance still
          fails on two 32-kHz stopped-noise controls. 49 software tests and
          exact cleanup verified; see
          [source v3 validation](B210_SOURCE_V3_VALIDATION_2026-09-06.md).
    - [x] Implement v4 stopped-control bounds from spectral overlap under an
          explicit independent Fourier-phase noise assumption, using per-window
          FFTs and a 16-window union bound. One preregistered independent matrix
          accepts 72/72 synthetic sources and 0/72 wrong sources; 56 software
          tests and exact cleanup pass. This qualifies only the numerical
          candidate, not live RF or production calibration; see
          [source v4 validation](B210_SOURCE_V4_VALIDATION_2026-09-06.md).
    - [x] Integrate fixed v4 with sealed raw/report/SigMF/source identity and
          model preflight; execute the registered 2.440-GHz RX40 tone/RML pair.
          Six bounded captures pass native quality/identity and restoration checks, but source
          qualification fails on window 15 (coherence 0.413 < 0.6) amid short
          raw-power excursions; no model/warmup ran. 64 tests and exact AGX/NX
          cleanup complete; see
          [v4 live validation](B210_V4_LIVE_VALIDATION_2026-09-06.md).
    - [x] User-requested single-1024-sample source is the new export default;
          versioned 20,480 complete-unit TX, sealed six-capture input and all
          65,535 pointwise I/Q/residual rows verified. Preserve all 512 segment
          summaries, source/carrier/DC separation, fixed-prefix scalar/FIR
          comparisons and explicitly posthoc fractional-delay diagnostics.
          76 software tests, real RX restoration and exact cleanup complete; see
          [1024 pointwise validation](B210_1024_POINTWISE_VALIDATION_2026-09-06.md).
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
          [LO-offset validation](B210_LO_OFFSET_VALIDATION_2026-09-06.md).
    - [ ] Identify remaining time-varying phase and stopped/background excursions;
          LO separation does not remove these effects or establish their origin.
      - [x] Characterize retained bursts and execute a registered 30-point RX-only
            frequency comparison: discovery selects 2455 MHz once; independent
            confirmation reduces peak background versus 2440 MHz but fails all
            three absolute quiet-background checks. Preserve the failure and all
            statistics, with no protocol/hardware-cause or classification claim.
            96 tests, real restoration, precise cleanup and six inventoried
            confirmation captures (~1.6 MB) verified; see
            [background validation](B210_BACKGROUND_VALIDATION_2026-09-07.md).
    - [x] Implement and live-validate an engineering +250-kHz LO / fixed 257-tap
          FIR rejection path: two captures suppress the LO band by 94.63/94.75 dB,
          preserve 99.9066% source power and show fixed-window source coherence
          0.997–0.999. Zero-offset rejection is approximately 0 dB. All three
          registered model blocks fail stopped-background gates, so model/warmup
          remain 0; this is not production RF-v1 or classification repair.
          89 tests and independent verification of 587,511 filtered samples pass.
          Non-evidence data and NX/P201 copies cleaned; per the new operator
          retention rule, 53 inventoried files (~3.3 MB) remain for sealed replay.
          See [LO rejection validation](B210_LO_REJECTION_VALIDATION_2026-09-07.md)
          and [retained evidence](B210_LO_REJECTION_EVIDENCE_2026-09-07.json).
    - [x] Complete the registered 2455-MHz 1024-source amplitude ABBA comparison
          (.2/.3/.3/.2), with explicit version-4 source lineage and strict center
          binding. One fixed low1 block passes source/background controls; source,
          filtered source, raw RX and FIR RX all predict ID 0 in all four windows.
          16 experimental model windows + 2 warmups, 101 software tests, 15 real
          captures/restorations and precise cleanup verified; 67 inventoried files
          (~4.1 MB) retain the complete success/failure matrix. See
          [2455 margin validation](B210_2455_MARGIN_VALIDATION_2026-09-07.md).
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
            [failure decomposition](B210_FAILURE_DECOMPOSITION_VALIDATION_2026-09-07.md).
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
      [`P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md`](P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md).
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
      [`P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md`](P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md).
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
      [`P201_MAMBA_BATCH_FAILURE_CANCEL_VALIDATION_2026-09-05.md`](P201_MAMBA_BATCH_FAILURE_CANCEL_VALIDATION_2026-09-05.md).
- [x] Freeze `rf_preprocess_v1` using train/validation and versioned unknown
      P201 evidence: hardware retune, no digital shift/filter/resampling, DC
      retained, shared 4,096-sample complex RMS, four contiguous 1,024-sample
      windows and mean logits. Selection did not open test; see
      [`RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md`](RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md).
- [x] Implement the independently hash-pinned integration-only RF-v1 runtime
      profile with shared-capture RMS and ordered float32 windows, reproduce the
      frozen offline golden bytes exactly, and live-validate the epoch-10 FP16
      Worker/full-logit AGX aggregation path. Success, Worker exit and direct
      capture cancel restore P201 RX1 and remove spool; all feature processes,
      ten P201 transient directories, three AGX feature roots and build staging
      were cleaned and verified. See
      [`RF_V1_RUNTIME_PARITY_VALIDATION_2026-09-05.md`](RF_V1_RUNTIME_PARITY_VALIDATION_2026-09-05.md).
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
      [`SDR_AGENT_SDRD_LONG_RECONNECT_FAULT_RECOVERY_VALIDATION_2026-09-03.md`](SDR_AGENT_SDRD_LONG_RECONNECT_FAULT_RECOVERY_VALIDATION_2026-09-03.md).
- [x] Complete bounded AGX software-acquisition overload testing: reject a
      278,528-byte point before backend/radio work, process 128 consecutive
      262,144-byte windows (32 MiB total) with continuous sequences and zero
      drop/overflow/clipping/timeout/health failures, bound AGX/P201 resources,
      and prove both IIO-deadline and client-disconnect restoration followed by
      a fresh successful generation; see
      [`P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md`](P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md).

Evidence:

- [`SDR_PREPROCESSING_SWEEP_ARCHITECTURE.md`](SDR_PREPROCESSING_SWEEP_ARCHITECTURE.md)
- [`../raspberry-pi/p201pro-rust/TEST_RESULTS.md`](../raspberry-pi/p201pro-rust/TEST_RESULTS.md)
- [`PI_SOFTWARE_SWEEP_FALLBACK_2026-09-01.md`](PI_SOFTWARE_SWEEP_FALLBACK_2026-09-01.md)
- [`SDR_AGENT_INITIAL_SURVEY_SETTINGS_VALIDATION_2026-09-01.md`](SDR_AGENT_INITIAL_SURVEY_SETTINGS_VALIDATION_2026-09-01.md)
- [`NX_B210_P201_RX1_LINK_VALIDATION_2026-09-04.md`](NX_B210_P201_RX1_LINK_VALIDATION_2026-09-04.md)
- [`P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md`](P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md)
- [`P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md`](P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md)
- [`P201_MAMBA_BATCH_FAILURE_CANCEL_VALIDATION_2026-09-05.md`](P201_MAMBA_BATCH_FAILURE_CANCEL_VALIDATION_2026-09-05.md)
- [`P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md`](P201_AGX_SOFTWARE_ACQUISITION_OVERLOAD_VALIDATION_2026-09-05.md)
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
      [`AMC_CORPUS_MANIFEST_V1.md`](AMC_CORPUS_MANIFEST_V1.md) and
      [`AMC_CORPUS_CONTRACT_VALIDATION_2026-09-05.md`](AMC_CORPUS_CONTRACT_VALIDATION_2026-09-05.md).
- [x] Build a bounded, versioned P201 receive-only corpus with session/date,
      center, rate, bandwidth, fixed RF input, gain, samples/bytes, quality and
      cleanup metadata; provide a visible manual-delete path and keep bulk IQ
      outside Git. The application-owned SQLite/package store rejects nonlocal
      writes, metadata/IQ mismatches and incomplete cleanup; a 4,096-sample
      RX1 row was live-captured, reference-validated, visibly deleted and then
      restored as an `unknown` application result; see
      [`P201_RX_CORPUS_STORE_VALIDATION_2026-09-05.md`](P201_RX_CORPUS_STORE_VALIDATION_2026-09-05.md).
- [x] Prove train/validation/test isolation by source sample, capture session
      and UTC day so crops, augmentation or repeated receptions of one source
      do not cross splits. Both complete retained split files have unique,
      in-range, fully covering global-row assignments with zero pairwise
      intersections; the cross-package P201 audit enforces parent inheritance,
      all three group keys and `receive_domain` for unknown receptions. See
      [`AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md`](AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md).
- [x] Pre-register and use only train statistics, complete validation groups and
      versioned `receive_domain/unknown` evidence to freeze the
      `rf_preprocess_v1` retraining contract: 2.1 MS/s without software
      resampling/frequency shift, DC retained, one RMS scale across four
      contiguous 1,024-sample windows, and mean-logit aggregation. The selection
      code never loaded the test member/result; labeled validation accuracy and
      unlabeled P201 quality/confidence remained separate. See
      [`RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md`](RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md).
- [x] Receive the user-trained epoch-10 RF-aligned checkpoint, retain its full
      147-entry provenance map in an isolated ignored AGX asset directory, and
      strictly evaluate all 95,607 grouped validation examples in FP32:
      aggregate accuracy matched the 4090 exactly at `0.6705575952` and NLL
      differed by only `6.8e-8`; test remained unopened and capability false. See
      [`RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md`](RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md).
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
      cleaned. See [`RF_V1_EVIDENCE_V1A_VALIDATION_2026-09-06.md`](RF_V1_EVIDENCE_V1A_VALIDATION_2026-09-06.md).
- [x] Pre-register the known-RF/OOD coverage and sampling rationale plus separate
      calibration and acceptance groups before fitting thresholds; track label
      evidence, ambiguous cases and class/name mapping without opening the
      locked test. The specification is
      [`RF_V1_KNOWN_RF_OOD_SAMPLING_V1.md`](RF_V1_KNOWN_RF_OOD_SAMPLING_V1.md),
      with clustered/effective sample-size rationale and explicit coverage gaps.
      This completes the tools/specification gate only; actual independently
      reviewed coverage remains V1b, not supplied by unknown receptions.
- [ ] Use independently labeled known-RF/OOD evidence with the final checkpoint
      to freeze scalar calibration plus confidence/agreement/SNR/bandwidth
      acceptance thresholds, then perform one locked test admission. The new
      validation-only temperature candidate `1.34647` remains non-production.
- [ ] Resolve the RML2018A numeric-ID/name-order dispute; until then, retain the
      numeric ID as trusted identity and mark every text name provisional.

Evidence:

- [`FPGA_RETIREMENT_DECISION_2026-09-02.md`](FPGA_RETIREMENT_DECISION_2026-09-02.md)
- [`NX_B210_MAMBA_D8_ASSET_HANDOFF.md`](NX_B210_MAMBA_D8_ASSET_HANDOFF.md)
- [`AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md`](AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md)
- [`P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md`](P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md)
- [`AMC_CORPUS_MANIFEST_V1.md`](AMC_CORPUS_MANIFEST_V1.md)
- [`AMC_CORPUS_CONTRACT_VALIDATION_2026-09-05.md`](AMC_CORPUS_CONTRACT_VALIDATION_2026-09-05.md)
- [`P201_RX_CORPUS_STORE_VALIDATION_2026-09-05.md`](P201_RX_CORPUS_STORE_VALIDATION_2026-09-05.md)
- [`AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md`](AMC_SPLIT_ISOLATION_VALIDATION_2026-09-05.md)
- [`RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md`](RF_PREPROCESS_V1_SELECTION_VALIDATION_2026-09-05.md)
- [`RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md`](RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md)
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
      [`NX_B210_MAMBA_D8_ASSET_HANDOFF.md`](NX_B210_MAMBA_D8_ASSET_HANDOFF.md).
- [x] Stage RML2018A seed44 and HisarMod2019 seed43 with their exact clean D8
      inference source, fixed splits and datasets under the ignored AGX-local
      asset root; strictly load both checkpoints and reproduce both complete
      FP32 test sets. Evidence:
      [`AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md`](AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md).
- [x] Retain seed44 as an experimental baseline and receive the user's
      validation-selected RF-aligned epoch-10 fine-tuned checkpoint using the
      exact frozen Chapter 4 `rf_preprocess_v1`. Its source, split, preprocessing,
      numeric labels, training config and checkpoint are pinned; strict AGX FP32
      loading and complete validation parity passed without opening test.
- [x] Select and hash-pin FP16 autocast for the epoch-10 validation candidate
      after complete FP32/FP16/BF16 comparison on AGX. This precision selection
      does not promote the checkpoint or enable runtime capability; see
      [`RF_V1_PRECISION_SELECTION_VALIDATION_2026-09-05.md`](RF_V1_PRECISION_SELECTION_VALIDATION_2026-09-05.md).
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
      [`P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md`](P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md).
- [x] Run the RF-aligned epoch-10 Worker with FP32 resident weights and the
      frozen FP16 autocast, return all 24 FP32 logits per ordered window, and
      aggregate them using float64 arithmetic mean followed by softmax on AGX.
      Strict request/source/capture/session/profile/preprocess/checkpoint/batch
      correlation, finite full-logit shape, replay/order rejection and bounded
      cancellation cleanup passed unit and live RX-only validation. Keep all
      probabilities uncalibrated, numeric IDs authoritative, names provisional
      and capability false; see
      [`RF_V1_RUNTIME_PARITY_VALIDATION_2026-09-05.md`](RF_V1_RUNTIME_PARITY_VALIDATION_2026-09-05.md).
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
      [`AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md`](AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md).
- [ ] Measure production Worker queue drops, cancellation, concurrency and
      sustained thermal behavior.
  - [x] S3 lifecycle implementation and finite actual RF-v1 Worker validation:
        one active/four-window batch plus one waiting slot, whole-batch and
        independent queue deadlines, reserved control connections, confirmed
        cancellation, child/supervisor kill and restart fencing, exact orphan
        cleanup and bounded metrics. Rust replay/health/cancel and negative
        tests passed; feature processes and temporary data were removed. See
        [`WORKER_SUPERVISOR_S3_VALIDATION_2026-09-06.md`](WORKER_SUPERVISOR_S3_VALIDATION_2026-09-06.md).
  - [x] S4b: 20-minute representative serialized replay/Planner resource evidence
        and exact cleanup passed with the explicit user exception for unavailable
        GPU temperature; CPU/SoC/Tj, memory, queue and latency gates passed. See
        [S4b validation](GPU_RESOURCE_S4B_VALIDATION_2026-09-06.md).
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
        [`GPU_LEASE_S4A_VALIDATION_2026-09-06.md`](GPU_LEASE_S4A_VALIDATION_2026-09-06.md).
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
      [`RECOGNITION_RESULT_S2_VALIDATION_2026-09-06.md`](RECOGNITION_RESULT_S2_VALIDATION_2026-09-06.md).
      The dependent Web build omission was corrected separately after V1a audit
      exposed it; 20 isolated Web tests and Clippy pass. See
      [`RECOGNITION_RESULT_S2_WEB_CORRECTION_2026-09-06.md`](RECOGNITION_RESULT_S2_WEB_CORRECTION_2026-09-06.md).
- [x] Define and validate `recognizer_admission_v1`, bounded six-gate evidence
      receipts and challenge-correlated `recognizer_health_v1`, including full
      model/profile/preprocess/precision identity, Worker instance and time,
      receipt hashes, 250-ms socket deadlines and no stale-success fallback.
      The real candidate reports `production_enabled=false`; two actual Worker
      instances, status-only forgery and malformed enable requests were tested.
      See [`RECOGNIZER_ADMISSION_S1_VALIDATION_2026-09-06.md`](RECOGNIZER_ADMISSION_S1_VALIDATION_2026-09-06.md).
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

- [`LOCAL_RECOGNIZER_INTERFACE.md`](LOCAL_RECOGNIZER_INTERFACE.md)
- [`AGX_SDRHARNESS_MIGRATION.md`](AGX_SDRHARNESS_MIGRATION.md)
- [`NX_B210_MAMBA_D8_ASSET_HANDOFF.md`](NX_B210_MAMBA_D8_ASSET_HANDOFF.md)
- [`AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md`](AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md)
- [`AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md`](AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md)
- [`P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md`](P201_AGX_MAMBA_SEED44_MULTIWINDOW_INTEGRATION_VALIDATION_2026-09-04.md)
- [`P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md`](P201_AGX_MAMBA_EXPERIMENTAL_E2E_VALIDATION_2026-09-04.md)
- [`RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md`](RF_ALIGNED_CHECKPOINT_AGX_VALIDATION_2026-09-05.md)
- [`RF_V1_PRECISION_SELECTION_VALIDATION_2026-09-05.md`](RF_V1_PRECISION_SELECTION_VALIDATION_2026-09-05.md)
- [`CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md`](CHAPTER_1_6_RX_ONLY_IMPLEMENTATION_PLAN.md)

## 7. Emitter/radiation-source identification

- [ ] Define whether the first target is modulation class, protocol/family,
      transmitter model, or individual physical emitter identity.
- [ ] Define lawful collection scope, labels, calibration, channel conditions,
      train/test separation, and unknown-emitter handling.
- [ ] Build a real-device RF-fingerprint dataset covering repeat captures,
      frequencies, gains, temperatures, locations, and channel variation.
- [ ] Implement frequency-offset, phase-noise, transient, PA-nonlinearity, and
      other candidate fingerprint features or end-to-end representations.
- [ ] Establish open-set rejection and confidence calibration.
- [ ] Validate device-level confusion, cross-day generalization, channel
      robustness, spoofing risk, and conclusion limits.
- [ ] Integrate only after modulation recognition and the bounded capture path
      are stable.

## 8. Verification, deployment, and operations

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
- [x] Add and validate the project-local `p201-sdr-workflow` skill for bounded
      access, cross-build, deployment, duplicate-instance gating and cleanup.
- [x] O1a adds deterministic bounded mutation across application-owned protocol
      boundaries (11 targets × 256 cases), alongside actual socket malformed/
      oversized/stale/duplicate/truncated/reordered regressions. C ASan/UBSan and
      isolated native Web/Planner recovery passed; no third-party SSH/IIOD fuzz
      or exhaustive coverage claim. See [O1a validation](OPERATIONS_O1A_VALIDATION_2026-09-06.md).
- [x] O1a unifies repeatable upstream/model restart, SDRD disconnect, fake-radio
      timeout, explicit transport overflow/restore, and cancellation/generation
      fault checks; these deterministic tests do not replace A1 real RF acceptance.
- [ ] Run and document a complete 24-hour autonomous-loop soak test.
- [x] O1a defines and isolated-validates current AGX logging, read-only health/
      local alert transitions, immutable candidate release verification and
      upgrade/rollback procedures. P201 follows its existing deployment workflow
      and Pi stays standby; user results are excluded from log/rollback cleanup.
  - [ ] A1: install/validate production log and monitoring configuration plus
        admitted coordinated deployment/rollback; O1a did not replace services.

## Current next milestone

S1/S2/V1a/S3/S4a/S6a/S5/S6b/S4b/O1a source and isolated acceptance are complete.
S4b retains the explicit user exception for unavailable GPU temperature.
Installed services remain unchanged and the actual recognizer stays unavailable.
Next is V1b/V3a evidence readiness review, then V2 only when its independent
label/name prerequisites are satisfied; do not infer data coverage from tooling.
GPU temperature remains unmeasured; actual independent labels, calibration,
production deployment/admission and the 24-hour full-loop soak remain open.

Execution order, prerequisites and permitted scheduling changes are maintained
only in
[`SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md`](SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md).
Chapter numbering here is a status ledger, not an instruction to implement in
that order. Each delivery has its own verification and exact cleanup record.
