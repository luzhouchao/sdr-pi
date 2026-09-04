use crate::execution::{ExecutionAuthorization, ExecutionObservation, SdrActionExecutor};
use crate::planner::Planner;
use crate::policy::ControllerPolicy;
use crate::protocol::{ObservationSummary, PlanRequest, ProposedAction, ValidatedPlan};
use crate::sdr::{SdrEngine, SdrError};
use crate::sweep::{
    SweepBackend, SweepEngine, SweepError, SweepFrequencies, SweepPlan, SweepReport,
};
use crate::ControllerError;
use serde::Serialize;
use serde_json::{json, Value};
use std::error::Error;
use std::fmt;
use std::fs::{File, OpenOptions};
use std::io::{self, Write};
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

const AUDIT_SCHEMA_VERSION: u16 = 1;
const MAX_AUDIT_EVENT_BYTES: usize = 32 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ApprovalMode {
    Pending,
    Automatic,
    Operator,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RunStatus {
    AwaitingApproval,
    PlannedOnly,
    Executed,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunReport {
    pub status: RunStatus,
    pub plan: ValidatedPlan,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub execution: Option<ExecutionObservation>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sweep: Option<SweepReport>,
    pub next_observation: ObservationSummary,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuditEvent {
    pub schema_version: u16,
    pub timestamp_unix_ms: u128,
    pub phase: &'static str,
    pub request_id: u64,
    pub session_generation: u64,
    pub payload: Value,
}

pub trait AuditSink {
    fn append(&mut self, event: &AuditEvent) -> io::Result<()>;
}

pub struct JsonlAuditAdapter {
    file: File,
}

impl JsonlAuditAdapter {
    pub fn open(path: impl AsRef<Path>) -> io::Result<Self> {
        let mut options = OpenOptions::new();
        options.create(true).append(true);
        #[cfg(unix)]
        options.mode(0o600);
        Ok(Self {
            file: options.open(path)?,
        })
    }
}

impl AuditSink for JsonlAuditAdapter {
    fn append(&mut self, event: &AuditEvent) -> io::Result<()> {
        let mut frame = serde_json::to_vec(event)
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
        if frame.len() > MAX_AUDIT_EVENT_BYTES {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "audit event exceeds 32 KiB",
            ));
        }
        frame.push(b'\n');
        self.file.write_all(&frame)?;
        self.file.flush()
    }
}

#[derive(Default)]
pub struct MemoryAuditAdapter {
    events: Vec<AuditEvent>,
}

impl MemoryAuditAdapter {
    pub fn events(&self) -> &[AuditEvent] {
        &self.events
    }
}

impl AuditSink for MemoryAuditAdapter {
    fn append(&mut self, event: &AuditEvent) -> io::Result<()> {
        self.events.push(event.clone());
        Ok(())
    }
}

pub struct Runner<O, P, E, S, A> {
    observer: O,
    planner: P,
    policy: ControllerPolicy,
    executor: E,
    sweep: SweepEngine<S>,
    survey_gain_db: i16,
    sweep_point_timeout_ms: u32,
    audit: A,
}

impl<O, P, E, S, A> Runner<O, P, E, S, A>
where
    O: SdrEngine,
    P: Planner,
    E: SdrActionExecutor,
    S: SweepBackend,
    A: AuditSink,
{
    pub fn new(
        observer: O,
        planner: P,
        executor: E,
        sweep_backend: S,
        survey_gain_db: i16,
        sweep_point_timeout_ms: u32,
        audit: A,
    ) -> Self {
        Self {
            observer,
            planner,
            policy: ControllerPolicy,
            executor,
            sweep: SweepEngine::new(sweep_backend),
            survey_gain_db,
            sweep_point_timeout_ms,
            audit,
        }
    }

    pub fn run_once(
        &mut self,
        mut request: PlanRequest,
        approval: ApprovalMode,
    ) -> Result<RunReport, RunnerError> {
        let live = match self.observer.observe() {
            Ok(observation) => observation,
            Err(error) => {
                self.audit(
                    "observation_failed",
                    &request,
                    json!({
                        "code": error.code,
                        "message": &error.message,
                        "metadata": &error.details,
                    }),
                )?;
                return Err(RunnerError::Sdr(error));
            }
        };
        let recognizer_available = request.observation.health.recognizer_available;
        let dropped_observations = request.observation.health.dropped_observations;
        request.observation.health =
            live.planner_health(recognizer_available, dropped_observations);
        request.observation.age_ms = 0;
        self.audit("input_observation", &request, json!(&request.observation))?;

        if let Err(error) = self.policy.validate_request(&request) {
            self.audit(
                "request_rejected",
                &request,
                json!({"code": error.code, "message": error.message.clone()}),
            )?;
            return Err(RunnerError::Controller(ControllerError::Policy(error)));
        }
        let response = match self.planner.plan(&request) {
            Ok(response) => response,
            Err(error) => {
                self.audit(
                    "planning_failed",
                    &request,
                    json!({"message": error.to_string()}),
                )?;
                return Err(RunnerError::Controller(ControllerError::Planner(error)));
            }
        };
        self.audit("planner_proposal", &request, json!(&response))?;
        let plan = match self.policy.validate_response(&request, response) {
            Ok(plan) => plan,
            Err(error) => {
                self.audit(
                    "validation_failed",
                    &request,
                    json!({"code": error.code, "message": error.message.clone()}),
                )?;
                return Err(RunnerError::Controller(ControllerError::Policy(error)));
            }
        };
        self.audit("validated_plan", &request, json!(&plan))?;

        if plan.approval_required && approval == ApprovalMode::Pending {
            self.audit(
                "awaiting_approval",
                &request,
                json!({"approval_required": true}),
            )?;
            return Ok(RunReport {
                status: RunStatus::AwaitingApproval,
                plan,
                execution: None,
                sweep: None,
                next_observation: request.observation,
            });
        }

        if !matches!(
            plan.action,
            ProposedAction::CaptureBoundedIq { .. }
                | ProposedAction::SurveyBand { .. }
                | ProposedAction::InspectCandidate { .. }
        ) {
            self.audit(
                "planned_only",
                &request,
                json!({"reason": "no production executor for this action"}),
            )?;
            return Ok(RunReport {
                status: RunStatus::PlannedOnly,
                plan,
                execution: None,
                sweep: None,
                next_observation: request.observation,
            });
        }

        let authorization = match approval {
            ApprovalMode::Operator => ExecutionAuthorization::operator_approved(&plan),
            ApprovalMode::Automatic | ApprovalMode::Pending => {
                ExecutionAuthorization::automatic(&plan).map_err(|error| {
                    let _ = self.audit(
                        "authorization_rejected",
                        &request,
                        json!({"code": error.code, "message": error.message}),
                    );
                    RunnerError::Sdr(error)
                })?
            }
        };
        self.audit("authorized", &request, json!({"mode": approval.as_str()}))?;

        match &plan.action {
            ProposedAction::CaptureBoundedIq { .. } => {
                let execution = match self.executor.execute(&plan, &authorization) {
                    Ok(observation) => observation,
                    Err(error) => {
                        self.audit_sdr_failure(&request, &error)?;
                        return Err(RunnerError::Sdr(error));
                    }
                };
                let mut next_observation = request.observation.clone();
                next_observation.age_ms = 0;
                next_observation.health = execution.post_execution_sdr.planner_health(
                    next_observation.health.recognizer_available,
                    next_observation.health.dropped_observations,
                );
                self.audit("execution_observation", &request, json!(&execution))?;
                Ok(RunReport {
                    status: RunStatus::Executed,
                    plan,
                    execution: Some(execution),
                    sweep: None,
                    next_observation,
                })
            }
            ProposedAction::SurveyBand {
                start_hz,
                stop_hz,
                step_hz,
                sample_rate_hz,
                rf_bandwidth_hz,
                dwell_ms,
            } => {
                let sweep = SweepPlan {
                    sweep_id: format!("request-{}", plan.request_id),
                    session_generation: plan.session_generation,
                    frequencies: SweepFrequencies::Range {
                        start_hz: *start_hz,
                        stop_hz: *stop_hz,
                        step_hz: *step_hz,
                    },
                    sample_rate_hz: *sample_rate_hz,
                    rf_bandwidth_hz: *rf_bandwidth_hz,
                    settle_ms: *dwell_ms,
                    frame_samples: 4_096,
                    aggregate_frames: 1,
                    point_timeout_ms: self.sweep_point_timeout_ms,
                    detection_threshold_db: 12.0,
                    gain_db: Some(self.survey_gain_db),
                };
                self.execute_sweep(&request, plan, sweep, None)
            }
            ProposedAction::InspectCandidate {
                candidate_id,
                center_hz,
                sample_rate_hz,
                rf_bandwidth_hz,
                dwell_ms,
            } => {
                let candidate_id = candidate_id.clone();
                let sweep = SweepPlan {
                    sweep_id: format!("inspect-{}", plan.request_id),
                    session_generation: plan.session_generation,
                    frequencies: SweepFrequencies::Centers {
                        centers_hz: vec![*center_hz],
                    },
                    sample_rate_hz: *sample_rate_hz,
                    rf_bandwidth_hz: *rf_bandwidth_hz,
                    settle_ms: *dwell_ms,
                    frame_samples: 4_096,
                    aggregate_frames: 1,
                    point_timeout_ms: self.sweep_point_timeout_ms,
                    detection_threshold_db: 12.0,
                    gain_db: Some(self.survey_gain_db),
                };
                self.execute_sweep(&request, plan, sweep, Some(candidate_id))
            }
            _ => unreachable!("non-executable action returned before authorization"),
        }
    }

    pub fn into_parts(self) -> (O, E, A) {
        (self.observer, self.executor, self.audit)
    }

    fn audit(
        &mut self,
        phase: &'static str,
        request: &PlanRequest,
        payload: Value,
    ) -> Result<(), RunnerError> {
        let timestamp_unix_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| RunnerError::Audit(io::Error::other(error)))?
            .as_millis();
        self.audit.append(&AuditEvent {
            schema_version: AUDIT_SCHEMA_VERSION,
            timestamp_unix_ms,
            phase,
            request_id: request.request_id,
            session_generation: request.session_generation,
            payload,
        })?;
        Ok(())
    }

    fn execute_sweep(
        &mut self,
        request: &PlanRequest,
        plan: ValidatedPlan,
        sweep_plan: SweepPlan,
        candidate_id: Option<String>,
    ) -> Result<RunReport, RunnerError> {
        let report = match self.sweep.run(&sweep_plan) {
            Ok(report) => report,
            Err(error) => {
                self.audit_sweep_failure(request, &error)?;
                return Err(RunnerError::Sweep(error));
            }
        };
        let post_execution_sdr = match self.observer.observe() {
            Ok(observation) => observation,
            Err(error) => {
                self.audit_sdr_failure(request, &error)?;
                return Err(RunnerError::Sdr(error));
            }
        };
        if !post_execution_sdr.online || !post_execution_sdr.healthy {
            let error = SdrError::new(
                "post_execution_health",
                "SDR is not healthy after sweep execution and restoration",
            );
            self.audit_sdr_failure(request, &error)?;
            return Err(RunnerError::Sdr(error));
        }
        let health = post_execution_sdr.planner_health(
            request.observation.health.recognizer_available,
            request.observation.health.dropped_observations,
        );
        let next_observation = match candidate_id.as_deref() {
            Some(candidate_id) => match report.planner_inspection_observation(
                &request.observation,
                candidate_id,
                health,
            ) {
                Ok(observation) => observation,
                Err(error) => {
                    self.audit_sweep_failure(request, &error)?;
                    return Err(RunnerError::Sweep(error));
                }
            },
            None => report.planner_observation(0, health, self.survey_gain_db),
        };
        self.audit(
            "execution_observation",
            request,
            json!({
                "sweep_id": &report.sweep_id,
                "backend": &report.backend,
                "backend_version": report.backend_version,
                "elapsed_ms": report.elapsed_ms,
                "point_count": report.points.len(),
                "candidate_count": report.candidates.len(),
                "post_execution_sdr": &post_execution_sdr,
                "next_observation": &next_observation,
            }),
        )?;
        Ok(RunReport {
            status: RunStatus::Executed,
            plan,
            execution: None,
            sweep: Some(report),
            next_observation,
        })
    }

    fn audit_sdr_failure(
        &mut self,
        request: &PlanRequest,
        error: &SdrError,
    ) -> Result<(), RunnerError> {
        self.audit(
            "execution_failed",
            request,
            json!({
                "code": error.code,
                "message": &error.message,
                "metadata": &error.details,
            }),
        )
    }

    fn audit_sweep_failure(
        &mut self,
        request: &PlanRequest,
        error: &SweepError,
    ) -> Result<(), RunnerError> {
        self.audit(
            "execution_failed",
            request,
            json!({
                "code": error.code,
                "message": &error.message,
                "metadata": &error.details,
            }),
        )
    }
}

impl ApprovalMode {
    fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Automatic => "automatic",
            Self::Operator => "operator",
        }
    }
}

#[derive(Debug)]
pub enum RunnerError {
    Controller(ControllerError),
    Sdr(SdrError),
    Sweep(SweepError),
    Audit(io::Error),
}

impl fmt::Display for RunnerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Controller(error) => write!(formatter, "controller: {error}"),
            Self::Sdr(error) => write!(formatter, "sdr: {error}"),
            Self::Sweep(error) => write!(formatter, "sweep: {error}"),
            Self::Audit(error) => write!(formatter, "audit: {error}"),
        }
    }
}

impl Error for RunnerError {}

impl From<ControllerError> for RunnerError {
    fn from(error: ControllerError) -> Self {
        Self::Controller(error)
    }
}

impl From<SdrError> for RunnerError {
    fn from(error: SdrError) -> Self {
        Self::Sdr(error)
    }
}

impl From<SweepError> for RunnerError {
    fn from(error: SweepError) -> Self {
        Self::Sweep(error)
    }
}

impl From<io::Error> for RunnerError {
    fn from(error: io::Error) -> Self {
        Self::Audit(error)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::execution::{CaptureObservation, ReplayActionExecutor};
    use crate::planner::PlannerError;
    #[cfg(unix)]
    use crate::planner::UnixPlannerAdapter;
    use crate::protocol::{
        ControllerState, HealthSummary, PlanResponse, PlanStatus, PlannerMeta, SafetyLimits,
        PROTOCOL_VERSION,
    };
    use crate::sdr::{ReplaySdrAdapter, RxInputIdentity, SdrSnapshot};
    use crate::sweep::{
        BackendSweep, ReplaySweepAdapter, SpectralSummary, SweepPoint,
        SPECTRAL_SUMMARY_ALGORITHM_ID, SPECTRAL_SUMMARY_SCHEMA_VERSION,
    };
    #[cfg(unix)]
    use std::io::Read;
    #[cfg(unix)]
    use std::os::unix::net::UnixListener;
    #[cfg(unix)]
    use std::thread;
    #[cfg(unix)]
    use std::time::Duration;

    struct ReplayPlanner {
        response: Option<PlanResponse>,
    }

    impl Planner for ReplayPlanner {
        fn plan(&mut self, _request: &PlanRequest) -> Result<PlanResponse, PlannerError> {
            Ok(self.response.take().expect("one replay response"))
        }
    }

    fn snapshot() -> SdrSnapshot {
        SdrSnapshot {
            online: true,
            healthy: true,
            health_flags: 0,
            iio_visible: true,
            can_retune: true,
            can_capture_iq: true,
            rx_input: Some(RxInputIdentity::fixed_p201_rx1_fixture()),
        }
    }

    fn request() -> PlanRequest {
        PlanRequest {
            protocol_version: PROTOCOL_VERSION,
            request_id: 7,
            session_generation: 3,
            instruction: "Capture the selected candidate".to_owned(),
            state: ControllerState::Idle,
            observation: ObservationSummary {
                age_ms: 100,
                health: HealthSummary {
                    sdr_online: false,
                    can_retune: false,
                    can_capture_iq: false,
                    recognizer_available: false,
                    dropped_observations: 0,
                },
                candidates: vec![crate::protocol::CandidateSummary {
                    id: "candidate-1".to_owned(),
                    center_hz: 433_920_000,
                    bandwidth_hz: 500_000,
                    peak_dbfs: -20.0,
                    snr_db: 10.0,
                    age_ms: 100,
                }],
                latest_sweep: None,
                recognition: None,
            },
            limits: SafetyLimits {
                min_freq_hz: 70_000_000,
                max_freq_hz: 6_000_000_000,
                max_span_hz: 20_000_000,
                max_bandwidth_hz: 10_000_000,
                max_dwell_ms: 5_000,
                max_iq_samples: 16_384,
                max_iq_bytes: 65_536,
                auto_approve_iq_bytes: 8_192,
                max_observation_age_ms: 2_000,
            },
        }
    }

    fn response(samples: u64) -> PlanResponse {
        PlanResponse {
            protocol_version: PROTOCOL_VERSION,
            request_id: 7,
            session_generation: 3,
            status: PlanStatus::Ok,
            action: Some(ProposedAction::CaptureBoundedIq {
                candidate_id: "candidate-1".to_owned(),
                center_hz: 433_920_000,
                sample_rate_hz: 2_100_000,
                rf_bandwidth_hz: 500_000,
                samples,
            }),
            error: None,
            planner: PlannerMeta {
                provider: "replay".to_owned(),
                model: "test".to_owned(),
            },
        }
    }

    fn execution() -> ExecutionObservation {
        ExecutionObservation {
            request_id: 7,
            session_generation: 3,
            capture: CaptureObservation {
                candidate_id: "candidate-1".to_owned(),
                feature_id: "agent-3-7".to_owned(),
                relative_path: "agent-3-7/capture-3-1.ci16".to_owned(),
                samples_captured: 4_096,
                bytes_written: 16_384,
                sequence: 1,
                dropped_samples: 0,
                overflow: false,
                timeout: crate::execution::ExecutionTimeoutMetadata {
                    limit_ms: 2_000,
                    elapsed_us: 1_000,
                    timed_out: false,
                },
                health: crate::execution::ExecutionHealthMetadata {
                    healthy: true,
                    flags: 0,
                    source: "replay".to_owned(),
                },
                rx_input: RxInputIdentity::fixed_p201_rx1_fixture(),
            },
            post_execution_sdr: snapshot(),
        }
    }

    fn sweep_point(
        index: usize,
        center_hz: u64,
        sample_rate_hz: u64,
        rf_bandwidth_hz: u64,
        power_dbfs: f32,
    ) -> SweepPoint {
        SweepPoint {
            point_index: index,
            request_id: index as u64 + 1,
            session_generation: 3,
            requested_center_hz: center_hz,
            actual_center_hz: center_hz,
            sample_rate_hz,
            rf_bandwidth_hz,
            sequence: index as u64 + 1,
            dropped_samples: 0,
            overflow: false,
            captured_samples: 4_096,
            band_power_dbfs: power_dbfs,
            spectral: SpectralSummary {
                schema_version: SPECTRAL_SUMMARY_SCHEMA_VERSION,
                algorithm_id: SPECTRAL_SUMMARY_ALGORITHM_ID.to_owned(),
                fft_size: 1_024,
                segment_count: 4,
                bin_width_hz: sample_rate_hz as f64 / 1_024.0,
                peak_frequency_hz: center_hz,
                peak_power_dbfs: power_dbfs,
                noise_floor_dbfs: power_dbfs - 10.0,
                measured_snr_db: 10.0,
                estimated_center_hz: center_hz,
                occupied_start_hz: center_hz.saturating_sub(rf_bandwidth_hz / 4),
                occupied_stop_hz: center_hz.saturating_add(rf_bandwidth_hz / 4),
                occupied_bandwidth_hz: rf_bandwidth_hz / 2,
            },
            clipped_samples: 0,
            status_flags: 0,
            elapsed_us: 1_000,
            timeout: crate::execution::ExecutionTimeoutMetadata {
                limit_ms: 250,
                elapsed_us: 1_000,
                timed_out: false,
            },
            health: crate::execution::ExecutionHealthMetadata {
                healthy: true,
                flags: 0,
                source: "replay".to_owned(),
            },
            rx_input: RxInputIdentity::fixed_p201_rx1_fixture(),
        }
    }

    fn sweep_response() -> PlanResponse {
        PlanResponse {
            protocol_version: PROTOCOL_VERSION,
            request_id: 7,
            session_generation: 3,
            status: PlanStatus::Ok,
            action: Some(ProposedAction::SurveyBand {
                start_hz: 433_000_000,
                stop_hz: 437_000_000,
                step_hz: 2_000_000,
                sample_rate_hz: 3_000_000,
                rf_bandwidth_hz: 2_500_000,
                dwell_ms: 5,
            }),
            error: None,
            planner: PlannerMeta {
                provider: "replay".to_owned(),
                model: "test".to_owned(),
            },
        }
    }

    fn inspection_response() -> PlanResponse {
        PlanResponse {
            protocol_version: PROTOCOL_VERSION,
            request_id: 7,
            session_generation: 3,
            status: PlanStatus::Ok,
            action: Some(ProposedAction::InspectCandidate {
                candidate_id: "candidate-1".to_owned(),
                center_hz: 433_920_000,
                sample_rate_hz: 2_100_000,
                rf_bandwidth_hz: 500_000,
                dwell_ms: 100,
            }),
            error: None,
            planner: PlannerMeta {
                provider: "replay".to_owned(),
                model: "test".to_owned(),
            },
        }
    }

    #[test]
    fn pending_operator_gate_stops_before_execution() {
        let mut runner = Runner::new(
            ReplaySdrAdapter::new([snapshot()]),
            ReplayPlanner {
                response: Some(response(4_096)),
            },
            ReplayActionExecutor::new([Ok(execution())]),
            ReplaySweepAdapter::new([]),
            20,
            250,
            MemoryAuditAdapter::default(),
        );
        let report = runner.run_once(request(), ApprovalMode::Pending).unwrap();
        assert_eq!(report.status, RunStatus::AwaitingApproval);
        assert!(report.execution.is_none());
        let (_, _, audit) = runner.into_parts();
        assert_eq!(audit.events().len(), 4);
        assert_eq!(audit.events()[3].phase, "awaiting_approval");
    }

    #[test]
    fn operator_approval_executes_and_returns_fresh_observation() {
        let mut runner = Runner::new(
            ReplaySdrAdapter::new([snapshot()]),
            ReplayPlanner {
                response: Some(response(4_096)),
            },
            ReplayActionExecutor::new([Ok(execution())]),
            ReplaySweepAdapter::new([]),
            20,
            250,
            MemoryAuditAdapter::default(),
        );
        let report = runner.run_once(request(), ApprovalMode::Operator).unwrap();
        assert_eq!(report.status, RunStatus::Executed);
        assert!(report.next_observation.health.can_capture_iq);
        assert_eq!(report.execution.unwrap().capture.bytes_written, 16_384);
        let (_, _, audit) = runner.into_parts();
        assert_eq!(audit.events().len(), 5);
        assert_eq!(audit.events()[4].phase, "execution_observation");
    }

    #[test]
    fn automatic_mode_rejects_a_plan_above_the_auto_capture_limit() {
        let mut runner = Runner::new(
            ReplaySdrAdapter::new([snapshot()]),
            ReplayPlanner {
                response: Some(response(4_096)),
            },
            ReplayActionExecutor::new([Ok(execution())]),
            ReplaySweepAdapter::new([]),
            20,
            250,
            MemoryAuditAdapter::default(),
        );
        let error = runner
            .run_once(request(), ApprovalMode::Automatic)
            .unwrap_err();
        assert!(matches!(error, RunnerError::Sdr(_)));
        let (_, _, audit) = runner.into_parts();
        assert_eq!(
            audit.events().last().unwrap().phase,
            "authorization_rejected"
        );
    }

    #[test]
    fn planner_failure_is_audited_before_returning() {
        let mut failed = response(4_096);
        failed.status = PlanStatus::Unavailable;
        failed.action = None;
        failed.error = Some("model did not submit exactly one plan".to_owned());
        let mut runner = Runner::new(
            ReplaySdrAdapter::new([snapshot()]),
            ReplayPlanner {
                response: Some(failed),
            },
            ReplayActionExecutor::new([Ok(execution())]),
            ReplaySweepAdapter::new([]),
            20,
            250,
            MemoryAuditAdapter::default(),
        );
        let error = runner
            .run_once(request(), ApprovalMode::Operator)
            .unwrap_err();
        assert!(matches!(error, RunnerError::Controller(_)));
        let (_, _, audit) = runner.into_parts();
        assert_eq!(audit.events().last().unwrap().phase, "validation_failed");
    }

    #[test]
    fn one_shot_survey_executes_and_returns_aggregate_observation() {
        let sweep = BackendSweep {
            backend: "replay".to_owned(),
            backend_version: 1,
            points: vec![
                sweep_point(0, 433_000_000, 3_000_000, 2_500_000, -70.0),
                sweep_point(1, 435_000_000, 3_000_000, 2_500_000, -40.0),
                sweep_point(2, 437_000_000, 3_000_000, 2_500_000, -69.0),
            ],
            dataset: None,
        };
        let mut runner = Runner::new(
            ReplaySdrAdapter::new([snapshot(), snapshot()]),
            ReplayPlanner {
                response: Some(sweep_response()),
            },
            ReplayActionExecutor::new([]),
            ReplaySweepAdapter::new([Ok(sweep)]),
            20,
            250,
            MemoryAuditAdapter::default(),
        );
        let report = runner.run_once(request(), ApprovalMode::Automatic).unwrap();
        assert_eq!(report.status, RunStatus::Executed);
        assert!(report.execution.is_none());
        assert_eq!(report.sweep.as_ref().unwrap().points.len(), 3);
        assert_eq!(report.next_observation.candidates[0].id, "request-7-1");
        assert_eq!(
            report
                .next_observation
                .latest_sweep
                .as_ref()
                .unwrap()
                .fixed_gain_db,
            20
        );
        let (_, _, audit) = runner.into_parts();
        assert_eq!(
            audit.events().last().unwrap().phase,
            "execution_observation"
        );
        assert!(!audit
            .events()
            .iter()
            .any(|event| event.phase == "planned_only"));
    }

    #[test]
    fn one_shot_inspection_executes_and_refreshes_selected_candidate() {
        let sweep = BackendSweep {
            backend: "replay".to_owned(),
            backend_version: 1,
            points: vec![sweep_point(0, 433_920_000, 2_100_000, 500_000, -25.0)],
            dataset: None,
        };
        let mut runner = Runner::new(
            ReplaySdrAdapter::new([snapshot(), snapshot()]),
            ReplayPlanner {
                response: Some(inspection_response()),
            },
            ReplayActionExecutor::new([]),
            ReplaySweepAdapter::new([Ok(sweep)]),
            20,
            250,
            MemoryAuditAdapter::default(),
        );
        let report = runner.run_once(request(), ApprovalMode::Automatic).unwrap();
        assert_eq!(report.status, RunStatus::Executed);
        assert_eq!(report.sweep.as_ref().unwrap().points.len(), 1);
        let candidate = report
            .next_observation
            .candidates
            .iter()
            .find(|candidate| candidate.id == "candidate-1")
            .unwrap();
        assert_eq!(candidate.peak_dbfs, -25.0);
        assert_eq!(candidate.snr_db, 10.0);
        assert_eq!(candidate.age_ms, 0);
        let (_, _, audit) = runner.into_parts();
        assert_eq!(
            audit.events().last().unwrap().phase,
            "execution_observation"
        );
        assert!(!audit
            .events()
            .iter()
            .any(|event| event.phase == "planned_only"));
    }

    #[cfg(unix)]
    #[test]
    fn complete_runner_audits_planner_socket_timeout_before_execution() {
        let socket_path = std::env::temp_dir().join(format!(
            "sdrharness-runner-timeout-{}-{}.sock",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let listener = UnixListener::bind(&socket_path).unwrap();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0_u8; 4_096];
            let _ = stream.read(&mut request);
            thread::sleep(Duration::from_millis(100));
        });
        let mut runner = Runner::new(
            ReplaySdrAdapter::new([snapshot()]),
            UnixPlannerAdapter::new(&socket_path, Duration::from_millis(10)),
            ReplayActionExecutor::new([]),
            ReplaySweepAdapter::new([]),
            20,
            250,
            MemoryAuditAdapter::default(),
        );
        let error = runner
            .run_once(request(), ApprovalMode::Automatic)
            .unwrap_err();
        assert!(matches!(error, RunnerError::Controller(_)));
        let (_, _, audit) = runner.into_parts();
        assert_eq!(audit.events().last().unwrap().phase, "planning_failed");
        assert!(audit.events().last().unwrap().payload["message"]
            .as_str()
            .unwrap()
            .contains("read planner response"));
        server.join().unwrap();
        std::fs::remove_file(socket_path).unwrap();
    }

    #[test]
    fn complete_runner_rejects_and_audits_stale_planner_result() {
        let mut stale = sweep_response();
        stale.session_generation -= 1;
        let mut runner = Runner::new(
            ReplaySdrAdapter::new([snapshot()]),
            ReplayPlanner {
                response: Some(stale),
            },
            ReplayActionExecutor::new([]),
            ReplaySweepAdapter::new([]),
            20,
            250,
            MemoryAuditAdapter::default(),
        );
        let error = runner
            .run_once(request(), ApprovalMode::Automatic)
            .unwrap_err();
        assert!(matches!(error, RunnerError::Controller(_)));
        let (_, _, audit) = runner.into_parts();
        assert_eq!(audit.events().last().unwrap().phase, "validation_failed");
        assert_eq!(
            audit.events().last().unwrap().payload["code"],
            "stale_session_generation"
        );
    }

    #[test]
    fn complete_runner_preserves_timeout_metadata_from_partial_sweep_failure() {
        let mut timeout = SweepError::new("remote_error", "capture_timeout_restored");
        timeout.details = Some(json!({
            "request_id": 9,
            "session_generation": 3,
            "sequence": 2,
            "dropped_samples": 0,
            "overflow": false,
            "timeout": {"limit_ms": 1, "elapsed_us": 3_100, "timed_out": true},
            "health": {"healthy": false, "flags": 4, "source": "iio_adapter"}
        }));
        let mut runner = Runner::new(
            ReplaySdrAdapter::new([snapshot()]),
            ReplayPlanner {
                response: Some(sweep_response()),
            },
            ReplayActionExecutor::new([]),
            ReplaySweepAdapter::new([Err(timeout)]),
            20,
            1,
            MemoryAuditAdapter::default(),
        );
        let error = runner
            .run_once(request(), ApprovalMode::Automatic)
            .unwrap_err();
        assert!(matches!(error, RunnerError::Sweep(_)));
        let (_, _, audit) = runner.into_parts();
        let failure = audit.events().last().unwrap();
        assert_eq!(failure.phase, "execution_failed");
        assert_eq!(failure.payload["metadata"]["session_generation"], 3);
        assert_eq!(failure.payload["metadata"]["sequence"], 2);
        assert_eq!(failure.payload["metadata"]["timeout"]["timed_out"], true);
        assert_eq!(failure.payload["metadata"]["health"]["flags"], 4);
    }

    #[test]
    fn complete_runner_audits_initial_sdr_disconnect_before_planning() {
        let mut runner = Runner::new(
            ReplaySdrAdapter::new([]),
            ReplayPlanner {
                response: Some(sweep_response()),
            },
            ReplayActionExecutor::new([]),
            ReplaySweepAdapter::new([]),
            20,
            250,
            MemoryAuditAdapter::default(),
        );
        let error = runner
            .run_once(request(), ApprovalMode::Automatic)
            .unwrap_err();
        assert!(matches!(error, RunnerError::Sdr(_)));
        let (_, _, audit) = runner.into_parts();
        assert_eq!(audit.events().len(), 1);
        assert_eq!(audit.events()[0].phase, "observation_failed");
        assert_eq!(audit.events()[0].payload["code"], "replay_exhausted");
    }

    #[test]
    fn complete_runner_rejects_stale_sdr_result_before_new_observation() {
        let mut stale_point = sweep_point(0, 433_000_000, 3_000_000, 2_500_000, -70.0);
        stale_point.session_generation = 2;
        let stale_sweep = BackendSweep {
            backend: "replay".to_owned(),
            backend_version: 1,
            points: vec![
                stale_point,
                sweep_point(1, 435_000_000, 3_000_000, 2_500_000, -40.0),
                sweep_point(2, 437_000_000, 3_000_000, 2_500_000, -69.0),
            ],
            dataset: None,
        };
        let mut runner = Runner::new(
            ReplaySdrAdapter::new([snapshot()]),
            ReplayPlanner {
                response: Some(sweep_response()),
            },
            ReplayActionExecutor::new([]),
            ReplaySweepAdapter::new([Ok(stale_sweep)]),
            20,
            250,
            MemoryAuditAdapter::default(),
        );
        let error = runner
            .run_once(request(), ApprovalMode::Automatic)
            .unwrap_err();
        assert!(matches!(error, RunnerError::Sweep(_)));
        let (_, _, audit) = runner.into_parts();
        let failure = audit.events().last().unwrap();
        assert_eq!(failure.phase, "execution_failed");
        assert_eq!(failure.payload["code"], "point_contract");
        assert!(!audit
            .events()
            .iter()
            .any(|event| event.phase == "execution_observation"));
    }
}
