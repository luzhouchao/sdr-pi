//! AGX result contract. Worker `ok` is inference success, never admission.
use crate::batch_recognition::{mean_logit_summary, IntegrationBatchRecognitionReport};
use crate::recognition_input::{LoadedRecognitionInputProfile, ProfileAdmission};
use crate::recognizer::{
    self, BoundedIqRef, IqFileRef, IqLayout, IqNormalization, IqSampleFormat, RecognitionRequest,
    RfV1WindowContract,
};
use serde::{Deserialize, Serialize};

pub const MAX_RESULT_BYTES: usize = 64 * 1024;
pub const MAX_OBSERVATION_BYTES: usize = 4096;

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecognitionStatus {
    Classified,
    Rejected,
    Unavailable,
    Error,
}
#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NameStatus {
    Provisional,
    Verified,
    Unavailable,
}
#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CalibrationStatus {
    Uncalibrated,
    Frozen,
    Unavailable,
}
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResultReference {
    pub id: String,
    pub sha256: String,
}
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ClassIdentity {
    pub numeric_id: u16,
    pub name: Option<String>,
    pub name_status: NameStatus,
    pub name_evidence: Option<ResultReference>,
}
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResultIdentity {
    pub model_id: String,
    pub checkpoint_sha256: String,
    pub profile_id: String,
    pub profile_sha256: String,
    pub preprocess_id: String,
    pub preprocess_sha256: String,
    pub compute: String,
    pub aggregation: String,
}
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecognitionSource {
    pub sweep_id: String,
    pub request_id: u64,
    pub session_generation: u64,
    pub sequence: u64,
    pub capture_request_id: u64,
    pub capture_sequence: u64,
}
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResultQuality {
    pub window_count: u16,
    pub window_agreement: f64,
    pub clipped_samples: u64,
    pub dropped_samples: u64,
    pub overflow: bool,
    pub healthy: bool,
}
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResultTiming {
    pub capture_us: u64,
    pub worker_total_us: u64,
    pub inference_us: u64,
}
/// Hash references identify immutable decisions, not filesystem paths. Their
/// scientific admission must be verified by the future production executor.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DecisionReferences {
    pub calibration: ResultReference,
    pub rejection: ResultReference,
    pub admission: ResultReference,
}
/// Explicit allowlist: no paths, tensors, per-window outputs or full logits.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecognitionObservation {
    pub schema_version: u16,
    pub candidate_id: String,
    pub request_id: u64,
    pub session_generation: u64,
    pub observed_at_unix_ms: u64,
    pub status: RecognitionStatus,
    pub reason: Option<String>,
    pub class: Option<ClassIdentity>,
    pub calibrated_confidence: Option<f64>,
    pub calibration_status: CalibrationStatus,
    pub decision_references: Option<DecisionReferences>,
    pub identity: Option<ResultIdentity>,
    pub source: Option<RecognitionSource>,
    pub quality: Option<ResultQuality>,
    pub timing: Option<ResultTiming>,
}
/// Full internal record. The experimental report is never projected to Planner.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecognitionResult {
    pub schema_version: u16,
    pub observation: RecognitionObservation,
    pub experimental_prediction: Option<ClassIdentity>,
    pub uncalibrated_probability: Option<f64>,
    pub experimental_batch: Option<IntegrationBatchRecognitionReport>,
}
fn check(ok: bool, message: &'static str) -> Result<(), String> {
    if ok {
        Ok(())
    } else {
        Err(message.to_owned())
    }
}
fn token(s: &str, max: usize) -> bool {
    !s.is_empty()
        && s.len() <= max
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-.:".contains(&b))
}
fn hash(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
}
fn reference(r: &ResultReference) -> bool {
    token(&r.id, 64) && hash(&r.sha256)
}
impl RecognitionObservation {
    pub fn validate(&self) -> Result<(), String> {
        check(
            self.schema_version == 1
                && token(&self.candidate_id, 64)
                && self.request_id > 0
                && self.session_generation > 0
                && self.observed_at_unix_ms > 0,
            "recognition correlation",
        )?;
        if let Some(reason) = &self.reason {
            check(token(reason, 64), "recognition reason code")?;
        }
        if let Some(id) = &self.identity {
            check(
                token(&id.model_id, 128)
                    && token(&id.profile_id, 128)
                    && token(&id.preprocess_id, 128)
                    && hash(&id.checkpoint_sha256)
                    && hash(&id.profile_sha256)
                    && hash(&id.preprocess_sha256)
                    && id.compute == "cuda_fp16_autocast"
                    && id.aggregation == "float64_arithmetic_mean_logits_then_softmax",
                "recognition identity",
            )?;
        }
        if let Some(source) = &self.source {
            check(
                token(&source.sweep_id, 64)
                    && source.request_id > 0
                    && source.session_generation > 0
                    && source.sequence > 0
                    && source.capture_request_id > 0
                    && source.capture_sequence > source.sequence,
                "recognition source",
            )?;
        }
        if let Some(q) = &self.quality {
            check(
                q.window_count == 4
                    && q.window_agreement.is_finite()
                    && (0.0..=1.0).contains(&q.window_agreement)
                    && (q.window_agreement * 4.0).fract() == 0.0,
                "recognition quality",
            )?;
        }
        if let Some(t) = &self.timing {
            check(
                t.capture_us <= 60_000_000
                    && t.inference_us <= t.worker_total_us
                    && t.worker_total_us <= 120_000_000,
                "recognition timing",
            )?;
        }
        if let Some(c) = &self.class {
            check(c.numeric_id < 24, "numeric class ID")?;
            check(
                match c.name_status {
                    NameStatus::Unavailable => c.name.is_none() && c.name_evidence.is_none(),
                    NameStatus::Provisional => {
                        c.name.as_ref().map_or(true, |n| token(n, 128)) && c.name_evidence.is_none()
                    }
                    NameStatus::Verified => {
                        c.name.as_ref().is_some_and(|n| token(n, 128))
                            && c.name_evidence.as_ref().is_some_and(reference)
                    }
                },
                "class name trust",
            )?;
        }
        if let Some(c) = self.calibrated_confidence {
            check(
                c.is_finite() && (0.0..=1.0).contains(&c),
                "calibrated confidence",
            )?;
        }
        if let Some(r) = &self.decision_references {
            check(
                reference(&r.calibration) && reference(&r.rejection) && reference(&r.admission),
                "decision references",
            )?;
        }
        check(
            (self.calibration_status == CalibrationStatus::Frozen)
                == self.decision_references.is_some(),
            "calibration status/references",
        )?;
        let decided = matches!(
            self.status,
            RecognitionStatus::Classified | RecognitionStatus::Rejected
        );
        check(
            !decided
                || (self.identity.is_some()
                    && self.source.is_some()
                    && self.quality.is_some()
                    && self.timing.is_some()
                    && self.decision_references.is_some()
                    && self.calibration_status == CalibrationStatus::Frozen),
            "decision requires identity, measurements and frozen references",
        )?;
        check(
            match self.status {
                RecognitionStatus::Classified => {
                    self.class.is_some()
                        && self.calibrated_confidence.is_some()
                        && self.reason.is_none()
                        && self.quality.as_ref().is_some_and(|q| {
                            q.healthy
                                && !q.overflow
                                && q.clipped_samples == 0
                                && q.dropped_samples == 0
                        })
                }
                RecognitionStatus::Rejected => self.class.is_none() && self.reason.is_some(),
                RecognitionStatus::Unavailable | RecognitionStatus::Error => {
                    self.class.is_none()
                        && self.calibrated_confidence.is_none()
                        && self.decision_references.is_none()
                        && self.reason.is_some()
                }
            },
            "recognition status semantics",
        )?;
        check(
            serde_json::to_vec(self).map_err(|e| e.to_string())?.len() <= MAX_OBSERVATION_BYTES,
            "recognition observation bound",
        )
    }
    pub fn validate_context(
        &self,
        generation: u64,
        now_ms: u64,
        max_age_ms: u64,
    ) -> Result<(), String> {
        self.validate()?;
        check(
            self.session_generation == generation
                && self.observed_at_unix_ms <= now_ms
                && now_ms - self.observed_at_unix_ms <= max_age_ms,
            "stale recognition observation",
        )
    }
}
impl RecognitionResult {
    pub fn from_experimental_batch(
        loaded: &LoadedRecognitionInputProfile,
        report: IntegrationBatchRecognitionReport,
        observed_at_unix_ms: u64,
    ) -> Result<Self, String> {
        validate_batch(loaded, &report)?;
        let b = &report.batch;
        let mean = report.mean_logit.as_ref().ok_or("missing aggregate")?;
        let observation = RecognitionObservation {
            schema_version: 1,
            candidate_id: b.candidate_id.clone(),
            request_id: b.request_id,
            session_generation: b.session_generation,
            observed_at_unix_ms,
            status: RecognitionStatus::Unavailable,
            reason: Some("production_admission_missing".to_owned()),
            class: None,
            calibrated_confidence: None,
            calibration_status: CalibrationStatus::Uncalibrated,
            decision_references: None,
            identity: Some(ResultIdentity {
                model_id: loaded.profile.model.model_id.clone(),
                checkpoint_sha256: loaded.profile.model.model_sha256.clone(),
                profile_id: b.profile_id.clone(),
                profile_sha256: b.profile_sha256.clone(),
                preprocess_id: b.preprocess_id.clone(),
                preprocess_sha256: b.preprocess_sha256.clone(),
                compute: "cuda_fp16_autocast".to_owned(),
                aggregation: mean.method.clone(),
            }),
            source: Some(RecognitionSource {
                sweep_id: b.source_sweep_id.clone(),
                request_id: b.source_request_id,
                session_generation: b.source_session_generation,
                sequence: b.source_sequence,
                capture_request_id: b.capture.sdrd_request_id,
                capture_sequence: b.capture.sequence,
            }),
            quality: Some(ResultQuality {
                window_count: b.window_count,
                window_agreement: mean.window_agreement,
                clipped_samples: b.windows.iter().map(|w| w.clipped_samples).sum(),
                dropped_samples: b.capture.dropped_samples,
                overflow: b.capture.overflow,
                healthy: b.capture.health.healthy,
            }),
            timing: Some(ResultTiming {
                capture_us: b.capture.timeout.elapsed_us,
                worker_total_us: report
                    .windows
                    .iter()
                    .map(|w| w.recognition.timing.total_us)
                    .sum(),
                inference_us: report
                    .windows
                    .iter()
                    .map(|w| w.recognition.timing.inference_us)
                    .sum(),
            }),
        };
        observation.validate()?;
        let experimental_prediction = Some(ClassIdentity {
            numeric_id: mean.numeric_class_id as u16,
            name: None,
            name_status: NameStatus::Provisional,
            name_evidence: None,
        });
        let uncalibrated_probability = Some(mean.probabilities[mean.numeric_class_id]);
        let result = Self {
            schema_version: 1,
            observation,
            experimental_prediction,
            uncalibrated_probability,
            experimental_batch: Some(report),
        };
        check(
            serde_json::to_vec(&result)
                .map_err(|e| e.to_string())?
                .len()
                <= MAX_RESULT_BYTES,
            "recognition result bound",
        )?;
        Ok(result)
    }
    /// Revalidate imported full records; never trust stored summaries or flags.
    pub fn validate(&self, loaded: &LoadedRecognitionInputProfile) -> Result<(), String> {
        check(self.schema_version == 1, "result schema")?;
        self.observation.validate()?;
        if let Some(identity) = &self.observation.identity {
            check(
                identity.model_id == loaded.profile.model.model_id
                    && identity.checkpoint_sha256 == loaded.profile.model.model_sha256
                    && identity.profile_id == loaded.profile.profile_id
                    && identity.profile_sha256 == loaded.manifest_sha256
                    && identity.preprocess_id == loaded.profile.preprocess.preprocess_id
                    && identity.preprocess_sha256 == loaded.profile.preprocess.spec_sha256,
                "result profile identity",
            )?;
        }
        check(
            !matches!(
                self.observation.status,
                RecognitionStatus::Classified | RecognitionStatus::Rejected
            ) || loaded.production_ready(),
            "candidate profile cannot carry production decisions",
        )?;
        if let Some(batch) = &self.experimental_batch {
            let expected = Self::from_experimental_batch(
                loaded,
                batch.clone(),
                self.observation.observed_at_unix_ms,
            )?;
            check(self == &expected, "altered experimental result")?;
        } else {
            check(
                self.experimental_prediction.is_none() && self.uncalibrated_probability.is_none(),
                "prediction without experimental evidence",
            )?;
        }
        check(
            serde_json::to_vec(self).map_err(|e| e.to_string())?.len() <= MAX_RESULT_BYTES,
            "recognition result bound",
        )
    }
    pub fn planner_observation(
        &self,
        loaded: &LoadedRecognitionInputProfile,
    ) -> Result<RecognitionObservation, String> {
        self.validate(loaded)?;
        Ok(self.observation.clone())
    }
    pub fn from_json(bytes: &[u8], loaded: &LoadedRecognitionInputProfile) -> Result<Self, String> {
        check(bytes.len() <= MAX_RESULT_BYTES, "recognition result bound")?;
        let result: Self = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
        result.validate(loaded)?;
        Ok(result)
    }
}

fn validate_batch(
    loaded: &LoadedRecognitionInputProfile,
    report: &IntegrationBatchRecognitionReport,
) -> Result<(), String> {
    let b = &report.batch;
    check(
        loaded.is_rf_v1()
            && !loaded.production_ready()
            && report.schema_version == 1
            && report.status == "ok"
            && report.admission == ProfileAdmission::IntegrationOnly
            && !report.production_enabled
            && !report.production_recognizer_available
            && report.transient_iq_removed
            && report.vote.is_none()
            && report.result_semantics
                == "unlabeled per-window predictions are integration evidence, not ground truth",
        "experimental batch semantics",
    )?;
    check(
        b.schema_version == 1
            && b.profile_admission == ProfileAdmission::IntegrationOnly
            && b.profile_id == loaded.profile.profile_id
            && b.profile_sha256 == loaded.manifest_sha256
            && b.preprocess_id == loaded.profile.preprocess.preprocess_id
            && b.preprocess_sha256 == loaded.profile.preprocess.spec_sha256
            && hash(&b.model_bytes_sha256)
            && b.request_id > 0
            && b.session_generation > 0
            && b.source_session_generation > 0
            && b.window_count == 4
            && b.samples_per_window == 1024
            && b.sample_rate_hz == 2_100_000
            && b.raw_bytes == 16_384
            && b.model_bytes == 32_768
            && b.windows.len() == 4
            && report.windows.len() == 4,
        "experimental batch identity/shape",
    )?;
    let c = &b.capture;
    check(
        c.session_generation == b.session_generation
            && c.center_hz.abs_diff(b.center_hz) <= 2
            && (70_000_000..=6_000_000_000).contains(&b.center_hz)
            && c.sample_rate_hz == b.sample_rate_hz
            && c.rf_bandwidth_hz == loaded.profile.rx.rf_bandwidth_hz
            && c.gain_db == loaded.profile.rx.gain_db
            && c.samples_captured == 4096
            && c.bytes_transferred == b.raw_bytes
            && c.rx_input.is_fixed_p201_rx1()
            && c.dropped_samples == 0
            && !c.overflow
            && !c.timeout.timed_out
            && c.timeout.limit_ms == loaded.profile.capture.capture_timeout_ms
            && c.timeout.elapsed_us <= u64::from(c.timeout.limit_ms) * 1000
            && c.health.healthy
            && c.health.flags == 0
            && c.health.source == "iio_adapter",
        "experimental capture",
    )?;
    let mut normalized_power = 0.0;
    for (i, (q, w)) in b.windows.iter().zip(&report.windows).enumerate() {
        check(
            q.window_index as usize == i
                && w.window_index as usize == i
                && q.output_offset_bytes == i as u64 * 8192
                && w.output_offset_bytes == q.output_offset_bytes
                && q.output_length_bytes == 8192
                && w.output_length_bytes == 8192
                && b.request_id.checked_add(i as u64) == Some(w.worker_request_id),
            "experimental window order/range",
        )?;
        check(
            q.raw_complex_rms_adc.is_finite()
                && (0.0..=2897.0).contains(&q.raw_complex_rms_adc)
                && q.raw_rms_dbfs.is_finite()
                && (q.raw_rms_dbfs
                    - 20.0 * (q.raw_complex_rms_adc.max(f64::MIN_POSITIVE) / 2048.0).log10())
                .abs()
                    < 1e-9
                && q.raw_dc_fraction.is_finite()
                && (0.0..=1.000001).contains(&q.raw_dc_fraction)
                && q.normalization_scale.is_finite()
                && q.normalization_scale > 0.0
                && q.normalization_scale <= 1.0
                && q.normalization_scale == b.windows[0].normalization_scale
                && q.normalized_complex_rms.is_finite()
                && (0.0..=2.000001).contains(&q.normalized_complex_rms)
                && (q.raw_complex_rms_adc * q.normalization_scale - q.normalized_complex_rms).abs()
                    < 1e-6
                && q.clipped_samples == 0,
            "experimental window quality",
        )?;
        normalized_power += q.normalized_complex_rms.powi(2) / 4.0;
        let request = RecognitionRequest {
            protocol_version: 1,
            request_id: w.worker_request_id,
            session_generation: b.session_generation,
            candidate_id: b.candidate_id.clone(),
            max_latency_ms: loaded.profile.capture.model_deadline_ms,
            iq: BoundedIqRef {
                storage: IqFileRef {
                    path: String::new(),
                    offset_bytes: w.output_offset_bytes,
                    length_bytes: w.output_length_bytes,
                },
                sample_format: IqSampleFormat::F32Le,
                layout: IqLayout::PlanarIq,
                normalization: IqNormalization::CaptureUnitRms,
                samples_per_channel: 1024,
                sample_rate_hz: b.sample_rate_hz,
                center_hz: b.center_hz,
            },
            rf_v1: Some(RfV1WindowContract {
                profile_sha256: b.profile_sha256.clone(),
                preprocess_sha256: b.preprocess_sha256.clone(),
                checkpoint_sha256: loaded.profile.model.model_sha256.clone(),
                batch_sha256: b.model_bytes_sha256.clone(),
                batch_request_id: b.request_id,
                source_sweep_id: b.source_sweep_id.clone(),
                source_request_id: b.source_request_id,
                source_session_generation: b.source_session_generation,
                source_sequence: b.source_sequence,
                capture_request_id: c.sdrd_request_id,
                capture_sequence: c.sequence,
                window_index: i as u16,
            }),
        };
        recognizer::validate_output(&request, &w.recognition).map_err(|e| e.to_string())?;
        let logits = &w.recognition.rf_v1.as_ref().ok_or("missing logits")?.logits;
        let top = (0..24)
            .max_by(|a, b| {
                logits[*a]
                    .partial_cmp(&logits[*b])
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| b.cmp(a))
            })
            .ok_or("empty logits")?;
        let denominator: f64 = logits
            .iter()
            .map(|v| (f64::from(*v) - f64::from(logits[top])).exp())
            .sum();
        check(
            w.recognition.label == format!("provisional:{top:02}")
                && (f64::from(w.recognition.confidence) - 1.0 / denominator).abs() < 1e-6,
            "window top1/logits mismatch",
        )?;
        let mut seen = std::collections::HashSet::from([top]);
        for alternative in &w.recognition.alternatives {
            let id = alternative
                .label
                .strip_prefix("provisional:")
                .and_then(|v| v.parse::<usize>().ok())
                .ok_or("alternative numeric ID")?;
            check(
                id < 24 && alternative.label == format!("provisional:{id:02}") && seen.insert(id),
                "alternative numeric ID",
            )?;
            check(
                (f64::from(alternative.confidence)
                    - (f64::from(logits[id]) - f64::from(logits[top])).exp() / denominator)
                    .abs()
                    < 1e-6,
                "alternative probability",
            )?;
        }
        check(
            w.recognition.backend == report.windows[0].recognition.backend
                && w.recognition.backend.model_id == loaded.profile.model.model_id
                && w.recognition.backend.model_sha256 == loaded.profile.model.model_sha256,
            "experimental backend identity",
        )?;
    }
    check((normalized_power.sqrt() - 1.0).abs() <= 1e-6, "shared RMS")?;
    let expected = mean_logit_summary(&report.windows).map_err(|e| e.to_string())?;
    check(
        report.mean_logit.as_ref() == Some(&expected),
        "altered mean-logit aggregate",
    )
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    pub(crate) fn verify_batch_result(
        profile: &LoadedRecognitionInputProfile,
        report: &IntegrationBatchRecognitionReport,
    ) {
        let result =
            RecognitionResult::from_experimental_batch(profile, report.clone(), 1000).unwrap();
        assert_eq!(
            result.experimental_prediction.as_ref().unwrap().numeric_id,
            1
        );
        assert_eq!(
            result.experimental_prediction.as_ref().unwrap().name_status,
            NameStatus::Provisional
        );
        let observation = result.planner_observation(profile).unwrap();
        assert_eq!(observation.status, RecognitionStatus::Unavailable);
        assert_eq!(
            observation.calibration_status,
            CalibrationStatus::Uncalibrated
        );
        assert!(observation.class.is_none());
        let bytes = serde_json::to_vec(&result).unwrap();
        assert_eq!(
            RecognitionResult::from_json(&bytes, profile).unwrap(),
            result
        );
        let json = serde_json::to_string(&observation).unwrap();
        for forbidden in [
            "experimental_batch",
            "logits",
            "probabilities",
            "output_offset",
            "path",
            "tensor",
            "provisional:01",
        ] {
            assert!(!json.contains(&format!("\"{forbidden}\":")), "{forbidden}");
        }
        assert!(observation.validate_context(12, 1100, 100).is_ok());
        for (generation, now, age) in [(13, 1100, 100), (12, 999, 100), (12, 1101, 100)] {
            assert!(observation.validate_context(generation, now, age).is_err());
        }
        for fault in [
            "flags",
            "cleanup",
            "source",
            "capture",
            "window",
            "request",
            "model",
            "compute",
            "backend",
            "nan",
            "short",
            "mean",
            "probability",
            "class",
            "agreement",
            "quality",
            "timing",
            "top1",
            "confidence",
            "alternative",
            "rms",
            "range",
            "preprocess",
        ] {
            let mut bad = report.clone();
            match fault {
                "flags" => bad.production_recognizer_available = true,
                "cleanup" => bad.transient_iq_removed = false,
                "source" => bad.batch.source_sequence += 1,
                "capture" => bad.batch.capture.session_generation += 1,
                "window" => bad.windows.swap(0, 1),
                "request" => bad.windows[0].worker_request_id += 1,
                "model" => bad.windows[0].recognition.backend.model_sha256 = "0".repeat(64),
                "compute" => {
                    bad.windows[0].recognition.rf_v1.as_mut().unwrap().compute = "fp32".into()
                }
                "backend" => bad.windows[1].recognition.backend.runtime = "different".into(),
                "nan" => bad.windows[0].recognition.rf_v1.as_mut().unwrap().logits[0] = f32::NAN,
                "short" => {
                    bad.windows[0]
                        .recognition
                        .rf_v1
                        .as_mut()
                        .unwrap()
                        .logits
                        .pop();
                }
                "mean" => bad.mean_logit.as_mut().unwrap().mean_logits[0] += 1.0,
                "probability" => bad.mean_logit.as_mut().unwrap().probabilities[0] += 0.01,
                "class" => bad.mean_logit.as_mut().unwrap().numeric_class_id = 0,
                "agreement" => bad.mean_logit.as_mut().unwrap().window_agreement = 1.0,
                "quality" => bad.batch.windows[0].clipped_samples = 1,
                "timing" => bad.windows[0].recognition.timing.inference_us = u64::MAX,
                "top1" => bad.windows[0].recognition.label = "provisional:23".into(),
                "confidence" => bad.windows[0].recognition.confidence = 0.99,
                "alternative" => bad.windows[0].recognition.alternatives.push(
                    crate::recognizer::RecognitionAlternative {
                        label: "provisional:02".into(),
                        confidence: 0.99,
                    },
                ),
                "rms" => bad.batch.windows[0].normalization_scale *= 0.5,
                "range" => bad.batch.windows[0].output_offset_bytes = 8192,
                "preprocess" => bad.batch.preprocess_sha256 = "0".repeat(64),
                _ => unreachable!(),
            }
            assert!(
                RecognitionResult::from_experimental_batch(profile, bad, 1000).is_err(),
                "{fault}"
            );
        }
        let mut bad = result.clone();
        bad.observation.status = RecognitionStatus::Classified;
        assert!(bad.planner_observation(profile).is_err());
        bad = result.clone();
        bad.experimental_prediction.as_mut().unwrap().numeric_id = 23;
        assert!(bad.validate(profile).is_err());
        let mut wire = serde_json::to_value(&result).unwrap();
        wire["observation"]["iq_path"] = "/private/iq".into();
        assert!(
            RecognitionResult::from_json(&serde_json::to_vec(&wire).unwrap(), profile).is_err()
        );
        assert!(RecognitionResult::from_json(&vec![b' '; MAX_RESULT_BYTES + 1], profile).is_err());
        assert!(RecognitionResult::from_json(&bytes[..bytes.len() - 1], profile).is_err());
        // serde typed structs reject duplicate keys, including nested fields.
        let duplicate = String::from_utf8(bytes).unwrap().replacen(
            "\"schema_version\":1",
            "\"schema_version\":1,\"schema_version\":1",
            1,
        );
        assert!(RecognitionResult::from_json(duplicate.as_bytes(), profile).is_err());
        let mut tied = report.clone();
        for w in &mut tied.windows {
            w.recognition.rf_v1.as_mut().unwrap().logits = vec![0.0; 24];
            w.recognition.rf_v1.as_mut().unwrap().logits[0] = -0.0;
            w.recognition.label = "provisional:00".into();
            w.recognition.confidence = 1.0 / 24.0;
        }
        tied.mean_logit = Some(mean_logit_summary(&tied.windows).unwrap());
        assert_eq!(
            RecognitionResult::from_experimental_batch(profile, tied, 1000)
                .unwrap()
                .experimental_prediction
                .unwrap()
                .numeric_id,
            0
        );
        verify_states(profile, observation);
    }
    #[test]
    fn retained_live_batch_converts_without_model_or_iq_access() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let loaded = crate::recognition_input::load_recognition_input_profile(
            &root,
            &root.join("jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json"),
        )
        .unwrap();
        let audit: serde_json::Value = serde_json::from_str(include_str!(
            "../../../../docs/RF_V1_RUNTIME_PARITY_AUDIT_2026-09-05.json"
        ))
        .unwrap();
        let report: IntegrationBatchRecognitionReport =
            serde_json::from_value(audit["cases"][0]["report"].clone()).unwrap();
        let result = RecognitionResult::from_experimental_batch(&loaded, report, 1000).unwrap();
        let wire = serde_json::to_vec(&result).unwrap();
        let restored = RecognitionResult::from_json(&wire, &loaded).unwrap();
        assert_eq!(restored.observation.status, RecognitionStatus::Unavailable);
        assert_eq!(
            restored
                .experimental_prediction
                .as_ref()
                .unwrap()
                .name_status,
            NameStatus::Provisional
        );
        assert_eq!(restored.planner_observation(&loaded).unwrap().class, None);
    }
    fn verify_states(
        profile: &LoadedRecognitionInputProfile,
        mut observation: RecognitionObservation,
    ) {
        observation.status = RecognitionStatus::Error;
        observation.reason = Some("worker_timeout".into());
        observation.validate().unwrap();
        let failure = RecognitionResult {
            schema_version: 1,
            observation: observation.clone(),
            experimental_prediction: None,
            uncalibrated_probability: None,
            experimental_batch: None,
        };
        assert_eq!(
            RecognitionResult::from_json(&serde_json::to_vec(&failure).unwrap(), profile).unwrap(),
            failure
        );
        observation.status = RecognitionStatus::Rejected;
        assert!(observation.validate().is_err());
        let evidence = ResultReference {
            id: "synthetic-only".into(),
            sha256: "a".repeat(64),
        };
        observation.calibration_status = CalibrationStatus::Frozen;
        observation.decision_references = Some(DecisionReferences {
            calibration: evidence.clone(),
            rejection: evidence.clone(),
            admission: evidence,
        });
        observation.reason = Some("low_confidence".into());
        observation.validate().unwrap();
        observation.status = RecognitionStatus::Classified;
        observation.reason = None;
        observation.class = Some(ClassIdentity {
            numeric_id: 1,
            name: Some("synthetic".into()),
            name_status: NameStatus::Provisional,
            name_evidence: None,
        });
        observation.calibrated_confidence = Some(0.75);
        observation.validate().unwrap();
        let forged = RecognitionResult {
            schema_version: 1,
            observation: observation.clone(),
            experimental_prediction: None,
            uncalibrated_probability: None,
            experimental_batch: None,
        };
        assert_eq!(
            forged.validate(profile).unwrap_err(),
            "candidate profile cannot carry production decisions"
        );
        observation.class.as_mut().unwrap().name_status = NameStatus::Verified;
        assert!(observation.validate().is_err());
        observation.class.as_mut().unwrap().name_status = NameStatus::Provisional;
        observation.class.as_mut().unwrap().numeric_id = 24;
        assert!(observation.validate().is_err());
        observation.class.as_mut().unwrap().numeric_id = 1;
        observation.calibrated_confidence = Some(f64::NAN);
        assert!(observation.validate().is_err());
        observation.calibrated_confidence = Some(0.75);
        observation.quality.as_mut().unwrap().healthy = false;
        assert!(observation.validate().is_err());
    }
}
