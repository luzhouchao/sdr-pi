use crate::execution::{ExecutionAuthorization, ExecutionObservation, SdrActionExecutor};
use crate::planner::Planner;
use crate::policy::ControllerPolicy;
use crate::protocol::{ObservationSummary, PlanRequest, ProposedAction, ValidatedPlan};
use crate::sdr::{SdrEngine, SdrError};
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

pub struct Runner<O, P, E, A> {
    observer: O,
    planner: P,
    policy: ControllerPolicy,
    executor: E,
    audit: A,
}

impl<O, P, E, A> Runner<O, P, E, A>
where
    O: SdrEngine,
    P: Planner,
    E: SdrActionExecutor,
    A: AuditSink,
{
    pub fn new(observer: O, planner: P, executor: E, audit: A) -> Self {
        Self {
            observer,
            planner,
            policy: ControllerPolicy,
            executor,
            audit,
        }
    }

    pub fn run_once(
        &mut self,
        mut request: PlanRequest,
        approval: ApprovalMode,
    ) -> Result<RunReport, RunnerError> {
        let live = self.observer.observe()?;
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
                next_observation: request.observation,
            });
        }

        if !matches!(plan.action, ProposedAction::CaptureBoundedIq { .. }) {
            self.audit(
                "planned_only",
                &request,
                json!({"reason": "no production executor for this action"}),
            )?;
            return Ok(RunReport {
                status: RunStatus::PlannedOnly,
                plan,
                execution: None,
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

        let execution = match self.executor.execute(&plan, &authorization) {
            Ok(observation) => observation,
            Err(error) => {
                self.audit(
                    "execution_failed",
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
            next_observation,
        })
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
    Audit(io::Error),
}

impl fmt::Display for RunnerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Controller(error) => write!(formatter, "controller: {error}"),
            Self::Sdr(error) => write!(formatter, "sdr: {error}"),
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
    use crate::protocol::{
        ControllerState, HealthSummary, PlanResponse, PlanStatus, PlannerMeta, SafetyLimits,
        PROTOCOL_VERSION,
    };
    use crate::sdr::{ReplaySdrAdapter, SdrSnapshot};

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
            },
            post_execution_sdr: snapshot(),
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
            MemoryAuditAdapter::default(),
        );
        let error = runner
            .run_once(request(), ApprovalMode::Operator)
            .unwrap_err();
        assert!(matches!(error, RunnerError::Controller(_)));
        let (_, _, audit) = runner.into_parts();
        assert_eq!(audit.events().last().unwrap().phase, "validation_failed");
    }
}
