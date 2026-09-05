use crate::recognition_input::{
    sha256_hex, LoadedRecognitionInputProfile, ModelReadyBatch, ModelReadyBatchSummary,
    ProfileAdmission,
};
use crate::recognizer::{
    BoundedIqRef, IqFileRef, IqLayout, IqNormalization, IqSampleFormat, LocalRecognizer,
    RecognitionOutput, RecognitionRequest, RecognizerError, RfV1WindowContract,
    RECOGNIZER_PROTOCOL_VERSION,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;
use std::fs::{self, DirBuilder, OpenOptions};
use std::io::{self, Write};
use std::os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};

pub const INTEGRATION_BATCH_RECOGNITION_SCHEMA_VERSION: u16 = 1;

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IntegrationWindowRecognition {
    pub window_index: u16,
    pub worker_request_id: u64,
    pub output_offset_bytes: u64,
    pub output_length_bytes: u64,
    pub recognition: RecognitionOutput,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IntegrationVoteSummary {
    pub method: String,
    pub top1_label: String,
    pub top1_vote_count: u16,
    pub window_count: u16,
    pub agreement_ratio: f32,
    pub mean_voter_confidence: f32,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IntegrationBatchRecognitionReport {
    pub schema_version: u16,
    pub status: String,
    pub admission: ProfileAdmission,
    pub production_enabled: bool,
    pub production_recognizer_available: bool,
    pub result_semantics: String,
    pub batch: ModelReadyBatchSummary,
    pub windows: Vec<IntegrationWindowRecognition>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub vote: Option<IntegrationVoteSummary>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mean_logit: Option<MeanLogitSummary>,
    pub transient_iq_removed: bool,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MeanLogitSummary {
    pub method: String,
    pub numeric_class_id: usize,
    pub mean_logits: Vec<f64>,
    pub probabilities: Vec<f64>,
    pub window_agreement: f64,
    pub calibrated: bool,
    pub display_names_status: String,
}

pub struct IntegrationBatchRecognitionEngine<R> {
    recognizer: R,
    spool_root: PathBuf,
}

impl<R: LocalRecognizer> IntegrationBatchRecognitionEngine<R> {
    pub fn new(recognizer: R, spool_root: impl Into<PathBuf>) -> Self {
        Self {
            recognizer,
            spool_root: spool_root.into(),
        }
    }

    pub fn run(
        &mut self,
        loaded: &LoadedRecognitionInputProfile,
        batch: ModelReadyBatch,
    ) -> Result<IntegrationBatchRecognitionReport, BatchRecognitionError> {
        self.run_with_cancel(loaded, batch, || false)
    }

    /// Cancellation discards in-flight replies and removes the spool before return.
    /// LocalRecognizer must finish within its bounded request deadline.
    pub fn run_with_cancel(
        &mut self,
        loaded: &LoadedRecognitionInputProfile,
        batch: ModelReadyBatch,
        cancelled: impl Fn() -> bool,
    ) -> Result<IntegrationBatchRecognitionReport, BatchRecognitionError> {
        validate_integration_batch(loaded, &batch)?;
        let spool_root = prepare_batch_spool(&self.spool_root, batch.summary.model_bytes)?;
        let spool_path = spool_root.join(format!(
            "recognition-batch-{}-{}.f32",
            batch.summary.session_generation, batch.summary.request_id
        ));
        let mut transient = TransientBatchFile::create(spool_path, &batch.model_bytes)?;
        let path = transient.path().to_string_lossy().into_owned();
        let mut windows = Vec::with_capacity(batch.summary.windows.len());

        let dispatch = (|| {
            for quality in &batch.summary.windows {
                if cancelled() {
                    return Err(BatchRecognitionError::new(
                        "cancelled",
                        "batch recognition cancelled",
                    ));
                }
                let worker_request_id = batch
                    .summary
                    .request_id
                    .checked_add(u64::from(quality.window_index))
                    .ok_or_else(|| {
                        BatchRecognitionError::new(
                            "worker_request_id",
                            "per-window recognizer request ID overflow",
                        )
                    })?;
                let request = RecognitionRequest {
                    rf_v1: loaded.is_rf_v1().then(|| RfV1WindowContract {
                        profile_sha256: loaded.manifest_sha256.clone(),
                        preprocess_sha256: loaded.profile.preprocess.spec_sha256.clone(),
                        checkpoint_sha256: loaded.profile.model.model_sha256.clone(),
                        batch_sha256: batch.summary.model_bytes_sha256.clone(),
                        batch_request_id: batch.summary.request_id,
                        source_sweep_id: batch.summary.source_sweep_id.clone(),
                        source_request_id: batch.summary.source_request_id,
                        source_session_generation: batch.summary.source_session_generation,
                        source_sequence: batch.summary.source_sequence,
                        capture_request_id: batch.summary.capture.sdrd_request_id,
                        capture_sequence: batch.summary.capture.sequence,
                        window_index: quality.window_index,
                    }),
                    protocol_version: RECOGNIZER_PROTOCOL_VERSION,
                    request_id: worker_request_id,
                    session_generation: batch.summary.session_generation,
                    candidate_id: batch.summary.candidate_id.clone(),
                    iq: BoundedIqRef {
                        storage: IqFileRef {
                            path: path.clone(),
                            offset_bytes: quality.output_offset_bytes,
                            length_bytes: quality.output_length_bytes,
                        },
                        sample_format: IqSampleFormat::F32Le,
                        layout: IqLayout::PlanarIq,
                        normalization: if loaded.is_rf_v1() {
                            IqNormalization::CaptureUnitRms
                        } else {
                            IqNormalization::UnitRms
                        },
                        samples_per_channel: batch.summary.samples_per_window,
                        sample_rate_hz: batch.summary.sample_rate_hz,
                        center_hz: batch.summary.center_hz,
                    },
                    max_latency_ms: loaded.profile.capture.model_deadline_ms,
                };
                let recognition = self.recognizer.classify(&request)?;
                if cancelled() {
                    return Err(BatchRecognitionError::new(
                        "cancelled",
                        "late result discarded after cancellation",
                    ));
                }
                crate::recognizer::validate_output(&request, &recognition)?;
                if recognition.backend.model_id != loaded.profile.model.model_id
                    || recognition.backend.model_sha256 != loaded.profile.model.model_sha256
                {
                    return Err(BatchRecognitionError::new(
                        "model_identity",
                        "recognizer output does not match the integration profile checkpoint",
                    ));
                }
                windows.push(IntegrationWindowRecognition {
                    window_index: quality.window_index,
                    worker_request_id,
                    output_offset_bytes: quality.output_offset_bytes,
                    output_length_bytes: quality.output_length_bytes,
                    recognition,
                });
            }

            Ok(())
        })();
        // Explicit cleanup on both outcomes: never hide a failed unlink in Drop.
        transient.remove()?;
        dispatch?;
        let (vote, mean_logit) = if loaded.is_rf_v1() {
            (None, Some(mean_logit_summary(&windows)?))
        } else {
            (Some(integration_vote(&windows)?), None)
        };
        Ok(IntegrationBatchRecognitionReport {
            schema_version: INTEGRATION_BATCH_RECOGNITION_SCHEMA_VERSION,
            status: "ok".to_owned(),
            admission: ProfileAdmission::IntegrationOnly,
            production_enabled: false,
            production_recognizer_available: false,
            result_semantics:
                "unlabeled per-window predictions are integration evidence, not ground truth"
                    .to_owned(),
            batch: batch.summary,
            windows,
            vote,
            mean_logit,
            transient_iq_removed: true,
        })
    }
}

fn validate_integration_batch(
    loaded: &LoadedRecognitionInputProfile,
    batch: &ModelReadyBatch,
) -> Result<(), BatchRecognitionError> {
    if loaded.profile.admission != ProfileAdmission::IntegrationOnly
        || loaded.profile.production_enabled
        || loaded.production_ready()
        || batch.summary.profile_admission != ProfileAdmission::IntegrationOnly
    {
        return Err(BatchRecognitionError::new(
            "admission",
            "the temporary batch engine accepts integration-only profiles",
        ));
    }
    if batch.summary.schema_version != 1
        || batch.summary.request_id == 0
        || batch.summary.session_generation == 0
        || batch.summary.capture.session_generation != batch.summary.session_generation
        || !batch.summary.capture.rx_input.is_fixed_p201_rx1()
        || batch.summary.source_request_id == 0
        || batch.summary.source_session_generation == 0
        || batch.summary.source_sequence == 0
        || batch.summary.source_sweep_id.is_empty()
        || batch.summary.raw_bytes != loaded.profile.capture.max_total_raw_bytes
        || batch.summary.profile_id != loaded.profile.profile_id
        || batch.summary.profile_sha256 != loaded.manifest_sha256
        || batch.summary.preprocess_id != loaded.profile.preprocess.preprocess_id
        || batch.summary.preprocess_sha256 != loaded.profile.preprocess.spec_sha256
        || batch.summary.window_count != loaded.profile.capture.window_count
        || batch.summary.samples_per_window != loaded.profile.capture.samples_per_window
        || batch.summary.sample_rate_hz != loaded.profile.rx.sample_rate_hz
        || batch.summary.model_bytes != loaded.profile.capture.max_total_model_bytes
        || batch.model_bytes.len() as u64 != batch.summary.model_bytes
        || sha256_hex(&batch.model_bytes) != batch.summary.model_bytes_sha256
        || batch.summary.windows.len() != usize::from(batch.summary.window_count)
    {
        return Err(BatchRecognitionError::new(
            "batch_contract",
            "model-ready batch does not match the loaded integration profile",
        ));
    }
    let expected_window_bytes = u64::from(batch.summary.samples_per_window) * 2 * 4;
    let mut expected_offset = 0_u64;
    for (expected_index, window) in batch.summary.windows.iter().enumerate() {
        if usize::from(window.window_index) != expected_index
            || window.output_offset_bytes != expected_offset
            || window.output_length_bytes != expected_window_bytes
        {
            return Err(BatchRecognitionError::new(
                "batch_offsets",
                "model-ready window offsets are not contiguous and exact",
            ));
        }
        expected_offset = expected_offset
            .checked_add(window.output_length_bytes)
            .ok_or_else(|| BatchRecognitionError::new("batch_offsets", "window range overflow"))?;
    }
    if expected_offset != batch.summary.model_bytes {
        return Err(BatchRecognitionError::new(
            "batch_offsets",
            "model-ready window ranges do not cover the batch exactly",
        ));
    }
    Ok(())
}

pub(crate) fn mean_logit_summary(
    windows: &[IntegrationWindowRecognition],
) -> Result<MeanLogitSummary, BatchRecognitionError> {
    if windows.len() != 4 {
        return Err(BatchRecognitionError::new(
            "logit_count",
            "exactly four full-logit windows required",
        ));
    }
    let mut mean_logits = vec![0.0_f64; 24];
    let mut window_top1 = Vec::new();
    for window in windows {
        let output = window
            .recognition
            .rf_v1
            .as_ref()
            .ok_or_else(|| BatchRecognitionError::new("logits", "missing full logits"))?;
        if output.logits.len() != 24 || output.logits.iter().any(|v| !v.is_finite()) {
            return Err(BatchRecognitionError::new(
                "logits",
                "expected 24 finite logits",
            ));
        }
        let mut top = 0;
        for (index, value) in output.logits.iter().enumerate() {
            mean_logits[index] += f64::from(*value) / 4.0;
            if *value > output.logits[top] {
                top = index;
            }
        }
        window_top1.push(top);
    }
    let mut numeric_class_id = 0;
    for index in 1..24 {
        if mean_logits[index] > mean_logits[numeric_class_id] {
            numeric_class_id = index;
        }
    }
    let mut probabilities: Vec<f64> = mean_logits
        .iter()
        .map(|v| (v - mean_logits[numeric_class_id]).exp())
        .collect();
    let sum: f64 = probabilities.iter().sum();
    probabilities.iter_mut().for_each(|v| *v /= sum);
    Ok(MeanLogitSummary {
        method: "float64_arithmetic_mean_logits_then_softmax".to_owned(),
        numeric_class_id,
        mean_logits,
        probabilities,
        window_agreement: window_top1
            .iter()
            .filter(|v| **v == numeric_class_id)
            .count() as f64
            / 4.0,
        calibrated: false,
        display_names_status: "provisional".to_owned(),
    })
}

fn integration_vote(
    windows: &[IntegrationWindowRecognition],
) -> Result<IntegrationVoteSummary, BatchRecognitionError> {
    let mut votes: BTreeMap<&str, (u16, f64)> = BTreeMap::new();
    for window in windows {
        let entry = votes
            .entry(window.recognition.label.as_str())
            .or_insert((0, 0.0));
        entry.0 = entry.0.saturating_add(1);
        entry.1 += f64::from(window.recognition.confidence);
    }
    let (top1_label, (top1_vote_count, confidence_sum)) = votes
        .into_iter()
        .max_by(|(left_label, left), (right_label, right)| {
            left.0
                .cmp(&right.0)
                .then_with(|| {
                    left.1
                        .partial_cmp(&right.1)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .then_with(|| right_label.cmp(left_label))
        })
        .ok_or_else(|| BatchRecognitionError::new("empty_batch", "no window result exists"))?;
    let window_count = u16::try_from(windows.len())
        .map_err(|_| BatchRecognitionError::new("window_count", "too many window results"))?;
    Ok(IntegrationVoteSummary {
        method: "top1_majority_vote_integration_only_v1".to_owned(),
        top1_label: top1_label.to_owned(),
        top1_vote_count,
        window_count,
        agreement_ratio: f32::from(top1_vote_count) / f32::from(window_count),
        mean_voter_confidence: (confidence_sum / f64::from(top1_vote_count)) as f32,
    })
}

pub fn prepare_batch_spool(
    path: &Path,
    required_bytes: u64,
) -> Result<PathBuf, BatchRecognitionError> {
    let root = ensure_private_spool_root(path)?;
    let available = crate::sweep::available_storage_bytes(&root)
        .map_err(|error| BatchRecognitionError::new("spool_space", error.to_string()))?;
    if required_bytes == 0 || available < required_bytes {
        return Err(BatchRecognitionError::new(
            "spool_space",
            "insufficient space for exact finite batch",
        ));
    }
    eprintln!(
        "validated_batch_spool path={} max_bytes={} available_bytes={}",
        root.display(),
        required_bytes,
        available
    );
    Ok(root)
}

fn ensure_private_spool_root(path: &Path) -> Result<PathBuf, BatchRecognitionError> {
    if !path.is_absolute() {
        return Err(BatchRecognitionError::new(
            "spool_root",
            "recognition spool root must be absolute",
        ));
    }
    if !path.exists() {
        let mut builder = DirBuilder::new();
        builder.mode(0o700);
        if let Err(error) = builder.create(path) {
            if error.kind() != io::ErrorKind::AlreadyExists {
                return Err(BatchRecognitionError::io("create_spool_root", error));
            }
        }
    }
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| BatchRecognitionError::io("stat_spool_root", error))?;
    // SAFETY: geteuid has no preconditions and does not mutate process state.
    let effective_uid = unsafe { libc::geteuid() };
    if metadata.file_type().is_symlink()
        || !metadata.is_dir()
        || metadata.uid() != effective_uid
        || metadata.mode() & 0o077 != 0
    {
        return Err(BatchRecognitionError::new(
            "spool_root",
            "spool root must be a real private directory owned by this user",
        ));
    }
    fs::canonicalize(path).map_err(|error| BatchRecognitionError::io("canonicalize_spool", error))
}

struct TransientBatchFile {
    path: PathBuf,
    removed: bool,
}

impl TransientBatchFile {
    fn create(path: PathBuf, bytes: &[u8]) -> Result<Self, BatchRecognitionError> {
        if bytes.is_empty() {
            return Err(BatchRecognitionError::new(
                "spool_shape",
                "model-ready batch is empty",
            ));
        }
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&path)
            .map_err(|error| BatchRecognitionError::io("create_spool_file", error))?;
        if let Err(error) = file.write_all(bytes).and_then(|_| file.flush()) {
            fs::remove_file(&path).map_err(|cleanup| {
                BatchRecognitionError::io("remove_partial_spool_file", cleanup)
            })?;
            return Err(BatchRecognitionError::io("write_spool_file", error));
        }
        Ok(Self {
            path,
            removed: false,
        })
    }

    fn path(&self) -> &Path {
        &self.path
    }

    fn remove(&mut self) -> Result<(), BatchRecognitionError> {
        fs::remove_file(&self.path)
            .map_err(|error| BatchRecognitionError::io("remove_spool_file", error))?;
        self.removed = true;
        Ok(())
    }
}

impl Drop for TransientBatchFile {
    fn drop(&mut self) {
        if !self.removed {
            let _ = fs::remove_file(&self.path);
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BatchRecognitionError {
    pub code: &'static str,
    pub message: String,
}

impl BatchRecognitionError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    fn io(code: &'static str, error: io::Error) -> Self {
        Self::new(code, error.to_string())
    }
}

impl From<RecognizerError> for BatchRecognitionError {
    fn from(error: RecognizerError) -> Self {
        Self::new(error.code, error.message)
    }
}

impl fmt::Display for BatchRecognitionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)
    }
}

impl Error for BatchRecognitionError {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::execution::{ExecutionHealthMetadata, ExecutionTimeoutMetadata};
    use crate::recognition_input::{
        build_model_ready_batch, load_recognition_input_profile, BatchCaptureMetadata,
        RecognitionTarget,
    };
    use crate::recognizer::{RecognitionTiming, RecognizerBackend, ReplayRecognizerAdapter};
    use crate::sdr::RxInputIdentity;
    use std::time::{SystemTime, UNIX_EPOCH};

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

    fn batch(profile: &LoadedRecognitionInputProfile) -> ModelReadyBatch {
        let target = RecognitionTarget {
            schema_version: 1,
            candidate_id: "candidate-1".to_owned(),
            source_sweep_id: "inspect-1".to_owned(),
            source_session_generation: 12,
            source_request_id: 4,
            source_sequence: 30,
            observed_at_unix_ms: 1,
            center_hz: 433_920_000,
            occupied_bandwidth_hz: 500_000,
            inspection_gain_db: 50,
            peak_dbfs: -30.0,
            noise_floor_dbfs: -50.0,
            estimated_snr_db: 20.0,
            clipped_samples: 0,
            dropped_samples: 0,
            overflow: false,
            health_flags: 0,
            health_source: "iio_adapter".to_owned(),
            rx_input: RxInputIdentity::fixed_p201_rx1_fixture(),
        };
        let capture = BatchCaptureMetadata {
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
                elapsed_us: 500,
                timed_out: false,
            },
            health: ExecutionHealthMetadata {
                healthy: true,
                flags: 0,
                source: "iio_adapter".to_owned(),
            },
            rx_input: target.rx_input.clone(),
        };
        let mut raw = Vec::with_capacity(profile.profile.capture.max_total_raw_bytes as usize);
        for index in 0..profile.total_complex_samples() {
            let i = (((index * 37 + 11) % 1_901) as i16) - 950;
            let q = (((index * 53 + 7) % 1_799) as i16) - 899;
            raw.extend_from_slice(&i.to_le_bytes());
            raw.extend_from_slice(&q.to_le_bytes());
        }
        build_model_ready_batch(profile, &target, 7, 12, capture, &raw).unwrap()
    }

    fn output(
        profile: &LoadedRecognitionInputProfile,
        label: &str,
        confidence: f32,
    ) -> RecognitionOutput {
        RecognitionOutput {
            rf_v1: None,
            candidate_id: "candidate-1".to_owned(),
            label: label.to_owned(),
            confidence,
            alternatives: Vec::new(),
            backend: RecognizerBackend {
                runtime: "test".to_owned(),
                runtime_version: "1".to_owned(),
                model_id: profile.profile.model.model_id.clone(),
                model_sha256: profile.profile.model.model_sha256.clone(),
                threads: 1,
            },
            timing: RecognitionTiming {
                map_us: 1,
                preprocess_us: 1,
                inference_us: 1,
                total_us: 3,
            },
        }
    }

    fn private_directory(label: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "sdrharness-batch-{label}-{}-{nonce}",
            std::process::id()
        ));
        let mut builder = DirBuilder::new();
        builder.mode(0o700);
        builder.create(&path).unwrap();
        path
    }

    #[test]
    fn classifies_all_contiguous_windows_and_removes_the_batch() {
        let profile = profile();
        let batch = batch(&profile);
        let recognizer = ReplayRecognizerAdapter::new([
            output(&profile, "provisional:03:test-a", 0.8),
            output(&profile, "provisional:03:test-a", 0.7),
            output(&profile, "provisional:05:test-b", 0.9),
            output(&profile, "provisional:03:test-a", 0.6),
        ]);
        let root = private_directory("success");
        let mut engine = IntegrationBatchRecognitionEngine::new(recognizer, &root);
        let report = engine.run(&profile, batch).unwrap();
        assert_eq!(report.windows.len(), 4);
        assert_eq!(
            report.vote.as_ref().unwrap().top1_label,
            "provisional:03:test-a"
        );
        assert_eq!(report.vote.as_ref().unwrap().top1_vote_count, 3);
        assert_eq!(report.vote.as_ref().unwrap().agreement_ratio, 0.75);
        assert!(!report.production_recognizer_available);
        assert!(report.transient_iq_removed);
        assert_eq!(fs::read_dir(&root).unwrap().count(), 0);
        fs::remove_dir(root).unwrap();
    }

    #[test]
    fn model_identity_failure_still_removes_the_batch() {
        let profile = profile();
        let batch = batch(&profile);
        let mut wrong = output(&profile, "provisional:03:test-a", 0.8);
        wrong.backend.model_sha256 = "0".repeat(64);
        let recognizer = ReplayRecognizerAdapter::new([wrong]);
        let root = private_directory("failure");
        let mut engine = IntegrationBatchRecognitionEngine::new(recognizer, &root);
        assert_eq!(
            engine.run(&profile, batch).unwrap_err().code,
            "model_identity"
        );
        assert_eq!(fs::read_dir(&root).unwrap().count(), 0);
        fs::remove_dir(root).unwrap();
    }
    struct LogitRecognizer {
        profile: LoadedRecognitionInputProfile,
        fault: &'static str,
        cancelled: std::rc::Rc<std::cell::Cell<bool>>,
    }

    impl LocalRecognizer for LogitRecognizer {
        fn classify(
            &mut self,
            request: &RecognitionRequest,
        ) -> Result<RecognitionOutput, RecognizerError> {
            let index = request.rf_v1.as_ref().unwrap().window_index;
            if self.fault == "worker_exit" && index == 1 {
                return Err(RecognizerError {
                    code: "connect",
                    message: "worker exited".to_owned(),
                });
            }
            let mut result = output(&self.profile, "provisional:00", 0.5);
            let mut logits = vec![0.0; 24];
            // Three votes for 0, but the full-logit mean correctly selects 1.
            if index < 3 {
                logits[0] = 1.0;
            } else {
                logits[1] = 12.0;
            }
            let mut contract = request.rf_v1.clone().unwrap();
            match self.fault {
                "profile" => contract.profile_sha256 = "0".repeat(64),
                "preprocess" => contract.preprocess_sha256 = "0".repeat(64),
                "checkpoint" => contract.checkpoint_sha256 = "0".repeat(64),
                "batch" => contract.batch_sha256 = "0".repeat(64),
                "source" => contract.source_request_id += 1,
                "order" => contract.window_index += 1,
                "short_logits" => {
                    logits.pop();
                }
                "nan" => logits[0] = f32::NAN,
                "cancel" => self.cancelled.set(true),
                _ => {}
            }
            if self.fault == "none" {
                let top = if index < 3 { 0 } else { 1 };
                result.label = format!("provisional:{top:02}");
                result.confidence = (1.0
                    / logits
                        .iter()
                        .map(|v| (f64::from(*v) - f64::from(logits[top])).exp())
                        .sum::<f64>()) as f32;
            }
            result.rf_v1 = Some(crate::recognizer::RfV1WindowOutput {
                contract,
                logits,
                request_id: request.request_id + u64::from(self.fault == "request"),
                session_generation: request.session_generation + u64::from(self.fault == "session"),
                compute: if self.fault == "precision" {
                    "fp32"
                } else {
                    "cuda_fp16_autocast"
                }
                .to_owned(),
            });
            Ok(result)
        }
    }

    #[test]
    fn rf_v1_full_logits_correlation_cancel_and_cleanup() {
        let repo = repository_root();
        let profile = load_recognition_input_profile(
            &repo,
            &repo.join("jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json"),
        )
        .unwrap();
        for fault in [
            "none",
            "worker_exit",
            "profile",
            "preprocess",
            "checkpoint",
            "batch",
            "source",
            "order",
            "short_logits",
            "nan",
            "cancel",
            "request",
            "session",
            "precision",
        ] {
            let cancelled = std::rc::Rc::new(std::cell::Cell::new(false));
            let recognizer = LogitRecognizer {
                profile: profile.clone(),
                fault,
                cancelled: cancelled.clone(),
            };
            let root = private_directory(fault);
            let mut engine = IntegrationBatchRecognitionEngine::new(recognizer, &root);
            let result = engine.run_with_cancel(&profile, batch(&profile), || cancelled.get());
            if fault == "none" {
                let report = result.unwrap();
                assert!(report.vote.is_none());
                crate::recognition_result::tests::verify_batch_result(&profile, &report);
                let mean = report.mean_logit.unwrap();
                assert_eq!(mean.numeric_class_id, 1);
                assert_eq!(mean.mean_logits[0], 0.75);
                assert_eq!(mean.mean_logits[1], 3.0);
                assert_eq!(mean.window_agreement, 0.25);
                assert!((mean.probabilities.iter().sum::<f64>() - 1.0).abs() < 1e-14);
                assert!(!mean.calibrated);
            } else {
                assert!(result.is_err(), "{fault}");
            }
            assert_eq!(fs::read_dir(&root).unwrap().count(), 0, "{fault}");
            fs::remove_dir(root).unwrap();
        }
    }

    #[test]
    fn rf_v1_rejects_reordered_batch_before_creating_spool() {
        let repo = repository_root();
        let profile = load_recognition_input_profile(
            &repo,
            &repo.join("jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json"),
        )
        .unwrap();
        let mut batch = batch(&profile);
        batch.summary.windows.swap(0, 1);
        let root = private_directory("reordered");
        let mut engine =
            IntegrationBatchRecognitionEngine::new(ReplayRecognizerAdapter::new([]), &root);
        assert_eq!(
            engine.run(&profile, batch).unwrap_err().code,
            "batch_offsets"
        );
        assert_eq!(fs::read_dir(&root).unwrap().count(), 0);
        fs::remove_dir(root).unwrap();
    }
}
