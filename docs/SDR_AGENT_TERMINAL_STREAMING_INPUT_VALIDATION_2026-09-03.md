# SDR Agent terminal streaming-input validation — 2026-09-03

## Outcome

The existing AGX `sdr-agent` terminal now remains responsive while the Pi
Agent Planner is streaming. Plain text during an active turn and `/steer`
enter Pi Agent's steering queue; `/follow-up` enters its follow-up queue; and
`/stop` uses an independent priority signal that is not blocked by either the
four-line terminal queue or the four-message Planner queue. This behavior is
provider-neutral and was deployed and validated with the local
Spark-X2.5-4B BF16 provider.

The terminal no longer waits synchronously for `prompt`, `steer`,
`follow_up`, or `abort` acknowledgements. It correlates asynchronous responses
by command ID and session generation. A late response or event from an older
generation is discarded without terminating the current terminal, while an
unknown response in the current generation remains a protocol error.

The local stdin queue uses `sync_channel(4)` and nonblocking admission. Once
`/stop` is observed, queued local input is drained, later input is rejected
until the stop has been dispatched, Pi Agent queues are cleared, and the
Controller advances the generation after `agent_end`. An executable proposal
still aborts remaining model input so queued text cannot cross an approval or
execution gate. A `hold` proposal ends its tool turn normally and permits
queued steer/follow-up work to receive separately correlated Rust validation.

No RX capture, retune or radio mutation was needed for this feature. Live
tests used only SDRD/1 read-only health observation, so the maximum captured
bytes and retained IQ bytes were both zero.

## Deployment and rollback

The deployed terminal is:

```text
/home/jetson/.local/lib/sdrharness/bin/sdr-agent
SHA-256 f84122a499d3cda82c8efedf3efc7157deccffe1ec5c7e58ae2b26a491d5029e
ELF 64-bit LSB PIE, ARM aarch64, stripped
```

The deployed Planner continues to run the repository source through the
existing `sdrharness-planner.service`:

```text
planner-worker/src/main.mjs
SHA-256 f33755b67749e0ab79d12b680a09923f2dada2952e0f3ccc3c217abab196ccb2

planner-worker/src/session-runtime.mjs
SHA-256 12eeadb6fda1f287e887be63874cc40b2cc89b5d4499663d923ab5099ccfd619
```

The pre-feature terminal rollback artifact is retained at:

```text
/home/jetson/.local/lib/sdrharness/releases/20260903-pre-terminal-streaming-v1/
```

The P201 daemon was not rebuilt or replaced. Its deployed hash remained
`0b1b6ac63323d4dd81401e3656855428786588aafcca001411a9f21b7f51ada0`.

## Automated validation

- `cargo test --all-targets`: 46 library and 8 terminal tests passed.
- `cargo clippy --all-targets --all-features -- -D warnings`: passed with no
  warnings.
- `cargo build --release --bin sdr-agent`: passed and produced the deployed
  hash above.
- `npm test`: 49 Planner/session tests passed. These include the Pi steering
  and follow-up queue limit, stale generation rejection, global inference
  lease, and correlation of a completed follow-up without falsely reporting
  the original request missing.
- `git diff --check`: passed.

The Rust terminal tests additionally cover a full local stdin queue, the
independent `/stop` signal, asynchronous prompt/queue success and failure, a
late pending response, an unknown old response/event, and rejection of an
unknown current-generation response.

## Live Spark and terminal validation

The Web service was deliberately stopped before taking direct ownership of
`/run/sdr-agent/session.sock`. The Planner was restarted to clear the prior
interactive lease, and the deployed terminal connected to the existing
session socket and P201 SDRD address.

1. A prompt and immediate `/follow-up` were accepted while generation was
   active. Spark produced a Rust-validated `hold` for `request=1`, followed by
   a second Rust-validated `hold` for `request=2` confirming that no IQ capture
   occurred. The queue then returned to idle without a false missing-plan
   error.
2. Explicit steer and follow-up commands were accepted concurrently with a
   live Spark/search turn. The Controller correlated and validated the steer
   result using the steer request ID, not the original request ID.
3. Four Planner queue entries were accepted and the fifth was rejected with
   `session queue limit of 4 reached`. In a separate burst, the four-line
   terminal queue rejected excess input without blocking the main loop.
4. With both model work and queued input present, `/stop` was still handled
   first. Four already queued terminal lines were explicitly discarded, text
   arriving after the stop signal was rejected, Pi Agent aborted, and
   `/status` showed queue 0 and generation 2 instead of generation 1.
5. All model proposals in this validation were `hold`; no approval, SDR
   execution, sweep, IQ capture, or result-store write occurred.

After the direct terminal exited, `sdrharness-web.service` was restored. Web,
Planner, Spark and the P201 recovery timer were all active and enabled;
`GET http://127.0.0.1:8787/api/state` returned HTTP 200 with a 31,542-byte
bounded response. The three legacy Spectrum units remained inactive and
disabled.

## P201 and host-key gate

The global `known_hosts` entry already contained the operator-approved current
P201 ECDSA key. A fresh scan and strict SSH connection both matched
`SHA256:i1Lnt/81XecFwnrhkIMSzo20C6+4bRVWvqmANS8L5Cs`; host-key checking was
not weakened. Strict SSH then confirmed one ARMv7 `sdrd` PID and one
`192.168.1.10:43110` listener. Final read-only SDRD/1
`HELLO/CAPABILITIES/HEALTH/QUIT` reported controlled mode, healthy IIO,
`session_faulted=false`, and retired FPGA compatibility fields fixed false/0.

This repin makes the current boot usable, but it does not remove the separate
documented blocker that P201 regenerates its Dropbear key after each reboot.
No QSPI formatting or other persistent-device mutation was performed.

## Cleanup

No P201 feature directory or IQ file was created. The exact AGX development
directory `/var/tmp/sdrharness-dev/terminal-streaming-input-20260903/` and the
Controller `target/` build directory are removed after the source/evidence
commit is prepared. A transient Web state response at
`/tmp/sdrharness-terminal-feature-web-state.json` was deleted immediately
after its HTTP status and byte count were recorded. No Web result, database,
credential, model, or rollback release was removed.
