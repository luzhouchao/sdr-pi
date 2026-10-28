use serde::{Deserialize, Serialize};

pub const PROTOCOL_VERSION: u16 = 1;
pub const MAX_FRAME_BYTES: usize = 32 * 1024;
pub const MAX_INSTRUCTION_BYTES: usize = 1024;
pub const MAX_CANDIDATES: usize = 32;
pub const MAX_SWEEP_POINTS: usize = 768;

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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cruise: Option<crate::autonomy::CruisePlanningSummary>,
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
    pub latest_sweep: Option<SweepObservationSummary>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub recognition: Option<RecognitionSummary>,
}

/// Compact, measured sweep data supplied to the upstream Planner. Each point
/// is `[actual_center_hz, band_power_dbfs]`; keeping the pair compact lets the
/// complete bounded 768-point sweep remain inside the Planner protocol frame.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SweepObservationSummary {
    pub sweep_id: String,
    pub sample_rate_hz: u64,
    pub rf_bandwidth_hz: u64,
    pub fixed_gain_db: i16,
    pub noise_floor_dbfs: f32,
    pub points: Vec<(u64, f32)>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HealthSummary {
    pub sdr_online: bool,
    pub can_retune: bool,
    pub can_capture_iq: bool,
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

pub use crate::recognition_result::RecognitionObservation as RecognitionSummary;

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
    StartTask {
        mission: String,
        target_sweeps: u8,
        max_steps: u8,
        max_seconds: u64,
        max_iq_bytes: u64,
        min_freq_hz: u64,
        max_freq_hz: u64,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        monitor_threshold_db: Option<u8>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        monitor_interval_secs: Option<u16>,
    },
    Hold {
        reason: String,
    },
    SurveyBand {
        start_hz: u64,
        stop_hz: u64,
        step_hz: u64,
        sample_rate_hz: u64,
        rf_bandwidth_hz: u64,
        dwell_ms: u64,
    },
    InspectCandidate {
        candidate_id: String,
        center_hz: u64,
        sample_rate_hz: u64,
        rf_bandwidth_hz: u64,
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

#[cfg(test)]
mod tests {
    use super::HealthSummary;

    #[test]
    fn retired_false_fpga_health_is_rejected() {
        let error = serde_json::from_str::<HealthSummary>(
            r#"{"sdr_online":true,"can_retune":true,"can_capture_iq":true,"fpga_available":false,"recognizer_available":false,"dropped_observations":0}"#,
        ).unwrap_err();
        assert!(error.to_string().contains("unknown field"));
    }

    #[test]
    fn retired_true_fpga_health_is_rejected() {
        let error = serde_json::from_str::<HealthSummary>(
            r#"{"sdr_online":true,"can_retune":true,"can_capture_iq":true,"fpga_available":true,"recognizer_available":false,"dropped_observations":0}"#,
        )
        .unwrap_err();
        assert!(error.to_string().contains("unknown field"));
    }
}
