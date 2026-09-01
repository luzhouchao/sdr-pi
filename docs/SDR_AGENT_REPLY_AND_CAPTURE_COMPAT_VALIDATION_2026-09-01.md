# SDR Agent visible reply and bounded-IQ compatibility validation

Date: 2026-09-01

AGX Web: `http://127.0.0.1:8787`

SDR endpoint: `192.168.1.10:43110`

Model: OpenCode Go / `deepseek-v4-flash`

## Cause and correction

The production bounded-IQ Adapter intentionally denies unknown SDRD capability
fields, but its local response shape lagged the deployed SDRD schema and omitted
the declared `software_summary` Boolean. The real capture therefore stopped at
capability decoding before opening a radio session. `CapabilitiesResponse` now
accepts that exact required field while continuing to reject undeclared fields;
the production mock includes the deployed response shape.

The Planner uses one structured `submit_plan` call and the Controller aborts
remaining generation after Rust validation. That kept hardware authority
deterministic, but a normal greeting could produce only a validated plan line
and no visible model card. The Controller now derives `Agent>` text from the
Rust-validated plan. A `hold` exposes its validated reason, while manual
hardware plans expose both the action and the approval gate. The system prompt
requires greetings, status questions and explanations to use a short
language-matched `hold.reason`; no separate text-to-hardware path was added.

## Verification budget

Before live work the AGX had 850,568,822,784 bytes free. The exact AGX feature
directory was:

```text
/var/tmp/sdrharness-dev/agent-reply-bounded-iq-fix-20260901/
```

All actions were receive-only on RX0. The manual survey was limited to
70–90 MHz, 1 MHz steps, 5 ms per point, 21 points and 344,064 processed bytes.
The automatic cruise was limited to two steps, 180 seconds and 4,194,304 bytes;
its requested bounded capture was 65,536 complex-int16 samples, 10 MHz sample
rate, 10 MHz RF bandwidth and 262,144 bytes. `/stop` remained available.

## Real Web, model and SDR results

Python Playwright drove the deployed Web UI using headless Chromium. The app's
long-lived event stream prevents a permanent `networkidle` state, so the test
attempted a five-second network-idle wait after DOM load and then inspected the
rendered controls. No page or browser-console errors were observed.

The Web sent this non-hardware request:

```text
你好，请用中文简短回复，不要操作硬件
```

The real model submitted a validated `hold`, and the visible model output was:

```text
Agent> 你好！我已就绪，当前不会操作任何硬件。如需要，请告诉我下一步要做什么（例如查看信号或调整频段）。
```

The Web then sent:

```text
请扫描 70000000–90000000 Hz，步进 1000000 Hz，每点 5 ms
```

The model returned a Rust-validated `survey_band`. The `Agent>` reply named the
same bounds and explicitly asked the operator to click approve or enter
`/approve`. Browser approval executed the real SDR sweep:

```text
points=21
elapsed_ms=2143
gain_db=20
noise_floor_dbfs=-51.0
candidates=1
processed_bytes=344064
clipped_samples=0
radio_restored=true
```

The resulting candidate `request-2-1` was centered at 90 MHz with 14 MHz
reported bandwidth, -35.3 dBFS peak and 15.7 dB SNR. A two-step automatic
cruise then asked the real model to perform one 65,536-sample bounded capture on
that candidate. Rust validated request 3 and automatic execution returned:

```text
samples_captured=65536
bytes_written=262144
dropped_samples=0
overflow=false
radio_restored=true
software_summary_shape_error=false
```

The browser immediately issued `/stop` after the successful result. The cruise
exited for `operator stopped`, the in-flight next model turn was aborted and
old plans were invalidated.

## Tests and deployed artifacts

```text
controller cargo fmt -- --check: pass
controller cargo test --all-targets: 42 library + 4 CLI tests passed
controller cargo clippy --all-targets -- -D warnings: pass
planner-worker npm test: 35 tests passed
web-console cargo test --all-targets: 13 tests passed
```

Deployed hashes used for live validation:

```text
e72402f9fff9a47a96cf7da2935d868e8ea6939da109934191c5dce77e649ba4  sdr-agent
f2667e5f59a03593e2604bae5c5e477567d36b734ceb8a6dbcdd594f1be93b25  system-prompt.mjs
61914d9d60e39ab9e09ac3f4fa4aef134ec99f2396e3601cbd19000610b63dc9  sdr-agent-web-console
```

Both `sdrharness-planner.service` and `sdrharness-web.service` were active with
zero service restarts after deployment.

## Cleanup gate

The capture Adapter deterministically used SDR feature directory
`/tmp/sdr-agent-dev/agent-2-3/`. The AGX used the direct wired route from
`192.168.1.20` to `root@192.168.1.10`; `sshpass` was installed from the Ubuntu
package and read the existing mode-`0600` password file without printing or
copying its contents. No second SDRD instance was started: port 43110 was
already listening and the existing `sdrd` PID remained 10640.

Before removal, the exact SDR directory resolved to itself and contained only:

```text
/tmp/sdr-agent-dev/agent-2-3/capture-2-3149.ci16  262144 bytes
```

The exact SDR directory was deleted and verified absent while
`/tmp/sdr-agent-dev/` and the existing SDRD process remained present. The exact
AGX directory
`/var/tmp/sdrharness-dev/agent-reply-bounded-iq-fix-20260901/`, including its
temporary browser scripts, screenshots and rollback binary, was also deleted
and verified absent before commit. No raw IQ, browser artifact, credential or
deployment staging file is retained in Git.
