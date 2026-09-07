# Candidate inspection and observation-restart live validation

Date: 2026-09-01  
AGX workspace: `/home/jetson/sdrharness`  
SDR endpoint: `192.168.1.10:43110`  
Scope: receive-only `inspect_candidate`, manual approval and structured restart recovery

## Failures reproduced from the Web console

The real OpenCode Go model selected `initial-1-7` from a successful initial
survey and proposed `inspect_candidate`, but the Controller described it as
`当前仅规划`. Step-approval mode did not retain that action, so `/approve`
reported `没有等待批准的计划`. This was an implementation gap rather than a
policy rejection: Rust had already validated the candidate ID, center,
bandwidth and dwell, but no production dispatch path existed.

Deployment testing then exposed two independent continuity faults:

- The Web persisted `初扫完成` and terminal text but not the structured
  `ObservationSummary`. After a Web restart, the new Controller correctly saw
  an empty candidate list and the real model returned `hold`; old log text was
  not safe executable state.
- A compressed summary contained newline characters. The Web wrote it to a
  line-oriented terminal, so every summary line became a separate command
  while the first Planner turn was active, producing repeated
  `当前步骤尚未结束` messages.

## Implemented bounded executor

`inspect_candidate` now enters the same pending approval gate as executable IQ
capture and `survey_band`. `/approve` dispatches a single-center
`SweepEngine + SdrdSoftwareSweepAdapter` operation; bounded automatic cruise
can dispatch it directly after Rust validation.

The production mapping is:

```text
candidate_id       -> must exist in the current structured observation
center_hz          -> must match the selected candidate within policy tolerance
bandwidth_hz       -> controlled RF bandwidth; sample rate is at least 2.083333 MS/s
dwell_ms           -> at most 1,000 ms before the bounded power summary
gain               -> saved fixed manual survey gain, currently 20 dB
capture            -> one CAPTURE_POWER summary, 4,096 complex-int16 samples
maximum bytes      -> 16,384
raw IQ persistence -> disabled
```

The action fails closed on SDR health/capability loss, candidate mismatch,
frequency or bandwidth violation, dwell or byte excess, gain-mode/readback
mismatch, clipping, malformed summary, cancellation failure or radio-state
restoration failure. `/stop` uses the existing independent SDRD cancel path.
In automatic cruise, a successful inspection counts as one step and 16,384
processed bytes.

On success, the selected candidate keeps its stable ID, receives the new
center, bandwidth and power measurement, and gets age zero. Its reference SNR
is recomputed against the prior fixed-gain noise estimate. Other candidates are
preserved with increased age, and any prior recognition result is cleared.
This compact observation is available to the next real Planner turn.

## Structured restart and compaction contract

After every accepted sweep, inspection or bounded capture, the Controller emits
a hidden typed observation event. The Web rejects malformed, oversized,
non-finite, out-of-band or duplicate-candidate observations before storing them
in the mode-`0700`, service-private Web state.

When a conversation process is recreated, the Web merges that observation into
the validated base `PlanningContext`, writes a mode-`0600` runtime request in
the Web state directory, and passes only its path to the Controller. The file
is removed when the child exits. Terminal text is never parsed back into a
candidate.

Carry-forward summaries and user commands are normalized to one terminal line
and bounded to the Controller's 1,024-byte instruction limit. Structured
candidates therefore survive independently of the 6 KiB textual summary and
the default 90% model-context compaction threshold.

## Real SDR and real model closure

The feature used one RX path, fixed 20 dB manual gain and no raw-IQ files. The
AGX validation directory was
`/var/tmp/sdrharness-dev/candidate-inspection-20260901/`; `/var/tmp` had
850,836,865,024 bytes free before testing. No SDR-side development file was
created.

Two bounded surveys legitimately produced no candidates before the final
closure:

```text
2.444–2.464 GHz, 2 MHz step, 11 points:
  noise floor -53.0 dBFS, candidates 0

83–90 MHz, 100 kHz step, 71 points:
  noise floor -40.1 dBFS, candidates 0
  (the occupied narrow window raised its local median baseline)
```

The validated 70–90 MHz reference window then returned fresh candidates:

```text
201 points, 100 kHz step, 10 ms dwell
elapsed_ms=14069
maximum_processed_bytes=3293184
noise_floor_dbfs=-52.0
candidates=8
clipped_samples=0
radio_restored=true
```

The Web service was restarted after this result. The active Controller command
used `/var/lib/sdrharness/web-console/runtime-request.json`, the file mode was
`0600`, and the restored structured candidate count remained eight. The
strongest was `request-3-8` at 89.6 MHz.

The real OpenCode Go model then submitted the requested inspection plan. Rust
validated it, the Web showed the manual gate, and the browser selected
`✓ 批准`:

```text
candidate_id=request-3-8
center_hz=89600000
rf_bandwidth_hz=10000000
dwell_ms=1000
gain_db=20
processed_bytes=16384

before: peak=-33.995743 dBFS, reference_snr=17.956627 dB
after:  peak=-37.500740 dBFS, reference_snr=14.451630 dB
clipped_samples=0
radio_restored=true
browser_page_errors=[]
```

This proves that `/approve` executed a current, model-proposed structured
candidate rather than replaying the old `initial-1-7` log entry.

## Tests and deployed artifacts

```text
controller: 42 library tests + 2 CLI tests passed
controller cargo clippy --all-targets -- -D warnings: pass
web-console: 13 tests passed
web-console cargo clippy --all-targets -- -D warnings: pass
planner-worker: system prompt test covers the 1,000 ms inspection ceiling
live_candidate_inspection=pass
```

Deployed hashes used for the live closure:

```text
AGX /home/jetson/.local/lib/sdrharness/bin/sdr-agent
9fa97ba523e117add534eb401a50238d1614efa9e1db30f5b66629c051941ccd

AGX /home/jetson/.local/lib/sdrharness/bin/sdr-agent-web-console
61914d9d60e39ab9e09ac3f4fa4aef134ec99f2396e3601cbd19000610b63dc9
```

The feature issued only controlled receive actions through SDRD/1. It did not
transmit, write arbitrary IIO/FPGA state, replace `BOOT.bin`, persist IQ or
change the recognizer. The exact AGX validation directory and its browser
screenshots/scripts were removed after verification; the SDR-local feature
directory was never created because no remote development file was needed.
