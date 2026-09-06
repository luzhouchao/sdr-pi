//! S3 whole-batch Unix adapter. Ownership transfers by rename to the supervisor.
use crate::batch_recognition::{
    mean_logit_summary, prepare_batch_spool, validate_integration_batch, window_request,
    BatchRecognitionError, IntegrationBatchRecognitionReport, IntegrationWindowRecognition,
};
use crate::recognition_input::{LoadedRecognitionInputProfile, ModelReadyBatch, ProfileAdmission};
use crate::recognizer::RecognitionOutput;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::Path;
use std::time::{Duration, Instant};

const FRAME: usize = 65536;
fn error(code: &'static str) -> BatchRecognitionError {
    BatchRecognitionError::new(code, code)
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisorHealth {
    pub schema_version: u16,
    pub operation: String,
    pub instance_id: String,
    pub worker_instance_id: Option<String>,
    pub ready: bool,
    pub recognizer_available: bool,
    pub minimum_generation: u64,
    pub active: Option<ActiveBatch>,
    pub queue_depth: u16,
    pub queue_capacity: u16,
    pub worker_pid: Option<u32>,
    pub fault: Option<String>,
    pub metrics: BTreeMap<String, u64>,
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ActiveBatch {
    pub request_id: u64,
    pub session_generation: u64,
    pub window: Option<u16>,
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisorCancel {
    pub schema_version: u16,
    pub operation: String,
    pub instance_id: String,
    pub worker_instance_id: String,
    pub request_id: u64,
    pub session_generation: u64,
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BatchReply {
    pub schema_version: u16,
    pub operation: String,
    pub instance_id: String,
    pub worker_instance_id: String,
    pub request_id: u64,
    pub session_generation: u64,
    pub status: String,
    pub spool_removed: bool,
    pub outputs: Vec<RecognitionOutput>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Rejection {
    schema_version: u16,
    operation: String,
    code: String,
}
fn hash(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|v| v.is_ascii_digit() || (b'a'..=b'f').contains(&v))
}

fn rpc(
    root: &Path,
    socket: &str,
    payload: &impl Serialize,
    timeout: Duration,
    cancelled: &dyn Fn() -> bool,
) -> Result<Vec<u8>, BatchRecognitionError> {
    let deadline = Instant::now() + timeout;
    let mut stream = crate::recognizer_admission::connect_bounded(
        &root.join(socket),
        deadline.min(Instant::now() + Duration::from_millis(250)),
    )
    .map_err(error)?;
    stream
        .set_read_timeout(Some(Duration::from_millis(20)))
        .map_err(|_| error("supervisor_timeout"))?;
    stream
        .set_write_timeout(Some(Duration::from_millis(20)))
        .map_err(|_| error("supervisor_timeout"))?;
    let mut bytes = serde_json::to_vec(payload).map_err(|_| error("supervisor_encode"))?;
    bytes.push(b'\n');
    if bytes.len() > FRAME {
        return Err(error("supervisor_frame"));
    }
    let mut written = 0;
    let mut response = Vec::new();
    loop {
        if cancelled() {
            return Err(error("cancelled"));
        }
        if Instant::now() >= deadline {
            return Err(error("supervisor_deadline"));
        }
        let outcome = if written < bytes.len() {
            stream.write(&bytes[written..]).map(|n| {
                written += n;
                n
            })
        } else {
            let mut chunk = [0u8; 4096];
            stream.read(&mut chunk).map(|n| {
                response.extend_from_slice(&chunk[..n]);
                n
            })
        };
        match outcome {
            Ok(0) => return Err(error("supervisor_closed")),
            Ok(_) => {}
            Err(e)
                if matches!(
                    e.kind(),
                    std::io::ErrorKind::WouldBlock
                        | std::io::ErrorKind::TimedOut
                        | std::io::ErrorKind::Interrupted
                ) =>
            {
                continue
            }
            Err(_) => return Err(error("supervisor_transport")),
        }
        if response.len() > FRAME {
            return Err(error("supervisor_frame"));
        }
        if response.contains(&b'\n') {
            if response.last() != Some(&b'\n')
                || response.iter().filter(|v| **v == b'\n').count() != 1
            {
                return Err(error("supervisor_frame"));
            }
            return Ok(response);
        }
    }
}

pub fn health(root: &Path) -> Result<SupervisorHealth, BatchRecognitionError> {
    let metadata = fs::symlink_metadata(root).map_err(|_| error("supervisor_root"))?;
    if !root.is_absolute()
        || fs::canonicalize(root).map_err(|_| error("supervisor_root"))? != root
        || !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != unsafe { libc::geteuid() }
    {
        return Err(error("supervisor_root"));
    }

    let response = rpc(
        root,
        "control.sock",
        &serde_json::json!({"schema_version":1,"operation":"health"}),
        Duration::from_millis(250),
        &|| false,
    )?;
    let health: SupervisorHealth =
        serde_json::from_slice(&response).map_err(|_| error("supervisor_health"))?;
    if health.schema_version != 1
        || health.operation != "health"
        || !hash(&health.instance_id)
        || health.worker_instance_id.as_ref().is_some_and(|v| !hash(v))
        || health.recognizer_available
        || health.queue_capacity != 1
        || health.queue_depth > 1
    {
        return Err(error("supervisor_health"));
    }
    Ok(health)
}

fn correlate(
    reply: &BatchReply,
    request: &SupervisorCancel,
    operation: &str,
) -> Result<(), BatchRecognitionError> {
    if reply.schema_version != 1
        || reply.operation != operation
        || reply.instance_id != request.instance_id
        || reply.worker_instance_id != request.worker_instance_id
        || reply.request_id != request.request_id
        || reply.session_generation != request.session_generation
        || !reply.spool_removed
        || (reply.status != "ok" && !reply.outputs.is_empty())
    {
        return Err(error("supervisor_correlation"));
    }
    Ok(())
}

pub fn cancel(
    root: &Path,
    request: &SupervisorCancel,
) -> Result<BatchReply, BatchRecognitionError> {
    if request.schema_version != 1
        || request.operation != "cancel"
        || !hash(&request.instance_id)
        || !hash(&request.worker_instance_id)
        || request.request_id == 0
        || request.session_generation == 0
    {
        return Err(error("supervisor_cancel_request"));
    }
    let response = rpc(
        root,
        "control.sock",
        request,
        Duration::from_secs(3),
        &|| false,
    )?;
    let reply: BatchReply =
        serde_json::from_slice(&response).map_err(|_| error("cancel_unconfirmed"))?;
    correlate(&reply, request, "cancel")?;
    if reply.status != "cancelled" || !reply.outputs.is_empty() {
        return Err(error("cancel_unconfirmed"));
    }
    Ok(reply)
}

pub fn run_supervised_batch(
    loaded: &LoadedRecognitionInputProfile,
    batch: ModelReadyBatch,
    root: &Path,
    cancelled: impl Fn() -> bool,
) -> Result<IntegrationBatchRecognitionReport, BatchRecognitionError> {
    validate_integration_batch(loaded, &batch)?;
    if !loaded.is_rf_v1() {
        return Err(error("supervisor_rf_v1_only"));
    }
    let health = health(root)?;
    if !health.ready
        || health.fault.is_some()
        || batch.summary.session_generation < health.minimum_generation
    {
        return Err(error("supervisor_unavailable"));
    }
    let worker = health
        .worker_instance_id
        .ok_or_else(|| error("supervisor_unavailable"))?;
    let incoming = prepare_batch_spool(&root.join("incoming"), batch.summary.model_bytes)?;
    let filename = format!(
        "batch-{}-{}-{}.f32",
        health.instance_id, batch.summary.session_generation, batch.summary.request_id
    );
    let path = incoming.join(&filename);
    let owned = root.join("owned").join(&filename);
    let requests = batch
        .summary
        .windows
        .iter()
        .map(|q| {
            window_request(
                loaded,
                &batch.summary,
                q,
                path.to_str().ok_or_else(|| error("spool_path"))?,
            )
        })
        .collect::<Result<Vec<_>, _>>()?;
    let cancel_request = SupervisorCancel {
        schema_version: 1,
        operation: "cancel".into(),
        instance_id: health.instance_id.clone(),
        worker_instance_id: worker.clone(),
        request_id: batch.summary.request_id,
        session_generation: batch.summary.session_generation,
    };
    let payload = serde_json::json!({"schema_version":1,"operation":"submit","instance_id":health.instance_id,"worker_instance_id":worker,"request_id":batch.summary.request_id,"session_generation":batch.summary.session_generation,"timeout_ms":5000,"requests":requests});
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)
        .map_err(|_| error("spool_create"))?;
    let result = (|| {
        file.write_all(&batch.model_bytes)
            .and_then(|_| file.sync_all())
            .map_err(|_| error("spool_write"))?;
        let wire = rpc(
            root,
            "supervisor.sock",
            &payload,
            Duration::from_secs(8),
            &cancelled,
        );
        let reply = match wire {
            Ok(ref bytes) => {
                if let Ok(rejection) = serde_json::from_slice::<Rejection>(bytes) {
                    if rejection.schema_version == 1
                        && rejection.operation == "error"
                        && !owned.exists()
                    {
                        return Err(BatchRecognitionError::new(
                            "supervisor_rejected",
                            rejection.code,
                        ));
                    }
                }
                serde_json::from_slice::<BatchReply>(bytes).map_err(|_| error("supervisor_reply"))
            }
            Err(e) => Err(e),
        };
        let reply = match reply {
            Ok(r) => r,
            Err(e) => {
                if owned.exists() {
                    cancel(root, &cancel_request)?;
                }
                return Err(e);
            }
        };
        correlate(&reply, &cancel_request, "submit")?;
        if path.exists() || owned.exists() {
            return Err(error("supervisor_cleanup_unconfirmed"));
        }
        if cancelled() {
            return Err(error("cancelled"));
        }
        if reply.status != "ok" {
            return Err(BatchRecognitionError::new(
                "supervisor_batch_failed",
                reply.status,
            ));
        }
        if reply.outputs.len() != 4 {
            return Err(error("supervisor_window_count"));
        }
        let mut windows = Vec::new();
        for ((output, request), quality) in reply
            .outputs
            .into_iter()
            .zip(&requests)
            .zip(&batch.summary.windows)
        {
            crate::recognizer::validate_output(request, &output)?;
            windows.push(IntegrationWindowRecognition {
                window_index: quality.window_index,
                worker_request_id: request.request_id,
                output_offset_bytes: quality.output_offset_bytes,
                output_length_bytes: quality.output_length_bytes,
                recognition: output,
            });
        }
        let mean = mean_logit_summary(&windows)?;
        let report = IntegrationBatchRecognitionReport {
            schema_version: 1,
            status: "ok".into(),
            admission: ProfileAdmission::IntegrationOnly,
            production_enabled: false,
            production_recognizer_available: false,
            result_semantics:
                "unlabeled per-window predictions are integration evidence, not ground truth".into(),
            batch: batch.summary,
            windows,
            vote: None,
            mean_logit: Some(mean),
            transient_iq_removed: true,
        };
        crate::recognition_result::RecognitionResult::from_experimental_batch(
            loaded,
            report.clone(),
            1,
        )
        .map_err(|e| BatchRecognitionError::new("supervisor_result", e))?;
        Ok(report)
    })();
    drop(file);
    // Remove producer-owned incoming first: a later atomic handoff can no longer
    // race the ownership check below. If rename already won, only the service
    // may remove owned IQ, and cancellation must be confirmed there.
    match fs::remove_file(&path) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err(error("spool_cleanup")),
    }
    if result.is_err() && owned.exists() {
        match cancel(root, &cancel_request) {
            Ok(_) => result,
            Err(e) => Err(e),
        }
    } else {
        result
    }
}

/// Explicit engineering replay seam: only a bounded private direct-child fixture,
/// never a dataset reader or a radio action.
pub fn read_replay(
    bytes: &[u8],
    spool_root: &Path,
) -> Result<ModelReadyBatch, BatchRecognitionError> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct ReplayInput {
        batch: crate::recognition_input::ModelReadyBatchSummary,
        model_bytes_file: String,
    }
    if bytes.len() > FRAME {
        return Err(error("replay_frame"));
    }
    let input: ReplayInput = serde_json::from_slice(bytes).map_err(|_| error("replay_request"))?;
    let root = fs::canonicalize(spool_root).map_err(|_| error("replay_root"))?;
    let path = Path::new(&input.model_bytes_file);
    let canonical = fs::canonicalize(path).map_err(|_| error("replay_file"))?;
    if !path.is_absolute() || canonical != path || canonical.parent() != Some(root.as_path()) {
        return Err(error("replay_path"));
    }
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|_| error("replay_file"))?;
    let metadata = file.metadata().map_err(|_| error("replay_file"))?;
    // SAFETY: geteuid has no preconditions.
    if !metadata.is_file()
        || metadata.len() != 32768
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != unsafe { libc::geteuid() }
    {
        return Err(error("replay_file"));
    }
    let mut model_bytes = Vec::new();
    file.take(32769)
        .read_to_end(&mut model_bytes)
        .map_err(|_| error("replay_read"))?;
    if model_bytes.len() != 32768 {
        return Err(error("replay_shape"));
    }
    Ok(ModelReadyBatch {
        summary: input.batch,
        model_bytes,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::recognition_input::load_recognition_input_profile;
    use crate::recognizer::{RecognitionTiming, RecognizerBackend, RfV1WindowOutput};
    use std::io::{BufRead, BufReader};
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::net::{UnixListener, UnixStream};
    use std::sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    };
    fn accept(listener: &UnixListener) -> UnixStream {
        listener.set_nonblocking(true).unwrap();
        let deadline = Instant::now() + Duration::from_secs(3);
        loop {
            match listener.accept() {
                Ok((stream, _)) => return stream,
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    assert!(Instant::now() < deadline);
                    std::thread::sleep(Duration::from_millis(1));
                }
                Err(e) => panic!("{e}"),
            }
        }
    }
    fn read(stream: &mut UnixStream) -> serde_json::Value {
        stream
            .set_read_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        let mut line = String::new();
        BufReader::new(stream).read_line(&mut line).unwrap();
        serde_json::from_str(&line).unwrap()
    }
    fn send(stream: &mut UnixStream, payload: &impl Serialize) {
        let mut data = serde_json::to_vec(payload).unwrap();
        data.push(b'\n');
        stream.write_all(&data).unwrap();
    }
    #[test]
    #[ignore = "explicit bounded synthetic replay export"]
    fn export_supervised_replay_fixture() {
        let root =
            std::path::PathBuf::from(std::env::var("S3_VALIDATION_DIR").expect("feature root"));
        assert!(
            root.starts_with("/var/tmp/sdrharness-dev") && root.canonicalize().unwrap() == root
        );
        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let profile = load_recognition_input_profile(
            &repo,
            &repo.join("jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json"),
        )
        .unwrap();
        let batch = crate::batch_recognition::tests::batch(&profile);
        let path = root.join("model.f32");
        fs::write(&path, &batch.model_bytes).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        fs::write(
            root.join("replay.json"),
            serde_json::to_vec(&serde_json::json!({"batch":batch.summary,"model_bytes_file":path}))
                .unwrap(),
        )
        .unwrap();
    }

    #[test]
    fn supervised_adapter_validates_results_cancel_ack_and_exact_cleanup() {
        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let profile = load_recognition_input_profile(
            &repo,
            &repo.join("jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json"),
        )
        .unwrap();
        for fault in [
            "none",
            "request",
            "worker",
            "spool",
            "logits",
            "cancel",
            "busy",
            "late_handoff",
        ] {
            let root = std::env::temp_dir().join(format!("s3r-{}-{fault}", std::process::id()));
            fs::create_dir(&root).unwrap();
            fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
            for name in ["incoming", "owned"] {
                fs::create_dir(root.join(name)).unwrap();
                fs::set_permissions(root.join(name), fs::Permissions::from_mode(0o700)).unwrap();
            }
            let control = UnixListener::bind(root.join("control.sock")).unwrap();
            let main = UnixListener::bind(root.join("supervisor.sock")).unwrap();
            let cancelled = Arc::new(AtomicBool::new(false));
            let flag = cancelled.clone();
            let runtime = root.clone();
            let model = profile.profile.model.clone();
            let worker = std::thread::spawn(move || {
                let mut stream = accept(&control);
                assert_eq!(read(&mut stream)["operation"], "health");
                send(
                    &mut stream,
                    &serde_json::json!({"schema_version":1,"operation":"health","instance_id":"a".repeat(64),"worker_instance_id":"b".repeat(64),"ready":true,"recognizer_available":false,"minimum_generation":1,"active":null,"queue_depth":0,"queue_capacity":1,"worker_pid":42,"fault":null,"metrics":{}}),
                );
                drop(stream);
                let mut stream = accept(&main);
                let q = read(&mut stream);
                let requests: Vec<crate::recognizer::RecognitionRequest> =
                    serde_json::from_value(q["requests"].clone()).unwrap();
                let path = Path::new(&requests[0].iq.storage.path);
                assert_eq!(fs::metadata(path).unwrap().len(), 32768);
                if fault == "busy" {
                    send(
                        &mut stream,
                        &serde_json::json!({"schema_version":1,"operation":"error","code":"busy"}),
                    );
                    return;
                }
                let owned = runtime.join("owned").join(path.file_name().unwrap());
                let mut reply = BatchReply {
                    schema_version: 1,
                    operation: "submit".into(),
                    instance_id: "a".repeat(64),
                    worker_instance_id: "b".repeat(64),
                    request_id: q["request_id"].as_u64().unwrap(),
                    session_generation: q["session_generation"].as_u64().unwrap(),
                    status: "ok".into(),
                    spool_removed: true,
                    outputs: Vec::new(),
                };
                if fault == "late_handoff" {
                    flag.store(true, Ordering::SeqCst);
                    let mut byte = [0u8; 1];
                    assert_eq!(stream.read(&mut byte).unwrap(), 0);
                    // Simulate acceptance racing the client's disconnected RPC.
                    match fs::rename(path, &owned) {
                        Ok(()) => {}
                        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return,
                        Err(e) => panic!("{e}"),
                    }
                } else {
                    fs::rename(path, &owned).unwrap();
                }
                if fault == "cancel" || fault == "late_handoff" {
                    flag.store(true, Ordering::SeqCst);
                    let mut cancellation = accept(&control);
                    let c = read(&mut cancellation);
                    assert_eq!(c["operation"], "cancel");
                    fs::remove_file(&owned).unwrap();
                    reply.operation = "cancel".into();
                    reply.status = "cancelled".into();
                    send(&mut cancellation, &reply);
                    return;
                }
                for request in requests {
                    reply.outputs.push(RecognitionOutput {
                        candidate_id: request.candidate_id,
                        label: "provisional:00".into(),
                        confidence: 1.0 / 24.0,
                        alternatives: vec![],
                        backend: RecognizerBackend {
                            runtime: "synthetic".into(),
                            runtime_version: "1".into(),
                            model_id: model.model_id.clone(),
                            model_sha256: model.model_sha256.clone(),
                            threads: 1,
                        },
                        timing: RecognitionTiming {
                            map_us: 1,
                            preprocess_us: 1,
                            inference_us: 1,
                            total_us: 3,
                        },
                        rf_v1: Some(RfV1WindowOutput {
                            contract: request.rf_v1.unwrap(),
                            request_id: request.request_id,
                            session_generation: request.session_generation,
                            compute: "cuda_fp16_autocast".into(),
                            logits: vec![0.0; 24],
                        }),
                    });
                }
                fs::remove_file(&owned).unwrap();
                match fault {
                    "request" => reply.request_id += 1,
                    "worker" => reply.worker_instance_id = "c".repeat(64),
                    "spool" => reply.spool_removed = false,
                    "logits" => {
                        reply.outputs[0].rf_v1.as_mut().unwrap().logits.pop();
                    }
                    _ => {}
                }
                send(&mut stream, &reply);
            });
            let result = run_supervised_batch(
                &profile,
                crate::batch_recognition::tests::batch(&profile),
                &root,
                || cancelled.load(Ordering::SeqCst),
            );
            if fault == "none" {
                assert!(!result.unwrap().production_recognizer_available);
            } else {
                assert!(result.is_err(), "{fault}");
            }
            worker.join().unwrap();
            assert_eq!(fs::read_dir(root.join("incoming")).unwrap().count(), 0);
            assert_eq!(fs::read_dir(root.join("owned")).unwrap().count(), 0);
            fs::remove_dir_all(root).unwrap();
        }
    }
}
