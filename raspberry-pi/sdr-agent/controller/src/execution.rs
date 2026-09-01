use crate::protocol::{ProposedAction, ValidatedPlan};
use crate::sdr::{SdrEngine, SdrError, SdrSnapshot, SdrdAdapter, SdrdWire};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::net::SocketAddr;
use std::thread;
use std::time::Duration;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionAuthorization {
    request_id: u64,
    session_generation: u64,
    operator_approved: bool,
}

impl ExecutionAuthorization {
    pub fn automatic(plan: &ValidatedPlan) -> Result<Self, SdrError> {
        if plan.approval_required {
            return Err(SdrError::new(
                "approval_required",
                "the validated plan requires explicit operator approval",
            ));
        }
        Ok(Self {
            request_id: plan.request_id,
            session_generation: plan.session_generation,
            operator_approved: false,
        })
    }

    pub fn operator_approved(plan: &ValidatedPlan) -> Self {
        Self {
            request_id: plan.request_id,
            session_generation: plan.session_generation,
            operator_approved: true,
        }
    }
}

pub trait SdrActionExecutor {
    fn execute(
        &mut self,
        plan: &ValidatedPlan,
        authorization: &ExecutionAuthorization,
    ) -> Result<ExecutionObservation, SdrError>;

    fn cancel(&mut self, session_generation: u64) -> Result<CancelObservation, SdrError>;
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CaptureObservation {
    pub candidate_id: String,
    pub feature_id: String,
    pub relative_path: String,
    pub samples_captured: u64,
    pub bytes_written: u64,
    pub sequence: u64,
    pub dropped_samples: u64,
    pub overflow: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionObservation {
    pub request_id: u64,
    pub session_generation: u64,
    pub capture: CaptureObservation,
    pub post_execution_sdr: SdrSnapshot,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CancelObservation {
    pub session_generation: u64,
    pub cancel_requested: bool,
}

pub struct ReplayActionExecutor {
    observations: VecDeque<Result<ExecutionObservation, SdrError>>,
}

impl ReplayActionExecutor {
    pub fn new(
        observations: impl IntoIterator<Item = Result<ExecutionObservation, SdrError>>,
    ) -> Self {
        Self {
            observations: observations.into_iter().collect(),
        }
    }
}

impl SdrActionExecutor for ReplayActionExecutor {
    fn execute(
        &mut self,
        plan: &ValidatedPlan,
        authorization: &ExecutionAuthorization,
    ) -> Result<ExecutionObservation, SdrError> {
        validate_authorization(plan, authorization)?;
        let observation = self
            .observations
            .pop_front()
            .ok_or_else(|| SdrError::new("replay_exhausted", "no replay executions remain"))??;
        if observation.request_id != plan.request_id
            || observation.session_generation != plan.session_generation
        {
            return Err(SdrError::new(
                "replay_correlation",
                "replay observation does not match the validated plan",
            ));
        }
        Ok(observation)
    }

    fn cancel(&mut self, session_generation: u64) -> Result<CancelObservation, SdrError> {
        if session_generation == 0 {
            return Err(SdrError::new(
                "cancel_generation",
                "cancel generation must be non-zero",
            ));
        }
        Ok(CancelObservation {
            session_generation,
            cancel_requested: true,
        })
    }
}

#[derive(Clone)]
pub struct SdrdActionAdapter {
    address: SocketAddr,
    timeout: Duration,
}

impl SdrdActionAdapter {
    pub fn new(address: SocketAddr, timeout: Duration) -> Self {
        Self { address, timeout }
    }

    fn execute_capture(
        &mut self,
        plan: &ValidatedPlan,
        candidate_id: &str,
        center_hz: u64,
        sample_rate_hz: u64,
        rf_bandwidth_hz: u64,
        samples: u64,
    ) -> Result<ExecutionObservation, SdrError> {
        let max_bytes = samples
            .checked_mul(4)
            .ok_or_else(|| SdrError::new("capture_bytes", "IQ byte count overflow"))?;
        let feature_id = format!("agent-{}-{}", plan.session_generation, plan.request_id);
        if feature_id.len() >= 64 {
            return Err(SdrError::new(
                "feature_id",
                "derived execution feature id exceeds the SDRD limit",
            ));
        }

        let mut wire = SdrdWire::connect(self.address, self.timeout)?;
        let hello: HelloResponse = wire.request("HELLO", "")?;
        if hello.server != "p201-sdrd"
            || hello.protocol != "SDRD/1"
            || hello.mode != "controlled"
            || !hello.mutating_commands
        {
            return Err(SdrError::new(
                "controlled_mode_unavailable",
                "SDRD is not the expected controlled endpoint",
            ));
        }
        let capabilities: CapabilitiesResponse = wire.request("CAPABILITIES", "")?;
        if capabilities.mode != "controlled"
            || !capabilities.iio_visible
            || !capabilities.radio_control
            || !capabilities.raw_iq_capture
            || capabilities.max_capture_bytes < max_bytes
        {
            return Err(SdrError::new(
                "execution_capability",
                "SDRD cannot execute the bounded IQ request",
            ));
        }

        let generation = plan.session_generation;
        let mut session_started = false;
        let execution = (|| {
            let start: StartResponse = wire.request("START_SESSION", &generation.to_string())?;
            if start.generation != generation
                || start.session_state != "owned"
                || !start.restore_armed
            {
                return Err(SdrError::new(
                    "session_start",
                    "SDRD did not arm state restoration",
                ));
            }
            session_started = true;

            let profile_arguments = format!(
                "{generation} {center_hz} {sample_rate_hz} {rf_bandwidth_hz} slow_attack 1"
            );
            let profile: ProfileResponse = wire.request("APPLY_PROFILE", &profile_arguments)?;
            if profile.generation != generation
                || profile.center_hz != center_hz
                || profile.sample_rate_hz != sample_rate_hz
                || profile.rf_bandwidth_hz != rf_bandwidth_hz
                || profile.gain_mode != "slow_attack"
                || profile.enabled_channels != 1
            {
                return Err(SdrError::new(
                    "profile_response",
                    "SDRD profile response does not match the request",
                ));
            }

            let capture_arguments = format!("{generation} {samples} {max_bytes} {feature_id}");
            let capture: CaptureResponse = wire.request("CAPTURE_IQ", &capture_arguments)?;
            validate_capture_response(&capture, generation, samples, max_bytes, &feature_id)?;

            let status: StatusResponse =
                wire.request("EXECUTION_STATUS", &generation.to_string())?;
            if status.generation != generation
                || !status.active
                || !status.profile_applied
                || !status.restore_armed
                || status.faulted
            {
                return Err(SdrError::new(
                    "execution_status",
                    "SDRD execution status is inconsistent",
                ));
            }

            let stop: StopResponse = wire.request("STOP_SESSION", &generation.to_string())?;
            if stop.generation != generation || !stop.stopped || !stop.restored {
                return Err(SdrError::new(
                    "restore_response",
                    "SDRD did not confirm stop and restoration",
                ));
            }
            session_started = false;
            let quit: QuitResponse = wire.request("QUIT", "")?;
            if !quit.closing {
                return Err(SdrError::new(
                    "quit_rejected",
                    "SDRD did not close the session",
                ));
            }

            Ok(CaptureObservation {
                candidate_id: candidate_id.to_owned(),
                feature_id,
                relative_path: capture.relative_path,
                samples_captured: capture.samples_captured,
                bytes_written: capture.bytes_written,
                sequence: capture.sequence,
                dropped_samples: capture.dropped_samples,
                overflow: capture.overflow,
            })
        })();

        let capture = match execution {
            Ok(capture) => capture,
            Err(error) => {
                if session_started {
                    let _: Result<StopResponse, _> =
                        wire.request("STOP_SESSION", &generation.to_string());
                }
                let _: Result<QuitResponse, _> = wire.request("QUIT", "");
                return Err(error);
            }
        };

        let post_execution_sdr = observe_after_worker_release(self.address, self.timeout)?;
        if !post_execution_sdr.online || !post_execution_sdr.healthy {
            return Err(SdrError::new(
                "post_execution_health",
                "SDR is not healthy after execution and restoration",
            ));
        }
        Ok(ExecutionObservation {
            request_id: plan.request_id,
            session_generation: plan.session_generation,
            capture,
            post_execution_sdr,
        })
    }
}

fn observe_after_worker_release(
    address: SocketAddr,
    timeout: Duration,
) -> Result<SdrSnapshot, SdrError> {
    const MAX_BUSY_RETRIES: usize = 20;
    for attempt in 0..=MAX_BUSY_RETRIES {
        let mut observer = SdrdAdapter::new(address, timeout);
        match observer.observe() {
            Ok(snapshot) => return Ok(snapshot),
            Err(error)
                if error.code == "remote_error"
                    && error.message == "server_busy"
                    && attempt < MAX_BUSY_RETRIES =>
            {
                thread::sleep(Duration::from_millis(10));
            }
            Err(error) => return Err(error),
        }
    }
    unreachable!("bounded observe retry loop always returns")
}

impl SdrActionExecutor for SdrdActionAdapter {
    fn execute(
        &mut self,
        plan: &ValidatedPlan,
        authorization: &ExecutionAuthorization,
    ) -> Result<ExecutionObservation, SdrError> {
        validate_authorization(plan, authorization)?;
        match &plan.action {
            ProposedAction::CaptureBoundedIq {
                candidate_id,
                center_hz,
                sample_rate_hz,
                rf_bandwidth_hz,
                samples,
            } => self.execute_capture(
                plan,
                candidate_id,
                *center_hz,
                *sample_rate_hz,
                *rf_bandwidth_hz,
                *samples,
            ),
            _ => Err(SdrError::new(
                "unsupported_action",
                "this executor slice supports only capture_bounded_iq",
            )),
        }
    }

    fn cancel(&mut self, session_generation: u64) -> Result<CancelObservation, SdrError> {
        if session_generation == 0 {
            return Err(SdrError::new(
                "cancel_generation",
                "cancel generation must be non-zero",
            ));
        }
        let mut wire = SdrdWire::connect(self.address, self.timeout)?;
        let response: CancelResponse =
            wire.request("CANCEL_SESSION", &session_generation.to_string())?;
        if response.generation != session_generation || !response.cancel_requested {
            return Err(SdrError::new(
                "cancel_response",
                "SDRD did not acknowledge the requested generation cancellation",
            ));
        }
        Ok(CancelObservation {
            session_generation,
            cancel_requested: true,
        })
    }
}

fn validate_authorization(
    plan: &ValidatedPlan,
    authorization: &ExecutionAuthorization,
) -> Result<(), SdrError> {
    if authorization.request_id != plan.request_id
        || authorization.session_generation != plan.session_generation
    {
        return Err(SdrError::new(
            "stale_authorization",
            "execution authorization does not match the validated plan",
        ));
    }
    if plan.approval_required && !authorization.operator_approved {
        return Err(SdrError::new(
            "approval_required",
            "operator approval is required for this plan",
        ));
    }
    Ok(())
}

fn validate_capture_response(
    response: &CaptureResponse,
    generation: u64,
    samples: u64,
    max_bytes: u64,
    feature_id: &str,
) -> Result<(), SdrError> {
    let expected_prefix = format!("{feature_id}/");
    let shaped_bytes = response
        .samples_captured
        .checked_mul(4)
        .ok_or_else(|| SdrError::new("capture_response", "capture byte count overflow"))?;
    if response.generation != generation
        || response.feature_id != feature_id
        || response.samples_captured > samples
        || response.bytes_written > max_bytes
        || response.bytes_written != shaped_bytes
        || response.relative_path.contains("..")
        || !response.relative_path.starts_with(&expected_prefix)
    {
        return Err(SdrError::new(
            "capture_response",
            "SDRD capture response violates the execution contract",
        ));
    }
    Ok(())
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HelloResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    server: String,
    protocol: String,
    mode: String,
    mutating_commands: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CapabilitiesResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    mode: String,
    iio_visible: bool,
    radio_control: bool,
    raw_iq_capture: bool,
    #[serde(rename = "software_summary")]
    _software_summary: bool,
    max_capture_bytes: u64,
    #[serde(rename = "fpga_backend")]
    _fpga_backend: String,
    #[serde(rename = "fpga_identity_valid")]
    _fpga_identity_valid: bool,
    #[serde(rename = "fpga_summary_version")]
    _fpga_summary_version: u32,
    #[serde(rename = "fpga_abi_version")]
    _fpga_abi_version: u32,
    #[serde(rename = "fpga_capability")]
    _fpga_capability: u32,
    #[serde(rename = "fpga_aggregate")]
    _fpga_aggregate: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StartResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    generation: u64,
    session_state: String,
    restore_armed: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProfileResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    generation: u64,
    center_hz: u64,
    sample_rate_hz: u64,
    rf_bandwidth_hz: u64,
    gain_mode: String,
    enabled_channels: u32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CaptureResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    generation: u64,
    feature_id: String,
    samples_captured: u64,
    bytes_written: u64,
    sequence: u64,
    dropped_samples: u64,
    overflow: bool,
    relative_path: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StatusResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    generation: u64,
    active: bool,
    profile_applied: bool,
    restore_armed: bool,
    faulted: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StopResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    generation: u64,
    stopped: bool,
    restored: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct QuitResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    closing: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CancelResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    generation: u64,
    cancel_requested: bool,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::{PlannerMeta, ProposedAction};
    use std::io::{BufRead, BufReader, Write};
    use std::net::TcpListener;
    use std::thread;

    fn plan(approval_required: bool) -> ValidatedPlan {
        ValidatedPlan {
            request_id: 7,
            session_generation: 3,
            approval_required,
            action: ProposedAction::CaptureBoundedIq {
                candidate_id: "candidate-1".to_owned(),
                center_hz: 433_920_000,
                sample_rate_hz: 2_100_000,
                rf_bandwidth_hz: 500_000,
                samples: 4096,
            },
            planner: PlannerMeta {
                provider: "test".to_owned(),
                model: "replay".to_owned(),
            },
        }
    }

    fn observation() -> ExecutionObservation {
        ExecutionObservation {
            request_id: 7,
            session_generation: 3,
            capture: CaptureObservation {
                candidate_id: "candidate-1".to_owned(),
                feature_id: "agent-3-7".to_owned(),
                relative_path: "agent-3-7/capture-3-1.ci16".to_owned(),
                samples_captured: 4096,
                bytes_written: 16_384,
                sequence: 1,
                dropped_samples: 0,
                overflow: false,
            },
            post_execution_sdr: SdrSnapshot {
                online: true,
                healthy: true,
                health_flags: 0,
                iio_visible: true,
                can_retune: true,
                can_capture_iq: true,
                fpga_available: false,
                fpga_backend: "disabled".to_owned(),
                fpga_summary_version: 0,
                fpga_abi_version: 0,
                fpga_capability: 0,
            },
        }
    }

    fn controlled_mock_server() -> (SocketAddr, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let handle = thread::spawn(move || {
            let response_groups = vec![
                vec![
                    "{\"schema_version\":1,\"request_id\":1,\"status\":\"ok\",\"server\":\"p201-sdrd\",\"protocol\":\"SDRD/1\",\"mode\":\"controlled\",\"mutating_commands\":true}\n",
                    "{\"schema_version\":1,\"request_id\":2,\"status\":\"ok\",\"mode\":\"controlled\",\"iio_visible\":true,\"radio_control\":true,\"raw_iq_capture\":true,\"software_summary\":true,\"max_capture_bytes\":67108864,\"fpga_backend\":\"disabled\",\"fpga_identity_valid\":false,\"fpga_summary_version\":0,\"fpga_abi_version\":0,\"fpga_capability\":0,\"fpga_aggregate\":false}\n",
                    "{\"schema_version\":1,\"request_id\":3,\"status\":\"ok\",\"generation\":3,\"session_state\":\"owned\",\"restore_armed\":true}\n",
                    "{\"schema_version\":1,\"request_id\":4,\"status\":\"ok\",\"generation\":3,\"center_hz\":433920000,\"sample_rate_hz\":2100000,\"rf_bandwidth_hz\":500000,\"gain_mode\":\"slow_attack\",\"enabled_channels\":1}\n",
                    "{\"schema_version\":1,\"request_id\":5,\"status\":\"ok\",\"generation\":3,\"feature_id\":\"agent-3-7\",\"samples_captured\":4096,\"bytes_written\":16384,\"sequence\":1,\"dropped_samples\":0,\"overflow\":false,\"relative_path\":\"agent-3-7/capture-3-1.ci16\"}\n",
                    "{\"schema_version\":1,\"request_id\":6,\"status\":\"ok\",\"generation\":3,\"active\":true,\"profile_applied\":true,\"restore_armed\":true,\"faulted\":false}\n",
                    "{\"schema_version\":1,\"request_id\":7,\"status\":\"ok\",\"generation\":3,\"stopped\":true,\"restored\":true}\n",
                    "{\"schema_version\":1,\"request_id\":8,\"status\":\"ok\",\"closing\":true}\n",
                ],
                vec![
                    "{\"schema_version\":1,\"request_id\":1,\"status\":\"ok\",\"server\":\"p201-sdrd\",\"protocol\":\"SDRD/1\",\"mode\":\"controlled\",\"mutating_commands\":true}\n",
                    "{\"schema_version\":1,\"request_id\":2,\"status\":\"ok\",\"mode\":\"controlled\",\"iio_visible\":true,\"radio_control\":true,\"raw_iq_capture\":true,\"software_summary\":true,\"max_capture_bytes\":67108864,\"fpga_backend\":\"disabled\",\"fpga_identity_valid\":false,\"fpga_summary_version\":0,\"fpga_abi_version\":0,\"fpga_capability\":0,\"fpga_aggregate\":false}\n",
                    "{\"schema_version\":1,\"request_id\":3,\"status\":\"ok\",\"healthy\":true,\"health_flags\":0,\"iio_phy_visible\":true,\"iio_rx_visible\":true,\"fpga_configured\":false,\"fpga_mapped\":false,\"fpga_identity_valid\":false,\"session_faulted\":false}\n",
                    "{\"schema_version\":1,\"request_id\":4,\"status\":\"ok\",\"closing\":true}\n",
                ],
            ];
            for responses in response_groups {
                let (mut stream, _) = listener.accept().unwrap();
                let mut reader = BufReader::new(stream.try_clone().unwrap());
                for response in responses {
                    let mut request = String::new();
                    reader.read_line(&mut request).unwrap();
                    assert!(request.starts_with("SDRD/1 "));
                    stream.write_all(response.as_bytes()).unwrap();
                    stream.flush().unwrap();
                }
            }
        });
        (address, handle)
    }

    #[test]
    fn replay_is_a_second_executor_adapter() {
        let plan = plan(true);
        let expected = observation();
        let mut executor = ReplayActionExecutor::new([Ok(expected.clone())]);
        let authorization = ExecutionAuthorization::operator_approved(&plan);
        assert_eq!(executor.execute(&plan, &authorization).unwrap(), expected);
    }

    #[test]
    fn automatic_authorization_rejects_required_approval() {
        let error = ExecutionAuthorization::automatic(&plan(true)).unwrap_err();
        assert_eq!(error.code, "approval_required");
    }

    #[test]
    fn stale_authorization_fails_before_adapter_work() {
        let plan = plan(true);
        let mut authorization = ExecutionAuthorization::operator_approved(&plan);
        authorization.session_generation += 1;
        let mut executor = ReplayActionExecutor::new([Ok(observation())]);
        assert_eq!(
            executor.execute(&plan, &authorization).unwrap_err().code,
            "stale_authorization"
        );
    }

    #[test]
    fn production_adapter_executes_and_observes_correlated_capture() {
        let plan = plan(true);
        let authorization = ExecutionAuthorization::operator_approved(&plan);
        let (address, server) = controlled_mock_server();
        let mut executor = SdrdActionAdapter::new(address, Duration::from_secs(1));
        assert_eq!(
            executor.execute(&plan, &authorization).unwrap(),
            observation()
        );
        server.join().unwrap();
    }

    #[test]
    fn production_adapter_cancels_on_an_independent_connection() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            let mut request = String::new();
            reader.read_line(&mut request).unwrap();
            assert_eq!(request, "SDRD/1 CANCEL_SESSION 1 3\n");
            stream
                .write_all(
                    b"{\"schema_version\":1,\"request_id\":1,\"status\":\"ok\",\"generation\":3,\"cancel_requested\":true}\n",
                )
                .unwrap();
            stream.flush().unwrap();
        });
        let mut executor = SdrdActionAdapter::new(address, Duration::from_secs(1));
        assert_eq!(
            executor.cancel(3).unwrap(),
            CancelObservation {
                session_generation: 3,
                cancel_requested: true,
            }
        );
        server.join().unwrap();
    }
}
