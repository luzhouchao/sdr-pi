# Automatic `survey_band` live validation

Date: 2026-09-01  
AGX workspace: `/home/jetson/sdrharness`  
SDR endpoint: `192.168.1.10:43110`  
Scope: receive-only automatic cruise with real SDR and OpenCode Go Planner

## Failure reproduced from the Web console

The original Web trace accepted a real Planner proposal for 70–90 MHz but then
stopped with `下一步没有生产执行器`. At that point `survey_band` was validated
as a plan-only action: the production dispatch path recognized only
`capture_bounded_iq`. The same trace contained repeated blank `Agent>` rows
because empty streaming assistant messages were printed by the Controller and
accepted by the Web process-output reader.

A simultaneous Planner/Web restart could also start the terminal before
`session.sock` existed, producing `No such file or directory` and an immediate
terminal exit. Finally, a model that called `submit_plan` and continued its
stream left the session run active; even after a sweep completed, the next
Planner turn remained blocked until the cruise time budget expired.

## Implemented execution path and safety bounds

`survey_band` now dispatches through the existing `SweepEngine` and
`SdrdSoftwareSweepAdapter` in both step-approval and automatic-cruise modes.
The Controller converts the validated model action into this bounded software
sweep:

```text
model start_hz/stop_hz/step_hz/dwell_ms -> sweep frequency plan and settle time
sample rate                            -> 10 MS/s
RF bandwidth                           -> 10 MHz
samples per point                      -> 4,096 complex-int16
frames per point                       -> 1
point timeout                          -> 250 ms
RX gain                                -> saved fixed manual survey gain
```

Policy and execution fail closed at 768 points, 300 seconds estimated duration,
the per-action receive-byte limit, and the remaining cruise receive-byte
budget. A planned sweep counts as one cruise step and its maximum processed
sample bytes count against the cumulative budget. Gain-mode or gain-readback
mismatch, clipping, execution failure, or radio-state restoration failure
prevents the observation from being accepted. `/stop` directly cancels either
an initial or planned sweep and reports the corresponding restoration path.

The saved settings value, 20 dB, is passed to every Controller process even
when no initial survey is due. Keeping manual gain fixed makes relative dBFS
measurements comparable under otherwise unchanged RF conditions; it is not a
dBm calibration.

On success, the compact sweep candidates replace `template.observation` and
therefore enter the next `PlanningContext`. Raw IQ is not persisted. Once the
first valid `submit_plan` arrives, the Controller aborts the remainder of that
model generation so execution and the next Planner turn cannot be held behind
irrelevant trailing output.

The Controller and Web now both suppress empty `Agent>` messages. The Web waits
up to five seconds for the Planner session socket before launching the terminal.
The Planner session runtime captures the active generation, Agent instance and
run lease so service shutdown/disposal cannot emit an event with an undefined
generation or leak the inference lease.

## Real SDR and real model closure

Before execution, the bounded plan and storage check were recorded:

```text
70–90 MHz, 100 kHz step, 201 points
10 ms dwell, 10 MS/s sample rate, 10 MHz RF bandwidth
4,096 complex-int16 samples per point, fixed manual gain 20 dB
3,293,184 maximum processed bytes
automatic cruise: 2 steps / 300 seconds / 4 MiB cumulative receive budget
raw IQ persistence: disabled
```

The deployed Web console drove the complete flow with the real P201 SDR and the
configured OpenCode Go `deepseek-v4-flash` model. Browser evidence reported
`live_automatic_survey_band=pass`, session generation 5. The first model turn
proposed the sweep; the production executor returned:

```text
points=201
elapsed_ms=14059
noise_floor_dbfs=-51.4
candidates=10
clipped_samples=0
radio_restored=true
cruise_steps=1/2
cruise_bytes=3293184/4194304
```

The ten compact candidates, spanning 83–90 MHz, were supplied to the next real
Planner turn. The model then proposed `hold` because the mission had obtained
real candidates and did not require IQ capture or recognition. Rust validated
the proposal and automatic cruise exited with
`上游建议停止或保持`. This proves the sweep result, rather than a fabricated
candidate, controlled the next step.

After the sweep, the read-only radio state matched the saved pre-sweep state:

```text
center_hz=2400000000
sample_rate_hz=30720000
rf_bandwidth_hz=18000000
gain_mode=slow_attack
scan_channel_mask=0
```

## Build, deployment and integrity evidence

Tests and strict lint checks passed before deployment:

```text
controller: 40 library tests + 2 CLI tests passed
controller cargo clippy --all-targets -- -D warnings: pass
controller release build: pass
web-console: 10 tests passed
web-console cargo clippy --all-targets -- -D warnings: pass
web-console release build: pass
planner-worker: 35 tests passed
```

Deployed hashes:

```text
AGX /home/jetson/.local/lib/sdrharness/bin/sdr-agent
f7e7cb1cdf881de11b011151f299725230b52b20ab56c4fac4815e1ecd34c738

AGX /home/jetson/.local/lib/sdrharness/bin/sdr-agent-web-console
8731b8e64f09c8827b7cdfc599e56e3f5ae527dd42dd97b88156b23d326eb145

P201 /sd/sdr-agent/current/sdrd
2e4f37080d37479d91b0343c6e0c42d1945c8b6dff2cde5255fb318d701eb0a0

P201 /sd/BOOT.bin
02c7f8f84f003879fda27021bb243517ccf8e9b85e7404a37db2e4dda1d8b951
```

Both `sdrharness-planner.service` and `sdrharness-web.service` were active after
a simultaneous restart. The Controller waited for the socket and connected;
the prior terminal startup race did not recur. No SDR-side temporary sweep file
or raw IQ file was present after validation. The isolated AGX and SDR feature
directories were removed during delivery cleanup.
