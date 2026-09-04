# SDR Agent project checklist

Last reviewed: 2026-09-03

This is the living source of truth for implementation status. Check an item only
after the exact wording is implemented and verified. Split partial work into a
completed item and a remaining item instead of marking an ambiguous partial
state.

## 1. Architecture and Agent Harness

- [x] Select Jetson AGX Orin as the primary future Agent, acquisition,
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

## 2. Planning policy and autonomous loop

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

Evidence:

- [`SDR_AGENT_ONESHOT_SWEEP_INSPECTION_VALIDATION_2026-09-03.md`](SDR_AGENT_ONESHOT_SWEEP_INSPECTION_VALIDATION_2026-09-03.md)
- [`SDR_AGENT_COMPLETE_LOOP_FAULT_RECOVERY_VALIDATION_2026-09-03.md`](SDR_AGENT_COMPLETE_LOOP_FAULT_RECOVERY_VALIDATION_2026-09-03.md)

## 3. SDR Linux control plane (`sdrd`)

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

## 4. AGX acquisition, aggregation, and sweep

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
- [ ] Feed only selected, bounded IQ windows into local recognition.
- [x] Retire the separate sustained 5/10-MS/s aggregate acceptance gate by
      explicit operator decision on 2026-09-03. This is a scope removal, not a
      claim that inline transport and AGX aggregation were newly measured at
      those rates; the characterized P201/AGX profile above remains the measured
      baseline.
- [x] Complete the long-duration reconnect, cancellation and fault-recovery
      portion with the chapter 3 bounded 1,800-second real-SDR run; see
      [`SDR_AGENT_SDRD_LONG_RECONNECT_FAULT_RECOVERY_VALIDATION_2026-09-03.md`](SDR_AGENT_SDRD_LONG_RECONNECT_FAULT_RECOVERY_VALIDATION_2026-09-03.md).
- [ ] Complete bounded AGX software-acquisition overload testing.

Evidence:

- [`SDR_PREPROCESSING_SWEEP_ARCHITECTURE.md`](SDR_PREPROCESSING_SWEEP_ARCHITECTURE.md)
- [`../raspberry-pi/p201pro-rust/TEST_RESULTS.md`](../raspberry-pi/p201pro-rust/TEST_RESULTS.md)
- [`PI_SOFTWARE_SWEEP_FALLBACK_2026-09-01.md`](PI_SOFTWARE_SWEEP_FALLBACK_2026-09-01.md)
- [`SDR_AGENT_INITIAL_SURVEY_SETTINGS_VALIDATION_2026-09-01.md`](SDR_AGENT_INITIAL_SURVEY_SETTINGS_VALIDATION_2026-09-01.md)
- [`NX_B210_P201_RX1_LINK_VALIDATION_2026-09-04.md`](NX_B210_P201_RX1_LINK_VALIDATION_2026-09-04.md)

## 5. Retired FPGA route

- [x] Retire FPGA aggregation by explicit user decision and fix production on
      P201 Linux/IIO bounded RX transport plus AGX software aggregation.
- [x] Remove the FPGA/Vivado tree, FPGA-only documents, MMIO Adapters and active
      Planner/controller snapshot capability from the working tree. Retain only
      constant false/zero SDRD/1 compatibility fields, strict acceptance of a
      legacy false Planner-health field, and the retirement decision;
      pre-cleanup evidence remains recoverable from Git history at `59cbb17`.

Evidence:

- [`FPGA_RETIREMENT_DECISION_2026-09-02.md`](FPGA_RETIREMENT_DECISION_2026-09-02.md)

## 6. Local modulation recognition

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
- [ ] Select and version one production Mamba checkpoint from the staged
      candidates, pin its exact model source, and define labels, preprocessing,
      sample-rate policy, precision and acceptance thresholds.
- [ ] Implement the AGX CUDA/Mamba Recognizer Adapter without exposing PyTorch,
      Triton, TensorRT or CUDA details through the Controller interface.
- [x] Numerically compare AGX FP32 with the 4090 training environment on the
      same 16 IQ rows per dataset: both argmax sets agree 16/16 and maximum
      absolute logits differences are `2.93e-5` (RML) and `1.18e-4` (Hisar).
- [ ] Compare FP16 and BF16 against the frozen FP32 corpus result and choose the
      production precision with explicit accuracy/numerical thresholds.
- [x] Measure offline preprocessing, host/device transfer, warm-up, inference,
      total p50/p99 latency, CUDA memory, CPU/RSS and thermal behavior for both
      complete test splits on AGX.
- [ ] Measure production Worker queue drops, cancellation, concurrency and
      sustained thermal behavior.
- [x] Generate offline confusion matrices, total accuracy, macro-F1, per-class
      precision/recall/F1 and per-SNR accuracy for both complete test splits.
- [ ] Resolve the disputed RML2018A class-name order and validate the RF input
      contract and rejection policy before enabling `recognizer_available`.
- [ ] Deploy the Recognizer Worker with one bounded queue and explicit thread
      limits.
- [ ] Integrate recognition results into Agent observations and the autonomous
      Runner.

Evidence:

- [`LOCAL_RECOGNIZER_INTERFACE.md`](LOCAL_RECOGNIZER_INTERFACE.md)
- [`AGX_SDRHARNESS_MIGRATION.md`](AGX_SDRHARNESS_MIGRATION.md)
- [`NX_B210_MAMBA_D8_ASSET_HANDOFF.md`](NX_B210_MAMBA_D8_ASSET_HANDOFF.md)
- [`AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md`](AGX_AMC_MAMBA_D8_OFFLINE_VALIDATION_2026-09-04.md)

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

Keep the receive-only bounded software sweep isolated from any Spectrum
collector and preserve the Raspberry Pi rollback path while validating the
P201-capture/AGX-aggregate cutover. The AGX clone, native build, runtime
baseline, Planner/Web runtime gate, prior bounded-IQ executor, fixed-gain
initial survey, automatic `survey_band` feedback loop and step-approved
candidate inspection are live-validated with the real SDR and both OpenCode Go
and the local Spark-X2.5-4B BF16 model. Inline-IQ AGX aggregation, persistent
Web results and optional SigMF are deployed and live-validated with both
storage modes, model feedback, browser readback, cancellation, cleanup and
radio restoration. The next implementation focus is sustained software-path
throughput/fault testing followed by the CUDA/Mamba recognizer. FPGA image,
register, DMA and boot work was explicitly retired on 2026-09-02 and is not a
future milestone.
