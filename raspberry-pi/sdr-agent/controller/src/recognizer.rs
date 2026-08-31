use serde::{Deserialize, Serialize};
use std::collections::{HashSet, VecDeque};
use std::error::Error;
use std::fmt;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::time::Duration;

pub const RECOGNIZER_PROTOCOL_VERSION: u16 = 1;
pub const RECOGNIZER_MAX_FRAME_BYTES: usize = 16 * 1024;
pub const RECOGNIZER_MAX_SAMPLES_PER_CHANNEL: u32 = 16_384;
pub const RECOGNIZER_MAX_ALTERNATIVES: usize = 8;

pub trait LocalRecognizer {
    fn classify(
        &mut self,
        request: &RecognitionRequest,
    ) -> Result<RecognitionOutput, RecognizerError>;
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecognitionRequest {
    pub protocol_version: u16,
    pub request_id: u64,
    pub session_generation: u64,
    pub candidate_id: String,
    pub iq: BoundedIqRef,
    pub max_latency_ms: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BoundedIqRef {
    pub storage: IqFileRef,
    pub sample_format: IqSampleFormat,
    pub layout: IqLayout,
    pub normalization: IqNormalization,
    pub samples_per_channel: u32,
    pub sample_rate_hz: u32,
    pub center_hz: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IqFileRef {
    pub path: String,
    pub offset_bytes: u64,
    pub length_bytes: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IqSampleFormat {
    F32Le,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IqLayout {
    PlanarIq,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IqNormalization {
    UnitRms,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecognitionOutput {
    pub candidate_id: String,
    pub label: String,
    pub confidence: f32,
    #[serde(default)]
    pub alternatives: Vec<RecognitionAlternative>,
    pub backend: RecognizerBackend,
    pub timing: RecognitionTiming,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecognitionAlternative {
    pub label: String,
    pub confidence: f32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecognizerBackend {
    pub runtime: String,
    pub runtime_version: String,
    pub model_id: String,
    pub model_sha256: String,
    pub threads: u16,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecognitionTiming {
    pub map_us: u64,
    pub preprocess_us: u64,
    pub inference_us: u64,
    pub total_us: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
enum RecognitionStatus {
    Ok,
    Error,
    Unavailable,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RecognitionResponse {
    protocol_version: u16,
    request_id: u64,
    session_generation: u64,
    status: RecognitionStatus,
    #[serde(default)]
    output: Option<RecognitionOutput>,
    #[serde(default)]
    error: Option<String>,
}

pub struct ReplayRecognizerAdapter {
    outputs: VecDeque<RecognitionOutput>,
}

impl ReplayRecognizerAdapter {
    pub fn new(outputs: impl IntoIterator<Item = RecognitionOutput>) -> Self {
        Self {
            outputs: outputs.into_iter().collect(),
        }
    }
}

impl LocalRecognizer for ReplayRecognizerAdapter {
    fn classify(
        &mut self,
        request: &RecognitionRequest,
    ) -> Result<RecognitionOutput, RecognizerError> {
        validate_request(request, None)?;
        let output = self
            .outputs
            .pop_front()
            .ok_or_else(|| RecognizerError::new("replay_exhausted", "no replay outputs remain"))?;
        validate_output(request, &output)?;
        Ok(output)
    }
}

#[cfg(unix)]
pub struct UnixRecognizerAdapter {
    socket_path: PathBuf,
    spool_root: PathBuf,
    timeout: Duration,
}

#[cfg(unix)]
impl UnixRecognizerAdapter {
    pub fn new(
        socket_path: impl Into<PathBuf>,
        spool_root: impl Into<PathBuf>,
        timeout: Duration,
    ) -> Self {
        Self {
            socket_path: socket_path.into(),
            spool_root: spool_root.into(),
            timeout,
        }
    }
}

#[cfg(unix)]
impl LocalRecognizer for UnixRecognizerAdapter {
    fn classify(
        &mut self,
        request: &RecognitionRequest,
    ) -> Result<RecognitionOutput, RecognizerError> {
        use std::io::{BufRead, BufReader, Read, Write};
        use std::os::unix::net::UnixStream;

        validate_request(request, None)?;
        let canonical_iq_path = validate_spool_file(request, &self.spool_root)?;
        let mut wire_request = request.clone();
        wire_request.iq.storage.path = canonical_iq_path
            .to_str()
            .ok_or_else(|| RecognizerError::new("iq_path", "IQ path is not valid UTF-8"))?
            .to_owned();
        let mut frame = serde_json::to_vec(&wire_request)
            .map_err(|error| RecognizerError::protocol("encode_request", error))?;
        if frame.len() > RECOGNIZER_MAX_FRAME_BYTES {
            return Err(RecognizerError::new(
                "request_too_large",
                "recognizer request exceeds 16 KiB",
            ));
        }
        frame.push(b'\n');

        let mut stream = UnixStream::connect(&self.socket_path)
            .map_err(|error| RecognizerError::io("connect", error))?;
        stream
            .set_read_timeout(Some(self.timeout))
            .map_err(|error| RecognizerError::io("set_read_timeout", error))?;
        stream
            .set_write_timeout(Some(self.timeout))
            .map_err(|error| RecognizerError::io("set_write_timeout", error))?;
        stream
            .write_all(&frame)
            .map_err(|error| RecognizerError::io("write_request", error))?;

        let mut response_frame = Vec::new();
        let reader = BufReader::new(stream);
        reader
            .take((RECOGNIZER_MAX_FRAME_BYTES + 1) as u64)
            .read_until(b'\n', &mut response_frame)
            .map_err(|error| RecognizerError::io("read_response", error))?;
        if response_frame.len() > RECOGNIZER_MAX_FRAME_BYTES + 1 {
            return Err(RecognizerError::new(
                "response_too_large",
                "recognizer response exceeds 16 KiB",
            ));
        }
        if response_frame.last() != Some(&b'\n') {
            return Err(RecognizerError::new(
                "response_framing",
                "recognizer response is not newline framed",
            ));
        }
        response_frame.pop();
        let response: RecognitionResponse = serde_json::from_slice(&response_frame)
            .map_err(|error| RecognizerError::protocol("decode_response", error))?;
        validate_response(request, response)
    }
}

fn validate_request(
    request: &RecognitionRequest,
    spool_root: Option<&Path>,
) -> Result<(), RecognizerError> {
    if request.protocol_version != RECOGNIZER_PROTOCOL_VERSION {
        return Err(RecognizerError::new(
            "protocol_version",
            "unsupported recognizer protocol version",
        ));
    }
    require_text(&request.candidate_id, 64, "candidate_id")?;
    if request.max_latency_ms == 0 || request.max_latency_ms > 5_000 {
        return Err(RecognizerError::new(
            "max_latency_ms",
            "max latency must be between 1 and 5000 ms",
        ));
    }
    let samples = request.iq.samples_per_channel;
    if !(256..=RECOGNIZER_MAX_SAMPLES_PER_CHANNEL).contains(&samples) || !samples.is_power_of_two()
    {
        return Err(RecognizerError::new(
            "samples_per_channel",
            "samples per channel must be a power of two between 256 and 16384",
        ));
    }
    if request.iq.sample_rate_hz == 0 || request.iq.sample_rate_hz > 30_720_000 {
        return Err(RecognizerError::new(
            "sample_rate_hz",
            "sample rate must be between 1 and 30720000 Hz",
        ));
    }
    if request.iq.center_hz > 6_000_000_000 {
        return Err(RecognizerError::new(
            "center_hz",
            "center frequency exceeds 6 GHz",
        ));
    }
    let expected_bytes = u64::from(samples)
        .checked_mul(2)
        .and_then(|value| value.checked_mul(4))
        .ok_or_else(|| RecognizerError::new("iq_length", "IQ byte length overflow"))?;
    if request.iq.storage.length_bytes != expected_bytes {
        return Err(RecognizerError::new(
            "iq_length",
            "IQ byte length does not match planar float32 shape",
        ));
    }
    if request.iq.storage.offset_bytes % 4 != 0 {
        return Err(RecognizerError::new(
            "iq_offset",
            "IQ byte offset must be float32 aligned",
        ));
    }
    if request.iq.storage.path.is_empty() || request.iq.storage.path.len() > 1024 {
        return Err(RecognizerError::new(
            "iq_path",
            "IQ path must contain between 1 and 1024 bytes",
        ));
    }
    if let Some(root) = spool_root {
        validate_spool_file(request, root)?;
    }
    Ok(())
}

fn validate_spool_file(
    request: &RecognitionRequest,
    spool_root: &Path,
) -> Result<PathBuf, RecognizerError> {
    let root = fs::canonicalize(spool_root)
        .map_err(|error| RecognizerError::io("canonicalize_spool_root", error))?;
    let path = Path::new(&request.iq.storage.path);
    if !path.is_absolute() {
        return Err(RecognizerError::new("iq_path", "IQ path must be absolute"));
    }
    let path = fs::canonicalize(path)
        .map_err(|error| RecognizerError::io("canonicalize_iq_path", error))?;
    if !path.starts_with(&root) {
        return Err(RecognizerError::new(
            "iq_path_escape",
            "IQ path is outside the configured spool root",
        ));
    }
    let metadata = fs::metadata(&path).map_err(|error| RecognizerError::io("stat_iq", error))?;
    if !metadata.is_file() {
        return Err(RecognizerError::new(
            "iq_not_file",
            "IQ reference is not a regular file",
        ));
    }
    let end = request
        .iq
        .storage
        .offset_bytes
        .checked_add(request.iq.storage.length_bytes)
        .ok_or_else(|| RecognizerError::new("iq_range", "IQ file range overflow"))?;
    if end > metadata.len() {
        return Err(RecognizerError::new(
            "iq_range",
            "IQ file range exceeds file length",
        ));
    }
    Ok(path)
}

fn validate_response(
    request: &RecognitionRequest,
    response: RecognitionResponse,
) -> Result<RecognitionOutput, RecognizerError> {
    if response.protocol_version != RECOGNIZER_PROTOCOL_VERSION {
        return Err(RecognizerError::new(
            "response_protocol_version",
            "unsupported recognizer response protocol version",
        ));
    }
    if response.request_id != request.request_id
        || response.session_generation != request.session_generation
    {
        return Err(RecognizerError::new(
            "response_correlation",
            "recognizer response does not match the active request",
        ));
    }
    match response.status {
        RecognitionStatus::Ok => {
            if response.error.is_some() {
                return Err(RecognizerError::new(
                    "response_shape",
                    "successful recognizer response contains an error",
                ));
            }
            let output = response.output.ok_or_else(|| {
                RecognizerError::new(
                    "response_shape",
                    "successful recognizer response has no output",
                )
            })?;
            validate_output(request, &output)?;
            Ok(output)
        }
        RecognitionStatus::Error | RecognitionStatus::Unavailable => {
            if response.output.is_some() {
                return Err(RecognizerError::new(
                    "response_shape",
                    "failed recognizer response contains an output",
                ));
            }
            let message = response.error.unwrap_or_else(|| {
                if response.status == RecognitionStatus::Unavailable {
                    "recognizer unavailable".to_owned()
                } else {
                    "recognizer failed".to_owned()
                }
            });
            Err(RecognizerError::new("remote_error", message))
        }
    }
}

fn validate_output(
    request: &RecognitionRequest,
    output: &RecognitionOutput,
) -> Result<(), RecognizerError> {
    if output.candidate_id != request.candidate_id {
        return Err(RecognizerError::new(
            "candidate_id",
            "recognizer output refers to a different candidate",
        ));
    }
    require_text(&output.label, 128, "label")?;
    require_confidence(output.confidence, "confidence")?;
    if output.alternatives.len() > RECOGNIZER_MAX_ALTERNATIVES {
        return Err(RecognizerError::new(
            "alternatives",
            "recognizer returned more than 8 alternatives",
        ));
    }
    let mut labels = HashSet::new();
    labels.insert(output.label.as_str());
    for alternative in &output.alternatives {
        require_text(&alternative.label, 128, "alternative_label")?;
        require_confidence(alternative.confidence, "alternative_confidence")?;
        if !labels.insert(alternative.label.as_str()) {
            return Err(RecognizerError::new(
                "duplicate_label",
                "recognizer returned a duplicate label",
            ));
        }
    }
    require_text(&output.backend.runtime, 64, "runtime")?;
    require_text(&output.backend.runtime_version, 64, "runtime_version")?;
    require_text(&output.backend.model_id, 128, "model_id")?;
    if output.backend.model_sha256.len() != 64
        || !output
            .backend
            .model_sha256
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit())
    {
        return Err(RecognizerError::new(
            "model_sha256",
            "model SHA-256 must contain exactly 64 hexadecimal characters",
        ));
    }
    if output.backend.threads == 0 || output.backend.threads > 4 {
        return Err(RecognizerError::new(
            "threads",
            "recognizer thread count must be between 1 and 4",
        ));
    }
    let accounted_us = output
        .timing
        .map_us
        .checked_add(output.timing.preprocess_us)
        .and_then(|value| value.checked_add(output.timing.inference_us))
        .ok_or_else(|| RecognizerError::new("timing", "recognizer timing overflow"))?;
    if output.timing.total_us < accounted_us
        || output.timing.total_us > u64::from(request.max_latency_ms) * 1_000
    {
        return Err(RecognizerError::new(
            "timing",
            "recognizer timing is inconsistent or exceeds the request deadline",
        ));
    }
    Ok(())
}

fn require_text(value: &str, max_bytes: usize, field: &'static str) -> Result<(), RecognizerError> {
    if value.is_empty()
        || value.len() > max_bytes
        || value.chars().any(|character| character.is_control())
    {
        return Err(RecognizerError::new(
            field,
            format!("{field} is empty, too long, or contains control characters"),
        ));
    }
    Ok(())
}

fn require_confidence(value: f32, field: &'static str) -> Result<(), RecognizerError> {
    if !value.is_finite() || !(0.0..=1.0).contains(&value) {
        return Err(RecognizerError::new(
            field,
            format!("{field} must be finite and between 0 and 1"),
        ));
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecognizerError {
    pub code: &'static str,
    pub message: String,
}

impl RecognizerError {
    fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    fn io(operation: &'static str, error: io::Error) -> Self {
        Self::new(operation, error.to_string())
    }

    fn protocol(operation: &'static str, error: serde_json::Error) -> Self {
        Self::new(operation, error.to_string())
    }
}

impl fmt::Display for RecognizerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)
    }
}

impl Error for RecognizerError {}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(path: String) -> RecognitionRequest {
        RecognitionRequest {
            protocol_version: RECOGNIZER_PROTOCOL_VERSION,
            request_id: 7,
            session_generation: 3,
            candidate_id: "candidate-1".to_owned(),
            iq: BoundedIqRef {
                storage: IqFileRef {
                    path,
                    offset_bytes: 0,
                    length_bytes: 2 * 2_048 * 4,
                },
                sample_format: IqSampleFormat::F32Le,
                layout: IqLayout::PlanarIq,
                normalization: IqNormalization::UnitRms,
                samples_per_channel: 2_048,
                sample_rate_hz: 1_000_000,
                center_hz: 433_920_000,
            },
            max_latency_ms: 500,
        }
    }

    fn output() -> RecognitionOutput {
        RecognitionOutput {
            candidate_id: "candidate-1".to_owned(),
            label: "GFSK".to_owned(),
            confidence: 0.91,
            alternatives: vec![RecognitionAlternative {
                label: "FSK".to_owned(),
                confidence: 0.07,
            }],
            backend: RecognizerBackend {
                runtime: "onnxruntime".to_owned(),
                runtime_version: "test".to_owned(),
                model_id: "amr-test".to_owned(),
                model_sha256: "0".repeat(64),
                threads: 1,
            },
            timing: RecognitionTiming {
                map_us: 20,
                preprocess_us: 100,
                inference_us: 2_000,
                total_us: 2_200,
            },
        }
    }

    #[test]
    fn replay_adapter_is_a_second_real_adapter() {
        let expected = output();
        let mut replay = ReplayRecognizerAdapter::new([expected.clone()]);
        assert_eq!(
            replay
                .classify(&request("/replay/iq.f32".to_owned()))
                .unwrap(),
            expected
        );
        assert_eq!(
            replay
                .classify(&request("/replay/iq.f32".to_owned()))
                .unwrap_err()
                .code,
            "replay_exhausted"
        );
    }

    #[test]
    fn rejects_shape_byte_mismatch_before_calling_backend() {
        let mut invalid = request("/replay/iq.f32".to_owned());
        invalid.iq.storage.length_bytes -= 4;
        let mut replay = ReplayRecognizerAdapter::new([output()]);
        assert_eq!(replay.classify(&invalid).unwrap_err().code, "iq_length");
    }

    #[test]
    fn rejects_stale_candidate_output() {
        let mut stale = output();
        stale.candidate_id = "candidate-old".to_owned();
        let mut replay = ReplayRecognizerAdapter::new([stale]);
        assert_eq!(
            replay
                .classify(&request("/replay/iq.f32".to_owned()))
                .unwrap_err()
                .code,
            "candidate_id"
        );
    }

    #[cfg(unix)]
    #[test]
    fn unix_adapter_validates_spool_and_correlates_response() {
        use std::io::{BufRead, BufReader, Write};
        use std::os::unix::net::UnixListener;
        use std::thread;

        let unique = format!(
            "sdr-recognizer-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        );
        let root = std::env::temp_dir().join(unique);
        fs::create_dir_all(&root).unwrap();
        let iq_path = root.join("window.f32");
        fs::write(&iq_path, vec![0_u8; 2 * 2_048 * 4]).unwrap();
        let socket_path = root.join("recognizer.sock");
        let listener = UnixListener::bind(&socket_path).unwrap();
        let expected = output();
        let server_output = expected.clone();
        let expected_iq_path = fs::canonicalize(&iq_path)
            .unwrap()
            .to_string_lossy()
            .into_owned();
        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut line = String::new();
            BufReader::new(stream.try_clone().unwrap())
                .read_line(&mut line)
                .unwrap();
            let observed: RecognitionRequest = serde_json::from_str(&line).unwrap();
            assert_eq!(observed.request_id, 7);
            assert_eq!(observed.iq.storage.path, expected_iq_path);
            let response = serde_json::json!({
                "protocol_version": 1,
                "request_id": 7,
                "session_generation": 3,
                "status": "ok",
                "output": server_output
            });
            writeln!(stream, "{response}").unwrap();
        });
        let mut adapter = UnixRecognizerAdapter::new(&socket_path, &root, Duration::from_secs(1));
        let observed = adapter
            .classify(&request(iq_path.to_string_lossy().into_owned()))
            .unwrap();
        assert_eq!(observed, expected);
        handle.join().unwrap();
        fs::remove_dir_all(&root).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn unix_adapter_rejects_file_outside_spool() {
        let unique = format!("sdr-recognizer-root-{}", std::process::id());
        let root = std::env::temp_dir().join(unique);
        fs::create_dir_all(&root).unwrap();
        let outside =
            std::env::temp_dir().join(format!("sdr-recognizer-outside-{}.f32", std::process::id()));
        fs::write(&outside, vec![0_u8; 2 * 2_048 * 4]).unwrap();
        let mut adapter =
            UnixRecognizerAdapter::new(root.join("missing.sock"), &root, Duration::from_secs(1));
        assert_eq!(
            adapter
                .classify(&request(outside.to_string_lossy().into_owned()))
                .unwrap_err()
                .code,
            "iq_path_escape"
        );
        fs::remove_file(outside).unwrap();
        fs::remove_dir_all(root).unwrap();
    }
}
