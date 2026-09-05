//! Admission is a local validation receipt AND a fresh, correlated Worker probe.
//! Planner input, a receipt's status alone, and a cached health reply confer no capability.
use crate::protocol::PlanRequest;
use crate::recognition_input::sha256_hex;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::os::fd::{AsRawFd, FromRawFd};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::os::unix::net::UnixStream;
use std::path::{Component, Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

pub const DEFAULT_ADMISSION_PATH: &str = "/home/jetson/sdrharness/jetson-agx/sdrharness/config/amc/rf-v1-recognizer-admission.candidate.json";
pub const DEFAULT_RECOGNIZER_SOCKET: &str = "/run/sdr-agent/recognizer.sock";
const MAX_BYTES: usize = 16 * 1024;
const PROBE_TIMEOUT: Duration = Duration::from_millis(250);
const GATES: [&str; 6] = [
    "input_profile",
    "calibration",
    "known_rf_ood",
    "locked_test",
    "worker_runtime",
    "deployment",
];

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecognizerIdentity {
    pub model_id: String,
    pub checkpoint_sha256: String,
    pub profile_sha256: String,
    pub preprocess_sha256: String,
    pub compute: String,
    pub resident_weight_precision: String,
    pub input_precision: String,
    pub logit_return_precision: String,
    pub sample_rate_hz: u32,
    pub window_count: u16,
    pub samples_per_window: u32,
    pub aggregation: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AdmissionStatus {
    Candidate,
    Admitted,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EvidenceRef {
    pub gate: String,
    pub path: String,
    pub sha256: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecognizerAdmission {
    pub schema_version: u16,
    pub schema_id: String,
    pub admission_id: String,
    pub status: AdmissionStatus,
    pub identity: RecognizerIdentity,
    pub evidence: Vec<EvidenceRef>,
}

/// A gate-specific local approval receipt; its underlying bounded report is
/// hash verified too. Report assessment belongs to that gate's validation task.
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct EvidenceReceipt {
    schema_version: u16,
    schema_id: String,
    admission_id: String,
    gate: String,
    outcome: String,
    identity: RecognizerIdentity,
    report_path: String,
    report_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AdmissionHealthRequest {
    pub protocol_version: u16,
    pub operation: String,
    pub request_id: u64,
    pub session_generation: u64,
    pub nonce: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecognizerHealth {
    pub schema_version: u16,
    pub schema_id: String,
    pub protocol_version: u16,
    pub request_id: u64,
    pub session_generation: u64,
    pub nonce: String,
    pub worker_instance_id: String,
    pub started_at_unix_ms: u64,
    pub observed_at_unix_ms: u64,
    pub status: String,
    pub identity: Option<RecognizerIdentity>,
    pub admission_sha256: Option<String>,
    pub production_enabled: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecognizerCapabilityObservation {
    pub recognizer_available: bool,
    pub reason: String,
    pub request_id: u64,
    pub session_generation: u64,
    pub observed_at_unix_ms: u64,
    pub worker_instance_id: Option<String>,
    pub admission_sha256: Option<String>,
}

pub trait RecognizerCapability {
    fn observe(&mut self, request_id: u64, generation: u64) -> RecognizerCapabilityObservation;
}

pub struct UnavailableRecognizer;
impl RecognizerCapability for UnavailableRecognizer {
    fn observe(&mut self, request_id: u64, generation: u64) -> RecognizerCapabilityObservation {
        unavailable(request_id, generation, "not_configured")
    }
}

fn unavailable(request_id: u64, generation: u64, reason: &str) -> RecognizerCapabilityObservation {
    RecognizerCapabilityObservation {
        recognizer_available: false,
        reason: reason.to_owned(),
        request_id,
        session_generation: generation,
        observed_at_unix_ms: now_ms(),
        worker_instance_id: None,
        admission_sha256: None,
    }
}

/// Call before sending context, validating a returned proposal and authorizing it.
/// Never copy availability from a request/template or a prior observation.
pub fn refresh_recognizer(
    request: &mut PlanRequest,
    probe: &mut dyn RecognizerCapability,
) -> RecognizerCapabilityObservation {
    request.observation.health.recognizer_available = false;
    let mut result = probe.observe(request.request_id, request.session_generation);
    let now = now_ms();
    if result.request_id == request.request_id
        && result.session_generation == request.session_generation
        && result.observed_at_unix_ms <= now
        && now - result.observed_at_unix_ms <= 1000
    {
        request.observation.health.recognizer_available = result.recognizer_available;
    } else {
        result.recognizer_available = false;
        result.reason = "capability_stale_or_mismatched".to_owned();
    }
    result
}

pub struct UnixRecognizerCapability {
    socket_path: PathBuf,
    admission_path: PathBuf,
    // Pin the first verified instance for each Controller generation. A restart
    // invalidates that generation; repeated probes cannot silently re-enable it.
    generation_instance: Option<(u64, String, String)>,
    invalidated_generation: Option<(u64, &'static str)>,
}

impl UnixRecognizerCapability {
    pub fn new(socket_path: impl Into<PathBuf>, admission_path: impl Into<PathBuf>) -> Self {
        Self {
            socket_path: socket_path.into(),
            admission_path: admission_path.into(),
            generation_instance: None,
            invalidated_generation: None,
        }
    }

    fn probe(
        &mut self,
        request_id: u64,
        generation: u64,
    ) -> Result<RecognizerCapabilityObservation, &'static str> {
        if request_id == 0 || generation == 0 {
            return Err("invalid_correlation");
        }
        if self
            .generation_instance
            .as_ref()
            .is_some_and(|(previous, _, _)| generation < *previous)
        {
            return Err("stale_generation");
        }
        let (admission, hash) = load_admission(&self.admission_path)?;
        let mut random = [0_u8; 32];
        File::open("/dev/urandom")
            .and_then(|mut file| file.read_exact(&mut random))
            .map_err(|_| "nonce_unavailable")?;
        let request = AdmissionHealthRequest {
            protocol_version: 1,
            operation: "admission_health".to_owned(),
            request_id,
            session_generation: generation,
            nonce: sha256_hex(&random),
        };
        let started = now_ms();
        let deadline = Instant::now() + PROBE_TIMEOUT;
        let mut stream = connect_bounded(&self.socket_path, deadline)?;
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .ok_or("health_timeout")?;
        stream
            .set_read_timeout(Some(remaining))
            .map_err(|_| "health_unavailable")?;
        stream
            .set_write_timeout(Some(remaining))
            .map_err(|_| "health_unavailable")?;
        let mut bytes = serde_json::to_vec(&request).map_err(|_| "health_request")?;
        bytes.push(b'\n');
        stream.write_all(&bytes).map_err(|_| "health_unavailable")?;
        let mut frame = Vec::new();
        // One byte at a time is bounded at 16 KiB and gives the entire response
        // a monotonic deadline even when a peer trickles bytes.
        loop {
            let remaining = deadline
                .checked_duration_since(Instant::now())
                .ok_or("health_timeout")?;
            stream
                .set_read_timeout(Some(remaining))
                .map_err(|_| "health_unavailable")?;
            let mut byte = [0];
            stream
                .read_exact(&mut byte)
                .map_err(|_| "health_unavailable")?;
            if byte[0] == b'\n' {
                break;
            }
            if frame.len() == MAX_BYTES {
                return Err("health_too_large");
            }
            frame.push(byte[0]);
        }
        let health: RecognizerHealth =
            serde_json::from_slice(&frame).map_err(|_| "health_schema")?;
        let ended = now_ms();
        validate_health(&admission, &hash, &request, &health, started, ended)?;
        if let Some((previous, instance, receipt)) = &self.generation_instance {
            if *previous == generation {
                if instance != &health.worker_instance_id {
                    self.invalidated_generation = Some((generation, "worker_restarted"));
                } else if receipt != &hash {
                    self.invalidated_generation = Some((generation, "admission_changed"));
                }
            }
        }
        if let Some((invalid, reason)) = self.invalidated_generation {
            if invalid == generation {
                return Err(reason);
            }
        }
        self.generation_instance =
            Some((generation, health.worker_instance_id.clone(), hash.clone()));
        let admitted = admission.status == AdmissionStatus::Admitted;
        let available = admitted && health.production_enabled && health.status == "ready";
        Ok(RecognizerCapabilityObservation {
            recognizer_available: available,
            reason: if !admitted {
                "candidate_not_admitted"
            } else if !health.production_enabled {
                "worker_not_admitted"
            } else if health.status != "ready" {
                "worker_busy"
            } else {
                "admitted_ready"
            }
            .to_owned(),
            request_id,
            session_generation: generation,
            observed_at_unix_ms: ended,
            worker_instance_id: Some(health.worker_instance_id),
            admission_sha256: Some(hash),
        })
    }
}

impl RecognizerCapability for UnixRecognizerCapability {
    fn observe(&mut self, request_id: u64, generation: u64) -> RecognizerCapabilityObservation {
        self.probe(request_id, generation)
            .unwrap_or_else(|reason| unavailable(request_id, generation, reason))
    }
}

fn connect_bounded(path: &Path, deadline: Instant) -> Result<UnixStream, &'static str> {
    let path = path.as_os_str().as_bytes();
    // SAFETY: zero is a valid initialization for sockaddr_un; the checked path
    // bytes and AF_UNIX family are filled before connect.
    let mut address: libc::sockaddr_un = unsafe { std::mem::zeroed() };
    if path.is_empty() || path.len() >= address.sun_path.len() || path.contains(&0) {
        return Err("health_socket_path");
    }
    address.sun_family = libc::AF_UNIX as libc::sa_family_t;
    for (dest, byte) in address.sun_path.iter_mut().zip(path) {
        *dest = *byte as libc::c_char;
    }
    // SAFETY: socket has no pointer arguments. A successful fd is owned exactly
    // once by stream, including every failure path below.
    let fd = unsafe {
        libc::socket(
            libc::AF_UNIX,
            libc::SOCK_STREAM | libc::SOCK_CLOEXEC | libc::SOCK_NONBLOCK,
            0,
        )
    };
    if fd < 0 {
        return Err("health_unavailable");
    }
    let stream = unsafe { UnixStream::from_raw_fd(fd) };
    // SAFETY: address is initialized and correctly sized for AF_UNIX.
    let result = unsafe {
        libc::connect(
            fd,
            (&address as *const libc::sockaddr_un).cast(),
            std::mem::size_of_val(&address) as libc::socklen_t,
        )
    };
    if result < 0 {
        let error = std::io::Error::last_os_error().raw_os_error();
        if error != Some(libc::EINPROGRESS) {
            return Err("health_unavailable");
        }
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .ok_or("health_timeout")?;
        let mut poll = libc::pollfd {
            fd,
            events: libc::POLLOUT,
            revents: 0,
        };
        // SAFETY: poll points at one valid pollfd for this call.
        if unsafe { libc::poll(&mut poll, 1, remaining.as_millis() as i32) } <= 0 {
            return Err("health_timeout");
        }
        let mut socket_error: libc::c_int = 0;
        let mut length = std::mem::size_of_val(&socket_error) as libc::socklen_t;
        // SAFETY: both output pointers are valid and correctly sized.
        if unsafe {
            libc::getsockopt(
                stream.as_raw_fd(),
                libc::SOL_SOCKET,
                libc::SO_ERROR,
                (&mut socket_error as *mut libc::c_int).cast(),
                &mut length,
            )
        } != 0
            || socket_error != 0
        {
            return Err("health_unavailable");
        }
    }
    stream
        .set_nonblocking(false)
        .map_err(|_| "health_unavailable")?;
    Ok(stream)
}

fn validate_health(
    admission: &RecognizerAdmission,
    hash: &str,
    request: &AdmissionHealthRequest,
    health: &RecognizerHealth,
    started: u64,
    ended: u64,
) -> Result<(), &'static str> {
    if health.schema_version != 1
        || health.schema_id != "recognizer_health_v1"
        || health.protocol_version != 1
    {
        return Err("health_schema");
    }
    if health.request_id != request.request_id
        || health.session_generation != request.session_generation
        || health.nonce != request.nonce
    {
        return Err("health_correlation");
    }
    if ended < started
        || health.observed_at_unix_ms < started
        || health.observed_at_unix_ms > ended
        || health.started_at_unix_ms == 0
        || health.started_at_unix_ms > health.observed_at_unix_ms
    {
        return Err("health_stale");
    }
    if !valid_hash(&health.worker_instance_id)
        || !matches!(health.status.as_str(), "ready" | "busy")
    {
        return Err("health_schema");
    }
    if health.identity.as_ref() != Some(&admission.identity)
        || health.admission_sha256.as_deref() != Some(hash)
    {
        return Err("health_identity");
    }
    Ok(())
}

fn read_regular(path: &Path, max_bytes: usize) -> Result<Vec<u8>, &'static str> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
        .map_err(|_| "admission_missing")?;
    let metadata = file.metadata().map_err(|_| "admission_file")?;
    if !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > max_bytes as u64
        || metadata.mode() & 0o022 != 0
    {
        return Err("admission_file");
    }
    let mut bytes = Vec::new();
    file.take((max_bytes + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| "admission_file")?;
    if bytes.len() > max_bytes {
        return Err("admission_file");
    }
    Ok(bytes)
}

fn referenced(
    root: &Path,
    relative: &str,
    hash: &str,
    maximum: usize,
) -> Result<Vec<u8>, &'static str> {
    let path = Path::new(relative);
    if path.is_absolute()
        || path
            .components()
            .any(|c| !matches!(c, Component::Normal(_)))
        || !valid_hash(hash)
    {
        return Err("evidence_path");
    }
    let candidate = root.join(path);
    let canonical = fs::canonicalize(&candidate).map_err(|_| "evidence_missing")?;
    if !canonical.starts_with(root) {
        return Err("evidence_path");
    }
    let bytes = read_regular(&candidate, maximum)?;
    if sha256_hex(&bytes) != hash {
        return Err("evidence_hash");
    }
    Ok(bytes)
}

pub fn load_admission(path: &Path) -> Result<(RecognizerAdmission, String), &'static str> {
    let bytes = read_regular(path, MAX_BYTES)?;
    let admission: RecognizerAdmission =
        serde_json::from_slice(&bytes).map_err(|_| "admission_schema")?;
    let identity = &admission.identity;
    if admission.schema_version != 1
        || admission.schema_id != "recognizer_admission_v1"
        || admission.admission_id.is_empty()
        || admission.admission_id.len() > 128
        || identity.model_id.is_empty()
        || identity.model_id.len() > 128
        || [
            &identity.checkpoint_sha256,
            &identity.profile_sha256,
            &identity.preprocess_sha256,
        ]
        .iter()
        .any(|h| !valid_hash(h))
        || identity.compute != "cuda_fp16_autocast"
        || identity.resident_weight_precision != "fp32"
        || identity.input_precision != "fp32"
        || identity.logit_return_precision != "fp32"
        || identity.sample_rate_hz != 2_100_000
        || identity.window_count != 4
        || identity.samples_per_window != 1024
        || identity.aggregation != "float64_arithmetic_mean_logits_then_softmax"
    {
        return Err("admission_identity");
    }
    if admission.status == AdmissionStatus::Candidate {
        if !admission.evidence.is_empty() {
            return Err("candidate_evidence");
        }
    } else {
        let gates: BTreeSet<_> = admission.evidence.iter().map(|e| e.gate.as_str()).collect();
        if admission.evidence.len() != GATES.len() || gates != GATES.into_iter().collect() {
            return Err("admission_incomplete");
        }
        let root = fs::canonicalize(path.parent().ok_or("admission_path")?)
            .map_err(|_| "admission_path")?;
        for reference in &admission.evidence {
            let bytes = referenced(&root, &reference.path, &reference.sha256, MAX_BYTES)?;
            let evidence: EvidenceReceipt =
                serde_json::from_slice(&bytes).map_err(|_| "evidence_schema")?;
            if evidence.schema_version != 1
                || evidence.schema_id != "recognizer_admission_evidence_v1"
                || evidence.admission_id != admission.admission_id
                || evidence.gate != reference.gate
                || evidence.identity != admission.identity
                || evidence.outcome != "pass"
            {
                return Err("evidence_identity");
            }
            referenced(
                &root,
                &evidence.report_path,
                &evidence.report_sha256,
                1024 * 1024,
            )?;
        }
    }
    Ok((admission, sha256_hex(&bytes)))
}

fn valid_hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|v| v.is_ascii_digit() || (b'a'..=b'f').contains(&v))
}
fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .try_into()
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader};
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::net::UnixListener;
    use std::thread;

    fn write_private(path: impl AsRef<Path>, bytes: impl AsRef<[u8]>) -> std::io::Result<()> {
        fs::write(&path, bytes)?;
        fs::set_permissions(path, fs::Permissions::from_mode(0o600))
    }

    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "adm-{}-{}",
                std::process::id(),
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            ));
            fs::create_dir(&path).unwrap();
            fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).unwrap();
            Self(path)
        }
        fn manifest(&self, admitted: bool) -> PathBuf {
            let mut admission: RecognizerAdmission = serde_json::from_slice(include_bytes!(
                "../../../../jetson-agx/sdrharness/config/amc/rf-v1-recognizer-admission.candidate.json")).unwrap();
            if admitted {
                admission.status = AdmissionStatus::Admitted;
                for gate in GATES {
                    let report_path = format!("{gate}.report");
                    let report =
                        format!("synthetic {gate} fixture; no actual dataset or test access");
                    write_private(self.0.join(&report_path), &report).unwrap();
                    let receipt = EvidenceReceipt {
                        schema_version: 1,
                        schema_id: "recognizer_admission_evidence_v1".to_owned(),
                        admission_id: admission.admission_id.clone(),
                        gate: gate.to_owned(),
                        outcome: "pass".to_owned(),
                        identity: admission.identity.clone(),
                        report_path,
                        report_sha256: sha256_hex(report.as_bytes()),
                    };
                    let bytes = serde_json::to_vec(&receipt).unwrap();
                    let path = format!("{gate}.json");
                    write_private(self.0.join(&path), &bytes).unwrap();
                    admission.evidence.push(EvidenceRef {
                        gate: gate.to_owned(),
                        path,
                        sha256: sha256_hex(&bytes),
                    });
                }
            }
            let path = self.0.join("admission.json");
            write_private(&path, serde_json::to_vec(&admission).unwrap()).unwrap();
            path
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }

    fn health(
        request: &AdmissionHealthRequest,
        admission: &RecognizerAdmission,
        hash: &str,
    ) -> RecognizerHealth {
        RecognizerHealth {
            schema_version: 1,
            schema_id: "recognizer_health_v1".to_owned(),
            protocol_version: 1,
            request_id: request.request_id,
            session_generation: request.session_generation,
            nonce: request.nonce.clone(),
            worker_instance_id: "a".repeat(64),
            started_at_unix_ms: now_ms() - 1000,
            observed_at_unix_ms: now_ms(),
            status: "ready".to_owned(),
            identity: Some(admission.identity.clone()),
            admission_sha256: Some(hash.to_owned()),
            production_enabled: true,
        }
    }

    fn server(
        path: &Path,
        count: usize,
        response: impl Fn(AdmissionHealthRequest, usize) -> Vec<u8> + Send + 'static,
    ) -> thread::JoinHandle<()> {
        let listener = UnixListener::bind(path).unwrap();
        listener.set_nonblocking(true).unwrap();
        thread::spawn(move || {
            for index in 0..count {
                let deadline = Instant::now() + Duration::from_secs(2);
                let (mut stream, _) = loop {
                    match listener.accept() {
                        Ok(value) => break value,
                        Err(error)
                            if error.kind() == std::io::ErrorKind::WouldBlock
                                && Instant::now() < deadline =>
                        {
                            thread::sleep(Duration::from_millis(1))
                        }
                        Err(error) => panic!("bounded fake Worker accept failed: {error}"),
                    }
                };
                stream
                    .set_read_timeout(Some(Duration::from_secs(1)))
                    .unwrap();
                let mut line = String::new();
                BufReader::new(stream.try_clone().unwrap())
                    .read_line(&mut line)
                    .unwrap();
                let request: AdmissionHealthRequest = serde_json::from_str(&line).unwrap();
                assert_eq!(request.operation, "admission_health");
                assert!(valid_hash(&request.nonce));
                let _ = stream.write_all(&response(request, index));
            }
        })
    }
    fn frame(health: &RecognizerHealth) -> Vec<u8> {
        let mut bytes = serde_json::to_vec(health).unwrap();
        bytes.push(b'\n');
        bytes
    }

    #[test]
    fn candidate_cannot_be_enabled_by_ready_worker_or_a_status_toggle() {
        let fixture = Fixture::new();
        let path = fixture.manifest(false);
        let (admission, hash) = load_admission(&path).unwrap();
        let socket = fixture.0.join("sock");
        let worker = server(&socket, 1, move |request, _| {
            frame(&health(&request, &admission, &hash))
        });
        let result = UnixRecognizerCapability::new(&socket, &path).observe(7, 3);
        assert!(!result.recognizer_available);
        assert_eq!(result.reason, "candidate_not_admitted");
        assert!(result.worker_instance_id.is_some());
        worker.join().unwrap();
        let (mut admission, _) = load_admission(&path).unwrap();
        admission.status = AdmissionStatus::Admitted;
        write_private(&path, serde_json::to_vec(&admission).unwrap()).unwrap();
        assert_eq!(load_admission(&path).unwrap_err(), "admission_incomplete");
    }

    #[test]
    fn evidence_reports_are_required_bound_and_hash_checked() {
        let fixture = Fixture::new();
        let path = fixture.manifest(true);
        assert!(load_admission(&path).is_ok());
        write_private(fixture.0.join("known_rf_ood.report"), b"changed").unwrap();
        assert_eq!(load_admission(&path).unwrap_err(), "evidence_hash");
        fixture.manifest(true);
        fs::remove_file(fixture.0.join("calibration.report")).unwrap();
        assert_eq!(load_admission(&path).unwrap_err(), "evidence_missing");
        fixture.manifest(true);
        let (mut admission, _) = load_admission(&path).unwrap();
        admission.evidence[0].path = "../escape".to_owned();
        write_private(&path, serde_json::to_vec(&admission).unwrap()).unwrap();
        assert_eq!(load_admission(&path).unwrap_err(), "evidence_path");
    }

    #[test]
    fn missing_corrupt_symlink_and_writable_admission_fail_closed() {
        let fixture = Fixture::new();
        let path = fixture.0.join("missing");
        let mut probe = UnixRecognizerCapability::new(fixture.0.join("sock"), &path);
        assert!(!probe.observe(7, 3).recognizer_available);
        write_private(&path, b"{broken}").unwrap();
        assert_eq!(probe.observe(7, 3).reason, "admission_schema");
        let valid = fixture.manifest(false);
        fs::remove_file(&path).unwrap();
        std::os::unix::fs::symlink(&valid, &path).unwrap();
        assert!(load_admission(&path).is_err());
        fs::set_permissions(&valid, fs::Permissions::from_mode(0o666)).unwrap();
        assert_eq!(load_admission(&valid).unwrap_err(), "admission_file");
    }

    #[test]
    fn stale_mismatched_or_unready_health_never_reuses_previous_success() {
        let fixture = Fixture::new();
        let path = fixture.manifest(true);
        let (admission, hash) = load_admission(&path).unwrap();
        let socket = fixture.0.join("sock");
        let worker = server(&socket, 13, move |request, index| {
            let mut h = health(&request, &admission, &hash);
            match index {
                1 => h.nonce = "0".repeat(64),
                2 => h.request_id += 1,
                3 => h.session_generation += 1,
                4 => h.observed_at_unix_ms = 1,
                5 => h.observed_at_unix_ms += 60_000,
                6 => h.identity.as_mut().unwrap().profile_sha256 = "0".repeat(64),
                7 => h.identity.as_mut().unwrap().checkpoint_sha256 = "0".repeat(64),
                8 => h.identity.as_mut().unwrap().preprocess_sha256 = "0".repeat(64),
                9 => h.identity.as_mut().unwrap().compute = "bf16".to_owned(),
                10 => h.production_enabled = false,
                11 => h.status = "busy".to_owned(),
                12 => h.admission_sha256 = None,
                _ => {}
            }
            frame(&h)
        });
        let mut probe = UnixRecognizerCapability::new(&socket, &path);
        assert!(probe.observe(7, 3).recognizer_available);
        for _ in 1..13 {
            assert!(!probe.observe(7, 3).recognizer_available);
        }
        worker.join().unwrap();
        assert!(!probe.observe(7, 3).recognizer_available);
    }

    #[test]
    fn worker_restart_invalidates_same_generation_until_new_context() {
        let fixture = Fixture::new();
        let path = fixture.manifest(true);
        let (admission, hash) = load_admission(&path).unwrap();
        let socket = fixture.0.join("sock");
        let worker = server(&socket, 4, move |request, index| {
            let mut h = health(&request, &admission, &hash);
            if index != 0 {
                h.worker_instance_id = "b".repeat(64);
            }
            frame(&h)
        });
        let mut probe = UnixRecognizerCapability::new(&socket, &path);
        assert!(probe.observe(7, 3).recognizer_available);
        assert_eq!(probe.observe(8, 3).reason, "worker_restarted");
        assert_eq!(probe.observe(9, 3).reason, "worker_restarted");
        assert!(probe.observe(10, 4).recognizer_available);
        worker.join().unwrap();
    }

    #[test]
    fn malformed_truncated_oversized_and_duplicate_health_frames_fail_closed() {
        let fixture = Fixture::new();
        let path = fixture.manifest(true);
        let socket = fixture.0.join("sock");
        let worker = server(&socket, 4, move |_, index| match index {
            0 => b"{\"production_enabled\":true}\n".to_vec(),
            1 => b"{\"schema_version\":1}".to_vec(),
            2 => vec![b'x'; MAX_BYTES + 1],
            _ => b"{\"schema_version\":1,\"schema_version\":1}\n".to_vec(),
        });
        let mut probe = UnixRecognizerCapability::new(&socket, &path);
        for _ in 0..4 {
            assert!(!probe.observe(7, 3).recognizer_available);
        }
        worker.join().unwrap();
    }

    #[test]
    fn unresponsive_worker_has_a_bounded_probe_deadline() {
        let fixture = Fixture::new();
        let path = fixture.manifest(false);
        let socket = fixture.0.join("sock");
        let worker = server(&socket, 1, move |_, _| {
            thread::sleep(Duration::from_millis(400));
            Vec::new()
        });
        let started = Instant::now();
        assert!(
            !UnixRecognizerCapability::new(&socket, &path)
                .observe(7, 3)
                .recognizer_available
        );
        assert!(started.elapsed() < Duration::from_millis(390));
        worker.join().unwrap();
    }

    #[test]
    fn full_listen_backlog_does_not_block_connect() {
        let fixture = Fixture::new();
        let socket = fixture.0.join("sock");
        let listener = UnixListener::bind(&socket).unwrap();
        // SAFETY: this valid listening socket remains open through the test.
        assert_eq!(unsafe { libc::listen(listener.as_raw_fd(), 1) }, 0);
        let _first = UnixStream::connect(&socket).unwrap();
        let _second = UnixStream::connect(&socket).unwrap();
        let started = Instant::now();
        assert!(connect_bounded(&socket, started + PROBE_TIMEOUT).is_err());
        assert!(started.elapsed() < PROBE_TIMEOUT);
    }
    #[test]
    fn changed_admission_requires_new_generation_and_old_generations_stay_stale() {
        let fixture = Fixture::new();
        let path = fixture.manifest(true);
        let (admission, _) = load_admission(&path).unwrap();
        let worker_path = path.clone();
        let socket = fixture.0.join("sock");
        let worker = server(&socket, 3, move |request, _| {
            let (_, hash) = load_admission(&worker_path).unwrap();
            frame(&health(&request, &admission, &hash))
        });
        let mut probe = UnixRecognizerCapability::new(&socket, &path);
        assert!(probe.observe(7, 3).recognizer_available);
        let mut changed = fs::read(&path).unwrap();
        changed.push(b' '); // Same semantic receipt, different audited bytes.
        write_private(&path, changed).unwrap();
        assert_eq!(probe.observe(8, 3).reason, "admission_changed");
        assert!(probe.observe(9, 4).recognizer_available);
        assert_eq!(probe.observe(10, 3).reason, "stale_generation");
        worker.join().unwrap();
    }
}
