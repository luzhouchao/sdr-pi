# SDR Agent project checklist

Last reviewed: 2026-09-01

This is the living source of truth for implementation status. Check an item only
after the exact wording is implemented and verified. Split partial work into a
completed item and a remaining item instead of marking an ambiguous partial
state.

## 1. Architecture and Pi Agent Harness

- [x] Keep Qwen inference, tokenization, and KV cache on the 4090 llama.cpp
      module.
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
- [x] Provide `/status`, `/history`, `/approve`, `/reject`, `/pause`, `/resume`,
      `/stop`, `/help`, and `/quit` terminal commands.
- [x] Provide a Tailscale-address-only Rust web console that exposes the live
      terminal, Qwen messages, validated plans, execution/sweep output and
      system errors without duplicating Controller policy or SDR access.
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
- [x] Deploy and live-test the interactive terminal while retaining the prior
      Pi release for rollback.
- [ ] Support concurrent terminal input while Qwen is streaming so users can
      invoke Pi-style steer/follow-up from the line interface.
- [ ] Persist and resume bounded interactive session history after terminal
      exit.
- [ ] Support multiple isolated interactive users or sessions.
- [ ] Live-test a second OpenAI-compatible provider such as DeepSeek without
      changing the Controller interface.

Evidence:

- [`SDR_AGENT_RUNTIME_DESIGN.md`](SDR_AGENT_RUNTIME_DESIGN.md)
- [`TERMINAL_AGENT_CLI_RESEARCH.md`](TERMINAL_AGENT_CLI_RESEARCH.md)
- [`SDR_AGENT_TERMINAL_DEPLOYMENT_2026-08-31.md`](SDR_AGENT_TERMINAL_DEPLOYMENT_2026-08-31.md)
- [`SDR_AGENT_EXECUTOR_DEPLOYMENT_2026-08-31.md`](SDR_AGENT_EXECUTOR_DEPLOYMENT_2026-08-31.md)
- [`SDR_AGENT_WEB_CONSOLE_DEPLOYMENT_2026-09-01.md`](SDR_AGENT_WEB_CONSOLE_DEPLOYMENT_2026-09-01.md)

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
- [ ] Add an automatic mode that repeats the Runner within a fixed session plan,
      resource budget, and stop condition.
- [x] Persist a root-only JSONL audit record joining operator input,
      model/provider, raw proposal, Rust validation, approval, execution and the
      resulting observation, including fail-closed planning attempts.
- [ ] Validate reconnect, cancellation, stale-result, timeout, and partial-action
      recovery for the complete loop.

## 3. SDR Linux control plane (`sdrd`)

- [x] Record the SDR Linux, IIO, FPGA, network, and boot baseline.
- [x] Verify that the current `/sd/BOOT.bin` matches the protected original
      backup.
- [x] Implement the C `sdrd` configuration parser, framed SDRD/1 protocol,
      request correlation, health reporting, and capability reporting.
- [x] Implement and unit-test FPGA backend identity, ABI, build ID, and aggregate
      capability probing.
- [x] Implement a read-only shadow mode that rejects all mutating commands.
- [x] Cross-build and temporarily validate shadow `sdrd` on the real SDR without
      changing IIO, FPGA, boot, or radio state.
- [x] Implement the Pi Rust `SdrdAdapter` for read-only shadow observation.
- [x] Define and unit-test the allowlisted SDRD/1 mutation command schema for ownership,
      retune, bounded capture, stop, restore, and execution status.
- [x] Implement the Adapter-backed connection ownership state machine and prove
      stop plus restore on explicit stop, disconnect, apply failure, and capture
      failure with a fake radio backend.
- [x] Implement and live-validate one persistent SDR-local IIO context and one
      session-owned RX buffer in the C Adapter.
- [x] Save and restore LO, sample rate, RF bandwidth, gain mode, and enabled
      channels on success, error, cancellation, and disconnect.
- [ ] Live-validate the same state restoration path after an IIO timeout.
- [x] Live-validate restoration of LO, sample rate, RF bandwidth, gain mode, and
      scan-channel mask after success and an apply/readback error.
- [x] Implement and live-validate bounded retune, explicit settle delay, and
      quantized LO readback tolerance in `sdrd`.
- [x] Implement and live-validate bounded complex-int16 IQ capture in `sdrd`.
- [x] Implement and live-validate direct in-flight cancel in `sdrd`.
- [x] Implement and live-validate explicit post-action stop, buffer teardown,
      and state restoration.
- [ ] Add sequence, overflow, dropped-sample, timeout, and health metadata to all
      execution results.
- [x] Deploy controlled `sdrd` for the current SDR boot with a private-link
      listener, protected-BOOT gate, retained `/sd` release, tested stop path,
      bounded live capture and verified state restoration.
- [ ] Make `sdrd` start automatically after an SDR reboot; the RAM root loses
      `/etc/init.d/S60sdrd`, so this requires a separately authorized and tested
      ramdisk or boot-chain change with golden rollback.
- [ ] Complete long-duration reconnect and fault-recovery testing on the real
      SDR.

Evidence:

- [`../sdr-system/docs/BASELINE_2026-08-31.md`](../sdr-system/docs/BASELINE_2026-08-31.md)
- [`../sdr-system/docs/SDRD_SHADOW_VALIDATION_2026-08-31.md`](../sdr-system/docs/SDRD_SHADOW_VALIDATION_2026-08-31.md)
- [`../sdr-system/docs/SDRD_CONTROLLED_INTERFACE_VALIDATION_2026-08-31.md`](../sdr-system/docs/SDRD_CONTROLLED_INTERFACE_VALIDATION_2026-08-31.md)
- [`../sdr-system/docs/SDRD_IIO_ADAPTER_VALIDATION_2026-08-31.md`](../sdr-system/docs/SDRD_IIO_ADAPTER_VALIDATION_2026-08-31.md)
- [`../sdr-system/docs/SDRD_PERSONAL_DEPLOYMENT_2026-09-01.md`](../sdr-system/docs/SDRD_PERSONAL_DEPLOYMENT_2026-09-01.md)
- [`SDR_AGENT_SDRD_OBSERVE_VALIDATION_2026-08-31.md`](SDR_AGENT_SDRD_OBSERVE_VALIDATION_2026-08-31.md)
- [`SDR_AGENT_CANCEL_VALIDATION_2026-09-01.md`](SDR_AGENT_CANCEL_VALIDATION_2026-09-01.md)
- [`SDR_AGENT_RUNNER_DEPLOYMENT_2026-09-01.md`](SDR_AGENT_RUNNER_DEPLOYMENT_2026-09-01.md)

## 4. Raspberry Pi acquisition, aggregation, and sweep

- [x] Implement direct Pi libiio probe and capture utilities in Rust.
- [x] Implement streaming Hann-windowed RustFFT aggregation.
- [x] Implement linear-power averaging and bounded report cadence.
- [x] Implement median noise estimation and threshold-based candidate detection.
- [x] Implement coarse PSD output and adjacent-candidate merging.
- [x] Validate the Pi software aggregate pipeline at approximately 2.1 MS/s on
      the real SDR.
- [x] Define the `SweepPlan` inputs, validation requirements, backend choices,
      result contract, and restoration requirements.
- [x] Implement the production `SweepEngine.run(plan)` module with replay and
      capability-gated SDRD FPGA-summary Adapters.
- [x] Ensure one Pi software-sweep process owns and reuses the IIO context, RX
      buffer, FFT plan and preallocated sample blocks throughout a sweep.
- [x] Execute a bounded Pi software multi-frequency sweep with per-point LO
      readback, compact candidates and verified state restoration.
- [x] Feed compact aggregate candidates into the Agent observation contract.
- [ ] Feed only selected, bounded IQ windows into local recognition.
- [ ] Validate aggregate mode at sustained 5 MS/s and 10 MS/s with CPU, dropped
      sample, latency, and thermal measurements.
- [ ] Complete long-duration acquisition, reconnect, cancellation, and overload
      tests.

Evidence:

- [`SDR_PREPROCESSING_SWEEP_ARCHITECTURE.md`](SDR_PREPROCESSING_SWEEP_ARCHITECTURE.md)
- [`../raspberry-pi/p201pro-rust/TEST_RESULTS.md`](../raspberry-pi/p201pro-rust/TEST_RESULTS.md)
- [`SDR_AGENT_FPGA_SWEEP_GATE_2026-09-01.md`](SDR_AGENT_FPGA_SWEEP_GATE_2026-09-01.md)
- [`PI_SOFTWARE_SWEEP_FALLBACK_2026-09-01.md`](PI_SOFTWARE_SWEEP_FALLBACK_2026-09-01.md)

## 5. SDR FPGA aggregation

- [x] Define the intended division between AD9361 filtering, FPGA fixed-rate
      processing, SDR Linux packaging, and Pi control.
- [x] Define the FPGA summary identity, version, capability, sequence, quality,
      overflow, timestamp, scaling, and payload metadata requirements.
- [x] Require the original raw-IQ path to remain available as a bypass and
      rollback path.
- [x] Implement SDRD-side probing for the documented aggregate registers and
      magic value.
- [x] Implement the bounded SDRD/1 aggregate-summary command, persistent MMIO
      Adapter, timeout/cancel seam, and fail-closed Harness capability gate.
- [ ] Recover or create a hardware-validated FPGA base matching the real board
      and documented interfaces.
- [ ] Implement the first FPGA shadow kernel for frame quality, I/Q sums, power,
      and bounded accumulation.
- [ ] Implement fixed-size FFT, power, coarse PSD, threshold, top-k, or band
      aggregation selected by measured end-to-end benefit.
- [ ] Implement a DMA/result ring for vector or repeated summary transport rather
      than runtime SSH/devmem polling.
- [ ] Generate a versioned FPGA image and record source commit, tool version,
      timing report, bitstream hash, register map, and rollback image.
- [ ] Compare FPGA shadow output numerically against the Pi software reference on
      the same captured IQ corpus.
- [ ] Pass raw-IQ bypass, overflow, stale-data, sequence-gap, rollback, thermal,
      and 30-minute stability tests.
- [ ] Deploy the FPGA aggregation image and enable `fpga_backend` only after
      identity and health probes pass on every start.

Evidence:

- [`../sdr-system/docs/P201_AGENT_FPGA_DIRECTION.md`](../sdr-system/docs/P201_AGENT_FPGA_DIRECTION.md)
- [`PERFORMANCE_OPTIMIZATION_PLAN.md`](PERFORMANCE_OPTIMIZATION_PLAN.md)

## 6. Local modulation recognition

- [x] Select ONNX as the production model interchange format.
- [x] Select ONNX Runtime C/C++ CPU as the reference Pi backend and ncnn CPU as
      the later optimization candidate.
- [x] Implement the Rust `LocalRecognizer` interface.
- [x] Implement replay and Unix-socket Recognizer Adapters.
- [x] Enforce bounded, canonical spool-root IQ references and fixed planar
      float32 IQ metadata.
- [x] Correlate recognition requests and results by request ID, session
      generation, and candidate ID.
- [x] Implement the dependency-free C++20 model-backend interface and
      `ReplayBackend` tests.
- [x] Implement the strict Pi `ModelPackageLoader` interface, filesystem and
      replay Adapters, manifest/path/size/SHA-256/label validation, and package
      inspection command.
- [ ] Select and version a real modulation-recognition label set, training
      corpus, preprocessing profile, and acceptance thresholds.
- [ ] Train or import a compact model and export a pinned ONNX artifact.
- [ ] Implement the persistent C++ ONNX Runtime Worker.
- [ ] Numerically compare Pi outputs with the workstation reference on the same
      IQ corpus.
- [ ] Measure preprocessing, copy/map, inference, total p50/p99 latency, CPU,
      RSS, drops, and thermal behavior.
- [ ] Validate confusion matrix, total accuracy, and per-class recall before
      enabling `recognizer_available`.
- [ ] Deploy the Recognizer Worker with one bounded queue and explicit thread
      limits.
- [ ] Integrate recognition results into Agent observations and the autonomous
      Runner.

Evidence:

- [`PI4_LIGHTWEIGHT_AMR_RUNTIME_RESEARCH.md`](PI4_LIGHTWEIGHT_AMR_RUNTIME_RESEARCH.md)
- [`LOCAL_RECOGNIZER_INTERFACE.md`](LOCAL_RECOGNIZER_INTERFACE.md)
- [`PI_ULTRALIGHT_MODEL_TRAINING_HANDOFF.md`](PI_ULTRALIGHT_MODEL_TRAINING_HANDOFF.md)

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
- [x] Add and validate a versioned `connect-p201-sdr` skill that selects a
      healthy direct or SSH-relay route instead of assuming a fixed Pi relay.
- [ ] Add automated protocol fuzzing for malformed, oversized, stale, duplicate,
      truncated, and reordered frames across all sockets.
- [ ] Add repeatable fault injection for 4090 loss, Pi Worker restart, SDRD loss,
      IIO timeout, FPGA stale data, overflow, and cancellation races.
- [ ] Run and document a complete 24-hour autonomous-loop soak test.
- [ ] Define production log rotation, health monitoring, alerting, update, and
      rollback procedures for Pi and SDR services.

## Current next milestone

The Harness has reached the FPGA-image gate. Resume sweep work only after a
hardware-validated image exposes the documented summary identity, writable
aggregate control, sequence/quality fields, and a rollback path. The Pi model
package seam is also ready. Recognition work now waits for the ultra-light ONNX
model, labels, manifest and reference corpus trained on the 4090.
