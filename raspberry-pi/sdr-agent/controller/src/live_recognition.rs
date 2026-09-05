use crate::execution::{
    observe_after_worker_release, ExecutionHealthMetadata, ExecutionTimeoutMetadata,
};
use crate::recognizer::{
    BoundedIqRef, IqFileRef, IqLayout, IqNormalization, IqSampleFormat, LocalRecognizer,
    RecognitionOutput, RecognitionRequest, RecognizerError, RECOGNIZER_PROTOCOL_VERSION,
};
use crate::sdr::{RxInputIdentity, SdrError, SdrSnapshot, SdrdWire};
use crate::sweep::{decode_base64, SweepError};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::error::Error;
use std::fmt;
use std::fs::{self, DirBuilder, OpenOptions};
use std::io::{self, Write};
use std::net::SocketAddr;
use std::os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

pub const LIVE_RECOGNITION_PROTOCOL_VERSION: u16 = 1;
pub const LIVE_RECOGNITION_SAMPLES_PER_CHANNEL: u32 = 1_024;
pub const LIVE_RECOGNITION_SAMPLE_RATE_HZ: u32 = 2_100_000;
pub const LIVE_RECOGNITION_RAW_BYTES: u64 = LIVE_RECOGNITION_SAMPLES_PER_CHANNEL as u64 * 4;
pub const LIVE_RECOGNITION_SPOOL_BYTES: u64 = LIVE_RECOGNITION_SAMPLES_PER_CHANNEL as u64 * 2 * 4;

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LiveRecognitionPlan {
    pub protocol_version: u16,
    pub request_id: u64,
    pub session_generation: u64,
    pub candidate_id: String,
    pub center_hz: u64,
    pub sample_rate_hz: u32,
    pub rf_bandwidth_hz: u32,
    pub gain_db: i16,
    pub settle_ms: u32,
    pub samples_per_channel: u32,
    pub capture_timeout_ms: u32,
    pub max_latency_ms: u32,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LiveCaptureSummary {
    pub sdrd_request_id: u64,
    pub sequence: u64,
    pub center_hz: u64,
    pub sample_rate_hz: u32,
    pub rf_bandwidth_hz: u32,
    pub gain_db: i16,
    pub samples_captured: u32,
    pub bytes_transferred: u64,
    pub dropped_samples: u64,
    pub overflow: bool,
    pub timeout: ExecutionTimeoutMetadata,
    pub health: ExecutionHealthMetadata,
    pub rx_input: RxInputIdentity,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LivePreprocessingSummary {
    pub input_format: String,
    pub output_format: String,
    pub remove_dc: bool,
    pub resample: bool,
    pub normalization: String,
    pub raw_complex_rms_adc: f64,
    pub normalization_scale: f64,
    pub normalized_complex_rms: f64,
    pub normalized_dc_fraction: f64,
    pub clipped_samples: u64,
    pub output_bytes: u64,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LiveRecognitionReport {
    pub protocol_version: u16,
    pub status: String,
    pub admission: String,
    pub request_id: u64,
    pub session_generation: u64,
    pub candidate_id: String,
    pub capture: LiveCaptureSummary,
    pub preprocessing: LivePreprocessingSummary,
    pub recognition: RecognitionOutput,
    pub transient_iq_removed: bool,
    pub post_execution_sdr: SdrSnapshot,
}

#[derive(Clone, Debug)]
pub struct CapturedCi16Window {
    pub capture: LiveCaptureSummary,
    pub iq_ci16_le: Vec<u8>,
    pub post_execution_sdr: SdrSnapshot,
}

pub trait LiveRecognitionCapture {
    fn capture(
        &mut self,
        plan: &LiveRecognitionPlan,
    ) -> Result<CapturedCi16Window, LiveRecognitionError>;
}

pub struct ReplayLiveRecognitionCapture {
    captures: VecDeque<Result<CapturedCi16Window, LiveRecognitionError>>,
}

impl ReplayLiveRecognitionCapture {
    pub fn new(
        captures: impl IntoIterator<Item = Result<CapturedCi16Window, LiveRecognitionError>>,
    ) -> Self {
        Self {
            captures: captures.into_iter().collect(),
        }
    }
}

impl LiveRecognitionCapture for ReplayLiveRecognitionCapture {
    fn capture(
        &mut self,
        _plan: &LiveRecognitionPlan,
    ) -> Result<CapturedCi16Window, LiveRecognitionError> {
        self.captures.pop_front().ok_or_else(|| {
            LiveRecognitionError::new("replay_exhausted", "no replay IQ captures remain")
        })?
    }
}

#[derive(Clone)]
pub struct SdrdLiveRecognitionCapture {
    address: SocketAddr,
    timeout: Duration,
}

impl SdrdLiveRecognitionCapture {
    pub fn new(address: SocketAddr, timeout: Duration) -> Self {
        Self { address, timeout }
    }
}

impl LiveRecognitionCapture for SdrdLiveRecognitionCapture {
    fn capture(
        &mut self,
        plan: &LiveRecognitionPlan,
    ) -> Result<CapturedCi16Window, LiveRecognitionError> {
        validate_live_plan(plan)?;
        let mut wire = SdrdWire::connect(self.address, self.timeout)?;
        let hello: HelloResponse = wire.request("HELLO", "")?;
        if hello.server != "p201-sdrd"
            || hello.protocol != "SDRD/1"
            || hello.mode != "controlled"
            || !hello.mutating_commands
        {
            return Err(LiveRecognitionError::new(
                "controlled_mode_unavailable",
                "SDRD is not the expected controlled endpoint",
            ));
        }
        let capabilities: CapabilitiesResponse = wire.request("CAPABILITIES", "")?;
        if capabilities.mode != "controlled"
            || !capabilities.iio_visible
            || !capabilities.radio_control
            || !capabilities.raw_iq_capture
            || capabilities.max_capture_bytes < LIVE_RECOGNITION_RAW_BYTES
            || !capabilities
                .rx_input
                .as_ref()
                .is_some_and(RxInputIdentity::is_fixed_p201_rx1)
        {
            let _: Result<QuitResponse, _> = wire.request("QUIT", "");
            return Err(LiveRecognitionError::new(
                "capture_capability",
                "SDRD cannot provide the bounded inline IQ window",
            ));
        }

        let generation = plan.session_generation;
        let mut session_started = false;
        let mut session_was_started = false;
        let execution = (|| {
            let start: StartResponse = wire.request("START_SESSION", &generation.to_string())?;
            session_started = true;
            session_was_started = true;
            if start.generation != generation
                || start.session_generation != generation
                || start.session_state != "owned"
                || !start.restore_armed
                || start.rx_input != capabilities.rx_input
            {
                return Err(LiveRecognitionError::new(
                    "session_start",
                    "SDRD did not arm recognition-capture restoration",
                ));
            }

            let profile_arguments = format!(
                "{generation} {} {} {} manual {} 1",
                plan.center_hz, plan.sample_rate_hz, plan.rf_bandwidth_hz, plan.gain_db
            );
            let profile: ProfileResponse = wire.request("APPLY_PROFILE", &profile_arguments)?;
            if profile.generation != generation
                || profile.session_generation != generation
                || profile.center_hz.abs_diff(plan.center_hz) > 2
                || profile.sample_rate_hz != u64::from(plan.sample_rate_hz)
                || profile.rf_bandwidth_hz != u64::from(plan.rf_bandwidth_hz)
                || profile.gain_mode != "manual"
                || profile.hardware_gain_db != Some(plan.gain_db)
                || profile.enabled_channels != 1
                || profile.rx_input != capabilities.rx_input
            {
                return Err(LiveRecognitionError::new(
                    "profile_response",
                    "SDRD recognition profile readback is inconsistent",
                ));
            }
            thread::sleep(Duration::from_millis(u64::from(plan.settle_ms)));

            let feature_id = format!("agx-recognize-{generation}-{}", plan.request_id);
            if feature_id.len() >= 64 {
                return Err(LiveRecognitionError::new(
                    "feature_id",
                    "derived recognition feature id exceeds the SDRD limit",
                ));
            }
            let capture_arguments = format!(
                "{generation} {} {} {feature_id} {}",
                plan.samples_per_channel, LIVE_RECOGNITION_RAW_BYTES, plan.capture_timeout_ms
            );
            let response: InlineCaptureResponse =
                wire.request("CAPTURE_IQ_INLINE", &capture_arguments)?;
            if response.generation != generation
                || response.session_generation != generation
                || response.samples_captured != u64::from(plan.samples_per_channel)
                || response.bytes_transferred != LIVE_RECOGNITION_RAW_BYTES
                || response.dropped_samples != 0
                || response.overflow
                || response.timeout.limit_ms != plan.capture_timeout_ms
                || response.timeout.timed_out
                || !response.health.healthy
                || response.health.flags != 0
                || response.health.source != "iio_adapter"
                || response.rx_input != capabilities.rx_input
            {
                return Err(LiveRecognitionError::new(
                    "capture_response",
                    "SDRD inline IQ response violates the recognition contract",
                ));
            }

            let stop: StopResponse = wire.request("STOP_SESSION", &generation.to_string())?;
            if stop.generation != generation
                || stop.session_generation != generation
                || !stop.stopped
                || !stop.restored
                || stop.rx_input != capabilities.rx_input
            {
                return Err(LiveRecognitionError::new(
                    "restore_response",
                    "SDRD did not confirm recognition-capture restoration",
                ));
            }
            session_started = false;
            let quit: QuitResponse = wire.request("QUIT", "")?;
            if !quit.closing {
                return Err(LiveRecognitionError::new(
                    "quit_rejected",
                    "SDRD did not close after recognition capture",
                ));
            }
            let iq_ci16_le = decode_base64(&response.iq_base64)?;
            if iq_ci16_le.len() as u64 != LIVE_RECOGNITION_RAW_BYTES {
                return Err(LiveRecognitionError::new(
                    "capture_shape",
                    "decoded recognition IQ has the wrong byte count",
                ));
            }
            Ok((profile, response, iq_ci16_le))
        })();

        let (profile, response, iq_ci16_le) = match execution {
            Ok(value) => value,
            Err(error) => {
                let mut restoration_failure = None;
                if session_started {
                    match wire.request::<StopResponse>("STOP_SESSION", &generation.to_string()) {
                        Ok(stop)
                            if stop.generation == generation
                                && stop.session_generation == generation
                                && stop.stopped
                                && stop.restored => {}
                        Ok(_) => {
                            restoration_failure = Some(
                                "SDRD stop response did not confirm recognition restoration"
                                    .to_owned(),
                            );
                        }
                        Err(stop_error) => {
                            restoration_failure = Some(format!(
                                "SDRD stop failed after recognition error: {stop_error}"
                            ));
                        }
                    }
                }
                let _: Result<QuitResponse, _> = wire.request("QUIT", "");
                if session_was_started {
                    drop(wire);
                    match observe_after_worker_release(self.address, self.timeout) {
                        Ok(snapshot) if snapshot.online && snapshot.healthy => {}
                        Ok(_) => {
                            restoration_failure = Some(
                                "SDR is not healthy after failed recognition capture".to_owned(),
                            );
                        }
                        Err(observe_error) => {
                            restoration_failure = Some(format!(
                                "SDR restoration health could not be observed: {observe_error}"
                            ));
                        }
                    }
                }
                if let Some(restoration_failure) = restoration_failure {
                    return Err(LiveRecognitionError {
                        code: "capture_restore_unverified",
                        message: restoration_failure,
                        details: Some(serde_json::json!({
                            "original_code": error.code,
                            "original_message": error.message,
                            "original_details": error.details,
                        })),
                    });
                }
                return Err(error);
            }
        };
        let post_execution_sdr = observe_after_worker_release(self.address, self.timeout)?;
        if !post_execution_sdr.online || !post_execution_sdr.healthy {
            return Err(LiveRecognitionError::new(
                "post_execution_health",
                "SDR is not healthy after recognition capture and restoration",
            ));
        }
        Ok(CapturedCi16Window {
            capture: LiveCaptureSummary {
                sdrd_request_id: response.request_id,
                sequence: response.sequence,
                center_hz: profile.center_hz,
                sample_rate_hz: plan.sample_rate_hz,
                rf_bandwidth_hz: plan.rf_bandwidth_hz,
                gain_db: plan.gain_db,
                samples_captured: plan.samples_per_channel,
                bytes_transferred: response.bytes_transferred,
                dropped_samples: response.dropped_samples,
                overflow: response.overflow,
                timeout: response.timeout,
                health: response.health,
                rx_input: response
                    .rx_input
                    .expect("validated recognition capture identity must be present"),
            },
            iq_ci16_le,
            post_execution_sdr,
        })
    }
}

pub struct LiveRecognitionEngine<C, R> {
    capture: C,
    recognizer: R,
    spool_root: PathBuf,
}

impl<C, R> LiveRecognitionEngine<C, R>
where
    C: LiveRecognitionCapture,
    R: LocalRecognizer,
{
    pub fn new(capture: C, recognizer: R, spool_root: impl Into<PathBuf>) -> Self {
        Self {
            capture,
            recognizer,
            spool_root: spool_root.into(),
        }
    }

    pub fn run(
        &mut self,
        plan: &LiveRecognitionPlan,
    ) -> Result<LiveRecognitionReport, LiveRecognitionError> {
        validate_live_plan(plan)?;
        let captured = self.capture.capture(plan)?;
        validate_captured_window(plan, &captured)?;
        let (planar_f32, preprocessing) = preprocess_ci16(&captured.iq_ci16_le)?;
        let spool_root = ensure_private_spool_root(&self.spool_root)?;
        let spool_path = spool_root.join(format!(
            "recognition-{}-{}.f32",
            plan.session_generation, plan.request_id
        ));
        let mut transient = TransientIqFile::create(spool_path, &planar_f32)?;
        let request = RecognitionRequest {
            rf_v1: None,
            protocol_version: RECOGNIZER_PROTOCOL_VERSION,
            request_id: plan.request_id,
            session_generation: plan.session_generation,
            candidate_id: plan.candidate_id.clone(),
            iq: BoundedIqRef {
                storage: IqFileRef {
                    path: transient.path().to_string_lossy().into_owned(),
                    offset_bytes: 0,
                    length_bytes: LIVE_RECOGNITION_SPOOL_BYTES,
                },
                sample_format: IqSampleFormat::F32Le,
                layout: IqLayout::PlanarIq,
                normalization: IqNormalization::UnitRms,
                samples_per_channel: LIVE_RECOGNITION_SAMPLES_PER_CHANNEL,
                sample_rate_hz: LIVE_RECOGNITION_SAMPLE_RATE_HZ,
                center_hz: captured.capture.center_hz,
            },
            max_latency_ms: plan.max_latency_ms,
        };
        let recognition = self.recognizer.classify(&request)?;
        transient.remove()?;
        Ok(LiveRecognitionReport {
            protocol_version: LIVE_RECOGNITION_PROTOCOL_VERSION,
            status: "ok".to_owned(),
            admission: "experimental_rf_only".to_owned(),
            request_id: plan.request_id,
            session_generation: plan.session_generation,
            candidate_id: plan.candidate_id.clone(),
            capture: captured.capture,
            preprocessing,
            recognition,
            transient_iq_removed: true,
            post_execution_sdr: captured.post_execution_sdr,
        })
    }

    pub fn into_parts(self) -> (C, R) {
        (self.capture, self.recognizer)
    }
}

pub fn validate_live_plan(plan: &LiveRecognitionPlan) -> Result<(), LiveRecognitionError> {
    if plan.protocol_version != LIVE_RECOGNITION_PROTOCOL_VERSION {
        return Err(LiveRecognitionError::new(
            "protocol_version",
            "unsupported live-recognition protocol version",
        ));
    }
    if plan.request_id == 0 || plan.session_generation == 0 {
        return Err(LiveRecognitionError::new(
            "correlation",
            "request id and session generation must be non-zero",
        ));
    }
    if plan.candidate_id.is_empty()
        || plan.candidate_id.len() > 64
        || plan.candidate_id.chars().any(char::is_control)
    {
        return Err(LiveRecognitionError::new(
            "candidate_id",
            "candidate id must contain 1 to 64 printable bytes",
        ));
    }
    if !(70_000_000..=6_000_000_000).contains(&plan.center_hz) {
        return Err(LiveRecognitionError::new(
            "center_hz",
            "recognition center must be between 70 MHz and 6 GHz",
        ));
    }
    if plan.sample_rate_hz != LIVE_RECOGNITION_SAMPLE_RATE_HZ {
        return Err(LiveRecognitionError::new(
            "sample_rate_hz",
            "experimental D8 recognition requires exactly 2.1 MS/s",
        ));
    }
    if !(200_000..=plan.sample_rate_hz).contains(&plan.rf_bandwidth_hz) {
        return Err(LiveRecognitionError::new(
            "rf_bandwidth_hz",
            "RF bandwidth must be between 200 kHz and the sample rate",
        ));
    }
    if !(0..=60).contains(&plan.gain_db) {
        return Err(LiveRecognitionError::new(
            "gain_db",
            "manual RX gain must be between 0 and 60 dB",
        ));
    }
    if plan.settle_ms > 1_000 {
        return Err(LiveRecognitionError::new(
            "settle_ms",
            "recognition settle time must not exceed one second",
        ));
    }
    if plan.samples_per_channel != LIVE_RECOGNITION_SAMPLES_PER_CHANNEL {
        return Err(LiveRecognitionError::new(
            "samples_per_channel",
            "experimental D8 recognition requires exactly 1024 complex samples",
        ));
    }
    if !(100..=5_000).contains(&plan.capture_timeout_ms) {
        return Err(LiveRecognitionError::new(
            "capture_timeout_ms",
            "capture timeout must be between 100 and 5000 ms",
        ));
    }
    if !(1..=5_000).contains(&plan.max_latency_ms) {
        return Err(LiveRecognitionError::new(
            "max_latency_ms",
            "recognizer latency must be between 1 and 5000 ms",
        ));
    }
    Ok(())
}

fn validate_captured_window(
    plan: &LiveRecognitionPlan,
    captured: &CapturedCi16Window,
) -> Result<(), LiveRecognitionError> {
    if captured.capture.center_hz.abs_diff(plan.center_hz) > 2
        || captured.capture.sample_rate_hz != plan.sample_rate_hz
        || captured.capture.rf_bandwidth_hz != plan.rf_bandwidth_hz
        || captured.capture.gain_db != plan.gain_db
        || captured.capture.samples_captured != plan.samples_per_channel
        || captured.capture.bytes_transferred != LIVE_RECOGNITION_RAW_BYTES
        || captured.capture.dropped_samples != 0
        || captured.capture.overflow
        || captured.capture.timeout.limit_ms != plan.capture_timeout_ms
        || captured.capture.timeout.timed_out
        || !captured.capture.health.healthy
        || captured.capture.health.flags != 0
        || captured.iq_ci16_le.len() as u64 != LIVE_RECOGNITION_RAW_BYTES
        || !captured.post_execution_sdr.online
        || !captured.post_execution_sdr.healthy
    {
        return Err(LiveRecognitionError::new(
            "capture_validation",
            "captured IQ or restored SDR state violates the live-recognition plan",
        ));
    }
    Ok(())
}

fn preprocess_ci16(
    bytes: &[u8],
) -> Result<(Vec<u8>, LivePreprocessingSummary), LiveRecognitionError> {
    if bytes.len() as u64 != LIVE_RECOGNITION_RAW_BYTES {
        return Err(LiveRecognitionError::new(
            "iq_shape",
            "input must contain exactly 1024 interleaved complex-int16 samples",
        ));
    }
    let mut i_values = Vec::with_capacity(LIVE_RECOGNITION_SAMPLES_PER_CHANNEL as usize);
    let mut q_values = Vec::with_capacity(LIVE_RECOGNITION_SAMPLES_PER_CHANNEL as usize);
    let mut power = 0.0_f64;
    let mut clipped_samples = 0_u64;
    let mut sum_i = 0.0_f64;
    let mut sum_q = 0.0_f64;
    for sample in bytes.chunks_exact(4) {
        let i = i16::from_le_bytes([sample[0], sample[1]]);
        let q = i16::from_le_bytes([sample[2], sample[3]]);
        if i <= -2_048 || i >= 2_047 || q <= -2_048 || q >= 2_047 {
            clipped_samples = clipped_samples.saturating_add(1);
        }
        let i_f64 = f64::from(i);
        let q_f64 = f64::from(q);
        power += i_f64 * i_f64 + q_f64 * q_f64;
        sum_i += i_f64;
        sum_q += q_f64;
        i_values.push(i_f64);
        q_values.push(q_f64);
    }
    if clipped_samples != 0 {
        return Err(LiveRecognitionError::new(
            "iq_clipped",
            "recognition IQ contains clipped ADC samples",
        ));
    }
    let sample_count = f64::from(LIVE_RECOGNITION_SAMPLES_PER_CHANNEL);
    let raw_complex_rms_adc = (power / sample_count).sqrt();
    if !raw_complex_rms_adc.is_finite() || raw_complex_rms_adc < 1.0 {
        return Err(LiveRecognitionError::new(
            "iq_rms",
            "recognition IQ is silent or below the one-code RMS floor",
        ));
    }
    let normalization_scale = 1.0 / raw_complex_rms_adc;
    let mut output = Vec::with_capacity(LIVE_RECOGNITION_SPOOL_BYTES as usize);
    let mut normalized_power = 0.0_f64;
    for values in [&i_values, &q_values] {
        for value in values {
            let normalized = (*value * normalization_scale) as f32;
            normalized_power += f64::from(normalized) * f64::from(normalized);
            output.extend_from_slice(&normalized.to_le_bytes());
        }
    }
    let normalized_complex_rms = (normalized_power / sample_count).sqrt();
    if (normalized_complex_rms - 1.0).abs() > 1.0e-6 {
        return Err(LiveRecognitionError::new(
            "iq_normalization",
            "float32 normalization did not produce complex unit RMS",
        ));
    }
    let mean_i = sum_i / sample_count * normalization_scale;
    let mean_q = sum_q / sample_count * normalization_scale;
    Ok((
        output,
        LivePreprocessingSummary {
            input_format: "ci16_le_interleaved".to_owned(),
            output_format: "f32_le_planar_iq".to_owned(),
            remove_dc: false,
            resample: false,
            normalization: "complex_unit_rms".to_owned(),
            raw_complex_rms_adc,
            normalization_scale,
            normalized_complex_rms,
            normalized_dc_fraction: (mean_i * mean_i + mean_q * mean_q).sqrt(),
            clipped_samples,
            output_bytes: LIVE_RECOGNITION_SPOOL_BYTES,
        },
    ))
}

fn ensure_private_spool_root(path: &Path) -> Result<PathBuf, LiveRecognitionError> {
    if !path.is_absolute() {
        return Err(LiveRecognitionError::new(
            "spool_root",
            "recognition spool root must be absolute",
        ));
    }
    if !path.exists() {
        let mut builder = DirBuilder::new();
        builder.mode(0o700);
        if let Err(error) = builder.create(path) {
            if error.kind() != io::ErrorKind::AlreadyExists {
                return Err(LiveRecognitionError::io("create_spool_root", error));
            }
        }
    }
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| LiveRecognitionError::io("stat_spool_root", error))?;
    // SAFETY: geteuid has no preconditions and does not mutate process state.
    let effective_uid = unsafe { libc::geteuid() };
    if metadata.file_type().is_symlink()
        || !metadata.is_dir()
        || metadata.uid() != effective_uid
        || metadata.mode() & 0o077 != 0
    {
        return Err(LiveRecognitionError::new(
            "spool_root",
            "spool root must be a real mode-0700 directory owned by this user",
        ));
    }
    fs::canonicalize(path).map_err(|error| LiveRecognitionError::io("canonicalize_spool", error))
}

struct TransientIqFile {
    path: PathBuf,
    removed: bool,
}

impl TransientIqFile {
    fn create(path: PathBuf, bytes: &[u8]) -> Result<Self, LiveRecognitionError> {
        if bytes.len() as u64 != LIVE_RECOGNITION_SPOOL_BYTES {
            return Err(LiveRecognitionError::new(
                "spool_shape",
                "model-ready IQ has the wrong byte count",
            ));
        }
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&path)
            .map_err(|error| LiveRecognitionError::io("create_spool_file", error))?;
        if let Err(error) = file.write_all(bytes).and_then(|_| file.flush()) {
            let _ = fs::remove_file(&path);
            return Err(LiveRecognitionError::io("write_spool_file", error));
        }
        drop(file);
        Ok(Self {
            path,
            removed: false,
        })
    }

    fn path(&self) -> &Path {
        &self.path
    }

    fn remove(&mut self) -> Result<(), LiveRecognitionError> {
        fs::remove_file(&self.path)
            .map_err(|error| LiveRecognitionError::io("remove_spool_file", error))?;
        self.removed = true;
        Ok(())
    }
}

impl Drop for TransientIqFile {
    fn drop(&mut self) {
        if !self.removed {
            let _ = fs::remove_file(&self.path);
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct LiveRecognitionError {
    pub code: &'static str,
    pub message: String,
    pub details: Option<serde_json::Value>,
}

impl LiveRecognitionError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            details: None,
        }
    }

    fn io(code: &'static str, error: io::Error) -> Self {
        Self::new(code, error.to_string())
    }
}

impl From<SdrError> for LiveRecognitionError {
    fn from(error: SdrError) -> Self {
        Self {
            code: error.code,
            message: error.message,
            details: error.details,
        }
    }
}

impl From<SweepError> for LiveRecognitionError {
    fn from(error: SweepError) -> Self {
        Self {
            code: error.code,
            message: error.message,
            details: error.details,
        }
    }
}

impl From<RecognizerError> for LiveRecognitionError {
    fn from(error: RecognizerError) -> Self {
        Self::new(error.code, error.message)
    }
}

impl fmt::Display for LiveRecognitionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)?;
        if let Some(details) = &self.details {
            write!(formatter, " metadata={details}")?;
        }
        Ok(())
    }
}

impl Error for LiveRecognitionError {}

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
struct StartResponse {
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
struct ProfileResponse {
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
struct InlineCaptureResponse {
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
struct StopResponse {
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
struct QuitResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    closing: bool,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::recognizer::{
        RecognitionAlternative, RecognitionTiming, RecognizerBackend, ReplayRecognizerAdapter,
    };
    use std::os::unix::fs::PermissionsExt;

    fn plan() -> LiveRecognitionPlan {
        LiveRecognitionPlan {
            protocol_version: LIVE_RECOGNITION_PROTOCOL_VERSION,
            request_id: 7,
            session_generation: 3,
            candidate_id: "candidate-1".to_owned(),
            center_hz: 433_920_000,
            sample_rate_hz: LIVE_RECOGNITION_SAMPLE_RATE_HZ,
            rf_bandwidth_hz: 1_500_000,
            gain_db: 20,
            settle_ms: 10,
            samples_per_channel: LIVE_RECOGNITION_SAMPLES_PER_CHANNEL,
            capture_timeout_ms: 500,
            max_latency_ms: 5_000,
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

    fn capture(bytes: Vec<u8>) -> CapturedCi16Window {
        CapturedCi16Window {
            capture: LiveCaptureSummary {
                sdrd_request_id: 5,
                sequence: 9,
                center_hz: 433_920_000,
                sample_rate_hz: LIVE_RECOGNITION_SAMPLE_RATE_HZ,
                rf_bandwidth_hz: 1_500_000,
                gain_db: 20,
                samples_captured: LIVE_RECOGNITION_SAMPLES_PER_CHANNEL,
                bytes_transferred: LIVE_RECOGNITION_RAW_BYTES,
                dropped_samples: 0,
                overflow: false,
                timeout: ExecutionTimeoutMetadata {
                    limit_ms: 500,
                    elapsed_us: 1_000,
                    timed_out: false,
                },
                health: ExecutionHealthMetadata {
                    healthy: true,
                    flags: 0,
                    source: "iio_adapter".to_owned(),
                },
                rx_input: RxInputIdentity::fixed_p201_rx1_fixture(),
            },
            iq_ci16_le: bytes,
            post_execution_sdr: snapshot(),
        }
    }

    fn iq_bytes(i: i16, q: i16) -> Vec<u8> {
        let mut bytes = Vec::with_capacity(LIVE_RECOGNITION_RAW_BYTES as usize);
        for _ in 0..LIVE_RECOGNITION_SAMPLES_PER_CHANNEL {
            bytes.extend_from_slice(&i.to_le_bytes());
            bytes.extend_from_slice(&q.to_le_bytes());
        }
        bytes
    }

    fn output() -> RecognitionOutput {
        RecognitionOutput {
            rf_v1: None,
            candidate_id: "candidate-1".to_owned(),
            label: "provisional:08:BPSK".to_owned(),
            confidence: 0.75,
            alternatives: vec![RecognitionAlternative {
                label: "provisional:19:QPSK".to_owned(),
                confidence: 0.2,
            }],
            backend: RecognizerBackend {
                runtime: "replay".to_owned(),
                runtime_version: "1".to_owned(),
                model_id: "experimental-rml-d8".to_owned(),
                model_sha256: "a".repeat(64),
                threads: 1,
            },
            timing: RecognitionTiming {
                map_us: 100,
                preprocess_us: 100,
                inference_us: 1_000,
                total_us: 1_500,
            },
        }
    }

    #[test]
    fn fixed_contract_rejects_other_sample_rates_and_lengths() {
        let mut invalid = plan();
        invalid.sample_rate_hz += 1;
        assert_eq!(
            validate_live_plan(&invalid).unwrap_err().code,
            "sample_rate_hz"
        );
        invalid = plan();
        invalid.samples_per_channel = 2_048;
        assert_eq!(
            validate_live_plan(&invalid).unwrap_err().code,
            "samples_per_channel"
        );
    }

    #[test]
    fn preprocessing_is_planar_complex_unit_rms_without_dc_removal() {
        let (output, summary) = preprocess_ci16(&iq_bytes(3, 4)).unwrap();
        assert_eq!(output.len() as u64, LIVE_RECOGNITION_SPOOL_BYTES);
        assert!(!summary.remove_dc);
        assert!(!summary.resample);
        assert_eq!(summary.raw_complex_rms_adc, 5.0);
        assert!((summary.normalized_complex_rms - 1.0).abs() < 1.0e-6);
        assert!((summary.normalized_dc_fraction - 1.0).abs() < 1.0e-6);
        let values = output
            .chunks_exact(4)
            .map(|value| f32::from_le_bytes(value.try_into().unwrap()))
            .collect::<Vec<_>>();
        assert!(values[..1_024]
            .iter()
            .all(|value| (*value - 0.6).abs() < 1.0e-6));
        assert!(values[1_024..]
            .iter()
            .all(|value| (*value - 0.8).abs() < 1.0e-6));
    }

    #[test]
    fn preprocessing_rejects_silence_and_clipping() {
        assert_eq!(preprocess_ci16(&iq_bytes(0, 0)).unwrap_err().code, "iq_rms");
        assert_eq!(
            preprocess_ci16(&iq_bytes(2_047, 0)).unwrap_err().code,
            "iq_clipped"
        );
    }

    #[test]
    fn engine_classifies_and_removes_the_private_spool_file() {
        let unique = format!(
            "sdr-live-recognition-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        );
        let root = std::env::temp_dir().join(unique);
        fs::create_dir(&root).unwrap();
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
        let capture = ReplayLiveRecognitionCapture::new([Ok(capture(iq_bytes(3, 4)))]);
        let recognizer = ReplayRecognizerAdapter::new([output()]);
        let mut engine = LiveRecognitionEngine::new(capture, recognizer, &root);
        let report = engine.run(&plan()).unwrap();
        assert_eq!(report.admission, "experimental_rf_only");
        assert_eq!(report.recognition.label, "provisional:08:BPSK");
        assert!(report.transient_iq_removed);
        assert_eq!(fs::read_dir(&root).unwrap().count(), 0);
        fs::remove_dir(root).unwrap();
    }

    #[test]
    fn engine_removes_the_private_spool_file_when_recognizer_fails() {
        let unique = format!(
            "sdr-live-recognition-failure-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        );
        let root = std::env::temp_dir().join(unique);
        fs::create_dir(&root).unwrap();
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
        let capture = ReplayLiveRecognitionCapture::new([Ok(capture(iq_bytes(3, 4)))]);
        let recognizer = ReplayRecognizerAdapter::new([]);
        let mut engine = LiveRecognitionEngine::new(capture, recognizer, &root);
        assert_eq!(engine.run(&plan()).unwrap_err().code, "replay_exhausted");
        assert_eq!(fs::read_dir(&root).unwrap().count(), 0);
        fs::remove_dir(root).unwrap();
    }
}
