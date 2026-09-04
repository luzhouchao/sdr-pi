use crate::execution::{
    CancelObservation, ExecutionHealthMetadata, ExecutionTimeoutMetadata, SdrActionExecutor,
    SdrdActionAdapter,
};
use crate::protocol::CandidateSummary;
use crate::sdr::{RxInputIdentity, SdrEngine, SdrdAdapter, SdrdWire};
use crate::sweep::{
    decode_base64, SweepReport, SPECTRAL_SUMMARY_ALGORITHM_ID, SPECTRAL_SUMMARY_SCHEMA_VERSION,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::error::Error;
use std::fmt;
use std::fs;
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

pub const RECOGNITION_INPUT_SCHEMA_VERSION: u16 = 1;
pub const MODEL_READY_BATCH_SCHEMA_VERSION: u16 = 1;
pub const MAX_PROFILE_BYTES: u64 = 64 * 1024;
pub const MAX_INLINE_RAW_BYTES: u64 = 256 * 1024;
const ADC_FULL_SCALE: f64 = 2_048.0;

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecognitionInputProfile {
    pub schema_version: u16,
    pub profile_id: String,
    pub admission: ProfileAdmission,
    pub production_enabled: bool,
    pub model: ProfileModel,
    pub rx: ProfileRx,
    pub capture: ProfileCapture,
    pub eligibility: ProfileEligibility,
    pub preprocess: ProfilePreprocess,
    pub limitations: ProfileLimitations,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProfileAdmission {
    IntegrationOnly,
    Production,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileModel {
    pub model_id: String,
    pub model_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileRx {
    pub front_panel_port: String,
    pub logical_channel: String,
    pub rf_port_select: String,
    pub sample_rate_hz: u32,
    pub rf_bandwidth_hz: u32,
    pub gain_db: i16,
    pub settle_ms: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileCapture {
    pub window_count: u16,
    pub samples_per_window: u32,
    pub capture_timeout_ms: u32,
    pub control_deadline_ms: u32,
    pub model_deadline_ms: u32,
    pub raw_bytes_per_complex_sample: u16,
    pub max_total_raw_bytes: u64,
    pub max_total_model_bytes: u64,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileEligibility {
    pub maximum_target_age_ms: u64,
    pub maximum_occupied_bandwidth_hz: u64,
    pub minimum_estimated_snr_db: f32,
    pub minimum_peak_dbfs: f32,
    pub maximum_peak_dbfs: f32,
    pub require_zero_dropped_samples: bool,
    pub require_no_overflow: bool,
    pub require_zero_health_flags: bool,
    pub maximum_clipped_samples: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfilePreprocess {
    pub preprocess_id: String,
    pub spec_path: String,
    pub spec_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileLimitations {
    pub production: bool,
    pub retraining: String,
    pub labels: String,
    pub rejection: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct PreprocessSpec {
    schema_version: u16,
    preprocess_id: String,
    admission: ProfileAdmission,
    input: PreprocessInput,
    transform: PreprocessTransform,
    output: PreprocessOutput,
    quality: PreprocessQuality,
    limitations: PreprocessLimitations,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct PreprocessInput {
    sample_format: String,
    layout: String,
    adc_bits: u16,
    sample_rate_hz: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct PreprocessTransform {
    frequency_alignment: String,
    resample: bool,
    remove_dc: bool,
    window_samples: u32,
    windowing: String,
    normalization: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct PreprocessOutput {
    sample_format: String,
    layout: String,
    bytes_per_window: u64,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct PreprocessQuality {
    minimum_raw_complex_rms_adc: f64,
    reject_clipped_adc_samples: bool,
    normalization_rms_tolerance: f64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct PreprocessLimitations {
    production: bool,
    reason: String,
    training_alignment: String,
}

#[derive(Clone, Debug)]
pub struct LoadedRecognitionInputProfile {
    pub profile: RecognitionInputProfile,
    pub manifest_path: PathBuf,
    pub manifest_sha256: String,
    preprocess: PreprocessSpec,
}

impl LoadedRecognitionInputProfile {
    pub fn production_ready(&self) -> bool {
        self.profile.admission == ProfileAdmission::Production
            && self.profile.production_enabled
            && self.preprocess.admission == ProfileAdmission::Production
            && self.preprocess.limitations.production
            && self.profile.limitations.production
    }

    pub fn total_complex_samples(&self) -> u64 {
        u64::from(self.profile.capture.window_count)
            * u64::from(self.profile.capture.samples_per_window)
    }
}

pub fn load_recognition_input_profile(
    repository_root: &Path,
    manifest_path: &Path,
) -> Result<LoadedRecognitionInputProfile, RecognitionInputError> {
    let repository_root = fs::canonicalize(repository_root)
        .map_err(|error| RecognitionInputError::io("repository_root", error))?;
    let manifest_input = if manifest_path.is_absolute() {
        manifest_path.to_owned()
    } else {
        repository_root.join(manifest_path)
    };
    let manifest_path =
        canonical_regular_file(&repository_root, &manifest_input, MAX_PROFILE_BYTES)?;
    let manifest_bytes = fs::read(&manifest_path)
        .map_err(|error| RecognitionInputError::io("profile_read", error))?;
    let manifest_sha256 = sha256_hex(&manifest_bytes);
    let profile: RecognitionInputProfile = serde_json::from_slice(&manifest_bytes)
        .map_err(|error| RecognitionInputError::protocol("profile_json", error))?;

    let relative_spec = Path::new(&profile.preprocess.spec_path);
    if relative_spec.is_absolute()
        || relative_spec
            .components()
            .any(|component| matches!(component, std::path::Component::ParentDir))
    {
        return Err(RecognitionInputError::new(
            "preprocess_path",
            "preprocess spec path must be repository-relative without parent traversal",
        ));
    }
    let spec_path = canonical_regular_file(
        &repository_root,
        &repository_root.join(relative_spec),
        MAX_PROFILE_BYTES,
    )?;
    let spec_bytes = fs::read(&spec_path)
        .map_err(|error| RecognitionInputError::io("preprocess_read", error))?;
    if sha256_hex(&spec_bytes) != profile.preprocess.spec_sha256 {
        return Err(RecognitionInputError::new(
            "preprocess_hash",
            "preprocess specification SHA-256 does not match the profile",
        ));
    }
    let preprocess: PreprocessSpec = serde_json::from_slice(&spec_bytes)
        .map_err(|error| RecognitionInputError::protocol("preprocess_json", error))?;
    validate_profile(&profile, &preprocess)?;
    Ok(LoadedRecognitionInputProfile {
        profile,
        manifest_path,
        manifest_sha256,
        preprocess,
    })
}

fn canonical_regular_file(
    repository_root: &Path,
    path: &Path,
    maximum_bytes: u64,
) -> Result<PathBuf, RecognitionInputError> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| RecognitionInputError::io("profile_stat", error))?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > maximum_bytes
    {
        return Err(RecognitionInputError::new(
            "profile_file",
            "profile input must be a bounded non-symlink regular file",
        ));
    }
    let canonical = fs::canonicalize(path)
        .map_err(|error| RecognitionInputError::io("profile_canonicalize", error))?;
    if !canonical.starts_with(repository_root) {
        return Err(RecognitionInputError::new(
            "profile_escape",
            "profile input escaped the repository root",
        ));
    }
    Ok(canonical)
}

fn validate_profile(
    profile: &RecognitionInputProfile,
    preprocess: &PreprocessSpec,
) -> Result<(), RecognitionInputError> {
    if profile.schema_version != RECOGNITION_INPUT_SCHEMA_VERSION
        || preprocess.schema_version != RECOGNITION_INPUT_SCHEMA_VERSION
    {
        return Err(RecognitionInputError::new(
            "schema_version",
            "unsupported recognition input profile schema",
        ));
    }
    require_text(&profile.profile_id, 128, "profile_id")?;
    require_text(&profile.model.model_id, 128, "model_id")?;
    require_sha256(&profile.model.model_sha256, "model_sha256")?;
    require_text(&profile.preprocess.preprocess_id, 128, "preprocess_id")?;
    require_sha256(&profile.preprocess.spec_sha256, "preprocess_sha256")?;
    if profile.preprocess.preprocess_id != preprocess.preprocess_id
        || profile.admission != preprocess.admission
        || profile.production_enabled != profile.limitations.production
        || (profile.production_enabled && profile.admission != ProfileAdmission::Production)
        || (!profile.production_enabled && profile.admission == ProfileAdmission::Production)
    {
        return Err(RecognitionInputError::new(
            "profile_admission",
            "profile, preprocessing and production admission do not agree",
        ));
    }
    if profile.rx.front_panel_port != "RX1"
        || profile.rx.logical_channel != "RX0"
        || profile.rx.rf_port_select != "A_BALANCED"
        || !(2_083_333..=30_720_000).contains(&profile.rx.sample_rate_hz)
        || !(200_000..=profile.rx.sample_rate_hz).contains(&profile.rx.rf_bandwidth_hz)
        || !(0..=60).contains(&profile.rx.gain_db)
        || profile.rx.settle_ms > 1_000
    {
        return Err(RecognitionInputError::new(
            "rx_profile",
            "recognition RX profile is outside the fixed P201 receive contract",
        ));
    }
    let capture = &profile.capture;
    if capture.window_count == 0
        || capture.window_count > 64
        || !(256..=16_384).contains(&capture.samples_per_window)
        || !capture.samples_per_window.is_power_of_two()
        || !(100..=5_000).contains(&capture.capture_timeout_ms)
        || !(100..=60_000).contains(&capture.control_deadline_ms)
        || !(1..=5_000).contains(&capture.model_deadline_ms)
        || capture.raw_bytes_per_complex_sample != 4
    {
        return Err(RecognitionInputError::new(
            "capture_profile",
            "recognition capture shape or deadline is outside limits",
        ));
    }
    let raw_bytes = u64::from(capture.window_count)
        .checked_mul(u64::from(capture.samples_per_window))
        .and_then(|value| value.checked_mul(4))
        .ok_or_else(|| RecognitionInputError::new("capture_bytes", "raw byte count overflow"))?;
    let model_bytes = u64::from(capture.window_count)
        .checked_mul(u64::from(capture.samples_per_window))
        .and_then(|value| value.checked_mul(2))
        .and_then(|value| value.checked_mul(4))
        .ok_or_else(|| RecognitionInputError::new("capture_bytes", "model byte count overflow"))?;
    if raw_bytes != capture.max_total_raw_bytes
        || model_bytes != capture.max_total_model_bytes
        || raw_bytes > MAX_INLINE_RAW_BYTES
    {
        return Err(RecognitionInputError::new(
            "capture_bytes",
            "profile byte bounds do not exactly match the declared window shape",
        ));
    }
    let eligibility = &profile.eligibility;
    if eligibility.maximum_target_age_ms == 0
        || eligibility.maximum_target_age_ms > 60_000
        || eligibility.maximum_occupied_bandwidth_hz == 0
        || eligibility.maximum_occupied_bandwidth_hz > u64::from(profile.rx.rf_bandwidth_hz)
        || !eligibility.minimum_estimated_snr_db.is_finite()
        || !(0.0..=100.0).contains(&eligibility.minimum_estimated_snr_db)
        || !eligibility.minimum_peak_dbfs.is_finite()
        || !eligibility.maximum_peak_dbfs.is_finite()
        || eligibility.minimum_peak_dbfs < -160.0
        || eligibility.maximum_peak_dbfs > 0.0
        || eligibility.minimum_peak_dbfs >= eligibility.maximum_peak_dbfs
        || !eligibility.require_zero_dropped_samples
        || !eligibility.require_no_overflow
        || !eligibility.require_zero_health_flags
    {
        return Err(RecognitionInputError::new(
            "eligibility_profile",
            "recognition eligibility gates are incomplete or outside limits",
        ));
    }
    if preprocess.input.sample_format != "ci16_le"
        || preprocess.input.layout != "interleaved_iq"
        || preprocess.input.adc_bits != 12
        || preprocess.input.sample_rate_hz != profile.rx.sample_rate_hz
        || preprocess.transform.frequency_alignment != "hardware_retune_to_candidate_center"
        || preprocess.transform.resample
        || preprocess.transform.remove_dc
        || preprocess.transform.window_samples != capture.samples_per_window
        || preprocess.transform.windowing != "contiguous_non_overlapping"
        || preprocess.transform.normalization != "per_window_complex_unit_rms"
        || preprocess.output.sample_format != "f32_le"
        || preprocess.output.layout != "window_major_planar_iq"
        || preprocess.output.bytes_per_window != u64::from(capture.samples_per_window) * 8
        || !preprocess.quality.minimum_raw_complex_rms_adc.is_finite()
        || preprocess.quality.minimum_raw_complex_rms_adc < 1.0
        || !preprocess.quality.reject_clipped_adc_samples
        || !preprocess.quality.normalization_rms_tolerance.is_finite()
        || !(0.0..=0.01).contains(&preprocess.quality.normalization_rms_tolerance)
    {
        return Err(RecognitionInputError::new(
            "preprocess_contract",
            "preprocess specification is not supported by this implementation",
        ));
    }
    Ok(())
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecognitionTarget {
    pub schema_version: u16,
    pub candidate_id: String,
    pub source_sweep_id: String,
    pub source_session_generation: u64,
    pub source_request_id: u64,
    pub source_sequence: u64,
    pub observed_at_unix_ms: u64,
    pub center_hz: u64,
    pub occupied_bandwidth_hz: u64,
    pub inspection_gain_db: i16,
    pub peak_dbfs: f32,
    pub noise_floor_dbfs: f32,
    pub estimated_snr_db: f32,
    pub clipped_samples: u64,
    pub dropped_samples: u64,
    pub overflow: bool,
    pub health_flags: u32,
    pub health_source: String,
    pub rx_input: RxInputIdentity,
}

impl RecognitionTarget {
    pub fn from_inspection(
        candidate: &CandidateSummary,
        report: &SweepReport,
        observed_at_unix_ms: u64,
        inspection_gain_db: i16,
    ) -> Result<Self, RecognitionInputError> {
        if report.points.len() != 1 || observed_at_unix_ms == 0 {
            return Err(RecognitionInputError::new(
                "target_source",
                "recognition target requires one timestamped inspection point",
            ));
        }
        let point = &report.points[0];
        let spectral = &point.spectral;
        let center_tolerance_hz = spectral.bin_width_hz.ceil().max(1.0) as u64;
        if candidate.id.is_empty()
            || candidate.id.len() > 64
            || candidate.age_ms != 0
            || spectral.schema_version != SPECTRAL_SUMMARY_SCHEMA_VERSION
            || spectral.algorithm_id != SPECTRAL_SUMMARY_ALGORITHM_ID
            || !spectral.bin_width_hz.is_finite()
            || spectral.bin_width_hz <= 0.0
            || !spectral.peak_power_dbfs.is_finite()
            || !spectral.noise_floor_dbfs.is_finite()
            || !spectral.measured_snr_db.is_finite()
            || (spectral.measured_snr_db
                - (spectral.peak_power_dbfs - spectral.noise_floor_dbfs).max(0.0))
            .abs()
                > 0.01
            || candidate.center_hz.abs_diff(spectral.estimated_center_hz) > center_tolerance_hz
            || candidate.bandwidth_hz != spectral.occupied_bandwidth_hz
            || (candidate.peak_dbfs - spectral.peak_power_dbfs).abs() > 0.01
            || (candidate.snr_db - spectral.measured_snr_db).abs() > 0.01
            || point.session_generation != report.session_generation
            || point.requested_center_hz.abs_diff(point.actual_center_hz) > 2
            || point.dropped_samples != 0
            || point.overflow
            || point.clipped_samples != 0
            || point.status_flags != 0
            || !point.health.healthy
            || point.health.flags != 0
            || !point.rx_input.is_fixed_p201_rx1()
            || !(0..=60).contains(&inspection_gain_db)
        {
            return Err(RecognitionInputError::new(
                "target_source",
                "inspection point is stale, inconsistent or unhealthy",
            ));
        }
        let noise_floor_dbfs = spectral.noise_floor_dbfs;
        let estimated_snr_db = spectral.measured_snr_db;
        if !noise_floor_dbfs.is_finite() || !estimated_snr_db.is_finite() {
            return Err(RecognitionInputError::new(
                "target_quality",
                "inspection SNR inputs are not finite",
            ));
        }
        Ok(Self {
            schema_version: RECOGNITION_INPUT_SCHEMA_VERSION,
            candidate_id: candidate.id.clone(),
            source_sweep_id: report.sweep_id.clone(),
            source_session_generation: report.session_generation,
            source_request_id: point.request_id,
            source_sequence: point.sequence,
            observed_at_unix_ms,
            center_hz: spectral.estimated_center_hz,
            occupied_bandwidth_hz: spectral.occupied_bandwidth_hz,
            inspection_gain_db,
            peak_dbfs: spectral.peak_power_dbfs,
            noise_floor_dbfs,
            estimated_snr_db,
            clipped_samples: point.clipped_samples,
            dropped_samples: point.dropped_samples,
            overflow: point.overflow,
            health_flags: point.health.flags,
            health_source: point.health.source.clone(),
            rx_input: point.rx_input.clone(),
        })
    }
}

pub fn validate_recognition_target(
    loaded: &LoadedRecognitionInputProfile,
    target: &RecognitionTarget,
    now_unix_ms: u64,
) -> Result<(), RecognitionInputError> {
    let profile = &loaded.profile;
    let expected_snr_db = (target.peak_dbfs - target.noise_floor_dbfs).max(0.0);
    let age_ms = now_unix_ms
        .checked_sub(target.observed_at_unix_ms)
        .ok_or_else(|| {
            RecognitionInputError::new("target_time", "target timestamp is in the future")
        })?;
    if target.schema_version != RECOGNITION_INPUT_SCHEMA_VERSION
        || target.candidate_id.is_empty()
        || target.candidate_id.len() > 64
        || target.candidate_id.chars().any(char::is_control)
        || target.source_sweep_id.is_empty()
        || target.source_sweep_id.len() > 128
        || target.source_session_generation == 0
        || target.source_request_id == 0
        || target.source_sequence == 0
        || age_ms > profile.eligibility.maximum_target_age_ms
        || !(70_000_000..=6_000_000_000).contains(&target.center_hz)
        || target.occupied_bandwidth_hz == 0
        || target.occupied_bandwidth_hz > profile.eligibility.maximum_occupied_bandwidth_hz
        || target.inspection_gain_db != profile.rx.gain_db
        || !target.peak_dbfs.is_finite()
        || target.peak_dbfs < profile.eligibility.minimum_peak_dbfs
        || target.peak_dbfs > profile.eligibility.maximum_peak_dbfs
        || !target.noise_floor_dbfs.is_finite()
        || !target.estimated_snr_db.is_finite()
        || (target.estimated_snr_db - expected_snr_db).abs() > 0.01
        || target.estimated_snr_db < profile.eligibility.minimum_estimated_snr_db
        || target.clipped_samples > profile.eligibility.maximum_clipped_samples
        || target.dropped_samples != 0
        || target.overflow
        || target.health_flags != 0
        || target.health_source != "iio_adapter"
        || !target.rx_input.is_fixed_p201_rx1()
    {
        return Err(RecognitionInputError::new(
            "target_ineligible",
            "recognition target is stale, out of profile, low quality or unhealthy",
        ));
    }
    Ok(())
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BatchCaptureMetadata {
    pub sdrd_request_id: u64,
    pub session_generation: u64,
    pub sequence: u64,
    pub center_hz: u64,
    pub sample_rate_hz: u32,
    pub rf_bandwidth_hz: u32,
    pub gain_db: i16,
    pub samples_captured: u64,
    pub bytes_transferred: u64,
    pub dropped_samples: u64,
    pub overflow: bool,
    pub timeout: ExecutionTimeoutMetadata,
    pub health: ExecutionHealthMetadata,
    pub rx_input: RxInputIdentity,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelWindowQuality {
    pub window_index: u16,
    pub raw_complex_rms_adc: f64,
    pub raw_rms_dbfs: f64,
    pub raw_dc_fraction: f64,
    pub normalization_scale: f64,
    pub normalized_complex_rms: f64,
    pub clipped_samples: u64,
    pub output_offset_bytes: u64,
    pub output_length_bytes: u64,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelReadyBatchSummary {
    pub schema_version: u16,
    pub request_id: u64,
    pub session_generation: u64,
    pub candidate_id: String,
    pub source_sweep_id: String,
    pub source_sequence: u64,
    pub profile_id: String,
    pub profile_sha256: String,
    pub profile_admission: ProfileAdmission,
    pub preprocess_id: String,
    pub preprocess_sha256: String,
    pub window_count: u16,
    pub samples_per_window: u32,
    pub sample_rate_hz: u32,
    pub center_hz: u64,
    pub raw_bytes: u64,
    pub model_bytes: u64,
    pub model_bytes_sha256: String,
    pub windows: Vec<ModelWindowQuality>,
    pub capture: BatchCaptureMetadata,
}

#[derive(Clone, Debug)]
pub struct ModelReadyBatch {
    pub summary: ModelReadyBatchSummary,
    pub model_bytes: Vec<u8>,
}

pub fn build_model_ready_batch(
    loaded: &LoadedRecognitionInputProfile,
    target: &RecognitionTarget,
    request_id: u64,
    session_generation: u64,
    capture: BatchCaptureMetadata,
    raw_ci16_le: &[u8],
) -> Result<ModelReadyBatch, RecognitionInputError> {
    if request_id == 0
        || session_generation == 0
        || capture.sdrd_request_id == 0
        || capture.session_generation != session_generation
        || capture.sequence == 0
        || capture.center_hz.abs_diff(target.center_hz) > 2
        || capture.sample_rate_hz != loaded.profile.rx.sample_rate_hz
        || capture.rf_bandwidth_hz != loaded.profile.rx.rf_bandwidth_hz
        || capture.gain_db != loaded.profile.rx.gain_db
        || capture.samples_captured != loaded.total_complex_samples()
        || capture.bytes_transferred != loaded.profile.capture.max_total_raw_bytes
        || capture.dropped_samples != 0
        || capture.overflow
        || capture.timeout.limit_ms != loaded.profile.capture.capture_timeout_ms
        || capture.timeout.timed_out
        || !capture.health.healthy
        || capture.health.flags != 0
        || capture.health.source != "iio_adapter"
        || capture.rx_input != target.rx_input
        || !capture.rx_input.is_fixed_p201_rx1()
        || raw_ci16_le.len() as u64 != loaded.profile.capture.max_total_raw_bytes
    {
        return Err(RecognitionInputError::new(
            "capture_contract",
            "captured IQ metadata or byte shape violates the admitted profile",
        ));
    }
    let samples_per_window = loaded.profile.capture.samples_per_window as usize;
    let raw_bytes_per_window = samples_per_window * 4;
    let model_bytes_per_window = samples_per_window * 8;
    let mut model_bytes = Vec::with_capacity(loaded.profile.capture.max_total_model_bytes as usize);
    let mut windows = Vec::with_capacity(loaded.profile.capture.window_count as usize);
    let mut total_clipped = 0_u64;
    for (window_index, raw_window) in raw_ci16_le.chunks_exact(raw_bytes_per_window).enumerate() {
        let mut i_values = Vec::with_capacity(samples_per_window);
        let mut q_values = Vec::with_capacity(samples_per_window);
        let mut power = 0.0_f64;
        let mut sum_i = 0.0_f64;
        let mut sum_q = 0.0_f64;
        let mut clipped_samples = 0_u64;
        for sample in raw_window.chunks_exact(4) {
            let i = i16::from_le_bytes([sample[0], sample[1]]);
            let q = i16::from_le_bytes([sample[2], sample[3]]);
            if i <= -2_048 || i >= 2_047 || q <= -2_048 || q >= 2_047 {
                clipped_samples = clipped_samples.saturating_add(1);
            }
            let i = f64::from(i);
            let q = f64::from(q);
            power += i * i + q * q;
            sum_i += i;
            sum_q += q;
            i_values.push(i);
            q_values.push(q);
        }
        total_clipped = total_clipped.saturating_add(clipped_samples);
        let sample_count = samples_per_window as f64;
        let raw_complex_rms_adc = (power / sample_count).sqrt();
        if !raw_complex_rms_adc.is_finite()
            || raw_complex_rms_adc < loaded.preprocess.quality.minimum_raw_complex_rms_adc
        {
            return Err(RecognitionInputError::new(
                "raw_rms",
                "one recognition window is silent or below the profile RMS floor",
            ));
        }
        if loaded.preprocess.quality.reject_clipped_adc_samples && clipped_samples != 0 {
            return Err(RecognitionInputError::new(
                "raw_clipping",
                "one recognition window contains clipped ADC samples",
            ));
        }
        let normalization_scale = 1.0 / raw_complex_rms_adc;
        let output_offset_bytes = model_bytes.len() as u64;
        let mut normalized_power = 0.0_f64;
        for values in [&i_values, &q_values] {
            for value in values {
                let normalized = (*value * normalization_scale) as f32;
                normalized_power += f64::from(normalized) * f64::from(normalized);
                model_bytes.extend_from_slice(&normalized.to_le_bytes());
            }
        }
        let normalized_complex_rms = (normalized_power / sample_count).sqrt();
        if (normalized_complex_rms - 1.0).abs()
            > loaded.preprocess.quality.normalization_rms_tolerance
        {
            return Err(RecognitionInputError::new(
                "normalization",
                "model-ready window failed the normalization tolerance",
            ));
        }
        let mean_i = sum_i / sample_count;
        let mean_q = sum_q / sample_count;
        windows.push(ModelWindowQuality {
            window_index: window_index as u16,
            raw_complex_rms_adc,
            raw_rms_dbfs: 20.0 * (raw_complex_rms_adc / ADC_FULL_SCALE).log10(),
            raw_dc_fraction: (mean_i * mean_i + mean_q * mean_q).sqrt() / raw_complex_rms_adc,
            normalization_scale,
            normalized_complex_rms,
            clipped_samples,
            output_offset_bytes,
            output_length_bytes: model_bytes_per_window as u64,
        });
    }
    if windows.len() != loaded.profile.capture.window_count as usize
        || model_bytes.len() as u64 != loaded.profile.capture.max_total_model_bytes
        || total_clipped > loaded.profile.eligibility.maximum_clipped_samples
    {
        return Err(RecognitionInputError::new(
            "model_batch_shape",
            "model-ready batch count, byte length or clipping exceeds the profile",
        ));
    }
    let model_bytes_sha256 = sha256_hex(&model_bytes);
    Ok(ModelReadyBatch {
        summary: ModelReadyBatchSummary {
            schema_version: MODEL_READY_BATCH_SCHEMA_VERSION,
            request_id,
            session_generation,
            candidate_id: target.candidate_id.clone(),
            source_sweep_id: target.source_sweep_id.clone(),
            source_sequence: target.source_sequence,
            profile_id: loaded.profile.profile_id.clone(),
            profile_sha256: loaded.manifest_sha256.clone(),
            profile_admission: loaded.profile.admission,
            preprocess_id: loaded.profile.preprocess.preprocess_id.clone(),
            preprocess_sha256: loaded.profile.preprocess.spec_sha256.clone(),
            window_count: loaded.profile.capture.window_count,
            samples_per_window: loaded.profile.capture.samples_per_window,
            sample_rate_hz: loaded.profile.rx.sample_rate_hz,
            center_hz: target.center_hz,
            raw_bytes: raw_ci16_le.len() as u64,
            model_bytes: model_bytes.len() as u64,
            model_bytes_sha256,
            windows,
            capture,
        },
        model_bytes,
    })
}

#[derive(Clone)]
pub struct SdrdModelReadyBatchCapture {
    address: SocketAddr,
}

impl SdrdModelReadyBatchCapture {
    pub fn new(address: SocketAddr) -> Self {
        Self { address }
    }

    pub fn cancel(
        &self,
        session_generation: u64,
        control_deadline_ms: u32,
    ) -> Result<CancelObservation, RecognitionInputError> {
        if !(100..=60_000).contains(&control_deadline_ms) {
            return Err(RecognitionInputError::new(
                "control_deadline",
                "cancel control deadline must be between 100 and 60000 ms",
            ));
        }
        let mut adapter = SdrdActionAdapter::new(
            self.address,
            Duration::from_millis(u64::from(control_deadline_ms)),
        );
        adapter
            .cancel(session_generation)
            .map_err(RecognitionInputError::from)
    }

    pub fn capture(
        &mut self,
        loaded: &LoadedRecognitionInputProfile,
        target: &RecognitionTarget,
        request_id: u64,
        session_generation: u64,
        now_unix_ms: u64,
    ) -> Result<ModelReadyBatch, RecognitionInputError> {
        validate_recognition_target(loaded, target, now_unix_ms)?;
        if request_id == 0 || session_generation == 0 {
            return Err(RecognitionInputError::new(
                "correlation",
                "request ID and session generation must be non-zero",
            ));
        }
        let timeout = Duration::from_millis(u64::from(loaded.profile.capture.control_deadline_ms));
        let mut wire = SdrdWire::connect(self.address, timeout)?;
        let hello: BatchHelloResponse = wire.request("HELLO", "")?;
        if hello.server != "p201-sdrd"
            || hello.protocol != "SDRD/1"
            || hello.mode != "controlled"
            || !hello.mutating_commands
        {
            return Err(RecognitionInputError::new(
                "controlled_mode",
                "SDRD is not the expected controlled receive-only endpoint",
            ));
        }
        let capabilities: BatchCapabilitiesResponse = wire.request("CAPABILITIES", "")?;
        if capabilities.mode != "controlled"
            || !capabilities.iio_visible
            || !capabilities.radio_control
            || !capabilities.raw_iq_capture
            || capabilities.max_capture_bytes < loaded.profile.capture.max_total_raw_bytes
            || !capabilities
                .rx_input
                .as_ref()
                .is_some_and(RxInputIdentity::is_fixed_p201_rx1)
        {
            let _: Result<BatchQuitResponse, _> = wire.request("QUIT", "");
            return Err(RecognitionInputError::new(
                "capture_capability",
                "SDRD cannot provide the bounded model-ready capture",
            ));
        }

        let mut session_started = false;
        let mut session_was_started = false;
        let execution = (|| {
            let start: BatchStartResponse =
                wire.request("START_SESSION", &session_generation.to_string())?;
            session_started = true;
            session_was_started = true;
            if start.generation != session_generation
                || start.session_generation != session_generation
                || start.session_state != "owned"
                || !start.restore_armed
                || start.rx_input != capabilities.rx_input
            {
                return Err(RecognitionInputError::new(
                    "session_start",
                    "SDRD did not arm model-ready capture restoration",
                ));
            }
            let profile_arguments = format!(
                "{session_generation} {} {} {} manual {} 1",
                target.center_hz,
                loaded.profile.rx.sample_rate_hz,
                loaded.profile.rx.rf_bandwidth_hz,
                loaded.profile.rx.gain_db
            );
            let profile: BatchProfileResponse =
                wire.request("APPLY_PROFILE", &profile_arguments)?;
            if profile.generation != session_generation
                || profile.session_generation != session_generation
                || profile.center_hz.abs_diff(target.center_hz) > 2
                || profile.sample_rate_hz != u64::from(loaded.profile.rx.sample_rate_hz)
                || profile.rf_bandwidth_hz != u64::from(loaded.profile.rx.rf_bandwidth_hz)
                || profile.gain_mode != "manual"
                || profile.hardware_gain_db != Some(loaded.profile.rx.gain_db)
                || profile.enabled_channels != 1
                || profile.rx_input != capabilities.rx_input
            {
                return Err(RecognitionInputError::new(
                    "profile_response",
                    "SDRD model-ready profile readback is inconsistent",
                ));
            }
            thread::sleep(Duration::from_millis(u64::from(
                loaded.profile.rx.settle_ms,
            )));
            let feature_id = format!("agx-model-batch-{session_generation}-{request_id}");
            if feature_id.len() >= 64 {
                return Err(RecognitionInputError::new(
                    "feature_id",
                    "derived model-ready feature ID exceeds the SDRD limit",
                ));
            }
            let capture_arguments = format!(
                "{session_generation} {} {} {feature_id} {}",
                loaded.total_complex_samples(),
                loaded.profile.capture.max_total_raw_bytes,
                loaded.profile.capture.capture_timeout_ms
            );
            let response: BatchInlineCaptureResponse =
                wire.request("CAPTURE_IQ_INLINE", &capture_arguments)?;
            if response.generation != session_generation
                || response.session_generation != session_generation
                || response.samples_captured != loaded.total_complex_samples()
                || response.bytes_transferred != loaded.profile.capture.max_total_raw_bytes
                || response.dropped_samples != 0
                || response.overflow
                || response.timeout.limit_ms != loaded.profile.capture.capture_timeout_ms
                || response.timeout.timed_out
                || !response.health.healthy
                || response.health.flags != 0
                || response.health.source != "iio_adapter"
                || response.rx_input != capabilities.rx_input
            {
                return Err(RecognitionInputError::new(
                    "capture_response",
                    "SDRD inline IQ response violates the model-ready profile",
                ));
            }
            let stop: BatchStopResponse =
                wire.request("STOP_SESSION", &session_generation.to_string())?;
            if stop.generation != session_generation
                || stop.session_generation != session_generation
                || !stop.stopped
                || !stop.restored
                || stop.rx_input != capabilities.rx_input
            {
                return Err(RecognitionInputError::new(
                    "restore_response",
                    "SDRD did not confirm model-ready capture restoration",
                ));
            }
            session_started = false;
            let quit: BatchQuitResponse = wire.request("QUIT", "")?;
            if !quit.closing {
                return Err(RecognitionInputError::new(
                    "quit_response",
                    "SDRD did not close the model-ready capture connection",
                ));
            }
            let raw_ci16_le = decode_base64(&response.iq_base64)
                .map_err(|error| RecognitionInputError::new(error.code, error.to_string()))?;
            Ok((profile, response, raw_ci16_le))
        })();

        let (profile, response, raw_ci16_le) = match execution {
            Ok(value) => value,
            Err(error) => {
                if error.code == "remote_error" && remote_error_proves_restoration(&error.message) {
                    session_started = false;
                }
                let mut restoration_failure = None;
                if session_started {
                    match wire.request::<BatchStopResponse>(
                        "STOP_SESSION",
                        &session_generation.to_string(),
                    ) {
                        Ok(stop)
                            if stop.generation == session_generation
                                && stop.session_generation == session_generation
                                && stop.stopped
                                && stop.restored
                                && stop.rx_input == capabilities.rx_input => {}
                        Ok(_) => {
                            restoration_failure = Some(
                                "SDRD stop response did not prove model-ready restoration"
                                    .to_owned(),
                            );
                        }
                        Err(stop_error) => {
                            restoration_failure = Some(format!(
                                "SDRD stop failed after model-ready capture error: {stop_error}"
                            ));
                        }
                    }
                }
                let _: Result<BatchQuitResponse, _> = wire.request("QUIT", "");
                drop(wire);
                if session_was_started {
                    match observe_restored_sdr(self.address, timeout) {
                        Ok(snapshot)
                            if snapshot.online
                                && snapshot.healthy
                                && snapshot
                                    .rx_input
                                    .as_ref()
                                    .is_some_and(RxInputIdentity::is_fixed_p201_rx1) => {}
                        Ok(_) => {
                            restoration_failure = Some(
                                "SDR is unhealthy after model-ready capture failure".to_owned(),
                            );
                        }
                        Err(observe_error) => {
                            restoration_failure = Some(format!(
                                "SDR restoration could not be observed: {observe_error}"
                            ));
                        }
                    }
                }
                if let Some(message) = restoration_failure {
                    return Err(RecognitionInputError::new(
                        "capture_restore_unverified",
                        message,
                    ));
                }
                return Err(error);
            }
        };
        let post_execution_sdr = observe_restored_sdr(self.address, timeout)?;
        if !post_execution_sdr.online
            || !post_execution_sdr.healthy
            || !post_execution_sdr
                .rx_input
                .as_ref()
                .is_some_and(RxInputIdentity::is_fixed_p201_rx1)
        {
            return Err(RecognitionInputError::new(
                "post_execution_health",
                "SDR is unhealthy after model-ready capture and restoration",
            ));
        }
        let rx_input = response
            .rx_input
            .clone()
            .ok_or_else(|| RecognitionInputError::new("rx_input", "capture identity is absent"))?;
        let capture = BatchCaptureMetadata {
            sdrd_request_id: response.request_id,
            session_generation: response.session_generation,
            sequence: response.sequence,
            center_hz: profile.center_hz,
            sample_rate_hz: loaded.profile.rx.sample_rate_hz,
            rf_bandwidth_hz: loaded.profile.rx.rf_bandwidth_hz,
            gain_db: loaded.profile.rx.gain_db,
            samples_captured: response.samples_captured,
            bytes_transferred: response.bytes_transferred,
            dropped_samples: response.dropped_samples,
            overflow: response.overflow,
            timeout: response.timeout,
            health: response.health,
            rx_input,
        };
        build_model_ready_batch(
            loaded,
            target,
            request_id,
            session_generation,
            capture,
            &raw_ci16_le,
        )
    }
}

fn observe_restored_sdr(
    address: SocketAddr,
    timeout: Duration,
) -> Result<crate::sdr::SdrSnapshot, RecognitionInputError> {
    let mut adapter = SdrdAdapter::new(address, timeout);
    adapter.observe().map_err(RecognitionInputError::from)
}

fn remote_error_proves_restoration(message: &str) -> bool {
    matches!(
        message,
        "capture_failed_restored"
            | "power_timeout_restored"
            | "power_failed_restored"
            | "apply_failed_restored"
            | "inline_transfer_failed_restored"
    )
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BatchHelloResponse {
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
struct BatchCapabilitiesResponse {
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
    #[serde(default)]
    rx_input: Option<RxInputIdentity>,
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
struct BatchStartResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    generation: u64,
    session_generation: u64,
    session_state: String,
    restore_armed: bool,
    #[serde(default)]
    rx_input: Option<RxInputIdentity>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BatchProfileResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    generation: u64,
    session_generation: u64,
    center_hz: u64,
    sample_rate_hz: u64,
    rf_bandwidth_hz: u64,
    gain_mode: String,
    hardware_gain_db: Option<i16>,
    enabled_channels: u32,
    #[serde(default)]
    rx_input: Option<RxInputIdentity>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BatchInlineCaptureResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    generation: u64,
    session_generation: u64,
    samples_captured: u64,
    bytes_transferred: u64,
    sequence: u64,
    dropped_samples: u64,
    overflow: bool,
    timeout: ExecutionTimeoutMetadata,
    health: ExecutionHealthMetadata,
    #[serde(default)]
    rx_input: Option<RxInputIdentity>,
    iq_base64: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BatchStopResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    generation: u64,
    session_generation: u64,
    stopped: bool,
    restored: bool,
    #[serde(default)]
    rx_input: Option<RxInputIdentity>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BatchQuitResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    closing: bool,
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut output = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(output, "{byte:02x}");
    }
    output
}

fn require_text(
    value: &str,
    maximum_bytes: usize,
    field: &'static str,
) -> Result<(), RecognitionInputError> {
    if value.is_empty()
        || value.len() > maximum_bytes
        || value.chars().any(|character| character.is_control())
    {
        return Err(RecognitionInputError::new(
            field,
            format!("{field} is empty, oversized or contains control characters"),
        ));
    }
    Ok(())
}

fn require_sha256(value: &str, field: &'static str) -> Result<(), RecognitionInputError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(RecognitionInputError::new(
            field,
            format!("{field} must be a lowercase SHA-256"),
        ));
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecognitionInputError {
    pub code: &'static str,
    pub message: String,
}

impl RecognitionInputError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    fn io(code: &'static str, error: std::io::Error) -> Self {
        Self::new(code, error.to_string())
    }

    fn protocol(code: &'static str, error: serde_json::Error) -> Self {
        Self::new(code, error.to_string())
    }
}

impl fmt::Display for RecognitionInputError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)
    }
}

impl Error for RecognitionInputError {}

impl From<crate::sdr::SdrError> for RecognitionInputError {
    fn from(error: crate::sdr::SdrError) -> Self {
        Self::new(error.code, error.message)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::execution::{ExecutionHealthMetadata, ExecutionTimeoutMetadata};
    use crate::sdr::RxInputIdentity;
    use crate::sweep::{SpectralSummary, SweepPoint, SPECTRAL_SUMMARY_SCHEMA_VERSION};
    use std::io::{BufRead, BufReader, Write};
    use std::net::TcpListener;

    fn repository_root() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
    }

    fn profile() -> LoadedRecognitionInputProfile {
        let root = repository_root();
        load_recognition_input_profile(
            &root,
            &root.join(
                "jetson-agx/sdrharness/config/amc/rml2018a-d8-current.integration-profile.json",
            ),
        )
        .unwrap()
    }

    fn point() -> SweepPoint {
        SweepPoint {
            point_index: 0,
            request_id: 11,
            session_generation: 9,
            requested_center_hz: 433_920_000,
            actual_center_hz: 433_920_000,
            sample_rate_hz: 2_100_000,
            rf_bandwidth_hz: 1_500_000,
            sequence: 17,
            dropped_samples: 0,
            overflow: false,
            captured_samples: 4_096,
            band_power_dbfs: -30.0,
            spectral: SpectralSummary {
                schema_version: SPECTRAL_SUMMARY_SCHEMA_VERSION,
                algorithm_id: "agx_welch_hann_dc_reject_obw99_v1".to_owned(),
                fft_size: 1_024,
                segment_count: 4,
                bin_width_hz: 2_100_000.0 / 1_024.0,
                peak_frequency_hz: 433_920_000,
                peak_power_dbfs: -30.0,
                noise_floor_dbfs: -50.0,
                measured_snr_db: 20.0,
                estimated_center_hz: 433_920_000,
                occupied_start_hz: 433_670_000,
                occupied_stop_hz: 434_170_000,
                occupied_bandwidth_hz: 500_000,
            },
            clipped_samples: 0,
            status_flags: 0,
            elapsed_us: 4_000,
            timeout: ExecutionTimeoutMetadata {
                limit_ms: 1_000,
                elapsed_us: 4_000,
                timed_out: false,
            },
            health: ExecutionHealthMetadata {
                healthy: true,
                flags: 0,
                source: "iio_adapter".to_owned(),
            },
            rx_input: RxInputIdentity::fixed_p201_rx1_fixture(),
        }
    }

    fn target() -> RecognitionTarget {
        let report = SweepReport {
            sweep_id: "inspect-11".to_owned(),
            session_generation: 9,
            backend: "replay".to_owned(),
            backend_version: 1,
            estimated_duration_ms: 100,
            elapsed_ms: 80,
            noise_floor_dbfs: -50.0,
            points: vec![point()],
            candidates: Vec::new(),
            dataset: None,
        };
        RecognitionTarget::from_inspection(
            &CandidateSummary {
                id: "candidate-1".to_owned(),
                center_hz: 433_920_000,
                bandwidth_hz: 500_000,
                peak_dbfs: -30.0,
                snr_db: 20.0,
                age_ms: 0,
            },
            &report,
            1_000_000,
            50,
        )
        .unwrap()
    }

    fn raw_fixture(profile: &LoadedRecognitionInputProfile) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(profile.profile.capture.max_total_raw_bytes as usize);
        for index in 0..profile.total_complex_samples() {
            let i = (((index * 37 + 11) % 1_901) as i16) - 950;
            let q = (((index * 53 + 7) % 1_799) as i16) - 899;
            bytes.extend_from_slice(&i.to_le_bytes());
            bytes.extend_from_slice(&q.to_le_bytes());
        }
        bytes
    }

    fn base64(bytes: &[u8]) -> String {
        const ALPHABET: &[u8; 64] =
            b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        let mut output = String::new();
        for chunk in bytes.chunks(3) {
            let first = u32::from(chunk[0]);
            let second = u32::from(*chunk.get(1).unwrap_or(&0));
            let third = u32::from(*chunk.get(2).unwrap_or(&0));
            let packed = (first << 16) | (second << 8) | third;
            output.push(ALPHABET[((packed >> 18) & 0x3f) as usize] as char);
            output.push(ALPHABET[((packed >> 12) & 0x3f) as usize] as char);
            output.push(if chunk.len() > 1 {
                ALPHABET[((packed >> 6) & 0x3f) as usize] as char
            } else {
                '='
            });
            output.push(if chunk.len() > 2 {
                ALPHABET[(packed & 0x3f) as usize] as char
            } else {
                '='
            });
        }
        output
    }

    fn controlled_capture_server(raw: Vec<u8>) -> (SocketAddr, std::thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let identity = serde_json::to_value(RxInputIdentity::fixed_p201_rx1_fixture()).unwrap();
        let first_identity = identity.clone();
        let handle = std::thread::spawn(move || {
            let first_responses = vec![
                serde_json::json!({"schema_version":1,"request_id":1,"status":"ok","server":"p201-sdrd","protocol":"SDRD/1","mode":"controlled","mutating_commands":true}),
                serde_json::json!({"schema_version":1,"request_id":2,"status":"ok","mode":"controlled","iio_visible":true,"radio_control":true,"raw_iq_capture":true,"software_summary":true,"max_capture_bytes":67108864_u64,"rx_input":first_identity,"fpga_backend":"disabled","fpga_identity_valid":false,"fpga_summary_version":0,"fpga_abi_version":0,"fpga_capability":0,"fpga_aggregate":false}),
                serde_json::json!({"schema_version":1,"request_id":3,"status":"ok","generation":12,"session_generation":12,"session_state":"owned","restore_armed":true,"rx_input":identity}),
                serde_json::json!({"schema_version":1,"request_id":4,"status":"ok","generation":12,"session_generation":12,"center_hz":433920000_u64,"sample_rate_hz":2100000,"rf_bandwidth_hz":1500000,"gain_mode":"manual","hardware_gain_db":50,"enabled_channels":1,"rx_input":identity}),
                serde_json::json!({"schema_version":1,"request_id":5,"status":"ok","generation":12,"session_generation":12,"samples_captured":4096,"bytes_transferred":16384,"sequence":31,"dropped_samples":0,"overflow":false,"timeout":{"limit_ms":1000,"elapsed_us":5000,"timed_out":false},"health":{"healthy":true,"flags":0,"source":"iio_adapter"},"rx_input":identity,"iq_base64":base64(&raw)}),
                serde_json::json!({"schema_version":1,"request_id":6,"status":"ok","generation":12,"session_generation":12,"stopped":true,"restored":true,"rx_input":identity}),
                serde_json::json!({"schema_version":1,"request_id":7,"status":"ok","closing":true}),
            ];
            let (mut first, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(first.try_clone().unwrap());
            for (index, response) in first_responses.into_iter().enumerate() {
                let mut request = String::new();
                reader.read_line(&mut request).unwrap();
                if index == 3 {
                    assert!(request.contains(" 433920000 2100000 1500000 manual 50 1"));
                }
                if index == 4 {
                    assert!(request.contains(" 4096 16384 agx-model-batch-12-7 1000"));
                }
                writeln!(first, "{response}").unwrap();
                first.flush().unwrap();
            }

            let observe_identity =
                serde_json::to_value(RxInputIdentity::fixed_p201_rx1_fixture()).unwrap();
            let observe_responses = vec![
                serde_json::json!({"schema_version":1,"request_id":1,"status":"ok","server":"p201-sdrd","protocol":"SDRD/1","mode":"controlled","mutating_commands":true}),
                serde_json::json!({"schema_version":1,"request_id":2,"status":"ok","mode":"controlled","iio_visible":true,"radio_control":true,"raw_iq_capture":true,"software_summary":true,"max_capture_bytes":67108864_u64,"rx_input":observe_identity,"fpga_backend":"disabled","fpga_identity_valid":false,"fpga_summary_version":0,"fpga_abi_version":0,"fpga_capability":0,"fpga_aggregate":false}),
                serde_json::json!({"schema_version":1,"request_id":3,"status":"ok","healthy":true,"health_flags":0,"iio_phy_visible":true,"iio_rx_visible":true,"rx_input":observe_identity,"fpga_configured":false,"fpga_mapped":false,"fpga_identity_valid":false,"session_faulted":false}),
                serde_json::json!({"schema_version":1,"request_id":4,"status":"ok","closing":true}),
            ];
            let (mut observe, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(observe.try_clone().unwrap());
            for response in observe_responses {
                let mut request = String::new();
                reader.read_line(&mut request).unwrap();
                writeln!(observe, "{response}").unwrap();
                observe.flush().unwrap();
            }
        });
        (address, handle)
    }

    fn capture(
        profile: &LoadedRecognitionInputProfile,
        target: &RecognitionTarget,
    ) -> BatchCaptureMetadata {
        BatchCaptureMetadata {
            sdrd_request_id: 5,
            session_generation: 12,
            sequence: 31,
            center_hz: target.center_hz,
            sample_rate_hz: profile.profile.rx.sample_rate_hz,
            rf_bandwidth_hz: profile.profile.rx.rf_bandwidth_hz,
            gain_db: profile.profile.rx.gain_db,
            samples_captured: profile.total_complex_samples(),
            bytes_transferred: profile.profile.capture.max_total_raw_bytes,
            dropped_samples: 0,
            overflow: false,
            timeout: ExecutionTimeoutMetadata {
                limit_ms: profile.profile.capture.capture_timeout_ms,
                elapsed_us: 5_000,
                timed_out: false,
            },
            health: ExecutionHealthMetadata {
                healthy: true,
                flags: 0,
                source: "iio_adapter".to_owned(),
            },
            rx_input: target.rx_input.clone(),
        }
    }

    #[test]
    fn loads_current_profile_as_integration_only() {
        let loaded = profile();
        assert!(!loaded.production_ready());
        assert_eq!(loaded.total_complex_samples(), 4_096);
        assert_eq!(loaded.profile.capture.max_total_raw_bytes, 16_384);
        assert_eq!(loaded.profile.capture.max_total_model_bytes, 32_768);
        let root = repository_root();
        assert!(load_recognition_input_profile(
            &root,
            Path::new(
                "jetson-agx/sdrharness/config/amc/rml2018a-d8-current.integration-profile.json"
            ),
        )
        .is_ok());
    }

    #[test]
    fn target_requires_fresh_healthy_inspection() {
        let loaded = profile();
        let target = target();
        validate_recognition_target(&loaded, &target, 1_004_999).unwrap();
        assert_eq!(
            validate_recognition_target(&loaded, &target, 1_005_001)
                .unwrap_err()
                .code,
            "target_ineligible"
        );
        let mut inconsistent = target;
        inconsistent.estimated_snr_db += 1.0;
        assert_eq!(
            validate_recognition_target(&loaded, &inconsistent, 1_000_001)
                .unwrap_err()
                .code,
            "target_ineligible"
        );
    }

    #[test]
    fn model_ready_batch_is_byte_reproducible() {
        let loaded = profile();
        let target = target();
        let raw = raw_fixture(&loaded);
        let fixture: serde_json::Value = serde_json::from_slice(
            &fs::read(repository_root().join(
                "raspberry-pi/sdr-agent/controller/tests/fixtures/model-ready-batch-v1.json",
            ))
            .unwrap(),
        )
        .unwrap();
        let batch =
            build_model_ready_batch(&loaded, &target, 7, 12, capture(&loaded, &target), &raw)
                .unwrap();
        assert_eq!(raw.len() as u64, fixture["raw_bytes"].as_u64().unwrap());
        assert_eq!(
            batch.model_bytes.len() as u64,
            fixture["model_bytes"].as_u64().unwrap()
        );
        assert_eq!(batch.summary.windows.len(), 4);
        assert_eq!(
            batch.summary.model_bytes_sha256,
            sha256_hex(&batch.model_bytes)
        );
        assert_eq!(sha256_hex(&raw), fixture["raw_sha256"].as_str().unwrap());
        assert_eq!(
            batch.summary.model_bytes_sha256,
            fixture["model_bytes_sha256"].as_str().unwrap()
        );
        assert_eq!(
            batch.summary.profile_sha256,
            fixture["profile_sha256"].as_str().unwrap()
        );
        assert_eq!(
            batch.summary.preprocess_sha256,
            fixture["preprocess_sha256"].as_str().unwrap()
        );
    }

    #[test]
    fn clipped_window_is_rejected() {
        let loaded = profile();
        let target = target();
        let mut raw = raw_fixture(&loaded);
        raw[..2].copy_from_slice(&2_047_i16.to_le_bytes());
        assert_eq!(
            build_model_ready_batch(&loaded, &target, 7, 12, capture(&loaded, &target), &raw,)
                .unwrap_err()
                .code,
            "raw_clipping"
        );
    }

    #[test]
    fn sdrd_capture_builds_one_contiguous_four_window_batch_and_restores() {
        let loaded = profile();
        let target = target();
        let raw = raw_fixture(&loaded);
        let (address, server) = controlled_capture_server(raw);
        let mut capture = SdrdModelReadyBatchCapture::new(address);
        let batch = capture.capture(&loaded, &target, 7, 12, 1_000_001).unwrap();
        assert_eq!(batch.summary.window_count, 4);
        assert_eq!(batch.summary.capture.sequence, 31);
        assert_eq!(
            batch.summary.model_bytes_sha256,
            "30a315ea74bbb39719e58498651f9e54e24d28129e10367d01dc3a602a1275df"
        );
        server.join().unwrap();
    }

    #[test]
    fn direct_cancel_uses_the_existing_independent_sdrd_path() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = String::new();
            BufReader::new(stream.try_clone().unwrap())
                .read_line(&mut request)
                .unwrap();
            assert_eq!(request, "SDRD/1 CANCEL_SESSION 1 12\n");
            stream
                .write_all(b"{\"schema_version\":1,\"request_id\":1,\"status\":\"ok\",\"generation\":12,\"session_generation\":12,\"cancel_requested\":true}\n")
                .unwrap();
        });
        let capture = SdrdModelReadyBatchCapture::new(address);
        assert!(capture.cancel(12, 1_000).unwrap().cancel_requested);
        server.join().unwrap();
    }

    #[test]
    fn restored_capture_error_is_observed_without_a_stale_stop() {
        let loaded = profile();
        let target = target();
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let identity = serde_json::to_value(RxInputIdentity::fixed_p201_rx1_fixture()).unwrap();
            let responses = vec![
                serde_json::json!({"schema_version":1,"request_id":1,"status":"ok","server":"p201-sdrd","protocol":"SDRD/1","mode":"controlled","mutating_commands":true}),
                serde_json::json!({"schema_version":1,"request_id":2,"status":"ok","mode":"controlled","iio_visible":true,"radio_control":true,"raw_iq_capture":true,"software_summary":true,"max_capture_bytes":67108864_u64,"rx_input":identity,"fpga_backend":"disabled","fpga_identity_valid":false,"fpga_summary_version":0,"fpga_abi_version":0,"fpga_capability":0,"fpga_aggregate":false}),
                serde_json::json!({"schema_version":1,"request_id":3,"status":"ok","generation":12,"session_generation":12,"session_state":"owned","restore_armed":true,"rx_input":identity}),
                serde_json::json!({"schema_version":1,"request_id":4,"status":"ok","generation":12,"session_generation":12,"center_hz":433920000_u64,"sample_rate_hz":2100000,"rf_bandwidth_hz":1500000,"gain_mode":"manual","hardware_gain_db":50,"enabled_channels":1,"rx_input":identity}),
                serde_json::json!({"schema_version":1,"request_id":5,"status":"error","error":"capture_failed_restored","generation":12,"session_generation":12,"sequence":32,"dropped_samples":0,"overflow":false,"timeout":{"limit_ms":1000,"elapsed_us":1001,"timed_out":true},"health":{"healthy":false,"flags":4,"source":"iio_adapter"}}),
                serde_json::json!({"schema_version":1,"request_id":6,"status":"ok","closing":true}),
            ];
            let (mut stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            for (index, response) in responses.into_iter().enumerate() {
                let mut request = String::new();
                reader.read_line(&mut request).unwrap();
                if index == 5 {
                    assert_eq!(request, "SDRD/1 QUIT 6\n");
                }
                writeln!(stream, "{response}").unwrap();
                stream.flush().unwrap();
            }

            let identity = serde_json::to_value(RxInputIdentity::fixed_p201_rx1_fixture()).unwrap();
            let observe_responses = vec![
                serde_json::json!({"schema_version":1,"request_id":1,"status":"ok","server":"p201-sdrd","protocol":"SDRD/1","mode":"controlled","mutating_commands":true}),
                serde_json::json!({"schema_version":1,"request_id":2,"status":"ok","mode":"controlled","iio_visible":true,"radio_control":true,"raw_iq_capture":true,"software_summary":true,"max_capture_bytes":67108864_u64,"rx_input":identity,"fpga_backend":"disabled","fpga_identity_valid":false,"fpga_summary_version":0,"fpga_abi_version":0,"fpga_capability":0,"fpga_aggregate":false}),
                serde_json::json!({"schema_version":1,"request_id":3,"status":"ok","healthy":true,"health_flags":0,"iio_phy_visible":true,"iio_rx_visible":true,"rx_input":identity,"fpga_configured":false,"fpga_mapped":false,"fpga_identity_valid":false,"session_faulted":false}),
                serde_json::json!({"schema_version":1,"request_id":4,"status":"ok","closing":true}),
            ];
            let (mut observe, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(observe.try_clone().unwrap());
            for response in observe_responses {
                let mut request = String::new();
                reader.read_line(&mut request).unwrap();
                writeln!(observe, "{response}").unwrap();
                observe.flush().unwrap();
            }
        });
        let mut capture = SdrdModelReadyBatchCapture::new(address);
        let error = capture
            .capture(&loaded, &target, 7, 12, 1_000_001)
            .unwrap_err();
        assert_eq!(error.code, "remote_error");
        assert_eq!(error.message, "capture_failed_restored");
        server.join().unwrap();
    }
}
