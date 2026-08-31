use serde::{Deserialize, Serialize};

pub const PROTOCOL_VERSION: u16 = 1;
pub const MAX_FRAME_BYTES: usize = 32 * 1024;
pub const MAX_INSTRUCTION_BYTES: usize = 1024;
pub const MAX_CANDIDATES: usize = 32;

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PlanRequest {
    pub protocol_version: u16,
    pub request_id: u64,
    pub session_generation: u64,
    pub instruction: String,
    pub state: ControllerState,
    pub observation: ObservationSummary,
    pub limits: SafetyLimits,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ControllerState {
    Idle,
    Surveying,
    Inspecting,
    Recognizing,
    Holding,
    Faulted,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObservationSummary {
    pub age_ms: u64,
    pub health: HealthSummary,
    #[serde(default)]
    pub candidates: Vec<CandidateSummary>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub recognition: Option<RecognitionSummary>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HealthSummary {
    pub sdr_online: bool,
    pub can_retune: bool,
    pub can_capture_iq: bool,
    pub fpga_available: bool,
    pub recognizer_available: bool,
    pub dropped_observations: u64,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CandidateSummary {
    pub id: String,
    pub center_hz: u64,
    pub bandwidth_hz: u64,
    pub peak_dbfs: f32,
    pub snr_db: f32,
    pub age_ms: u64,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecognitionSummary {
    pub candidate_id: String,
    pub label: String,
    pub confidence: f32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SafetyLimits {
    pub min_freq_hz: u64,
    pub max_freq_hz: u64,
    pub max_span_hz: u64,
    pub max_bandwidth_hz: u64,
    pub max_dwell_ms: u64,
    pub max_iq_samples: u64,
    pub max_iq_bytes: u64,
    pub auto_approve_iq_bytes: u64,
    pub max_observation_age_ms: u64,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PlanResponse {
    pub protocol_version: u16,
    pub request_id: u64,
    pub session_generation: u64,
    pub status: PlanStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub action: Option<ProposedAction>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    pub planner: PlannerMeta,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PlanStatus {
    Ok,
    Error,
    Unavailable,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PlannerMeta {
    pub provider: String,
    pub model: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum ProposedAction {
    Hold {
        reason: String,
    },
    SurveyBand {
        start_hz: u64,
        stop_hz: u64,
        step_hz: u64,
        dwell_ms: u64,
    },
    InspectCandidate {
        candidate_id: String,
        center_hz: u64,
        bandwidth_hz: u64,
        dwell_ms: u64,
    },
    CaptureBoundedIq {
        candidate_id: String,
        center_hz: u64,
        sample_rate_hz: u64,
        rf_bandwidth_hz: u64,
        samples: u64,
    },
    RunLocalRecognition {
        candidate_id: String,
    },
    StopSession {
        reason: String,
    },
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ValidatedPlan {
    pub request_id: u64,
    pub session_generation: u64,
    pub approval_required: bool,
    pub action: ProposedAction,
    pub planner: PlannerMeta,
}
