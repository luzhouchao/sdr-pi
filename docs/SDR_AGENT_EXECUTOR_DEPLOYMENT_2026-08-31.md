# SDR Agent Rust executor deployment

Date: 2026-08-31

## Outcome

The Raspberry Pi Rust Harness now contains a deep `SdrActionExecutor` module.
Its interface accepts a `ValidatedPlan` plus a correlated execution
authorization and returns one `ExecutionObservation`. The implementation hides
SDRD/1 connection setup, identity and capability checks, ownership generation,
profile application, bounded capture, status verification, stop/restore, quit,
and a second post-execution health observation.

Two Adapters exercise the same seam:

- `ReplayActionExecutor` for deterministic policy and caller tests;
- `SdrdActionAdapter` for the production SDRD/1 path.

This first slice supports only `capture_bounded_iq`. Survey, inspection,
recognition, automatic loops, and in-flight cancellation remain explicit
unsupported work rather than implicit behavior.

## Authorization and correlation

The Executor rejects an authorization whose request ID or session generation
does not match the validated plan. A plan marked `approval_required` cannot use
automatic authorization. Standalone execute mode accepts the original
`PlanRequest` plus `PlanResponse`, reruns `ControllerPolicy`, and requires
`--approval operator` for the development fixture.

The derived SDR data feature ID is `agent-<generation>-<request>`. The returned
observation retains request ID, generation, candidate ID, sample/byte counts,
sequence, dropped/overflow metadata, safe relative IQ path, and post-restore SDR
health.

## Build and deployment

Rust 1.98.0 validation passed:

- `cargo fmt -- --check`;
- 20 unit/integration tests, including a two-connection controlled SDRD mock;
- `cargo clippy --all-targets -- -D warnings`;
- stripped static `aarch64-unknown-linux-musl` release build.

Final deployed artifact hashes are:

```text
sdr-agent-controller 95a385bda93a0f770b02f302b3cc147bc4412391bd19841ce8f15b873401b38a
sdr-agent            4bb26bcb86aea858aa6b4b353ef7a4e5aa4eb4e9e7f969291ea1c9ef983e83c7
```

The Pi release is:

```text
/opt/sdr-agent/current -> /opt/sdr-agent/releases/20260831-executor-v1
```

The prior `/opt/sdr-agent/releases/20260831-agent-cli-v1` release remains the
immediate rollback. The Planner Worker was not changed or restarted and stayed
active throughout deployment.

## Live controlled execution

The approved development envelope used:

```text
request_id=101
session_generation=11
candidate=development-2442m
center_hz=2442000000
sample_rate_hz=2100000
rf_bandwidth_hz=2000000
samples=4096
maximum_bytes=16384
```

The Pi production Adapter completed controlled hello/capability checks,
ownership, profile application, bounded capture, execution status, stop and
restoration, quit, and a second health observation. It returned 4096 samples,
16,384 bytes, sequence 1, zero reported drops, no overflow, and
`post_execution_sdr.healthy=true`.

The captured file SHA-256 was
`424c1dacc32602df3db0f12b0e4e47eef5206a3fada64e5f93e996de5f558f96`.
The raw IQ itself was deleted and never entered Git.

After execution, the SDR read back its original 2452 MHz LO, 2.1 MS/s sample
rate, 2 MHz bandwidth, `slow_attack`, and scan mask zero. The known libiio 0.21
buffer-disable warning remained visible, while protocol return, health, state
restoration, and IIOD visibility were successful.

## Cleanup and remaining boundary

The following exact temporary directories were resolved, removed, and verified
absent:

```text
SDR: /tmp/sdr-agent-dev/agent-11-101/
SDR: /tmp/sdr-agent-dev/rust-executor-v1/
Pi:  /var/tmp/sdr-agent-dev/rust-executor-v1/
```

Controlled `sdrd` was stopped and was not installed as a service. The terminal
can be launched with `--sdrd` when a reviewed controlled endpoint is already
running; its normal no-flag invocation does not gain hardware authority.
`/stop` still cannot interrupt a synchronous in-flight capture and remains open
in the project checklist.
