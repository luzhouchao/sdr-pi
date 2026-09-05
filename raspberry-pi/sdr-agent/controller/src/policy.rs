use crate::protocol::{
    CandidateSummary, ControllerState, PlanRequest, PlanResponse, PlanStatus, ProposedAction,
    SafetyLimits, ValidatedPlan, MAX_CANDIDATES, MAX_INSTRUCTION_BYTES, MAX_SWEEP_POINTS,
    PROTOCOL_VERSION,
};

const MAX_SURVEY_POINTS: u64 = 768;
const MAX_SURVEY_DURATION_MS: u64 = 300_000;
const SURVEY_POINT_TIMEOUT_MS: u64 = 250;
const SURVEY_FRAME_BYTES: u64 = 4_096 * 4;
const MAX_INSPECTION_DWELL_MS: u64 = 1_000;
use std::collections::HashSet;
use std::error::Error;
use std::fmt;

pub struct ControllerPolicy;

impl ControllerPolicy {
    pub fn validate_request(&self, request: &PlanRequest) -> Result<(), PolicyError> {
        require(
            request.protocol_version == PROTOCOL_VERSION,
            "protocol_version",
            "unsupported planner protocol version",
        )?;
        require(request.request_id > 0, "request_id", "must be non-zero")?;
        require(
            !request.instruction.trim().is_empty()
                && request.instruction.len() <= MAX_INSTRUCTION_BYTES,
            "instruction",
            "must contain 1 to 1024 bytes",
        )?;
        validate_limits(&request.limits)?;
        require(
            request.observation.age_ms <= request.limits.max_observation_age_ms,
            "observation_stale",
            "observation is older than the configured limit",
        )?;
        require(
            request.observation.candidates.len() <= MAX_CANDIDATES,
            "too_many_candidates",
            "candidate count exceeds the protocol limit",
        )?;
        let mut candidate_ids = HashSet::new();
        for candidate in &request.observation.candidates {
            validate_candidate(candidate, &request.limits)?;
            require(
                candidate_ids.insert(candidate.id.as_str()),
                "duplicate_candidate_id",
                "candidate ids must be unique",
            )?;
        }
        if let Some(sweep) = &request.observation.latest_sweep {
            require(
                valid_label(&sweep.sweep_id, 64),
                "sweep_id",
                "latest sweep id is invalid",
            )?;
            require(
                !sweep.points.is_empty() && sweep.points.len() <= MAX_SWEEP_POINTS,
                "sweep_points",
                "latest sweep must contain between one and 768 points",
            )?;
            require(
                (2_100_000..=30_720_000).contains(&sweep.sample_rate_hz)
                    && (200_000..=sweep.sample_rate_hz).contains(&sweep.rf_bandwidth_hz)
                    && (0..=60).contains(&sweep.fixed_gain_db)
                    && sweep.noise_floor_dbfs.is_finite(),
                "sweep_profile",
                "latest sweep radio profile is invalid",
            )?;
            let mut previous_hz = None;
            for (center_hz, power_dbfs) in &sweep.points {
                validate_frequency(*center_hz, &request.limits)?;
                require(
                    power_dbfs.is_finite()
                        && previous_hz.map_or(true, |previous| previous < *center_hz),
                    "sweep_point",
                    "latest sweep points must be finite, unique, and ascending",
                )?;
                previous_hz = Some(*center_hz);
            }
        }
        if let Some(recognition) = &request.observation.recognition {
            require(
                valid_label(&recognition.candidate_id, 64),
                "recognition_candidate_id",
                "invalid candidate id",
            )?;
            require(
                valid_label(&recognition.label, 128),
                "recognition_label",
                "invalid recognition label",
            )?;
            require(
                recognition.confidence.is_finite() && (0.0..=1.0).contains(&recognition.confidence),
                "recognition_confidence",
                "must be finite and between zero and one",
            )?;
            require(
                candidate_ids.contains(recognition.candidate_id.as_str()),
                "recognition_stale",
                "recognition does not refer to a current candidate",
            )?;
        }
        Ok(())
    }

    pub fn validate_response(
        &self,
        request: &PlanRequest,
        response: PlanResponse,
    ) -> Result<ValidatedPlan, PolicyError> {
        require(
            response.protocol_version == PROTOCOL_VERSION,
            "response_protocol_version",
            "planner returned an unsupported protocol version",
        )?;
        require(
            response.request_id == request.request_id,
            "response_request_id",
            "planner response does not match the request",
        )?;
        require(
            response.session_generation == request.session_generation,
            "stale_session_generation",
            "planner response belongs to a stale controller session",
        )?;
        require(
            valid_label(&response.planner.provider, 64),
            "planner_provider",
            "invalid planner provider",
        )?;
        require(
            valid_label(&response.planner.model, 128),
            "planner_model",
            "invalid planner model",
        )?;

        if response.status != PlanStatus::Ok {
            require(
                response.action.is_none(),
                "planner_error_action",
                "failed planner response must not contain an action",
            )?;
            let message = response
                .error
                .filter(|value| !value.trim().is_empty() && value.len() <= 512)
                .unwrap_or_else(|| "planner failed without a bounded error message".to_owned());
            return Err(PolicyError::new("planner_unavailable", message));
        }
        require(
            response.error.is_none(),
            "planner_ok_error",
            "successful planner response must not contain an error",
        )?;
        let action = response.action.ok_or_else(|| {
            PolicyError::new("planner_missing_action", "planner returned no action")
        })?;
        let approval_required = validate_action(request, &action)?;

        Ok(ValidatedPlan {
            request_id: request.request_id,
            session_generation: request.session_generation,
            approval_required,
            action,
            planner: response.planner,
        })
    }
}

fn validate_limits(limits: &SafetyLimits) -> Result<(), PolicyError> {
    require(
        limits.min_freq_hz >= 70_000_000 && limits.min_freq_hz < limits.max_freq_hz,
        "limits_frequency",
        "invalid minimum or maximum frequency",
    )?;
    require(
        limits.max_freq_hz <= 6_000_000_000,
        "limits_frequency",
        "maximum frequency exceeds the AD9361 policy limit",
    )?;
    require(
        limits.max_span_hz > 0 && limits.max_span_hz <= limits.max_freq_hz - limits.min_freq_hz,
        "limits_span",
        "invalid maximum scan span",
    )?;
    require(
        (200_000..=56_000_000).contains(&limits.max_bandwidth_hz),
        "limits_bandwidth",
        "invalid maximum bandwidth",
    )?;
    require(
        (1..=60_000).contains(&limits.max_dwell_ms),
        "limits_dwell",
        "invalid maximum dwell time",
    )?;
    require(
        limits.max_iq_samples > 0
            && limits.max_iq_bytes > 0
            && limits.auto_approve_iq_bytes <= limits.max_iq_bytes,
        "limits_iq",
        "invalid IQ capture limits",
    )?;
    require(
        limits.max_observation_age_ms > 0,
        "limits_observation_age",
        "invalid observation age limit",
    )
}

fn validate_candidate(
    candidate: &CandidateSummary,
    limits: &SafetyLimits,
) -> Result<(), PolicyError> {
    require(
        valid_label(&candidate.id, 64),
        "candidate_id",
        "candidate id must contain 1 to 64 printable bytes",
    )?;
    validate_frequency(candidate.center_hz, limits)?;
    require(
        candidate.bandwidth_hz > 0 && candidate.bandwidth_hz <= limits.max_bandwidth_hz,
        "candidate_bandwidth",
        "candidate bandwidth exceeds the policy limit",
    )?;
    require(
        candidate.peak_dbfs.is_finite() && candidate.snr_db.is_finite(),
        "candidate_power",
        "candidate power values must be finite",
    )?;
    require(
        candidate.age_ms <= limits.max_observation_age_ms,
        "candidate_stale",
        "candidate is older than the configured limit",
    )
}

fn validate_action(request: &PlanRequest, action: &ProposedAction) -> Result<bool, PolicyError> {
    if request.state == ControllerState::Faulted
        && !matches!(
            action,
            ProposedAction::Hold { .. } | ProposedAction::StopSession { .. }
        )
    {
        return Err(PolicyError::new(
            "faulted_state",
            "only hold or stop is allowed while the controller is faulted",
        ));
    }

    match action {
        ProposedAction::Hold { reason } | ProposedAction::StopSession { reason } => {
            validate_reason(reason)?;
            Ok(false)
        }
        ProposedAction::SurveyBand {
            start_hz,
            stop_hz,
            step_hz,
            sample_rate_hz,
            rf_bandwidth_hz,
            dwell_ms,
        } => {
            require_sdr_capability(request, true, false)?;
            validate_frequency(*start_hz, &request.limits)?;
            validate_frequency(*stop_hz, &request.limits)?;
            require(
                start_hz < stop_hz && stop_hz - start_hz <= request.limits.max_span_hz,
                "survey_span",
                "survey span is empty or exceeds the policy limit",
            )?;
            require(
                *step_hz > 0 && *step_hz <= stop_hz - start_hz,
                "survey_step",
                "survey step is invalid",
            )?;
            validate_radio_profile(*sample_rate_hz, *rf_bandwidth_hz, &request.limits)?;
            require(
                *step_hz <= rf_bandwidth_hz.saturating_mul(4) / 5,
                "survey_coverage",
                "survey step exceeds 80 percent of RF bandwidth",
            )?;
            validate_dwell(*dwell_ms, &request.limits)?;
            let span_hz = stop_hz - start_hz;
            let point_count = span_hz
                .checked_add(step_hz.saturating_sub(1))
                .and_then(|rounded| rounded.checked_div(*step_hz))
                .and_then(|intervals| intervals.checked_add(1))
                .ok_or_else(|| PolicyError::new("survey_points", "survey point count overflow"))?;
            require(
                point_count <= MAX_SURVEY_POINTS,
                "survey_points",
                "survey exceeds the 768-point execution limit",
            )?;
            let estimated_duration_ms = point_count
                .checked_mul(dwell_ms.saturating_add(SURVEY_POINT_TIMEOUT_MS))
                .ok_or_else(|| PolicyError::new("survey_duration", "survey duration overflow"))?;
            require(
                estimated_duration_ms <= MAX_SURVEY_DURATION_MS,
                "survey_duration",
                "survey exceeds the 300-second execution limit",
            )?;
            let processed_bytes = point_count
                .checked_mul(SURVEY_FRAME_BYTES)
                .ok_or_else(|| PolicyError::new("survey_bytes", "survey byte budget overflow"))?;
            require(
                processed_bytes <= request.limits.max_iq_bytes,
                "survey_bytes",
                "survey exceeds the per-action receive-byte limit",
            )?;
            Ok(false)
        }
        ProposedAction::InspectCandidate {
            candidate_id,
            center_hz,
            sample_rate_hz,
            rf_bandwidth_hz,
            dwell_ms,
        } => {
            require_sdr_capability(request, true, false)?;
            let candidate = find_candidate(request, candidate_id)?;
            validate_frequency(*center_hz, &request.limits)?;
            validate_radio_profile(*sample_rate_hz, *rf_bandwidth_hz, &request.limits)?;
            require(
                center_hz.abs_diff(candidate.center_hz)
                    <= candidate.bandwidth_hz.max(*rf_bandwidth_hz),
                "inspect_candidate_mismatch",
                "inspection frequency does not match the selected candidate",
            )?;
            validate_dwell(*dwell_ms, &request.limits)?;
            require(
                *dwell_ms <= MAX_INSPECTION_DWELL_MS,
                "inspect_dwell",
                "candidate inspection dwell exceeds the one-second execution limit",
            )?;
            require(
                SURVEY_FRAME_BYTES <= request.limits.max_iq_bytes,
                "inspect_bytes",
                "candidate inspection exceeds the per-action receive-byte limit",
            )?;
            Ok(false)
        }
        ProposedAction::CaptureBoundedIq {
            candidate_id,
            center_hz,
            sample_rate_hz,
            rf_bandwidth_hz,
            samples,
        } => {
            require_sdr_capability(request, false, true)?;
            let candidate = find_candidate(request, candidate_id)?;
            validate_frequency(*center_hz, &request.limits)?;
            require(
                center_hz.abs_diff(candidate.center_hz) <= candidate.bandwidth_hz,
                "capture_candidate_mismatch",
                "capture frequency does not match the selected candidate",
            )?;
            require(
                (2_100_000..=30_720_000).contains(sample_rate_hz),
                "capture_sample_rate",
                "sample rate is outside the supported range",
            )?;
            require(
                (200_000..=request.limits.max_bandwidth_hz).contains(rf_bandwidth_hz)
                    && rf_bandwidth_hz <= sample_rate_hz,
                "capture_bandwidth",
                "RF bandwidth is invalid or exceeds the sample rate",
            )?;
            require(
                *samples > 0 && *samples <= request.limits.max_iq_samples,
                "capture_samples",
                "IQ sample count exceeds the policy limit",
            )?;
            let bytes = samples
                .checked_mul(4)
                .ok_or_else(|| PolicyError::new("capture_bytes", "IQ byte count overflow"))?;
            require(
                bytes <= request.limits.max_iq_bytes,
                "capture_bytes",
                "IQ byte count exceeds the policy limit",
            )?;
            Ok(bytes > request.limits.auto_approve_iq_bytes)
        }
        ProposedAction::RunLocalRecognition { candidate_id } => {
            require(
                request.observation.health.recognizer_available,
                "recognizer_unavailable",
                "local recognizer is not available",
            )?;
            find_candidate(request, candidate_id)?;
            Ok(true)
        }
    }
}

fn require_sdr_capability(
    request: &PlanRequest,
    retune: bool,
    capture: bool,
) -> Result<(), PolicyError> {
    require(
        request.observation.health.sdr_online,
        "sdr_offline",
        "SDR is offline",
    )?;
    require(
        !retune || request.observation.health.can_retune,
        "retune_unavailable",
        "the current SDR capability set is read-only",
    )?;
    require(
        !capture || request.observation.health.can_capture_iq,
        "capture_unavailable",
        "bounded IQ capture is not available",
    )
}

fn find_candidate<'a>(
    request: &'a PlanRequest,
    candidate_id: &str,
) -> Result<&'a CandidateSummary, PolicyError> {
    request
        .observation
        .candidates
        .iter()
        .find(|candidate| candidate.id == candidate_id)
        .ok_or_else(|| PolicyError::new("unknown_candidate", "candidate id is not current"))
}

fn validate_frequency(frequency_hz: u64, limits: &SafetyLimits) -> Result<(), PolicyError> {
    require(
        (limits.min_freq_hz..=limits.max_freq_hz).contains(&frequency_hz),
        "frequency",
        "frequency is outside the configured range",
    )
}

fn validate_dwell(dwell_ms: u64, limits: &SafetyLimits) -> Result<(), PolicyError> {
    require(
        dwell_ms > 0 && dwell_ms <= limits.max_dwell_ms,
        "dwell",
        "dwell time exceeds the configured limit",
    )
}

fn validate_radio_profile(
    sample_rate_hz: u64,
    rf_bandwidth_hz: u64,
    limits: &SafetyLimits,
) -> Result<(), PolicyError> {
    require(
        (2_100_000..=30_720_000).contains(&sample_rate_hz),
        "sample_rate",
        "sample rate is outside the controlled hardware range",
    )?;
    require(
        (200_000..=limits.max_bandwidth_hz).contains(&rf_bandwidth_hz)
            && rf_bandwidth_hz <= sample_rate_hz,
        "rf_bandwidth",
        "RF bandwidth is invalid or exceeds the sample rate",
    )
}

fn validate_reason(reason: &str) -> Result<(), PolicyError> {
    require(
        valid_label(reason, 256),
        "reason",
        "reason must contain 1 to 256 printable bytes",
    )
}

fn valid_label(value: &str, max_bytes: usize) -> bool {
    !value.trim().is_empty()
        && value.len() <= max_bytes
        && value.chars().all(|character| !character.is_control())
}

fn require(condition: bool, code: &'static str, message: &str) -> Result<(), PolicyError> {
    if condition {
        Ok(())
    } else {
        Err(PolicyError::new(code, message))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PolicyError {
    pub code: &'static str,
    pub message: String,
}

impl PolicyError {
    fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl fmt::Display for PolicyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)
    }
}

impl Error for PolicyError {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::{HealthSummary, ObservationSummary, PlannerMeta, RecognitionSummary};

    fn request() -> PlanRequest {
        PlanRequest {
            protocol_version: PROTOCOL_VERSION,
            request_id: 7,
            session_generation: 3,
            instruction: "Inspect the strongest current candidate".to_owned(),
            state: ControllerState::Idle,
            observation: ObservationSummary {
                age_ms: 100,
                health: HealthSummary {
                    sdr_online: true,
                    can_retune: true,
                    can_capture_iq: true,
                    recognizer_available: true,
                    dropped_observations: 0,
                },
                candidates: vec![CandidateSummary {
                    id: "candidate-1".to_owned(),
                    center_hz: 433_920_000,
                    bandwidth_hz: 200_000,
                    peak_dbfs: -18.0,
                    snr_db: 16.0,
                    age_ms: 100,
                }],
                latest_sweep: None,
                recognition: Some(RecognitionSummary {
                    candidate_id: "candidate-1".to_owned(),
                    label: "unknown".to_owned(),
                    confidence: 0.4,
                }),
            },
            limits: SafetyLimits {
                min_freq_hz: 70_000_000,
                max_freq_hz: 6_000_000_000,
                max_span_hz: 20_000_000,
                max_bandwidth_hz: 10_000_000,
                max_dwell_ms: 5_000,
                max_iq_samples: 1_048_576,
                max_iq_bytes: 4_194_304,
                auto_approve_iq_bytes: 262_144,
                max_observation_age_ms: 2_000,
            },
        }
    }

    fn response(request: &PlanRequest, action: ProposedAction) -> PlanResponse {
        PlanResponse {
            protocol_version: PROTOCOL_VERSION,
            request_id: request.request_id,
            session_generation: request.session_generation,
            status: PlanStatus::Ok,
            action: Some(action),
            error: None,
            planner: PlannerMeta {
                provider: "qwen4090".to_owned(),
                model: "qwen3.8-27b".to_owned(),
            },
        }
    }

    #[test]
    fn accepts_bounded_candidate_inspection() {
        let request = request();
        let plan = ControllerPolicy
            .validate_response(
                &request,
                response(
                    &request,
                    ProposedAction::InspectCandidate {
                        candidate_id: "candidate-1".to_owned(),
                        center_hz: 433_920_000,
                        sample_rate_hz: 2_100_000,
                        rf_bandwidth_hz: 500_000,
                        dwell_ms: 500,
                    },
                ),
            )
            .unwrap();
        assert!(!plan.approval_required);
    }

    #[test]
    fn rejects_candidate_inspection_above_execution_dwell_limit() {
        let request = request();
        let error = ControllerPolicy
            .validate_response(
                &request,
                response(
                    &request,
                    ProposedAction::InspectCandidate {
                        candidate_id: "candidate-1".to_owned(),
                        center_hz: 433_920_000,
                        sample_rate_hz: 2_100_000,
                        rf_bandwidth_hz: 500_000,
                        dwell_ms: 1_001,
                    },
                ),
            )
            .unwrap_err();
        assert_eq!(error.code, "inspect_dwell");
    }

    #[test]
    fn rejects_stale_session_generation() {
        let request = request();
        let mut response = response(
            &request,
            ProposedAction::Hold {
                reason: "wait".to_owned(),
            },
        );
        response.session_generation += 1;
        assert_eq!(
            ControllerPolicy
                .validate_response(&request, response)
                .unwrap_err()
                .code,
            "stale_session_generation"
        );
    }

    #[test]
    fn rejects_retune_when_sdrd_is_read_only() {
        let mut request = request();
        request.observation.health.can_retune = false;
        let result = ControllerPolicy.validate_response(
            &request,
            response(
                &request,
                ProposedAction::SurveyBand {
                    start_hz: 430_000_000,
                    stop_hz: 440_000_000,
                    step_hz: 500_000,
                    sample_rate_hz: 2_100_000,
                    rf_bandwidth_hz: 2_000_000,
                    dwell_ms: 100,
                },
            ),
        );
        assert_eq!(result.unwrap_err().code, "retune_unavailable");
    }

    #[test]
    fn accepts_executable_survey_and_rejects_excessive_points() {
        let request = request();
        let plan = ControllerPolicy
            .validate_response(
                &request,
                response(
                    &request,
                    ProposedAction::SurveyBand {
                        start_hz: 70_000_000,
                        stop_hz: 90_000_000,
                        step_hz: 100_000,
                        sample_rate_hz: 2_100_000,
                        rf_bandwidth_hz: 2_000_000,
                        dwell_ms: 10,
                    },
                ),
            )
            .unwrap();
        assert!(!plan.approval_required);

        let error = ControllerPolicy
            .validate_response(
                &request,
                response(
                    &request,
                    ProposedAction::SurveyBand {
                        start_hz: 70_000_000,
                        stop_hz: 90_000_000,
                        step_hz: 10_000,
                        sample_rate_hz: 2_100_000,
                        rf_bandwidth_hz: 2_000_000,
                        dwell_ms: 10,
                    },
                ),
            )
            .unwrap_err();
        assert_eq!(error.code, "survey_points");
    }

    #[test]
    fn large_bounded_iq_capture_requires_approval() {
        let request = request();
        let plan = ControllerPolicy
            .validate_response(
                &request,
                response(
                    &request,
                    ProposedAction::CaptureBoundedIq {
                        candidate_id: "candidate-1".to_owned(),
                        center_hz: 433_920_000,
                        sample_rate_hz: 2_100_000,
                        rf_bandwidth_hz: 500_000,
                        samples: 131_072,
                    },
                ),
            )
            .unwrap();
        assert!(plan.approval_required);
    }

    #[test]
    fn faulted_state_only_allows_hold_or_stop() {
        let mut request = request();
        request.state = ControllerState::Faulted;
        let result = ControllerPolicy.validate_response(
            &request,
            response(
                &request,
                ProposedAction::RunLocalRecognition {
                    candidate_id: "candidate-1".to_owned(),
                },
            ),
        );
        assert_eq!(result.unwrap_err().code, "faulted_state");
    }

    #[test]
    fn rejects_duplicate_candidate_ids() {
        let mut request = request();
        request
            .observation
            .candidates
            .push(request.observation.candidates[0].clone());
        assert_eq!(
            ControllerPolicy
                .validate_request(&request)
                .unwrap_err()
                .code,
            "duplicate_candidate_id"
        );
    }

    #[test]
    fn serde_rejects_unknown_request_fields() {
        let value = serde_json::json!({
            "protocol_version": 1,
            "request_id": 1,
            "session_generation": 1,
            "instruction": "hold",
            "state": "idle",
            "observation": {
                "age_ms": 0,
                "health": {
                    "sdr_online": true,
                    "can_retune": false,
                    "can_capture_iq": false,
                    "recognizer_available": false,
                    "dropped_observations": 0
                },
                "candidates": []
            },
            "limits": {
                "min_freq_hz": 70000000,
                "max_freq_hz": 6000000000_u64,
                "max_span_hz": 20000000,
                "max_bandwidth_hz": 10000000,
                "max_dwell_ms": 5000,
                "max_iq_samples": 1048576,
                "max_iq_bytes": 4194304,
                "auto_approve_iq_bytes": 262144,
                "max_observation_age_ms": 2000
            },
            "unexpected": true
        });
        assert!(serde_json::from_value::<PlanRequest>(value).is_err());
    }
    #[test]
    fn recognition_requires_operator_approval_and_rejects_unavailable() {
        let mut request = request();
        let action = ProposedAction::RunLocalRecognition {
            candidate_id: "candidate-1".to_owned(),
        };
        let plan = ControllerPolicy
            .validate_response(&request, response(&request, action.clone()))
            .unwrap();
        assert!(plan.approval_required);
        assert_eq!(
            crate::execution::ExecutionAuthorization::automatic(&plan)
                .unwrap_err()
                .code,
            "approval_required"
        );
        request.observation.health.recognizer_available = false;
        assert_eq!(
            ControllerPolicy
                .validate_response(&request, response(&request, action))
                .unwrap_err()
                .code,
            "recognizer_unavailable"
        );
    }
}
