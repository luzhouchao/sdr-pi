# Single SDR Agent CLI — 2026-09-07

Baseline: `6ed1fa16a56b7cf4ead9f2af62853be694330fce`, branch
`codex/recognizer-amc-offline-validation`. The operator changed the RX client
compatibility audit into a concrete request to merge the installed CLI entries
and keep one. This delivery implements and installs that single entry.
Machine-readable evidence: [audit](../evidence/UNIFIED_CLI_AUDIT_2026-09-07.json).

## Actual entry points and change

The installed Web server already used the RX1-compatible interactive
`sdr-agent` (`d722990c…`). The separate installed `sdr-agent-controller`
(`3cbad970…`) failed read-only observation with `unknown field rx_input`.
The retained 20260905 corpus release's Controller (`6815166e…`) could observe
the live daemon, but had not been synchronized into the active bin directory.
This was not evidence that the entire Web RX path was broken. Recovery had
already been repaired with the separate `sdr-agent-health` (`13102e30…`).

There is now one Controller executable:

| Invocation | Purpose |
| --- | --- |
| `sdr-agent` with existing interactive options | Terminal Agent and the child process launched by Web; `/help`, `/status`, `/stop`, approval and conversation handling |
| `sdr-agent --mode plan/observe/sweep/execute/cancel/run-once …` | Existing scripted Controller operations, explicit mode selection |
| `sdr-agent --mode health --sdrd HOST:PORT [--timeout-ms 1..1000]` | Strict read-only recovery health probe; unhealthy state exits nonzero |
| `sdr-agent --help` | Entry-point usage without connecting to hardware, Planner or model |

The previous batch, interactive and health implementations moved into
`controller/src/cli/`. Only their entry functions/argument handoff changed;
the same Controller library, strict protocol parsing, policy, receive budgets,
approval, cancellation and health checks are reused. Cargo has exactly one
binary target, `sdr-agent`; its package/library name stays
`sdr-agent-controller`. Dispatch reads flag positions, rejects duplicate or
missing modes and does not treat an instruction value of `--mode` as a flag.
The old default-plan invocation must now specify `--mode plan`.

Native build staging, active validation scripts, the operations release example
and recovery script now use this entry. Obsolete generated CLI files are
removed from build staging. Historical validation documents and rollback
artifacts retain their original names as evidence. The Web HTTP server remains
`sdr-agent-web-console`; it is a different service and launches the unified CLI.

## Verification

- `cargo test --locked --all-targets`: **125 passed**, one intentionally ignored
  synthetic replay export; no model experiment run. Existing CLI health tests
  now launch the unified executable, including unhealthy/malformed identity,
  bounded option surface and stalled endpoint cases. New dispatch regression
  checks cover argument-value confusion and duplicate/missing modes.
- Cargo fmt, all-target Clippy with `-D warnings`, native release build,
  Cargo metadata single-binary check, two Bash syntax checks and five modified
  Python scripts' AST parsing passed. The build is stripped AArch64 Linux ELF.
- Live CLI: verified RX1 observation, two-point sweep, invalid frequency
  rejection, forced 1 ms capture timeout, active `--mode cancel` and complete
  state restoration passed.
- Isolated installed Web server + the **same final release CLI** + private real
  Node session sockets: headless Chromium created a conversation, received two
  real points, displayed the archive, deleted the test result with the visible
  confirmation button, and stopped a running longer initial survey. Result
  count returned to zero, IQ bytes were zero and browser JS errors were zero.
  A local HTTP sink counted **zero model requests**. The visible observation
  retained `recognizer_available=false`.
- Installed production validation: Web restarted and launched the new CLI
  (PID `475403`, executable hash verified through `/proc`); `/status` reported
  an open session, idle upstream and no pending approval. Initial surveys stayed
  `complete`, so restart performed no new RF capture. Both existing user session
  IDs and existing acquisition/corpus API results were preserved.
- Recovery uses `sdr-agent --mode health`, returned `Result=success` and
  `ExecMainStatus=0`; its timer was restored active. No P201 daemon replacement
  or reboot: PID `5909` stayed unchanged throughout.

### Finite RX plan and state

RX1/RX0/A_BALANCED, 2.455–2.470 GHz in 1 MHz steps, 10 MS/s, 10 MHz bandwidth,
manual gain 20 dB, 4096 ci16 samples/point, one frame, no SigMF persistence.
Success surveys use two points and 20 ms settle; cancellation surveys are
bounded to 16 points and 1000 ms settle. Normal point deadline is 250 ms; CLI
adds one single-point 1 ms timeout case. Each CLI attempt permits at most
19 points / 311,296 bytes; each Web attempt at most 18 points / 294,912 bytes.
All six registered attempts together permit at most **1,802,240 raw bytes**
(including cases that exited before RX); their combined conservative RX time
bound is 137,610 ms. Each attempt recorded over 808 GB free space before RX.
No TX, B210, NX, model inference, training or locked-test access occurred.

AGX roots are explicitly listed in the audit. P201 transport uses native
`/tmp/sdr-agent-dev/agx-sweep-<generation>-<point>` paths, enumerated and checked
absent after each run. Final Web plans pre-recorded exact generations and paths
before the browser action. `/stop`, `--mode cancel`, script signal cleanup and
connection-close restoration remained available.

Before/after readback included **both** RX gain modes, gains and port selection,
plus all scan masks/buffers. Restored LO was 5,985,999,996 Hz, rate 30,720,000,
bandwidth 30,000,000, both RX manual gain 60 dB/A_BALANCED, all scan/buffers zero.
User result/corpus stores were not used for development cleanup.

### Failed validation assertions retained

The audit preserves failed attempts instead of rewriting them as passes:

1. The first CLI harness queried `EXECUTION_STATUS` on a second connection
   during a sweep. SDRD correctly returned `server_busy` (only its dedicated
   cancellation connection is admitted concurrently). Cleanup's immediate
   snapshot was too early; a separate follow-up confirmed full restoration and
   idle state on the same PID. The final harness waits for the read-only LO
   readback, sends dedicated cancellation and polls restoration before judging.
2. The first Web harness had a Python HTTP-module/function name collision and
   exited before RX. The second waited for network idle despite persistent SSE;
   it also exited before RX. Final browser readiness uses a successful state
   response and rendered controls after the bounded network-idle wait.
3. The third Web attempt actually completed two RX points, but its assertion
   assumed the newer Web source's generated request file. The installed Web
   uses the base request for fresh sessions and spells its completion status
   `complete`. Its generation-1 paths were separately checked absent. The final
   validation follows the installed version and pre-registers unique request
   generations. The deployed Web itself did not need a protocol repair.
4. The first installation passed health/recovery and launched the new CLI, but
   demanded byte-identical entire event histories after Web restart. The
   existing Web deliberately compacts its active history into a bounded summary
   and retains 48 recent events on restart. That assertion triggered a real
   rollback of all four original files. The final deployment verified the
   retained 48 events, summary, session identities and unchanged results instead.
   Do not claim the full event array was byte-identical. A retry also stopped at
   the existing-release preflight before making changes; final retry verified
   and reused the original release/rollback hashes without overwriting them.

These harness/acceptance issues did not change the binary under test, relax a
radio safety gate or change model admission. Native RX errors retained their
original failure outcomes.

## Deployment and rollback

Active `/home/jetson/.local/lib/sdrharness/bin/` now contains only the unified
CLI and Web server among `sdr-agent*` entries. The old Controller and health
executables were removed only after the new health, Web and recovery checks
passed. There are no compatibility executable aliases.

Unified CLI: 2,544,408 bytes, SHA-256
`24b8340dd5c56bcf643a44e1eadbd11450e3b5e528d2ec72dc26103e9f23e25f`.
Its active path is a hard link to the release artifact (mode 0755).

- Release: `/home/jetson/.local/lib/sdrharness/releases/20260907-unified-cli-v1/`.
- Rollback: `/home/jetson/.local/lib/sdrharness/releases/20260907-before-unified-cli-v1/`.
- Eight inventoried release/rollback files total **5,319,940 bytes**, including
  manifests; exact sizes and hashes are in the audit. These are necessary
  deployment/rollback artifacts, not IQ evidence or uncleaned build output.
- Recovery script: `/home/jetson/.local/lib/sdrharness/scripts/recover-p201-sdrd.sh`.
- Installed Web hash stays `4e2a56ebe7e303c560046c5dde2bbcc169226201b9e01b19f9454b3472ff2834`.

Rollback procedure: while idle, stop the recovery timer/oneshot and Web, confirm
its old CLI child has exited, restore the four `bin/*` / `scripts/*` files from
the named rollback through same-directory temporary files and atomic rename,
then start recovery, Web and timer. Verify the original hashes, one P201 daemon,
health and unchanged radio readback. The original recovery script requires its
original health binary, so restore them together. This rollback was exercised
by the first deployment assertion above. Keep the active release; remove a
retired rollback directory only after explicitly deciding to discard that
rollback, verifying its exact resolved path and the audit inventory.

## Scope and cleanup

This installs the current unified Controller/interactive binary. Its linked
S1/S2/engineering code is consequently present on disk, but production Worker,
Web recognition UI, profiles, calibration and release-admission configuration
were not deployed. It is **not A1** or end-to-end production recognition
deployment. `recognizer_available=false`, frozen epoch-10/FP16/RF-v1,
provisional text names and all V1b/V2/V3/A1 gates remain unchanged.

Cleanup removed **1,827 files / 816,198,886 logical bytes** across seven exact
feature roots and verified their absence. The audit records removed roots, file/byte counts,
process/socket shutdown and absence checks. Browser captures, private SQLite,
dummy provider settings, scripts/logs, caches and build outputs are temporary;
only this source, bounded audit and the listed releases remain. No new IQ
diagnostic package is retained. Existing RF diagnostic inventories and user
application results are untouched.
