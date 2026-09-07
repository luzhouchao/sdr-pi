# SDR Agent bounded terminal-session resume validation — 2026-09-03

## Outcome

The existing AGX `sdr-agent` terminal now persists a bounded private
conversation record and safely restores it after terminal exit, unexpected
process failure, or Planner service restart. It does not serialize or restore
a validated plan, approval decision, active model run, SDR action, candidate,
queue, or session generation.

Direct interactive terminals default to:

```text
$XDG_STATE_HOME/sdrharness/terminal-session.json
```

or, when `XDG_STATE_HOME` is absent or relative:

```text
$HOME/.local/state/sdrharness/terminal-session.json
```

An operator may select another absolute path with `--session-state`; the Web
process explicitly uses `--session-state off` because Web already owns its own
bounded per-conversation persistence. This prevents a Web child and a direct
terminal from sharing private history.

## Hard bounds and safety behavior

The terminal state schema contains only `schema_version`, `saved_at_ms`, and
conversation `history`. Its hard limits are:

- 64 KiB serialized state file;
- 32 resumable operator/Agent entries;
- 2,048 bytes per normalized single-line entry;
- 6,144 bytes for the in-memory carry-forward summary;
- 1,024 bytes for the one PlanningContext instruction that combines the
  bounded summary with the current command;
- seven days maximum state age, with future timestamps rejected.

Only entries whose internal kind is `operator`, `operator steer`,
`operator follow_up`, or `agent` are serialized. Approval, rejection,
validated-plan, execution, cancellation, error and status records are excluded.
Unknown JSON fields are rejected, so a file containing `pending_plan` or
similar action state cannot be loaded. The restored summary is explicitly
labelled as unprivileged conversation context without approval or execution
authority, and the next proposal still passes normal Rust validation.

The parent directory must be a real owner-only directory. Existing state must
be a regular file owned by the current account with exact mode `0600`; loose
permissions, symlinks, oversized data, malformed entries, unknown fields and
unsupported schemas fail closed. Each save uses a mode-`0600` sibling created
with `create_new`, full write plus `sync_all`, atomic rename and parent-directory
sync. A failed write removes only its exact temporary sibling.

## Automated validation

- Controller `cargo test --all-targets`: 46 library and 11 terminal tests
  passed.
- Controller strict Clippy passed with `--all-targets --all-features --
  -D warnings`.
- Web `cargo test --all-targets`: 15 tests passed; strict Clippy passed.
- Planner/session `npm test`: 49 tests passed as a regression gate.
- Both AArch64 release builds completed and were stripped.

The new terminal tests prove atomic/private writes, entry and summary limits,
normalization of multiline/oversized model text, rejection of expired or
mode-`0644` state, rejection of action-bearing unknown fields, exclusion of
approval/execution records, and the final 1,024-byte carry-forward limit.

## Live AGX/Spark validation

The live test used the private development state path:

```text
/var/tmp/sdrharness-dev/terminal-session-resume-20260903/live-state/session.json
```

No capture or retune was requested; maximum captured and retained IQ bytes were
zero.

1. A real local-Spark `hold` turn recorded the marker `ALPHA-0903`. Graceful
   terminal exit left a 264-byte regular mode-`0600` file inside a mode-`0700`
   directory. Inspection showed exactly two conversation entries and no
   `pending` or `session_generation` field.
2. After restarting `sdrharness-planner.service`, a new terminal reported two
   restored entries. `/history` rendered both, and the next bounded Planner
   instruction included the unprivileged carry-forward label. Spark correctly
   returned a Rust-validated `hold` that referenced `ALPHA-0903`.
3. A deliberately invalid survey proposal failed Rust coverage validation and
   terminated the terminal without executing hardware. After another Planner
   restart, five already persisted safe entries were restored and `/status`
   showed no pending approval, no queue, and a fresh generation.
4. A valid three-point survey proposal was then allowed to reach the manual
   gate only. `/status` showed a pending plan. The terminal exited without
   `/approve`; after service restart the next process restored nine
   conversation entries but `/status` showed no pending plan, no active run,
   queue 0, request ID 1 and fresh generation 1. No SDR action occurred.
5. The final deployed binary repeated that restore/status gate successfully.
   Starting the deployed Web produced HTTP 200, and its child command line
   contained `--session-state off`; the direct-terminal default state path
   remained absent.

## Deployment and rollback

```text
/home/jetson/.local/lib/sdrharness/bin/sdr-agent
SHA-256 6f506e4e95ac358cebabd1928f8bd8d689655e20ed85ca0be82b7fad4429c8e7

/home/jetson/.local/lib/sdrharness/bin/sdr-agent-web-console
SHA-256 c2393185e1fba028f08029f3d1bf1a25cf36bc2de8f9157546637333b4e985a0
```

Both are stripped AArch64 PIE executables. The immediately previous terminal
and Web binaries are retained at:

```text
/home/jetson/.local/lib/sdrharness/releases/20260903-pre-terminal-resume-v1/
```

The P201 daemon, config and startup entry were not rebuilt or replaced.

## Cleanup

The live test state, staged binaries, test temporary roots and both Cargo
`target/` directories are removed after the evidence/checklist change is
prepared. No user Web result, Web state/database, credential, model, capture,
raw IQ or rollback release is deleted.
