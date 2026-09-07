# Initial-survey settings and fixed-gain live validation

Date: 2026-09-01  
AGX workspace: `/home/jetson/sdrharness`  
SDR endpoint: `192.168.1.10:43110`  
Scope: receive-only initial survey, settings UI, OpenCode Go planning closure

## Implemented operator contract

- A gear entry beside the LAN connection indicator opens a separate settings
  page.
- Model/API, model inventory, context window, 90% default compaction threshold,
  initial-survey mode/range/dwell and fixed RX gain are form state until the
  operator presses `保存设置`.
- The private provider file remains mode `0600`; a saved change is snapshotted
  only by the next new conversation.
- A new conversation runs at most one initial survey. Persisted states are
  `pending`, `running`, `complete`, `failed`, and `skipped`; process or Web
  restart does not turn a completed survey back into pending.
- Full-band mode fixes the frequency plan but leaves RX gain editable. Custom
  mode exposes the bounded range. Disabled mode performs no initial survey.
- The default fixed gain is 20 dB and the accepted operator range is 0–60 dB.
  Any gain-mode/readback mismatch or any clipped sample invalidates the sweep,
  stops the session, and restores the saved radio state.

Fixed gain makes dBFS measurements comparable across points in the same sweep
and across later sweeps only when gain, sample rate, bandwidth, antenna,
placement and environment remain the same. It does not calibrate dBFS to dBm.
The practical adjustment rule is: lower gain after any clipping; raise it only
when weak-signal sensitivity is insufficient and a bounded verification sweep
still reports zero clipping.

## Software and deployment evidence

All unit tests and strict lint checks passed:

```text
sdrd_tests=pass
controller: 41 tests passed (39 library + 2 CLI)
web-console: 10 tests passed
planner-worker: 34 tests passed
controller/web cargo clippy --all-targets -- -D warnings: pass
node --check public/app.js: pass
```

The ARMv7 SDRD build requires only `GLIBC_2.4`, `GLIBC_2.7`, and
`GLIBC_2.17`. Deployed hashes:

```text
P201 /sd/sdr-agent/current/sdrd
P201 /sd/sdr-agent/releases/20260901-initial-survey-fixed-gain-v2/sdrd
2e4f37080d37479d91b0343c6e0c42d1945c8b6dff2cde5255fb318d701eb0a0

AGX /home/jetson/.local/lib/sdrharness/bin/sdr-agent
b1f0d71218eb7978c14be3fd4fbc36454e90ce17177cd5d53fca9b30524face4

AGX /home/jetson/.local/lib/sdrharness/bin/sdr-agent-web-console
1b9ab9275b691e67b1630e7673a48ecb146325370a6470760682a70b88f692b1
```

The protected `/sd/BOOT.bin` remained unchanged:

```text
02c7f8f84f003879fda27021bb243517ccf8e9b85e7404a37db2e4dda1d8b951
```

Browser interaction verified that the gain input is visible and enabled in
full-band mode, the budget text changes with the input, a temporary value is
persisted only after `保存设置`, and the final saved value is 20 dB. The saved
model remained `opencode-go/deepseek-v4-flash`, context window 196,608, and
compaction threshold 90%.

## Gain selection validation

The bounded three-point preflight used RX0, 2.400/2.408/2.416 GHz, 10 MS/s,
10 MHz bandwidth, 5 ms settle, and 4,096 complex-int16 samples per point. It
wrote no raw IQ.

At 30 dB, 2.416 GHz clipped 488 of 4,096 samples. The run was rejected and the
radio restored. Repeating at 20 dB returned `gain_mode=manual` and
`hardware_gain_db=20` at every point with clip counts `0, 0, 0`. Before and
after each run, read-only radio probes matched:

```text
center_hz=2400000000
sample_rate_hz=30720000
rf_bandwidth_hz=18000000
gain_mode=slow_attack
scan_channel_mask=0
```

This live result is why 20 dB, rather than the initially proposed 30 dB, is the
default.

## Full real-SDR and real-model closure

The full receive-only plan was recorded before execution:

```text
70 MHz–6 GHz, 8 MHz step, 743 points
10 MS/s, 10 MHz RF bandwidth, 5 ms settle
4,096 complex-int16 samples per point, manual 20 dB
12,173,312 maximum processed sample bytes, no raw IQ persisted
```

Live result:

```text
elapsed_ms=46023
noise_floor_dbfs=-52.9
candidates=8
clip_count=0 at every accepted point
strongest=initial-1-8, 5790 MHz, -32.81 dBFS, SNR 20.1 dB
radio_restored=true
```

The Web then submitted an analysis-only instruction through the deployed
OpenCode Go provider. `deepseek-v4-flash` returned a structured hold proposal;
Rust validated it without tuning or capture:

```text
保持当前状态：分析请求：保持状态，不调谐/采集。最强候选
initial-1-8（5790 MHz，-32.81 dBFS，SNR 20.1 dB）。固定增益下候选可比
（统一增益与带宽）。峰值均低于 0 dBFS，未削顶；数据新鲜。
```

Persisted session evidence was `initial_survey_status=complete`, generation 1,
`compaction_count=0`, and exactly one `首次扫频已开始` event. Restarting the
deployed Web service preserved the same session, complete status and start
count, proving it did not repeat the initial survey.

The earlier 2.422 GHz ranking produced under `slow_attack` AGC is retained only
as historical bring-up evidence. It is not a valid fixed-gain ordering and is
superseded by this run.
