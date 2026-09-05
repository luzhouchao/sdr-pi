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
S2 及其 Web 依赖校验修正完成；V1a 工具/规范和隔离 Web 验证完成，生产服务未替换。

- [x] P201 RX1 有界采集/传输、停止、恢复、固定输入身份及长期重连验证完成（第3章）。
- [x] AGX 扫频/精查、结果存储和 RX 语料基础、split 隔离完成（第1/4/5章）。
- [x] RF-v1 预处理、用户训练 epoch-10 checkpoint 的 validation 和 FP16 选择完成。
- [x] 共享 RMS/四窗/full-logit/mean-logit runtime、golden 和有限实收故障清理完成。
- [x] S1：准入/health/人工批准源码、测试及隔离真实 Worker 验证完成；生产服务未替换。
- [x] S2：统一完整结果与 Planner 紧凑 observation、四状态/校准身份、RF-v1 batch 严格转换和真实报告 replay 完成；生产阈值未冻结，能力仍为 false。
- [ ] S3：生产 Worker 队列、整批 deadline、取消确认、强杀/重启清理和指标。
- [ ] S4：共享 GPU 调度与持续资源验收。
  - [ ] S4a：推理租约、串行执行、取消/故障释放和实机正确性。
  - [ ] S4b：最终代表性负载下的显存/RSS/队列/热稳定性证据。
- [ ] S5：Runner 识别执行、批准、预算/audit、联合 stop、Spark 回灌及固定 Planner 回归。
- [ ] S6：用户识别结果交付。
  - [ ] S6a：完整结果保存/恢复/查看/删除；可先用 replay 或明确实验结果验证。
  - [ ] S6b：S5 后真实闭环、浏览器结果和 Spark 紧凑摘要验收。
- [ ] V1：RF-v1 独立数据证据准备。
  - [x] V1a：版本化派生、独立证据接入、采样/覆盖/校准与验收分组规范完成；隔离 HTTP/浏览器/删除及失败清理验证通过，未部署。
  - [ ] V1b：获得并审核足够的独立 known-RF/OOD 标签；实际覆盖达到预注册条件。
- [ ] V2：根据 validation 和独立证据冻结校准/拒识，并完成独立验收。
- [ ] V3：标签空间与模型准入。
  - [ ] V3a：解决数字 ID/文本名称映射证据问题；解决前文本仍 provisional。
  - [ ] V3b：规则冻结后执行一次 locked test；不得用 test 反复调参。
- [ ] A1：production profile、可回滚部署、RX-only 矩阵验收和真实正向 capability。
- [ ] O1：持续运行和运维。
  - [ ] O1a：可重复故障/fuzz、日志/健康告警/升级回滚流程。
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
- [ ] Persist full bounded recognition records in the application result store
      and add a visible per-record manual-delete path without retaining IQ by
      default.
- [ ] Live-validate that local Spark-X2.5-4B sees only a compact recognition
      summary, explains the result without presenting an unlabeled top-1 as
      ground truth, and proposes one newly validated receive-only next step.

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
- [ ] Feed each classified/rejected/unavailable/error recognition observation
      into the next local Spark-X2.5-4B turn, and validate that Rust permits only
      a fresh receive-only next step: re-inspect, bounded re-capture/re-recognize,
      move to another measured candidate, survey, hold, or stop.
- [ ] Extend the priority `/stop` path to cancel the active recognition request
      as well as the already-supported Planner and SDR work, then discard every
      late Worker result whose request ID or session generation is stale and
      release the shared Spark/Mamba inference gate before later work.
- [ ] Build a fixed receive-only Planner regression covering all six actions,
      numeric limits, recognition statuses, failures and stop races. Require
      every accepted proposal to pass Rust policy; the current five-case BF16
      smoke is only 4/5 because one inspection proposed an out-of-range 48 MS/s
      rate, although Rust rejected it safely. See
      [`AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md`](AGX_SPARK_MAMBA_PLANNER_PERFORMANCE_VALIDATION_2026-09-04.md).

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
- [ ] Define and live-validate the shared AGX CUDA admission policy for the
      resident Spark-X2.5-4B Planner and Mamba Worker. For production v1,
      serialize active inference, bound queue/deadline/memory/thermal use, and
      prove cancellation releases the gate before a subsequent Planner turn.
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
- [ ] Add automated protocol fuzzing for malformed, oversized, stale, duplicate,
      truncated, and reordered frames across all sockets.
- [ ] Add repeatable fault injection for upstream-model loss, Planner Worker
      restart, SDRD loss, IIO timeout, transport overflow, and cancellation
      races.
- [ ] Run and document a complete 24-hour autonomous-loop soak test.
- [ ] Define production log rotation, health monitoring, alerting, update, and
      rollback procedures for Pi and SDR services.

## Current next milestone

S2 (including its dependent Web correction) and V1a tools/specification are
complete. V1a passed isolated native Web/HTTP/browser and deletion validation;
installed services remain unchanged and the actual recognizer stays unavailable.
Actual independently reviewed labels/coverage (V1b), calibration and admission
remain open. The next default independent unit is S3 Worker lifecycle.

Execution order, prerequisites and permitted scheduling changes are maintained
only in
[`SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md`](SDR_AGENT_ACTUAL_DELIVERY_ORDER_2026-09-06.md).
Chapter numbering here is a status ledger, not an instruction to implement in
that order. Each delivery has its own verification and exact cleanup record.
