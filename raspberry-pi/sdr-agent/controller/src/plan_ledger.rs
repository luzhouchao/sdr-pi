//! Persistent reception decisions. No approval or hardware work is recovered.
//! One bounded snapshot, an OS lifetime lock, and fsync+rename publication.
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};

const MAX_BYTES: u64 = 8 * 1024 * 1024;
const MAX_RECORDS: usize = 4096;

#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct PlanIdentity {
    pub plan_id: String,
    pub hash: String,
    pub app_session_id: String,
    pub controller_epoch: String,
    pub session_generation: u64,
    pub request_id: u64,
    pub deadline_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Decision {
    Accepted,
    Rejected,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum ExecutionState {
    Accepted,
    PendingApproval,
    Executing,
    Completed,
    Failed,
    Cancelled,
    Unknown,
}

#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct PlanRecord {
    pub identity: PlanIdentity,
    pub decision: Decision,
    pub execution: ExecutionState,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Snapshot {
    schema_version: u16,
    app_session_id: String,
    records: BTreeMap<String, PlanRecord>,
}

pub struct PlanLedger {
    root: PathBuf,
    _lock: File,
    state: Snapshot,
    epoch: String,
    failed: bool,
}

fn invalid(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}
fn id_valid(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 128
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}
fn private_file(path: &Path, create: bool) -> io::Result<File> {
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(create)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.uid() != unsafe { libc::geteuid() }
        || metadata.mode() & 0o077 != 0
    {
        return Err(invalid(
            "ledger requires an owned private single-link regular file",
        ));
    }
    Ok(file)
}

pub fn fresh_epoch() -> io::Result<String> {
    let mut bytes = [0u8; 16];
    File::open("/dev/urandom")?.read_exact(&mut bytes)?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

pub fn action_hash(action: &serde_json::Value) -> io::Result<String> {
    // serde_json's default map is sorted; actions contain only bounded integers
    // and strings. This matches the Worker canonical JSON for normalized plans.
    Ok(format!("{:x}", Sha256::digest(serde_json::to_vec(action)?)))
}

impl PlanLedger {
    pub fn open(root: &Path, app_session_id: &str) -> io::Result<Self> {
        if !root.is_absolute() || !id_valid(app_session_id) {
            return Err(invalid("invalid ledger identity or path"));
        }
        fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(root)?;
        let meta = fs::symlink_metadata(root)?;
        if !meta.is_dir()
            || meta.uid() != unsafe { libc::geteuid() }
            || meta.mode() & 0o077 != 0
            || fs::canonicalize(root)? != root
        {
            return Err(invalid(
                "ledger directory must be canonical, private and owned",
            ));
        }
        let lock = private_file(&root.join("owner.lock"), true)?;
        if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
            return Err(io::Error::last_os_error());
        }
        let state_path = root.join("plans.json");
        let state = match private_file(&state_path, false) {
            Ok(mut file) => {
                if file.metadata()?.len() > MAX_BYTES {
                    return Err(invalid("ledger exceeds byte limit"));
                }
                let mut bytes = Vec::new();
                Read::by_ref(&mut file)
                    .take(MAX_BYTES + 1)
                    .read_to_end(&mut bytes)?;
                if bytes.len() as u64 > MAX_BYTES {
                    return Err(invalid("ledger exceeds byte limit"));
                }
                serde_json::from_slice::<Snapshot>(&bytes)?
            }
            Err(e) if e.kind() == io::ErrorKind::NotFound => Snapshot {
                schema_version: 1,
                app_session_id: app_session_id.to_owned(),
                records: BTreeMap::new(),
            },
            Err(e) => return Err(e),
        };
        if state.schema_version != 1
            || state.app_session_id != app_session_id
            || state.records.len() > MAX_RECORDS
        {
            return Err(invalid("invalid ledger schema or session"));
        }
        for (id, record) in &state.records {
            if id != &record.identity.plan_id || record.identity.app_session_id != app_session_id {
                return Err(invalid("invalid persisted plan identity"));
            }
            validate_identity(&record.identity)?;
        }
        let mut ledger = Self {
            root: root.to_owned(),
            _lock: lock,
            state,
            epoch: fresh_epoch()?,
            failed: false,
        };
        // A new Controller never restores approval or treats an interrupted
        // execution as absent. Unknown remains visible and cannot be retried.
        let mut next = ledger.state.clone();
        for record in next.records.values_mut() {
            if matches!(
                record.execution,
                ExecutionState::Accepted
                    | ExecutionState::PendingApproval
                    | ExecutionState::Executing
            ) {
                record.execution = ExecutionState::Unknown;
            }
        }
        ledger.publish(next)?;
        Ok(ledger)
    }

    pub fn epoch(&self) -> &str {
        &self.epoch
    }
    pub fn app_session_id(&self) -> &str {
        &self.state.app_session_id
    }
    pub fn get(&self, plan_id: &str) -> Option<&PlanRecord> {
        self.state.records.get(plan_id)
    }
    pub fn by_request(&self, request_id: u64, generation: u64) -> Option<&PlanRecord> {
        self.state.records.values().find(|r| {
            r.identity.controller_epoch == self.epoch
                && r.identity.request_id == request_id
                && r.identity.session_generation == generation
        })
    }

    /// Return an existing decision only for the same immutable identity.
    /// `false` means the caller must return the stored ACK without execution.
    pub fn admit(
        &mut self,
        identity: PlanIdentity,
        decision: Decision,
        pending_approval: bool,
    ) -> io::Result<bool> {
        self.healthy()?;
        validate_identity(&identity)?;
        if let Some(prior) = self.state.records.get(&identity.plan_id) {
            if prior.identity != identity {
                return Err(invalid("plan id conflicts with persisted identity"));
            }
            return Ok(false);
        }
        if decision == Decision::Accepted
            && (identity.deadline_unix_ms <= now_ms()
                || identity.deadline_unix_ms.saturating_sub(now_ms()) > 120_000)
        {
            return Err(invalid("plan reception deadline expired or invalid"));
        }
        if identity.app_session_id != self.state.app_session_id
            || identity.controller_epoch != self.epoch
        {
            return Err(invalid("stale Controller epoch or wrong business session"));
        }
        if self.state.records.values().any(|r| {
            r.identity.controller_epoch == identity.controller_epoch
                && r.identity.session_generation == identity.session_generation
                && r.identity.request_id == identity.request_id
        }) {
            return Err(invalid("request already has a reception decision"));
        }
        if self.state.records.len() >= MAX_RECORDS {
            return Err(invalid("ledger record capacity reached; archive required"));
        }
        let execution = if decision == Decision::Rejected {
            ExecutionState::Failed
        } else if pending_approval {
            ExecutionState::PendingApproval
        } else {
            ExecutionState::Accepted
        };
        let mut next = self.state.clone();
        next.records.insert(
            identity.plan_id.clone(),
            PlanRecord {
                identity,
                decision,
                execution,
            },
        );
        self.publish(next)?;
        Ok(true)
    }

    /// Persist the crossing of the hardware boundary before starting work.
    pub fn begin(&mut self, request_id: u64, generation: u64) -> io::Result<()> {
        self.healthy()?;
        let mut next = self.state.clone();
        let record = next
            .records
            .values_mut()
            .find(|r| {
                r.identity.controller_epoch == self.epoch
                    && r.identity.request_id == request_id
                    && r.identity.session_generation == generation
            })
            .ok_or_else(|| invalid("execution has no reception decision"))?;
        if record.decision != Decision::Accepted
            || !matches!(
                record.execution,
                ExecutionState::Accepted | ExecutionState::PendingApproval
            )
        {
            return Err(invalid("plan cannot cross execution boundary again"));
        }
        if record.identity.deadline_unix_ms <= now_ms() {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "plan execution deadline expired",
            ));
        }
        record.execution = ExecutionState::Executing;
        self.publish(next)
    }

    pub fn finish(
        &mut self,
        request_id: u64,
        generation: u64,
        state: ExecutionState,
    ) -> io::Result<()> {
        self.healthy()?;
        if !matches!(
            state,
            ExecutionState::Completed
                | ExecutionState::Failed
                | ExecutionState::Cancelled
                | ExecutionState::Unknown
        ) {
            return Err(invalid("invalid terminal state"));
        }
        let mut next = self.state.clone();
        let record = next
            .records
            .values_mut()
            .find(|r| {
                r.identity.controller_epoch == self.epoch
                    && r.identity.request_id == request_id
                    && r.identity.session_generation == generation
            })
            .ok_or_else(|| invalid("result has no reception decision"))?;
        if record.decision != Decision::Accepted
            || !matches!(
                record.execution,
                ExecutionState::Accepted
                    | ExecutionState::PendingApproval
                    | ExecutionState::Executing
            )
        {
            return Err(invalid("result cannot replace a terminal record"));
        }
        record.execution = state;
        self.publish(next)
    }

    pub fn invalidate_generation(&mut self, generation: u64) -> io::Result<()> {
        self.healthy()?;
        let mut next = self.state.clone();
        for record in next.records.values_mut() {
            if record.identity.controller_epoch == self.epoch
                && record.identity.session_generation == generation
            {
                match record.execution {
                    ExecutionState::Executing => record.execution = ExecutionState::Unknown,
                    ExecutionState::Accepted | ExecutionState::PendingApproval => {
                        record.execution = ExecutionState::Cancelled
                    }
                    _ => {}
                }
            }
        }
        self.publish(next)
    }

    fn healthy(&self) -> io::Result<()> {
        if self.failed {
            Err(invalid("ledger failed; restart and reconcile required"))
        } else {
            Ok(())
        }
    }
    fn publish(&mut self, next: Snapshot) -> io::Result<()> {
        self.healthy()?;
        let result = (|| {
            let bytes = serde_json::to_vec(&next)?;
            if bytes.len() as u64 > MAX_BYTES {
                return Err(invalid("ledger byte capacity reached"));
            }
            let tmp = self.root.join("plans.next");
            // A prior interrupted temporary file is data, never a lock. Open
            // without following links and validate before truncating it.
            let mut file = private_file(&tmp, true)?;
            file.set_len(0)?;
            file.write_all(&bytes)?;
            file.sync_all()?;
            fs::rename(&tmp, self.root.join("plans.json"))?;
            File::open(&self.root)?.sync_all()?;
            Ok(())
        })();
        match result {
            Ok(()) => {
                self.state = next;
                Ok(())
            }
            Err(e) => {
                self.failed = true;
                Err(e)
            }
        }
    }
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u128::from(u64::MAX)) as u64
}

fn validate_identity(id: &PlanIdentity) -> io::Result<()> {
    if id.plan_id.len() != 36
        || !id
            .plan_id
            .bytes()
            .all(|b| b.is_ascii_hexdigit() || b == b'-')
        || id.hash.len() != 64
        || !id.hash.bytes().all(|b| b.is_ascii_hexdigit())
        || !id_valid(&id.app_session_id)
        || !id_valid(&id.controller_epoch)
    {
        return Err(invalid("invalid plan identity"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Temp(PathBuf);
    impl Temp {
        fn new() -> Self {
            let root = std::env::var_os("TMPDIR").expect("explicit feature TMPDIR required");
            Self(PathBuf::from(root).join(format!("plan-ledger-{}", fresh_epoch().unwrap())))
        }
    }
    impl Drop for Temp {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    fn identity(ledger: &PlanLedger) -> PlanIdentity {
        PlanIdentity {
            plan_id: "a0000000-0000-0000-0000-000000000001".into(),
            hash: "a".repeat(64),
            app_session_id: ledger.app_session_id().into(),
            controller_epoch: ledger.epoch().into(),
            session_generation: 3,
            request_id: 9,
            deadline_unix_ms: now_ms() + 120_000,
        }
    }
    #[test]
    fn reception_is_idempotent_but_conflicts_and_second_request_plan_reject() {
        let root = Temp::new();
        let mut ledger = PlanLedger::open(&root.0, "app").unwrap();
        let id = identity(&ledger);
        assert!(ledger.admit(id.clone(), Decision::Accepted, true).unwrap());
        assert!(!ledger.admit(id.clone(), Decision::Rejected, false).unwrap());
        assert_eq!(
            ledger.get(&id.plan_id).unwrap().decision,
            Decision::Accepted
        );
        let mut conflict = id.clone();
        conflict.hash = "b".repeat(64);
        assert!(ledger.admit(conflict, Decision::Accepted, false).is_err());
        let mut second = id;
        second.plan_id = "b0000000-0000-0000-0000-000000000002".into();
        assert!(ledger.admit(second, Decision::Accepted, false).is_err());
    }
    #[test]
    fn execution_crosses_once_and_reopen_does_not_restore_approval() {
        let root = Temp::new();
        let mut ledger = PlanLedger::open(&root.0, "app").unwrap();
        let id = identity(&ledger);
        ledger.admit(id.clone(), Decision::Accepted, true).unwrap();
        ledger.begin(9, 3).unwrap();
        assert!(ledger.begin(9, 3).is_err());
        drop(ledger);
        let mut reopened = PlanLedger::open(&root.0, "app").unwrap();
        assert_ne!(reopened.epoch(), id.controller_epoch);
        assert_eq!(
            reopened.get(&id.plan_id).unwrap().execution,
            ExecutionState::Unknown
        );
        assert!(!reopened
            .admit(id.clone(), Decision::Accepted, false)
            .unwrap());
        assert!(reopened.begin(9, 3).is_err());
        let mut stale = id;
        stale.plan_id = "b0000000-0000-0000-0000-000000000002".into();
        assert!(reopened.admit(stale, Decision::Accepted, false).is_err());
    }
    #[test]
    fn expired_pending_is_distinct_from_replay_and_never_crosses_execution() {
        let root = Temp::new();
        let mut ledger = PlanLedger::open(&root.0, "app").unwrap();
        let id = identity(&ledger);
        ledger.admit(id.clone(), Decision::Accepted, true).unwrap();
        // Deterministically expire an admitted fixture without weakening the
        // production admission deadline or waiting for wall-clock time.
        ledger
            .state
            .records
            .get_mut(&id.plan_id)
            .unwrap()
            .identity
            .deadline_unix_ms = 1;
        assert_eq!(
            ledger.begin(9, 3).unwrap_err().kind(),
            io::ErrorKind::TimedOut
        );
        assert_eq!(
            ledger.get(&id.plan_id).unwrap().execution,
            ExecutionState::PendingApproval
        );
        ledger.finish(9, 3, ExecutionState::Cancelled).unwrap();
        assert_eq!(
            ledger.begin(9, 3).unwrap_err().kind(),
            io::ErrorKind::InvalidData
        );
    }

    #[test]
    fn generation_invalidation_cancels_pending_and_execution_remains_unknown() {
        let root = Temp::new();
        let mut ledger = PlanLedger::open(&root.0, "app").unwrap();
        let id = identity(&ledger);
        ledger.admit(id.clone(), Decision::Accepted, true).unwrap();
        ledger.invalidate_generation(3).unwrap();
        assert_eq!(
            ledger.get(&id.plan_id).unwrap().execution,
            ExecutionState::Cancelled
        );
        assert!(ledger.begin(9, 3).is_err());
    }
    #[test]
    fn terminal_result_survives_reopen_without_becoming_retryable() {
        let root = Temp::new();
        let mut ledger = PlanLedger::open(&root.0, "app").unwrap();
        let id = identity(&ledger);
        ledger.admit(id.clone(), Decision::Accepted, false).unwrap();
        ledger.begin(9, 3).unwrap();
        ledger.finish(9, 3, ExecutionState::Completed).unwrap();
        assert!(ledger.finish(9, 3, ExecutionState::Unknown).is_err());
        drop(ledger);
        let reopened = PlanLedger::open(&root.0, "app").unwrap();
        assert_eq!(
            reopened.get(&id.plan_id).unwrap().execution,
            ExecutionState::Completed
        );
    }
    #[test]
    fn second_owner_symlink_and_corrupt_snapshot_are_rejected() {
        let root = Temp::new();
        let ledger = PlanLedger::open(&root.0, "app").unwrap();
        assert!(PlanLedger::open(&root.0, "app").is_err());
        drop(ledger);
        fs::write(root.0.join("plans.json"), b"corrupt").unwrap();
        assert!(PlanLedger::open(&root.0, "app").is_err());
        fs::remove_file(root.0.join("plans.json")).unwrap();
        std::os::unix::fs::symlink("missing", root.0.join("plans.json")).unwrap();
        assert!(PlanLedger::open(&root.0, "app").is_err());
    }
    #[test]
    fn failed_write_latches_closed_even_after_fault_is_removed() {
        let root = Temp::new();
        let mut ledger = PlanLedger::open(&root.0, "app").unwrap();
        let id = identity(&ledger);
        fs::create_dir(root.0.join("plans.next")).unwrap();
        assert!(ledger.admit(id.clone(), Decision::Accepted, false).is_err());
        fs::remove_dir(root.0.join("plans.next")).unwrap();
        assert!(ledger.admit(id, Decision::Accepted, false).is_err());
    }
    #[test]
    fn canonical_hash_matches_worker_fixture() {
        assert_eq!(
            action_hash(&serde_json::json!({"reason":"safe","kind":"hold"})).unwrap(),
            "dde1285d9e0526364a0145df379b15e3e59f9e1b19858faa18f39e9e64c4bef8"
        );
    }
    #[test]
    fn child_owner() {
        let Some(root) = std::env::var_os("SDR_LEDGER_TEST_CHILD") else {
            return;
        };
        let root = PathBuf::from(root);
        let mut ledger = PlanLedger::open(&root, "app").unwrap();
        let id = identity(&ledger);
        ledger.admit(id.clone(), Decision::Accepted, true).unwrap();
        ledger.begin(9, 3).unwrap();
        fs::write(root.join("ready.json"), serde_json::to_vec(&id).unwrap()).unwrap();
        loop {
            std::thread::park();
        }
    }
    #[test]
    fn sigkill_releases_owner_and_keeps_execution_unknown() {
        let root = Temp::new();
        let mut child = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "plan_ledger::tests::child_owner", "--nocapture"])
            .env("SDR_LEDGER_TEST_CHILD", &root.0)
            .stdout(std::process::Stdio::null())
            .spawn()
            .unwrap();
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        while !root.0.join("ready.json").exists() && std::time::Instant::now() < deadline {
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        let ready = root.0.join("ready.json").exists();
        if !ready {
            let _ = child.kill();
            let _ = child.wait();
            panic!("child did not reach durable fault point");
        }
        assert!(PlanLedger::open(&root.0, "app").is_err());
        child.kill().unwrap();
        child.wait().unwrap();
        let id: PlanIdentity =
            serde_json::from_slice(&fs::read(root.0.join("ready.json")).unwrap()).unwrap();
        let mut reopened = PlanLedger::open(&root.0, "app").unwrap();
        assert_eq!(
            reopened.get(&id.plan_id).unwrap().execution,
            ExecutionState::Unknown
        );
        assert!(!reopened.admit(id, Decision::Accepted, false).unwrap());
        assert!(reopened.begin(9, 3).is_err());
    }
    #[test]
    fn expiry_blocks_reception_and_late_approval() {
        let root = Temp::new();
        let mut ledger = PlanLedger::open(&root.0, "app").unwrap();
        let mut id = identity(&ledger);
        id.deadline_unix_ms = now_ms() - 1;
        assert!(ledger.admit(id.clone(), Decision::Accepted, true).is_err());
        id.deadline_unix_ms = now_ms() + 50;
        ledger.admit(id, Decision::Accepted, true).unwrap();
        std::thread::sleep(std::time::Duration::from_millis(60));
        assert!(ledger.begin(9, 3).is_err());
    }
}
