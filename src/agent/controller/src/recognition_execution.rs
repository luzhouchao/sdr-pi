//! S5 explicitly selected engineering RX/recognition lifecycle. Never enables capability.
use crate::execution::{
    validate_authorization, ExecutionAuthorization, SdrActionExecutor, SdrdActionAdapter,
};
use crate::policy::ControllerPolicy;
use crate::protocol::{
    ObservationSummary, PlanRequest, PlanResponse, PlanStatus, ProposedAction, ValidatedPlan,
    PROTOCOL_VERSION,
};
use crate::recognition_input::{
    frozen_rf_v1_profile, RecognitionTarget, SdrdModelReadyBatchCapture,
};
use crate::recognition_result::{
    CalibrationStatus, RecognitionObservation, RecognitionResult, RecognitionStatus,
};
use crate::sdr::{SdrEngine, SdrError, SdrSnapshot, SdrdAdapter};
use crate::sweep::{SdrdSoftwareSweepAdapter, SweepEngine, SweepFrequencies, SweepPlan};
use serde::{Deserialize, Serialize};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::sync::{
    atomic::{AtomicBool, AtomicU8, Ordering},
    Arc,
};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

pub const MAX_RX_BYTES: u64 = 32768; // fresh inspection + model capture, each 4096 ci16
pub const MAX_JOB_MS: u64 = 30000;
#[derive(Clone, Debug)]
pub struct EngineeringRecognition {
    pub supervisor_root: PathBuf,
    pub archive_address: SocketAddr,
}
#[derive(Clone, Default)]
pub struct RecognitionCancellation(Arc<AtomicBool>, Option<Instant>);
impl RecognitionCancellation {
    pub fn with_deadline(deadline: Instant) -> Self {
        Self(Arc::new(AtomicBool::new(false)), Some(deadline))
    }
    pub fn deadline_expired(&self) -> bool {
        self.1.is_some_and(|deadline| Instant::now() >= deadline)
    }
    pub fn cancel(&self) {
        self.0.store(true, Ordering::Release);
    }
    pub fn cancelled(&self) -> bool {
        self.0.load(Ordering::Acquire) || self.deadline_expired()
    }
}
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct RecognitionExecutionReport {
    pub engineering_only: bool,
    pub maximum_rx_bytes: u64,
    pub request_id: u64,
    pub session_generation: u64,
    pub result: RecognitionResult,
    pub archive_id: Option<i64>,
    pub archive_error: Option<String>,
    pub post_execution_sdr: SdrSnapshot,
    pub next_observation: ObservationSummary,
}
fn err(code: &'static str) -> SdrError {
    SdrError::new(code, code)
}
pub fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}
impl EngineeringRecognition {
    pub fn new(supervisor_root: PathBuf, archive_address: SocketAddr) -> Result<Self, SdrError> {
        if !supervisor_root.is_absolute()
            || !archive_address.ip().is_loopback()
            || archive_address.port() == 0
        {
            return Err(err("engineering_config"));
        }
        Ok(Self {
            supervisor_root,
            archive_address,
        })
    }
    pub fn validate_plan(
        &self,
        request: &PlanRequest,
        response: PlanResponse,
    ) -> Result<ValidatedPlan, SdrError> {
        ControllerPolicy
            .validate_engineering_response(request, response)
            .map_err(|e| SdrError::new(e.code, e.message))
    }
    pub fn preflight(&self, request: &PlanRequest, plan: &ValidatedPlan) -> Result<(), SdrError> {
        let validated = self.validate_plan(
            request,
            PlanResponse {
                protocol_version: PROTOCOL_VERSION,
                request_id: plan.request_id,
                session_generation: plan.session_generation,
                status: PlanStatus::Ok,
                planner: plan.planner.clone(),
                action: Some(plan.action.clone()),
                error: None,
            },
        )?;
        if validated != *plan || !matches!(plan.action, ProposedAction::RunLocalRecognition { .. })
        {
            return Err(err("recognition_plan"));
        }
        let h = crate::supervised_recognition::health(&self.supervisor_root)
            .map_err(|e| SdrError::new(e.code, e.to_string()))?;
        if !h.ready
            || h.fault.is_some()
            || h.active.is_some()
            || h.queue_depth != 0
            || h.recognizer_available
            || h.minimum_generation > plan.session_generation
            || !h.metrics.contains_key("gpu_acquired")
        {
            return Err(err("supervised_gpu_unavailable"));
        }
        crate::batch_recognition::prepare_batch_spool(
            &self.supervisor_root.join("incoming"),
            32768,
        )
        .map_err(|e| SdrError::new(e.code, e.to_string()))?;
        Ok(())
    }
    pub fn execute(
        &self,
        address: SocketAddr,
        request: &PlanRequest,
        plan: &ValidatedPlan,
        authorization: &ExecutionAuthorization,
        cancellation: &RecognitionCancellation,
    ) -> Result<RecognitionExecutionReport, SdrError> {
        if !plan.approval_required {
            return Err(err("recognition_approval_required"));
        }
        validate_authorization(plan, authorization)?;
        self.preflight(request, plan)?;
        if cancellation.cancelled() {
            return Err(err("cancelled"));
        }
        let ProposedAction::RunLocalRecognition { candidate_id } = &plan.action else {
            return Err(err("recognition_action"));
        };
        let candidate = request
            .observation
            .candidates
            .iter()
            .find(|c| &c.id == candidate_id)
            .ok_or_else(|| err("recognition_candidate"))?;
        let profile = frozen_rf_v1_profile().map_err(|e| SdrError::new(e.code, e.to_string()))?;
        let sweep = SweepPlan {
            sweep_id: format!("recognition-inspect-{}", plan.request_id),
            session_generation: plan.session_generation,
            frequencies: SweepFrequencies::Centers {
                centers_hz: vec![candidate.center_hz],
            },
            sample_rate_hz: 2_100_000,
            rf_bandwidth_hz: 1_500_000,
            settle_ms: 100,
            frame_samples: 4096,
            aggregate_frames: 1,
            point_timeout_ms: 1000,
            detection_threshold_db: 12.0,
            gain_db: Some(50),
        };
        crate::sweep::validate_plan(&sweep).map_err(|e| SdrError::new(e.code, e.to_string()))?;
        eprintln!("validated_s5_rx_plan={} maximum_rx_bytes={} maximum_model_bytes=32768 estimated_max_ms={} agx_spool={} p201_batch_feature=agx-model-batch-{}-{} stop=recognition_cancellation",serde_json::to_string(&sweep).unwrap(),MAX_RX_BYTES,MAX_JOB_MS,self.supervisor_root.join("incoming").display(),plan.session_generation,plan.request_id);
        let stage = Arc::new(AtomicU8::new(1)); // 1 SDR phase, 2 model/archive, 3 complete
        let control_stage = stage.clone();
        let control = cancellation.clone();
        let generation = plan.session_generation;
        let cancel_worker = std::thread::spawn(move || {
            let deadline = Instant::now() + Duration::from_millis(MAX_JOB_MS);
            while control_stage.load(Ordering::Acquire) != 3 {
                if Instant::now() >= deadline {
                    control.cancel();
                }
                if control.cancelled() && control_stage.load(Ordering::Acquire) == 1 {
                    let mut adapter = SdrdActionAdapter::new(address, Duration::from_millis(250));
                    let _ = adapter.cancel(generation); // Owner still must prove restoration before returning.
                }
                std::thread::sleep(Duration::from_millis(10));
            }
        });
        let mut next = request.observation.clone();
        next.recognition = None;
        let work = (|| {
            if cancellation.cancelled() {
                return Err(err("cancelled"));
            }
            let backend = SdrdSoftwareSweepAdapter::new(
                address,
                Duration::from_millis(u64::from(profile.profile.capture.control_deadline_ms)),
            );
            let inspection = SweepEngine::new(backend)
                .run(&sweep)
                .map_err(|e| SdrError::new(e.code, e.to_string()))?;
            if cancellation.cancelled() {
                return Err(err("cancelled"));
            }
            next = inspection
                .planner_inspection_observation(&next, candidate_id, next.health.clone())
                .map_err(|e| SdrError::new(e.code, e.to_string()))?;
            let measured = next
                .candidates
                .iter()
                .find(|c| &c.id == candidate_id)
                .ok_or_else(|| err("inspection_candidate"))?;
            let target = RecognitionTarget::from_inspection(measured, &inspection, now_ms(), 50)
                .map_err(|e| SdrError::new(e.code, e.to_string()))?;
            if target.center_hz < request.limits.min_freq_hz
                || target.center_hz > request.limits.max_freq_hz
            {
                return Err(err("recognition_frequency"));
            }
            eprintln!(
                "s5_recognition_source={}",
                serde_json::to_string(&target).unwrap()
            );
            let batch = SdrdModelReadyBatchCapture::new(address)
                .capture(
                    &profile,
                    &target,
                    plan.request_id,
                    plan.session_generation,
                    now_ms(),
                )
                .map_err(|e| SdrError::new(e.code, e.to_string()))?;
            stage.store(2, Ordering::Release);
            if cancellation.cancelled() {
                return Err(err("cancelled"));
            }
            let batch = crate::supervised_recognition::run_supervised_batch(
                &profile,
                batch,
                &self.supervisor_root,
                || cancellation.cancelled(),
            )
            .map_err(|e| SdrError::new(e.code, e.to_string()))?;
            RecognitionResult::from_experimental_batch(&profile, batch, now_ms())
                .map_err(|e| SdrError::new("recognition_result", e))
        })();
        let model_phase = stage.load(Ordering::Acquire) == 2;
        stage.store(3, Ordering::Release);
        cancel_worker
            .join()
            .map_err(|_| err("cancel_worker_panicked"))?;
        // Restoration is required on success, error and cancellation before the
        // caller may renew a session or use later observations.
        let snapshot = SdrdAdapter::new(
            address,
            Duration::from_millis(u64::from(profile.profile.capture.control_deadline_ms)),
        )
        .observe()?;
        if !snapshot.online
            || !snapshot.healthy
            || !snapshot
                .rx_input
                .as_ref()
                .is_some_and(|r| r.is_fixed_p201_rx1())
        {
            return Err(err("recognition_restore_unverified"));
        }
        if let Err(error) = &work {
            if error.code.contains("restore") || error.code == "post_execution_health" {
                return Err(err("recognition_restore_unverified"));
            }
        }
        if model_phase
            && work
                .as_ref()
                .is_err_and(|error| !matches!(error.code, "cancelled" | "supervisor_batch_failed"))
        {
            // Transport/cleanup ambiguity is a controller fault, never a
            // confirmed cancellation merely because the stop flag was set.
            return Err(err("recognition_worker_release_unverified"));
        }

        if cancellation.cancelled() {
            return Err(err("cancelled"));
        }
        if let Err(error) = &work {
            eprintln!(
                "s5_execution_failure code={} message={}",
                error.code,
                error.message.chars().take(512).collect::<String>()
            );
        }
        let result = match work {
            Ok(r) => r,
            Err(e) => RecognitionResult {
                schema_version: 1,
                observation: RecognitionObservation {
                    schema_version: 1,
                    candidate_id: candidate_id.clone(),
                    request_id: plan.request_id,
                    session_generation: plan.session_generation,
                    observed_at_unix_ms: now_ms(),
                    status: RecognitionStatus::Error,
                    reason: Some(e.code.into()),
                    class: None,
                    calibrated_confidence: None,
                    calibration_status: CalibrationStatus::Unavailable,
                    decision_references: None,
                    identity: None,
                    source: None,
                    quality: None,
                    timing: None,
                },
                experimental_prediction: None,
                uncalibrated_probability: None,
                experimental_batch: None,
            },
        };
        result
            .validate(&profile)
            .map_err(|e| SdrError::new("recognition_result", e))?;
        let (archive_id, archive_error) = match self.archive(&result) {
            Ok(id) => (Some(id), None),
            Err(e) => (None, Some(e.code.into())),
        };
        if cancellation.cancelled() {
            return Err(err("cancelled"));
        }
        next.age_ms = 0;
        next.health = snapshot.planner_health(false, next.health.dropped_observations);
        next.recognition = Some(
            result
                .planner_observation(&profile)
                .map_err(|e| SdrError::new("recognition_observation", e))?,
        );
        Ok(RecognitionExecutionReport {
            engineering_only: true,
            maximum_rx_bytes: MAX_RX_BYTES,
            request_id: plan.request_id,
            session_generation: plan.session_generation,
            result,
            archive_id,
            archive_error,
            post_execution_sdr: snapshot,
            next_observation: next,
        })
    }
    fn archive(&self, result: &RecognitionResult) -> Result<i64, SdrError> {
        let bytes=serde_json::to_vec(&serde_json::json!({"schema_version":1,"session_id":format!("runner-{}",result.observation.session_generation),"origin":"engineering_rx","result":result})).map_err(|_|err("archive_encode"))?;
        if bytes.len() > 66560 {
            return Err(err("archive_bound"));
        }
        let deadline = Instant::now() + Duration::from_millis(1500);
        let mut stream =
            TcpStream::connect_timeout(&self.archive_address, Duration::from_millis(500))
                .map_err(|_| err("archive_connect"))?;
        stream
            .set_read_timeout(Some(Duration::from_millis(20)))
            .map_err(|_| err("archive_timeout"))?;
        stream
            .set_write_timeout(Some(Duration::from_millis(20)))
            .map_err(|_| err("archive_timeout"))?;
        let mut wire=format!("POST /api/recognition-results HTTP/1.1\r\nHost: {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",self.archive_address,bytes.len()).into_bytes();
        wire.extend_from_slice(&bytes);
        let mut sent = 0;
        let mut response = Vec::new();
        loop {
            if Instant::now() >= deadline {
                return Err(err("archive_timeout"));
            }
            let writing = sent < wire.len();
            let outcome = if writing {
                stream.write(&wire[sent..]).map(|n| {
                    sent += n;
                    n
                })
            } else {
                let mut chunk = [0u8; 1024];
                stream.read(&mut chunk).map(|n| {
                    response.extend_from_slice(&chunk[..n]);
                    n
                })
            };
            match outcome {
                Ok(0) if !writing => break,
                Ok(0) => return Err(err("archive_closed")),
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
                Err(_) => return Err(err("archive_transport")),
            }
            if response.len() > 16384 {
                return Err(err("archive_bound"));
            }
        }
        if response.len() > 16384 || !response.starts_with(b"HTTP/1.1 201 ") {
            return Err(err("archive_response"));
        }
        let split = response
            .windows(4)
            .position(|p| p == b"\r\n\r\n")
            .ok_or_else(|| err("archive_frame"))?;
        let header = std::str::from_utf8(&response[..split]).map_err(|_| err("archive_frame"))?;
        let mut length = None;
        for line in header.split("\r\n").skip(1) {
            let (name, value) = line.split_once(':').ok_or_else(|| err("archive_frame"))?;
            if name.eq_ignore_ascii_case("transfer-encoding") {
                return Err(err("archive_encoding"));
            }
            if name.eq_ignore_ascii_case("content-length") {
                if length.is_some() {
                    return Err(err("archive_frame"));
                }
                length = Some(
                    value
                        .trim()
                        .parse::<usize>()
                        .map_err(|_| err("archive_frame"))?,
                );
            }
        }
        if length != Some(response.len() - split - 4) {
            return Err(err("archive_frame"));
        }
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Receipt {
            id: i64,
            created_at_ms: u64,
            session_id: String,
            origin: String,
            experimental_prediction: Option<crate::recognition_result::ClassIdentity>,
            uncalibrated_probability: Option<f64>,
            production_result: bool,
            iq_retained: bool,
            observation: RecognitionObservation,
        }
        let receipt: Receipt =
            serde_json::from_slice(&response[split + 4..]).map_err(|_| err("archive_receipt"))?;
        if receipt.id <= 0
            || receipt.created_at_ms == 0
            || receipt.session_id != format!("runner-{}", result.observation.session_generation)
            || receipt.origin != "engineering_rx"
            || receipt.experimental_prediction != result.experimental_prediction
            || receipt.uncalibrated_probability != result.uncalibrated_probability
            || receipt.production_result
            || receipt.iq_retained
            || receipt.observation != result.observation
        {
            return Err(err("archive_correlation"));
        }
        Ok(receipt.id)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cancellation_observes_original_deadline_and_explicit_stop() {
        let expired = RecognitionCancellation::with_deadline(Instant::now());
        assert!(expired.cancelled());
        assert!(expired.deadline_expired());
        let future =
            RecognitionCancellation::with_deadline(Instant::now() + Duration::from_secs(60));
        assert!(!future.cancelled());
        future.clone().cancel();
        assert!(future.cancelled());
        assert!(!future.deadline_expired());
    }

    pub(crate) fn request() -> PlanRequest {
        serde_json::from_value(serde_json::json!({"protocol_version":1,"request_id":10,"session_generation":20,"instruction":"bounded engineering check","state":"idle","observation":{"age_ms":0,"health":{"sdr_online":true,"can_retune":true,"can_capture_iq":true,"recognizer_available":false,"dropped_observations":0},"candidates":[{"id":"candidate-1","center_hz":433920000,"bandwidth_hz":200000,"peak_dbfs":-30.0,"snr_db":10.0,"age_ms":0}]},"limits":{"min_freq_hz":70000000,"max_freq_hz":6000000000u64,"max_span_hz":5930000000u64,"max_bandwidth_hz":30000000,"max_dwell_ms":1000,"max_iq_samples":4096,"max_iq_bytes":32768,"auto_approve_iq_bytes":32768,"max_observation_age_ms":10000}})).unwrap()
    }
    fn proposal(request: &PlanRequest, action: serde_json::Value) -> PlanResponse {
        serde_json::from_value(serde_json::json!({"protocol_version":1,"request_id":request.request_id,"session_generation":request.session_generation,"status":"ok","planner":{"provider":"synthetic-regression","model":"fixture"},"action":action})).unwrap()
    }
    #[test]
    fn fixed_six_action_regression_and_host_only_engineering_approval() {
        let request = request();
        let config = EngineeringRecognition::new(
            PathBuf::from("/not-running"),
            "127.0.0.1:1".parse().unwrap(),
        )
        .unwrap();
        for action in [
            serde_json::json!({"kind":"hold","reason":"bounded"}),
            serde_json::json!({"kind":"stop_session","reason":"stop"}),
            serde_json::json!({"kind":"survey_band","start_hz":433000000,"stop_hz":434000000,"step_hz":1000000,"sample_rate_hz":2100000,"rf_bandwidth_hz":1500000,"dwell_ms":5}),
            serde_json::json!({"kind":"inspect_candidate","candidate_id":"candidate-1","center_hz":433920000,"sample_rate_hz":2100000,"rf_bandwidth_hz":1500000,"dwell_ms":100}),
            serde_json::json!({"kind":"capture_bounded_iq","candidate_id":"candidate-1","center_hz":433920000,"sample_rate_hz":2100000,"rf_bandwidth_hz":1500000,"samples":4096}),
            serde_json::json!({"kind":"run_local_recognition","candidate_id":"candidate-1"}),
        ] {
            let proposal = proposal(&request, action);
            let recognition = matches!(
                proposal.action,
                Some(ProposedAction::RunLocalRecognition { .. })
            );
            let normal = ControllerPolicy.validate_response(&request, proposal.clone());
            if recognition {
                assert_eq!(normal.unwrap_err().code, "recognizer_unavailable");
            } else {
                normal.unwrap();
            }
            let plan = config.validate_plan(&request, proposal).unwrap();
            if recognition {
                assert!(plan.approval_required);
                assert!(ExecutionAuthorization::automatic(&plan).is_err());
            }
            assert!(!request.observation.health.recognizer_available);
        }
    }
    #[test]
    fn engineering_rejects_stale_foreign_unhealthy_and_underbudget_requests() {
        let config = EngineeringRecognition::new(
            PathBuf::from("/not-running"),
            "127.0.0.1:1".parse().unwrap(),
        )
        .unwrap();
        let action =
            serde_json::json!({"kind":"run_local_recognition","candidate_id":"candidate-1"});
        for fault in [
            "generation",
            "request",
            "candidate",
            "bytes",
            "samples",
            "bandwidth",
            "dwell",
            "offline",
            "capture",
            "retune",
            "faulted",
            "age",
        ] {
            let mut request = request();
            let mut response = proposal(&request, action.clone());
            match fault {
                "generation" => response.session_generation += 1,
                "request" => response.request_id += 1,
                "candidate" => request.observation.candidates.clear(),
                "bytes" => request.limits.max_iq_bytes = 16384,
                "samples" => request.limits.max_iq_samples = 1024,
                "bandwidth" => request.limits.max_bandwidth_hz = 1500000,
                "dwell" => request.limits.max_dwell_ms = 50,
                "offline" => request.observation.health.sdr_online = false,
                "capture" => request.observation.health.can_capture_iq = false,
                "retune" => request.observation.health.can_retune = false,
                "faulted" => request.state = crate::protocol::ControllerState::Faulted,
                "age" => request.observation.candidates[0].age_ms = 10001,
                _ => unreachable!(),
            }
            assert!(config.validate_plan(&request, response).is_err(), "{fault}");
        }
        for hz in [69_999_999_u64, 6_000_000_001] {
            let request = request();
            let response = proposal(
                &request,
                serde_json::json!({"kind":"inspect_candidate","candidate_id":"candidate-1","center_hz":hz,"sample_rate_hz":48000000,"rf_bandwidth_hz":1500000,"dwell_ms":100}),
            );
            assert!(config.validate_plan(&request, response).is_err());
        }
    }
    #[test]
    fn preflight_rejects_busy_old_generation_or_unleased_worker_before_rx() {
        use std::io::{BufRead, BufReader};
        use std::os::unix::{fs::PermissionsExt, net::UnixListener};
        for fault in ["none", "busy", "queued", "generation", "no_gpu"] {
            let root =
                std::env::temp_dir().join(format!("s5-preflight-{}-{fault}", std::process::id()));
            std::fs::create_dir(&root).unwrap();
            std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
            let listener = UnixListener::bind(root.join("control.sock")).unwrap();
            let worker = std::thread::spawn(move || {
                listener.set_nonblocking(true).unwrap();
                let deadline = Instant::now() + Duration::from_secs(2);
                let mut stream = loop {
                    match listener.accept() {
                        Ok((s, _)) => break s,
                        Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                            assert!(Instant::now() < deadline);
                            std::thread::sleep(Duration::from_millis(1));
                        }
                        Err(e) => panic!("{e}"),
                    }
                };
                stream
                    .set_read_timeout(Some(Duration::from_secs(2)))
                    .unwrap();
                let mut line = String::new();
                BufReader::new(stream.try_clone().unwrap())
                    .read_line(&mut line)
                    .unwrap();
                let mut h = serde_json::json!({"schema_version":1,"operation":"health","instance_id":"a".repeat(64),"worker_instance_id":"b".repeat(64),"ready":true,"recognizer_available":false,"minimum_generation":1,"active":null,"queue_depth":0,"queue_capacity":1,"worker_pid":42,"fault":null,"metrics":{"gpu_acquired":1}});
                match fault {
                    "busy" => {
                        h["active"] =
                            serde_json::json!({"request_id":9,"session_generation":20,"window":0})
                    }
                    "queued" => h["queue_depth"] = 1.into(),
                    "generation" => h["minimum_generation"] = 21.into(),
                    "no_gpu" => h["metrics"] = serde_json::json!({}),
                    _ => {}
                }
                writeln!(stream, "{}", h).unwrap();
            });
            let config =
                EngineeringRecognition::new(root.clone(), "127.0.0.1:9".parse().unwrap()).unwrap();
            let request = request();
            let plan=config.validate_plan(&request,proposal(&request,serde_json::json!({"kind":"run_local_recognition","candidate_id":"candidate-1"}))).unwrap();
            assert_eq!(
                config.preflight(&request, &plan).is_ok(),
                fault == "none",
                "{fault}"
            );
            worker.join().unwrap();
            std::fs::remove_dir_all(root).unwrap();
        }
    }

    #[test]
    fn archive_receipt_is_correlated_and_bounded() {
        use std::net::TcpListener;
        for fault in ["none", "origin", "session", "request", "retained", "status"] {
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            let config = EngineeringRecognition::new(
                PathBuf::from("/unused"),
                listener.local_addr().unwrap(),
            )
            .unwrap();
            let result = RecognitionResult {
                schema_version: 1,
                observation: RecognitionObservation {
                    schema_version: 1,
                    candidate_id: "candidate-1".into(),
                    request_id: 10,
                    session_generation: 20,
                    observed_at_unix_ms: now_ms(),
                    status: RecognitionStatus::Error,
                    reason: Some("synthetic_failure".into()),
                    class: None,
                    calibrated_confidence: None,
                    calibration_status: CalibrationStatus::Unavailable,
                    decision_references: None,
                    identity: None,
                    source: None,
                    quality: None,
                    timing: None,
                },
                experimental_prediction: None,
                uncalibrated_probability: None,
                experimental_batch: None,
            };
            let mut value = serde_json::json!({"id":1,"created_at_ms":now_ms(),"session_id":"runner-20","origin":"engineering_rx","production_result":false,"iq_retained":false,"observation":result.observation,"experimental_prediction":null,"uncalibrated_probability":null});
            match fault {
                "origin" => value["origin"] = "synthetic_fixture".into(),
                "session" => value["session_id"] = "wrong".into(),
                "request" => value["observation"]["request_id"] = 11.into(),
                "retained" => value["iq_retained"] = true.into(),
                _ => {}
            }
            let worker = std::thread::spawn(move || {
                listener.set_nonblocking(true).unwrap();
                let deadline = Instant::now() + Duration::from_secs(3);
                let mut stream = loop {
                    match listener.accept() {
                        Ok((s, _)) => break s,
                        Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                            assert!(Instant::now() < deadline);
                            std::thread::sleep(Duration::from_millis(1));
                        }
                        Err(e) => panic!("{e}"),
                    }
                };
                stream
                    .set_read_timeout(Some(Duration::from_secs(2)))
                    .unwrap();
                let mut body = Vec::new();
                loop {
                    let mut b = [0; 1024];
                    let n = stream.read(&mut b).unwrap();
                    assert!(n > 0);
                    body.extend_from_slice(&b[..n]);
                    if let Some(p) = body.windows(4).position(|p| p == b"\r\n\r\n") {
                        let header = String::from_utf8_lossy(&body[..p]);
                        let len = header
                            .lines()
                            .find_map(|l| l.strip_prefix("Content-Length: "))
                            .unwrap()
                            .parse::<usize>()
                            .unwrap();
                        if body.len() == p + 4 + len {
                            break;
                        }
                    }
                }
                let body = serde_json::to_vec(&value).unwrap();
                let status = if fault == "status" { 200 } else { 201 };
                write!(
                    stream,
                    "HTTP/1.1 {status} Response\r\nContent-Length: {}\r\n\r\n",
                    body.len()
                )
                .unwrap();
                stream.write_all(&body).unwrap();
            });
            assert_eq!(config.archive(&result).is_ok(), fault == "none", "{fault}");
            worker.join().unwrap();
        }
    }
}
