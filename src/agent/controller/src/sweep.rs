use crate::execution::{ExecutionHealthMetadata, ExecutionTimeoutMetadata};
use crate::protocol::{CandidateSummary, HealthSummary, ObservationSummary};
use crate::sdr::{RxInputIdentity, SdrError, SdrdWire};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::cmp::Ordering;
use std::collections::VecDeque;
use std::error::Error;
use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::net::SocketAddr;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

pub const MAX_POINTS: usize = 768;
pub const SPECTRAL_SUMMARY_SCHEMA_VERSION: u16 = 1;
pub const SPECTRAL_SUMMARY_ALGORITHM_ID: &str = "agx_welch_hann_dc_reject_obw99_v1";
const MAX_DURATION_MS: u64 = 300_000;
const MAX_INLINE_IQ_BYTES_PER_POINT: u64 = 256 * 1024;
const ADC_FULL_SCALE: f64 = 2_048.0;
const MIN_POWER: f64 = 1.0e-20;
const MAX_PLANNER_CANDIDATE_BANDWIDTH_HZ: u64 = 10_000_000;
const MAX_SPECTRAL_FFT_SIZE: usize = 4_096;

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SweepPlan {
    pub sweep_id: String,
    pub session_generation: u64,
    pub frequencies: SweepFrequencies,
    pub sample_rate_hz: u64,
    pub rf_bandwidth_hz: u64,
    pub settle_ms: u64,
    pub frame_samples: u32,
    pub aggregate_frames: u32,
    pub point_timeout_ms: u32,
    pub detection_threshold_db: f32,
    #[serde(default)]
    pub gain_db: Option<i16>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum SweepFrequencies {
    Range {
        start_hz: u64,
        stop_hz: u64,
        step_hz: u64,
    },
    Centers {
        centers_hz: Vec<u64>,
    },
}

#[derive(Clone, Debug, PartialEq)]
pub struct ValidatedSweepPlan {
    pub sweep_id: String,
    pub session_generation: u64,
    pub centers_hz: Vec<u64>,
    pub sample_rate_hz: u64,
    pub rf_bandwidth_hz: u64,
    pub settle_ms: u64,
    pub frame_samples: u32,
    pub aggregate_frames: u32,
    pub point_timeout_ms: u32,
    pub detection_threshold_db: f32,
    pub gain_db: Option<i16>,
    pub samples_per_point: u64,
    pub iq_bytes_per_point: u64,
    pub maximum_iq_bytes: u64,
    pub estimated_duration_ms: u64,
    pub maximum_summary_bytes: u64,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SweepPoint {
    pub point_index: usize,
    pub request_id: u64,
    pub session_generation: u64,
    pub requested_center_hz: u64,
    pub actual_center_hz: u64,
    pub sample_rate_hz: u64,
    pub rf_bandwidth_hz: u64,
    pub sequence: u64,
    pub dropped_samples: u64,
    pub overflow: bool,
    pub captured_samples: u64,
    pub band_power_dbfs: f32,
    pub spectral: SpectralSummary,
    pub clipped_samples: u64,
    pub status_flags: u32,
    pub elapsed_us: u64,
    pub timeout: ExecutionTimeoutMetadata,
    pub health: ExecutionHealthMetadata,
    pub rx_input: RxInputIdentity,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SpectralSummary {
    pub schema_version: u16,
    pub algorithm_id: String,
    pub fft_size: u32,
    pub segment_count: u32,
    pub bin_width_hz: f64,
    pub peak_frequency_hz: u64,
    pub peak_power_dbfs: f32,
    pub noise_floor_dbfs: f32,
    pub measured_snr_db: f32,
    pub estimated_center_hz: u64,
    pub occupied_start_hz: u64,
    pub occupied_stop_hz: u64,
    pub occupied_bandwidth_hz: u64,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SweepCandidate {
    pub id: String,
    pub start_hz: u64,
    pub stop_hz: u64,
    pub center_hz: u64,
    pub bandwidth_hz: u64,
    pub peak_dbfs: f32,
    pub snr_db: f32,
    pub point_count: usize,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SweepReport {
    pub sweep_id: String,
    pub session_generation: u64,
    pub backend: String,
    pub backend_version: u32,
    pub estimated_duration_ms: u64,
    pub elapsed_ms: u64,
    pub noise_floor_dbfs: f32,
    pub points: Vec<SweepPoint>,
    pub candidates: Vec<SweepCandidate>,
    pub dataset: Option<SweepDataset>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SweepDataset {
    pub format: String,
    pub datatype: String,
    pub data_path: String,
    pub metadata_path: String,
    pub bytes: u64,
}

impl SweepReport {
    pub fn planner_observation(
        &self,
        age_ms: u64,
        health: HealthSummary,
        fixed_gain_db: i16,
    ) -> ObservationSummary {
        let first_point = self.points.first();
        ObservationSummary {
            age_ms,
            health,
            candidates: self
                .candidates
                .iter()
                .take(crate::protocol::MAX_CANDIDATES)
                .map(|candidate| CandidateSummary {
                    id: candidate.id.clone(),
                    center_hz: candidate.center_hz,
                    // The sweep report preserves the full contiguous active
                    // region. Planning receives a peak-centered inspection
                    // window that cannot exceed the production policy limit.
                    bandwidth_hz: candidate
                        .bandwidth_hz
                        .min(MAX_PLANNER_CANDIDATE_BANDWIDTH_HZ),
                    peak_dbfs: candidate.peak_dbfs,
                    snr_db: candidate.snr_db,
                    age_ms,
                })
                .collect(),
            latest_sweep: first_point.map(|point| crate::protocol::SweepObservationSummary {
                sweep_id: self.sweep_id.clone(),
                sample_rate_hz: point.sample_rate_hz,
                rf_bandwidth_hz: point.rf_bandwidth_hz,
                fixed_gain_db,
                noise_floor_dbfs: self.noise_floor_dbfs,
                points: self
                    .points
                    .iter()
                    .map(|point| (point.actual_center_hz, point.band_power_dbfs))
                    .collect(),
            }),
            recognition: None,
        }
    }

    pub fn planner_inspection_observation(
        &self,
        previous: &ObservationSummary,
        candidate_id: &str,
        health: HealthSummary,
    ) -> Result<ObservationSummary, SweepError> {
        if self.points.len() != 1 {
            return Err(SweepError::new(
                "inspection_points",
                "candidate inspection must return exactly one summary point",
            ));
        }
        let point = &self.points[0];
        let mut candidates = previous.candidates.clone();
        for candidate in &mut candidates {
            candidate.age_ms = candidate.age_ms.saturating_add(self.elapsed_ms);
        }
        let candidate = candidates
            .iter_mut()
            .find(|candidate| candidate.id == candidate_id)
            .ok_or_else(|| {
                SweepError::new(
                    "inspection_candidate",
                    "inspected candidate is absent from the prior observation",
                )
            })?;
        candidate.center_hz = point.spectral.estimated_center_hz;
        candidate.bandwidth_hz = point.spectral.occupied_bandwidth_hz;
        candidate.peak_dbfs = point.spectral.peak_power_dbfs;
        candidate.snr_db = point.spectral.measured_snr_db;
        candidate.age_ms = 0;
        Ok(ObservationSummary {
            age_ms: 0,
            health,
            candidates,
            latest_sweep: previous.latest_sweep.clone(),
            recognition: None,
        })
    }
}

pub trait SweepBackend {
    fn run_points(&mut self, plan: &ValidatedSweepPlan) -> Result<BackendSweep, SweepError>;
}

#[derive(Clone, Debug, PartialEq)]
pub struct BackendSweep {
    pub backend: String,
    pub backend_version: u32,
    pub points: Vec<SweepPoint>,
    pub dataset: Option<SweepDataset>,
}

pub struct SweepEngine<B> {
    backend: B,
}

impl<B: SweepBackend> SweepEngine<B> {
    pub fn new(backend: B) -> Self {
        Self { backend }
    }

    pub fn run(&mut self, plan: &SweepPlan) -> Result<SweepReport, SweepError> {
        let validated = validate_plan(plan)?;
        let started = Instant::now();
        let backend = self.backend.run_points(&validated)?;
        validate_points(&validated, &backend.points)?;
        let noise_floor_dbfs = median_power_dbfs(&backend.points)?;
        let candidates = merge_candidates(&validated, &backend.points, noise_floor_dbfs);
        Ok(SweepReport {
            sweep_id: validated.sweep_id,
            session_generation: validated.session_generation,
            backend: backend.backend,
            backend_version: backend.backend_version,
            estimated_duration_ms: validated.estimated_duration_ms,
            elapsed_ms: started.elapsed().as_millis().try_into().unwrap_or(u64::MAX),
            noise_floor_dbfs,
            points: backend.points,
            candidates,
            dataset: backend.dataset,
        })
    }
}

pub fn validate_completed_sweep(
    plan: &SweepPlan,
    report: &SweepReport,
) -> Result<ValidatedSweepPlan, SweepError> {
    let validated = validate_plan(plan)?;
    if report.sweep_id != validated.sweep_id
        || report.session_generation != validated.session_generation
        || report.estimated_duration_ms != validated.estimated_duration_ms
        || report.elapsed_ms > MAX_DURATION_MS.saturating_mul(2)
    {
        return Err(SweepError::new(
            "report_contract",
            "completed sweep identity, duration, or generation does not match its plan",
        ));
    }
    validate_points(&validated, &report.points)?;
    let noise_floor_dbfs = median_power_dbfs(&report.points)?;
    if report.noise_floor_dbfs != noise_floor_dbfs
        || report.candidates != merge_candidates(&validated, &report.points, noise_floor_dbfs)
    {
        return Err(SweepError::new(
            "report_aggregate",
            "completed sweep aggregate or candidate set is not reproducible from its points",
        ));
    }
    Ok(validated)
}

pub struct ReplaySweepAdapter {
    sweeps: VecDeque<Result<BackendSweep, SweepError>>,
}

impl ReplaySweepAdapter {
    pub fn new(sweeps: impl IntoIterator<Item = Result<BackendSweep, SweepError>>) -> Self {
        Self {
            sweeps: sweeps.into_iter().collect(),
        }
    }
}

impl SweepBackend for ReplaySweepAdapter {
    fn run_points(&mut self, _plan: &ValidatedSweepPlan) -> Result<BackendSweep, SweepError> {
        self.sweeps
            .pop_front()
            .ok_or_else(|| SweepError::new("replay_exhausted", "no replay sweeps remain"))?
    }
}

#[derive(Clone)]
pub struct SdrdSoftwareSweepAdapter {
    address: SocketAddr,
    timeout: Duration,
    sigmf_directory: Option<PathBuf>,
}

impl SdrdSoftwareSweepAdapter {
    pub fn new(address: SocketAddr, timeout: Duration) -> Self {
        Self {
            address,
            timeout,
            sigmf_directory: None,
        }
    }

    pub fn with_sigmf_directory(mut self, directory: impl Into<PathBuf>) -> Self {
        self.sigmf_directory = Some(directory.into());
        self
    }
}

impl SweepBackend for SdrdSoftwareSweepAdapter {
    fn run_points(&mut self, plan: &ValidatedSweepPlan) -> Result<BackendSweep, SweepError> {
        run_sdrd_points(
            self.address,
            self.timeout,
            plan,
            self.sigmf_directory.as_deref(),
        )
    }
}

fn run_sdrd_points(
    address: SocketAddr,
    timeout: Duration,
    plan: &ValidatedSweepPlan,
    sigmf_directory: Option<&Path>,
) -> Result<BackendSweep, SweepError> {
    let mut wire = SdrdWire::connect(address, timeout)?;
    let hello: HelloResponse = wire.request("HELLO", "")?;
    if hello.server != "p201-sdrd"
        || hello.protocol != "SDRD/1"
        || hello.mode != "controlled"
        || !hello.mutating_commands
    {
        return Err(SweepError::new(
            "controlled_mode_unavailable",
            "SDRD is not the expected controlled endpoint",
        ));
    }
    let capabilities: CapabilitiesResponse = wire.request("CAPABILITIES", "")?;
    if !capabilities.iio_visible
        || !capabilities.radio_control
        || !capabilities
            .rx_input
            .as_ref()
            .is_some_and(RxInputIdentity::is_fixed_p201_rx1)
    {
        return Err(SweepError::new(
            "radio_capability",
            "SDRD cannot own and retune the receive path",
        ));
    }
    if !capabilities.raw_iq_capture {
        let _: Result<QuitResponse, _> = wire.request("QUIT", "");
        return Err(SweepError::new(
            "raw_iq_transport_unavailable",
            "SDRD does not expose bounded raw-IQ acquisition for AGX aggregation",
        ));
    }

    let generation = plan.session_generation;
    let mut session_started = false;
    let execution = (|| {
        let start: StartResponse = wire.request("START_SESSION", &generation.to_string())?;
        if start.generation != generation
            || start.session_generation != generation
            || !start.restore_armed
            || start.rx_input != capabilities.rx_input
        {
            return Err(SweepError::new(
                "session_start",
                "SDRD did not arm sweep restoration",
            ));
        }
        session_started = true;
        let mut points = Vec::with_capacity(plan.centers_hz.len());
        let mut sigmf = sigmf_directory
            .map(|directory| SigmfWriter::create(directory, plan))
            .transpose()?;
        for (point_index, center_hz) in plan.centers_hz.iter().copied().enumerate() {
            let profile_args = if let Some(gain_db) = plan.gain_db {
                format!(
                    "{generation} {center_hz} {} {} manual {gain_db} 1",
                    plan.sample_rate_hz, plan.rf_bandwidth_hz
                )
            } else {
                format!(
                    "{generation} {center_hz} {} {} slow_attack 1",
                    plan.sample_rate_hz, plan.rf_bandwidth_hz
                )
            };
            let profile: ProfileResponse = wire.request("APPLY_PROFILE", &profile_args)?;
            if profile.generation != generation
                || profile.session_generation != generation
                || profile.center_hz.abs_diff(center_hz) > 2
                || profile.sample_rate_hz != plan.sample_rate_hz
                || profile.rf_bandwidth_hz != plan.rf_bandwidth_hz
                || profile.gain_mode
                    != if plan.gain_db.is_some() {
                        "manual"
                    } else {
                        "slow_attack"
                    }
                || profile.hardware_gain_db != plan.gain_db
                || profile.rx_input != capabilities.rx_input
            {
                return Err(SweepError::new(
                    "profile_response",
                    "SDRD sweep profile readback is inconsistent",
                ));
            }
            thread::sleep(Duration::from_millis(plan.settle_ms));
            let captured_samples = plan.samples_per_point;
            let bytes = plan.iq_bytes_per_point;
            let feature_id = format!("agx-sweep-{generation}-{point_index}");
            let capture_args = format!(
                "{generation} {captured_samples} {bytes} {feature_id} {}",
                plan.point_timeout_ms
            );
            let capture: InlineCaptureResponse =
                wire.request("CAPTURE_IQ_INLINE", &capture_args)?;
            if capture.generation != generation
                || capture.session_generation != generation
                || capture.samples_captured != captured_samples
                || capture.bytes_transferred != bytes
                || capture.dropped_samples != 0
                || capture.overflow
                || capture.timeout.limit_ms != plan.point_timeout_ms
                || capture.timeout.timed_out
                || !capture.health.healthy
                || capture.health.flags != 0
                || capture.health.source != "iio_adapter"
                || capture.rx_input != capabilities.rx_input
            {
                return Err(SweepError::new(
                    "agx_capture_shape",
                    "inline IQ response does not match the validated AGX aggregation plan",
                ));
            }
            let iq = decode_base64(&capture.iq_base64)?;
            if let Some(writer) = sigmf.as_mut() {
                writer.append(point_index, center_hz, &iq)?;
            }
            let (band_power_dbfs, spectral, clipped) = analyze_ci16_window(
                &iq,
                captured_samples,
                profile.center_hz,
                profile.sample_rate_hz,
            )?;
            let response_generation = capture.generation;
            let sequence = capture.sequence;
            let aggregate_samples = captured_samples;
            let status_flags = capture.health.flags;
            let elapsed_us = capture.timeout.elapsed_us;
            if response_generation != generation || status_flags != 0 {
                return Err(SweepError::new(
                    "summary_quality",
                    "SDR summary reported invalid, stale, overflow, or shape flags",
                ));
            }
            if clipped != 0 {
                return Err(SweepError::new(
                    "summary_clipped",
                    "SDR summary clipped at the configured fixed gain; lower survey gain and retry",
                ));
            }
            if aggregate_samples != captured_samples {
                return Err(SweepError::new(
                    "summary_shape",
                    "aggregate sample count does not match the plan",
                ));
            }
            points.push(SweepPoint {
                point_index,
                request_id: capture.request_id,
                session_generation: capture.session_generation,
                requested_center_hz: center_hz,
                actual_center_hz: profile.center_hz,
                sample_rate_hz: profile.sample_rate_hz,
                rf_bandwidth_hz: profile.rf_bandwidth_hz,
                sequence,
                dropped_samples: capture.dropped_samples,
                overflow: capture.overflow,
                captured_samples,
                band_power_dbfs,
                spectral,
                clipped_samples: clipped,
                status_flags,
                elapsed_us,
                timeout: capture.timeout,
                health: capture.health,
                rx_input: capture
                    .rx_input
                    .expect("validated SDRD inline capture identity must be present"),
            });
        }
        let stop: StopResponse = wire.request("STOP_SESSION", &generation.to_string())?;
        if stop.generation != generation
            || stop.session_generation != generation
            || !stop.stopped
            || !stop.restored
            || stop.rx_input != capabilities.rx_input
        {
            return Err(SweepError::new(
                "restore_response",
                "SDRD did not confirm sweep restoration",
            ));
        }
        session_started = false;
        let quit: QuitResponse = wire.request("QUIT", "")?;
        if !quit.closing {
            return Err(SweepError::new("quit_rejected", "SDRD did not close"));
        }
        let dataset = sigmf.map(|writer| writer.finish()).transpose()?;
        Ok(BackendSweep {
            backend: "agx_iq_software_aggregate".to_owned(),
            backend_version: 1,
            points,
            dataset,
        })
    })();

    if execution.is_err() {
        if session_started {
            let _: Result<StopResponse, _> = wire.request("STOP_SESSION", &generation.to_string());
        }
        let _: Result<QuitResponse, _> = wire.request("QUIT", "");
    }
    execution
}

struct SigmfWriter {
    data: File,
    data_path: PathBuf,
    metadata_path: PathBuf,
    captures: Vec<serde_json::Value>,
    samples_written: u64,
    sample_rate_hz: u64,
    rf_bandwidth_hz: u64,
    gain_db: Option<i16>,
    created_at_ms: u64,
    committed: bool,
}

impl SigmfWriter {
    fn create(directory: &Path, plan: &ValidatedSweepPlan) -> Result<Self, SweepError> {
        if directory.exists() {
            let metadata = fs::symlink_metadata(directory)
                .map_err(|error| SweepError::new("sigmf_directory", error.to_string()))?;
            if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
                return Err(SweepError::new(
                    "sigmf_directory",
                    "SigMF output path must be a real directory",
                ));
            }
        } else {
            fs::create_dir_all(directory)
                .map_err(|error| SweepError::new("sigmf_directory", error.to_string()))?;
        }
        fs::set_permissions(directory, fs::Permissions::from_mode(0o700))
            .map_err(|error| SweepError::new("sigmf_directory", error.to_string()))?;
        let required_data_bytes = (plan.centers_hz.len() as u64)
            .checked_mul(u64::from(plan.frame_samples))
            .and_then(|value| value.checked_mul(u64::from(plan.aggregate_frames)))
            .and_then(|value| value.checked_mul(4))
            .ok_or_else(|| SweepError::new("sigmf_size", "SigMF byte count overflow"))?;
        let required_with_metadata = required_data_bytes
            .checked_add(1024 * 1024)
            .ok_or_else(|| SweepError::new("sigmf_size", "SigMF space check overflow"))?;
        let available = available_storage_bytes(directory)?;
        if available < required_with_metadata {
            return Err(SweepError::new(
                "sigmf_space",
                format!(
                    "AGX capture directory has {available} free bytes but this finite scan requires {required_with_metadata} bytes"
                ),
            ));
        }
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let stem = format!("{}-{}-{nonce}", plan.sweep_id, plan.session_generation);
        let data_path = directory.join(format!("{stem}.sigmf-data"));
        let metadata_path = directory.join(format!("{stem}.sigmf-meta"));
        let data = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&data_path)
            .map_err(|error| SweepError::new("sigmf_create", error.to_string()))?;
        Ok(Self {
            data,
            data_path,
            metadata_path,
            captures: Vec::with_capacity(plan.centers_hz.len()),
            samples_written: 0,
            sample_rate_hz: plan.sample_rate_hz,
            rf_bandwidth_hz: plan.rf_bandwidth_hz,
            gain_db: plan.gain_db,
            created_at_ms: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis()
                .try_into()
                .unwrap_or(u64::MAX),
            committed: false,
        })
    }

    fn append(&mut self, point_index: usize, center_hz: u64, iq: &[u8]) -> Result<(), SweepError> {
        if iq.is_empty() || iq.len() % 4 != 0 {
            return Err(SweepError::new(
                "sigmf_iq_shape",
                "SigMF IQ block must contain complete complex-int16 samples",
            ));
        }
        self.captures.push(json!({
            "core:sample_start": self.samples_written,
            "core:frequency": center_hz,
            "sdrharness:point_index": point_index,
            "sdrharness:rf_bandwidth_hz": self.rf_bandwidth_hz,
            "sdrharness:gain_db": self.gain_db,
        }));
        self.data
            .write_all(iq)
            .map_err(|error| SweepError::new("sigmf_write", error.to_string()))?;
        self.samples_written = self
            .samples_written
            .checked_add((iq.len() / 4) as u64)
            .ok_or_else(|| SweepError::new("sigmf_size", "SigMF sample count overflow"))?;
        Ok(())
    }

    fn finish(mut self) -> Result<SweepDataset, SweepError> {
        self.data
            .sync_all()
            .map_err(|error| SweepError::new("sigmf_sync", error.to_string()))?;
        let metadata = json!({
            "global": {
                "core:datatype": "ci16_le",
                "core:sample_rate": self.sample_rate_hz,
                "core:version": "1.2.5",
                "core:recorder": "sdrharness-agx",
                "sdrharness:created_at_unix_ms": self.created_at_ms,
                "sdrharness:sample_layout": "interleaved_iq",
            },
            "captures": self.captures,
            "annotations": [],
        });
        let mut metadata_file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&self.metadata_path)
            .map_err(|error| SweepError::new("sigmf_meta_create", error.to_string()))?;
        serde_json::to_writer_pretty(&mut metadata_file, &metadata)
            .map_err(|error| SweepError::new("sigmf_meta_write", error.to_string()))?;
        metadata_file
            .write_all(b"\n")
            .and_then(|_| metadata_file.sync_all())
            .map_err(|error| SweepError::new("sigmf_meta_sync", error.to_string()))?;
        let bytes = self.samples_written.saturating_mul(4);
        self.committed = true;
        Ok(SweepDataset {
            format: "sigmf".to_owned(),
            datatype: "ci16_le".to_owned(),
            data_path: self.data_path.to_string_lossy().into_owned(),
            metadata_path: self.metadata_path.to_string_lossy().into_owned(),
            bytes,
        })
    }
}

pub fn available_storage_bytes(path: &Path) -> Result<u64, SweepError> {
    let path = std::ffi::CString::new(path.as_os_str().as_bytes())
        .map_err(|_| SweepError::new("sigmf_space", "capture directory contains a NUL byte"))?;
    let mut stat = std::mem::MaybeUninit::<libc::statvfs>::uninit();
    // SAFETY: `path` is a valid NUL-terminated pathname and `stat` points to
    // writable storage for one `statvfs` result.
    if unsafe { libc::statvfs(path.as_ptr(), stat.as_mut_ptr()) } != 0 {
        return Err(SweepError::new(
            "sigmf_space",
            std::io::Error::last_os_error().to_string(),
        ));
    }
    // SAFETY: statvfs returned success and initialized the output structure.
    let stat = unsafe { stat.assume_init() };
    let available = (stat.f_bavail as u128).saturating_mul(stat.f_frsize as u128);
    Ok(available.min(u128::from(u64::MAX)) as u64)
}

impl Drop for SigmfWriter {
    fn drop(&mut self) {
        if !self.committed {
            let _ = fs::remove_file(&self.data_path);
            let _ = fs::remove_file(&self.metadata_path);
        }
    }
}

fn aggregate_ci16_power(bytes: &[u8], samples: u64) -> Result<(u64, u64), SweepError> {
    let expected = samples
        .checked_mul(4)
        .and_then(|value| usize::try_from(value).ok())
        .ok_or_else(|| SweepError::new("agx_iq_shape", "IQ byte count overflow"))?;
    if bytes.len() != expected {
        return Err(SweepError::new(
            "agx_iq_shape",
            "decoded IQ length does not match the capture sample count",
        ));
    }
    let mut power = 0_u64;
    let mut clipped = 0_u64;
    for sample in bytes.chunks_exact(4) {
        let i = i16::from_le_bytes([sample[0], sample[1]]);
        let q = i16::from_le_bytes([sample[2], sample[3]]);
        let i64_value = i64::from(i);
        let q64_value = i64::from(q);
        power = power
            .checked_add((i64_value * i64_value + q64_value * q64_value) as u64)
            .ok_or_else(|| SweepError::new("agx_power_overflow", "AGX IQ power sum overflow"))?;
        if i <= -2048 || i >= 2047 || q <= -2048 || q >= 2047 {
            clipped = clipped.saturating_add(1);
        }
    }
    Ok((power, clipped))
}

pub fn analyze_ci16_window(
    bytes: &[u8],
    samples: u64,
    tuned_center_hz: u64,
    sample_rate_hz: u64,
) -> Result<(f32, SpectralSummary, u64), SweepError> {
    let (power, clipped) = aggregate_ci16_power(bytes, samples)?;
    let band_power_dbfs = u96_power_dbfs(power as u32, (power >> 32) as u32, 0, samples)?;
    let spectral = spectral_summary_ci16(bytes, samples, tuned_center_hz, sample_rate_hz)?;
    Ok((band_power_dbfs, spectral, clipped))
}

fn spectral_summary_ci16(
    bytes: &[u8],
    samples: u64,
    tuned_center_hz: u64,
    sample_rate_hz: u64,
) -> Result<SpectralSummary, SweepError> {
    let expected = samples
        .checked_mul(4)
        .and_then(|value| usize::try_from(value).ok())
        .ok_or_else(|| SweepError::new("spectral_shape", "IQ byte count overflow"))?;
    if bytes.len() != expected || samples < 64 || sample_rate_hz == 0 {
        return Err(SweepError::new(
            "spectral_shape",
            "spectral summary requires at least 64 complete complex samples",
        ));
    }

    let available = usize::try_from(samples)
        .map_err(|_| SweepError::new("spectral_shape", "sample count exceeds this host"))?;
    let fft_size = largest_power_of_two(available.min(MAX_SPECTRAL_FFT_SIZE));
    if fft_size < 64 {
        return Err(SweepError::new(
            "spectral_shape",
            "spectral FFT size is below the minimum",
        ));
    }
    let segment_count = available / fft_size;
    let mut averaged_power = vec![0.0_f64; fft_size];
    let mut window = Vec::with_capacity(fft_size);
    for index in 0..fft_size {
        window.push(
            0.5 - 0.5 * (2.0 * std::f64::consts::PI * index as f64 / (fft_size - 1) as f64).cos(),
        );
    }
    let coherent_sum: f64 = window.iter().sum();
    let normalization = (coherent_sum * ADC_FULL_SCALE).powi(2);
    if !normalization.is_finite() || normalization <= 0.0 {
        return Err(SweepError::new(
            "spectral_window",
            "spectral window normalization is invalid",
        ));
    }

    for segment_index in 0..segment_count {
        let start_sample = segment_index * fft_size;
        let segment = &bytes[start_sample * 4..(start_sample + fft_size) * 4];
        let mut mean_i = 0.0_f64;
        let mut mean_q = 0.0_f64;
        for sample in segment.chunks_exact(4) {
            mean_i += f64::from(i16::from_le_bytes([sample[0], sample[1]]));
            mean_q += f64::from(i16::from_le_bytes([sample[2], sample[3]]));
        }
        mean_i /= fft_size as f64;
        mean_q /= fft_size as f64;

        let mut spectrum = Vec::with_capacity(fft_size);
        for (index, sample) in segment.chunks_exact(4).enumerate() {
            let i = f64::from(i16::from_le_bytes([sample[0], sample[1]])) - mean_i;
            let q = f64::from(i16::from_le_bytes([sample[2], sample[3]])) - mean_q;
            spectrum.push((i * window[index], q * window[index]));
        }
        radix2_fft_in_place(&mut spectrum);
        for (output, (real, imaginary)) in averaged_power.iter_mut().zip(spectrum) {
            *output += (real * real + imaginary * imaginary) / normalization;
        }
    }
    for power in &mut averaged_power {
        *power /= segment_count as f64;
    }

    let mut sorted_noise = averaged_power.clone();
    sorted_noise.sort_unstable_by(|left, right| left.partial_cmp(right).unwrap_or(Ordering::Equal));
    let noise_linear = sorted_noise[sorted_noise.len() / 2].max(MIN_POWER);
    let (peak_index, peak_linear) = averaged_power
        .iter()
        .copied()
        .enumerate()
        .max_by(|(_, left), (_, right)| left.partial_cmp(right).unwrap_or(Ordering::Equal))
        .ok_or_else(|| SweepError::new("spectral_empty", "spectral FFT returned no bins"))?;
    let peak_linear = peak_linear.max(MIN_POWER);
    let bin_width_hz = sample_rate_hz as f64 / fft_size as f64;
    let peak_frequency_hz =
        absolute_bin_frequency(tuned_center_hz, sample_rate_hz, fft_size, peak_index);

    let ordered_indices: Vec<usize> = (fft_size / 2..fft_size).chain(0..fft_size / 2).collect();
    let ordered_power: Vec<f64> = ordered_indices
        .iter()
        .map(|index| averaged_power[*index])
        .collect();
    let smoothed_power: Vec<f64> = (0..ordered_power.len())
        .map(|position| {
            let start = position.saturating_sub(2);
            let stop = (position + 2).min(ordered_power.len() - 1);
            ordered_power[start..=stop].iter().sum::<f64>() / (stop - start + 1) as f64
        })
        .collect();
    let peak_position = ordered_indices
        .iter()
        .position(|index| *index == peak_index)
        .unwrap_or(fft_size / 2);
    let component_threshold = noise_linear * 4.0;
    let (component_start, component_stop) = if smoothed_power[peak_position] >= component_threshold
    {
        signal_component_bounds(&smoothed_power, peak_position, component_threshold, 8)
    } else {
        (peak_position, peak_position)
    };
    let excess: Vec<f64> = ordered_power[component_start..=component_stop]
        .iter()
        .map(|power| (*power - noise_linear).max(0.0))
        .collect();
    let total_excess: f64 = excess.iter().sum();
    let (lower_offset, upper_offset) = if total_excess > MIN_POWER {
        let lower_target = total_excess * 0.005;
        let upper_target = total_excess * 0.995;
        let mut cumulative = 0.0_f64;
        let mut lower = 0_usize;
        let mut upper = excess.len() - 1;
        let mut lower_found = false;
        for (position, value) in excess.iter().copied().enumerate() {
            cumulative += value;
            if !lower_found && cumulative >= lower_target {
                lower = position;
                lower_found = true;
            }
            if cumulative >= upper_target {
                upper = position;
                break;
            }
        }
        (lower, upper.max(lower))
    } else {
        (
            peak_position - component_start,
            peak_position - component_start,
        )
    };
    let lower_position = component_start + lower_offset;
    let upper_position = component_start + upper_offset;
    let occupied_start_hz = absolute_bin_frequency(
        tuned_center_hz,
        sample_rate_hz,
        fft_size,
        ordered_indices[lower_position],
    );
    let occupied_stop_hz = absolute_bin_frequency(
        tuned_center_hz,
        sample_rate_hz,
        fft_size,
        ordered_indices[upper_position],
    );
    let occupied_bandwidth_hz = (((upper_position - lower_position + 1) as f64) * bin_width_hz)
        .ceil()
        .max(1.0) as u64;
    let estimated_center_hz = occupied_start_hz / 2
        + occupied_stop_hz / 2
        + (occupied_start_hz % 2 + occupied_stop_hz % 2) / 2;
    let peak_power_dbfs = (10.0 * peak_linear.log10()) as f32;
    let noise_floor_dbfs = (10.0 * noise_linear.log10()) as f32;
    let measured_snr_db = (peak_power_dbfs - noise_floor_dbfs).max(0.0);
    if !bin_width_hz.is_finite()
        || !peak_power_dbfs.is_finite()
        || !noise_floor_dbfs.is_finite()
        || !measured_snr_db.is_finite()
    {
        return Err(SweepError::new(
            "spectral_non_finite",
            "spectral summary produced a non-finite measurement",
        ));
    }
    Ok(SpectralSummary {
        schema_version: SPECTRAL_SUMMARY_SCHEMA_VERSION,
        algorithm_id: SPECTRAL_SUMMARY_ALGORITHM_ID.to_owned(),
        fft_size: fft_size as u32,
        segment_count: segment_count as u32,
        bin_width_hz,
        peak_frequency_hz,
        peak_power_dbfs,
        noise_floor_dbfs,
        measured_snr_db,
        estimated_center_hz,
        occupied_start_hz,
        occupied_stop_hz,
        occupied_bandwidth_hz,
    })
}

fn signal_component_bounds(
    smoothed_power: &[f64],
    peak_position: usize,
    threshold: f64,
    maximum_gap_bins: usize,
) -> (usize, usize) {
    let mut start = peak_position;
    let mut below = 0_usize;
    for position in (0..peak_position).rev() {
        if smoothed_power[position] >= threshold {
            start = position;
            below = 0;
        } else {
            below += 1;
            if below > maximum_gap_bins {
                break;
            }
        }
    }
    let mut stop = peak_position;
    below = 0;
    for (position, power) in smoothed_power
        .iter()
        .copied()
        .enumerate()
        .skip(peak_position + 1)
    {
        if power >= threshold {
            stop = position;
            below = 0;
        } else {
            below += 1;
            if below > maximum_gap_bins {
                break;
            }
        }
    }
    (start, stop)
}

fn largest_power_of_two(value: usize) -> usize {
    if value == 0 {
        return 0;
    }
    1_usize << (usize::BITS - 1 - value.leading_zeros())
}

fn absolute_bin_frequency(
    tuned_center_hz: u64,
    sample_rate_hz: u64,
    fft_size: usize,
    bin_index: usize,
) -> u64 {
    let signed_bin = if bin_index < fft_size / 2 {
        bin_index as i64
    } else {
        bin_index as i64 - fft_size as i64
    };
    let offset_hz = signed_bin as f64 * sample_rate_hz as f64 / fft_size as f64;
    (tuned_center_hz as f64 + offset_hz)
        .round()
        .clamp(0.0, u64::MAX as f64) as u64
}

fn radix2_fft_in_place(values: &mut [(f64, f64)]) {
    let length = values.len();
    debug_assert!(length.is_power_of_two());
    let mut reversed = 0_usize;
    for index in 1..length {
        let mut bit = length >> 1;
        while reversed & bit != 0 {
            reversed ^= bit;
            bit >>= 1;
        }
        reversed ^= bit;
        if index < reversed {
            values.swap(index, reversed);
        }
    }
    let mut stage_length = 2_usize;
    while stage_length <= length {
        let angle = -2.0 * std::f64::consts::PI / stage_length as f64;
        let (twiddle_imaginary, twiddle_real) = angle.sin_cos();
        for start in (0..length).step_by(stage_length) {
            let mut twiddle = (1.0_f64, 0.0_f64);
            for offset in 0..stage_length / 2 {
                let even = values[start + offset];
                let odd = values[start + offset + stage_length / 2];
                let rotated = (
                    odd.0 * twiddle.0 - odd.1 * twiddle.1,
                    odd.0 * twiddle.1 + odd.1 * twiddle.0,
                );
                values[start + offset] = (even.0 + rotated.0, even.1 + rotated.1);
                values[start + offset + stage_length / 2] =
                    (even.0 - rotated.0, even.1 - rotated.1);
                twiddle = (
                    twiddle.0 * twiddle_real - twiddle.1 * twiddle_imaginary,
                    twiddle.0 * twiddle_imaginary + twiddle.1 * twiddle_real,
                );
            }
        }
        stage_length *= 2;
    }
}

pub(crate) fn decode_base64(input: &str) -> Result<Vec<u8>, SweepError> {
    if input.is_empty() || input.len() % 4 != 0 {
        return Err(SweepError::new("agx_iq_base64", "invalid IQ base64 length"));
    }
    let mut output = Vec::with_capacity(input.len() / 4 * 3);
    for (block_index, block) in input.as_bytes().chunks_exact(4).enumerate() {
        let last = block_index + 1 == input.len() / 4;
        let a = base64_value(block[0])?;
        let b = base64_value(block[1])?;
        let c_padding = block[2] == b'=';
        let d_padding = block[3] == b'=';
        if c_padding && !d_padding || (!last && (c_padding || d_padding)) {
            return Err(SweepError::new(
                "agx_iq_base64",
                "invalid IQ base64 padding",
            ));
        }
        let c = if c_padding {
            0
        } else {
            base64_value(block[2])?
        };
        let d = if d_padding {
            0
        } else {
            base64_value(block[3])?
        };
        let packed =
            (u32::from(a) << 18) | (u32::from(b) << 12) | (u32::from(c) << 6) | u32::from(d);
        output.push((packed >> 16) as u8);
        if !c_padding {
            output.push((packed >> 8) as u8);
        }
        if !d_padding {
            output.push(packed as u8);
        }
    }
    Ok(output)
}

fn base64_value(value: u8) -> Result<u8, SweepError> {
    match value {
        b'A'..=b'Z' => Ok(value - b'A'),
        b'a'..=b'z' => Ok(value - b'a' + 26),
        b'0'..=b'9' => Ok(value - b'0' + 52),
        b'+' => Ok(62),
        b'/' => Ok(63),
        _ => Err(SweepError::new(
            "agx_iq_base64",
            "invalid IQ base64 character",
        )),
    }
}

pub fn validate_plan(plan: &SweepPlan) -> Result<ValidatedSweepPlan, SweepError> {
    if plan.sweep_id.is_empty()
        || plan.sweep_id.len() >= 64
        || !plan
            .sweep_id
            .bytes()
            .all(|value| value.is_ascii_alphanumeric() || matches!(value, b'-' | b'_'))
    {
        return Err(SweepError::new(
            "sweep_id",
            "sweep id must be a safe non-empty identifier shorter than 64 bytes",
        ));
    }
    if plan.session_generation == 0 {
        return Err(SweepError::new(
            "session_generation",
            "session generation must be non-zero",
        ));
    }
    let centers_hz = expand_centers(&plan.frequencies)?;
    if centers_hz.is_empty() || centers_hz.len() > MAX_POINTS {
        return Err(SweepError::new(
            "point_count",
            "sweep must contain between one and 768 points",
        ));
    }
    if centers_hz.windows(2).any(|pair| pair[0] >= pair[1])
        || centers_hz
            .iter()
            .any(|center| !(70_000_000..=6_000_000_000).contains(center))
    {
        return Err(SweepError::new(
            "frequencies",
            "sweep centers must be unique, ascending, and between 70 MHz and 6 GHz",
        ));
    }
    if !(2_100_000..=30_720_000).contains(&plan.sample_rate_hz)
        || !(200_000..=56_000_000).contains(&plan.rf_bandwidth_hz)
        || plan.rf_bandwidth_hz > plan.sample_rate_hz
    {
        return Err(SweepError::new(
            "radio_profile",
            "sample rate or RF bandwidth is outside the controlled profile",
        ));
    }
    if plan
        .gain_db
        .is_some_and(|gain_db| !(0..=60).contains(&gain_db))
    {
        return Err(SweepError::new(
            "gain",
            "manual sweep gain must be between 0 and 60 dB",
        ));
    }
    if centers_hz.len() > 1
        && centers_hz
            .windows(2)
            .any(|pair| pair[1] - pair[0] > plan.rf_bandwidth_hz.saturating_mul(4) / 5)
    {
        return Err(SweepError::new(
            "coverage_gap",
            "sweep step exceeds 80 percent of RF bandwidth",
        ));
    }
    if plan.settle_ms > 1_000
        || !(64..=65_535).contains(&plan.frame_samples)
        || plan.aggregate_frames == 0
        || plan.aggregate_frames > 65_535
        || !(1..=5_000).contains(&plan.point_timeout_ms)
        || !plan.detection_threshold_db.is_finite()
        || !(1.0..=60.0).contains(&plan.detection_threshold_db)
    {
        return Err(SweepError::new(
            "summary_profile",
            "settle, frame, aggregate, timeout, or threshold is outside limits",
        ));
    }
    let samples_per_point = u64::from(plan.frame_samples)
        .checked_mul(u64::from(plan.aggregate_frames))
        .ok_or_else(|| SweepError::new("sample_count", "sample count overflow"))?;
    let iq_bytes_per_point = samples_per_point
        .checked_mul(4)
        .ok_or_else(|| SweepError::new("sample_count", "IQ byte count overflow"))?;
    if iq_bytes_per_point > MAX_INLINE_IQ_BYTES_PER_POINT {
        return Err(SweepError::new(
            "agx_capture_size",
            "one AGX software-aggregate point exceeds the 256 KiB transport frame",
        ));
    }
    let maximum_iq_bytes = iq_bytes_per_point
        .checked_mul(centers_hz.len() as u64)
        .ok_or_else(|| SweepError::new("sample_count", "total IQ byte count overflow"))?;
    let point_ms = plan
        .settle_ms
        .checked_add(u64::from(plan.point_timeout_ms))
        .ok_or_else(|| SweepError::new("duration", "sweep duration overflow"))?;
    let estimated_duration_ms = point_ms
        .checked_mul(centers_hz.len() as u64)
        .ok_or_else(|| SweepError::new("duration", "sweep duration overflow"))?;
    if estimated_duration_ms > MAX_DURATION_MS {
        return Err(SweepError::new(
            "duration",
            "estimated sweep duration exceeds 300 seconds",
        ));
    }
    Ok(ValidatedSweepPlan {
        sweep_id: plan.sweep_id.clone(),
        session_generation: plan.session_generation,
        centers_hz,
        sample_rate_hz: plan.sample_rate_hz,
        rf_bandwidth_hz: plan.rf_bandwidth_hz,
        settle_ms: plan.settle_ms,
        frame_samples: plan.frame_samples,
        aggregate_frames: plan.aggregate_frames,
        point_timeout_ms: plan.point_timeout_ms,
        detection_threshold_db: plan.detection_threshold_db,
        gain_db: plan.gain_db,
        samples_per_point,
        iq_bytes_per_point,
        maximum_iq_bytes,
        estimated_duration_ms,
        maximum_summary_bytes: (MAX_POINTS as u64) * 256,
    })
}

fn expand_centers(frequencies: &SweepFrequencies) -> Result<Vec<u64>, SweepError> {
    match frequencies {
        SweepFrequencies::Centers { centers_hz } => Ok(centers_hz.clone()),
        SweepFrequencies::Range {
            start_hz,
            stop_hz,
            step_hz,
        } => {
            if start_hz > stop_hz || *step_hz == 0 {
                return Err(SweepError::new(
                    "frequency_range",
                    "range requires start <= stop and a positive step",
                ));
            }
            let mut centers = Vec::new();
            let mut center = *start_hz;
            loop {
                centers.push(center);
                if center == *stop_hz {
                    break;
                }
                let next = center.checked_add(*step_hz).ok_or_else(|| {
                    SweepError::new("frequency_range", "frequency range overflow")
                })?;
                center = next.min(*stop_hz);
                if centers.len() > MAX_POINTS {
                    return Err(SweepError::new(
                        "frequency_range",
                        "range must contain at most 768 points",
                    ));
                }
            }
            Ok(centers)
        }
    }
}

fn validate_points(plan: &ValidatedSweepPlan, points: &[SweepPoint]) -> Result<(), SweepError> {
    if points.len() != plan.centers_hz.len() {
        return Err(SweepError::new(
            "point_count",
            "backend point count does not match the validated plan",
        ));
    }
    let mut previous_sequence = None;
    for (index, point) in points.iter().enumerate() {
        if point.point_index != index
            || point.request_id == 0
            || point.session_generation != plan.session_generation
            || point.requested_center_hz != plan.centers_hz[index]
            || point.actual_center_hz.abs_diff(plan.centers_hz[index]) > 2
            || point.sample_rate_hz != plan.sample_rate_hz
            || point.rf_bandwidth_hz != plan.rf_bandwidth_hz
            || !point.band_power_dbfs.is_finite()
            || !spectral_summary_matches_point(point)
            || point.dropped_samples != 0
            || point.overflow
            || point.status_flags != 0
            || point.timeout.limit_ms == 0
            || point.timeout.timed_out
            || point.timeout.elapsed_us != point.elapsed_us
            || !point.health.healthy
            || point.health.flags != point.status_flags
            || point.health.source.is_empty()
            || previous_sequence.is_some_and(|previous| point.sequence <= previous)
        {
            return Err(SweepError::new(
                "point_contract",
                "backend point violates the sweep result contract",
            ));
        }
        previous_sequence = Some(point.sequence);
    }
    Ok(())
}

fn spectral_summary_matches_point(point: &SweepPoint) -> bool {
    let spectral = &point.spectral;
    let expected_bin_width = point.sample_rate_hz as f64 / f64::from(spectral.fft_size);
    let expected_segments = point
        .captured_samples
        .checked_div(u64::from(spectral.fft_size))
        .unwrap_or(0);
    let half_sample_rate = point.sample_rate_hz / 2;
    let passband_start = point.actual_center_hz.saturating_sub(half_sample_rate);
    let passband_stop = point.actual_center_hz.saturating_add(half_sample_rate);
    let occupied_span = spectral
        .occupied_stop_hz
        .saturating_sub(spectral.occupied_start_hz);
    let expected_center = spectral.occupied_start_hz / 2
        + spectral.occupied_stop_hz / 2
        + (spectral.occupied_start_hz % 2 + spectral.occupied_stop_hz % 2) / 2;
    spectral.schema_version == SPECTRAL_SUMMARY_SCHEMA_VERSION
        && spectral.algorithm_id == SPECTRAL_SUMMARY_ALGORITHM_ID
        && (64..=MAX_SPECTRAL_FFT_SIZE as u32).contains(&spectral.fft_size)
        && spectral.fft_size.is_power_of_two()
        && spectral.segment_count > 0
        && u64::from(spectral.segment_count) == expected_segments
        && spectral.bin_width_hz.is_finite()
        && (spectral.bin_width_hz - expected_bin_width).abs() <= expected_bin_width * 1.0e-9
        && spectral.peak_frequency_hz >= passband_start
        && spectral.peak_frequency_hz <= passband_stop
        && spectral.estimated_center_hz >= passband_start
        && spectral.estimated_center_hz <= passband_stop
        && spectral.occupied_start_hz >= passband_start
        && spectral.occupied_start_hz <= spectral.occupied_stop_hz
        && spectral.occupied_stop_hz <= passband_stop
        && spectral.estimated_center_hz == expected_center
        && spectral.occupied_bandwidth_hz >= occupied_span.max(1)
        && spectral.occupied_bandwidth_hz
            <= occupied_span.saturating_add((spectral.bin_width_hz.ceil() as u64) * 2)
        && spectral.occupied_bandwidth_hz <= point.sample_rate_hz
        && spectral.peak_power_dbfs.is_finite()
        && spectral.noise_floor_dbfs.is_finite()
        && spectral.measured_snr_db.is_finite()
        && spectral.measured_snr_db >= 0.0
        && (spectral.measured_snr_db
            - (spectral.peak_power_dbfs - spectral.noise_floor_dbfs).max(0.0))
        .abs()
            <= 0.001
}

fn median_power_dbfs(points: &[SweepPoint]) -> Result<f32, SweepError> {
    let mut powers: Vec<f32> = points.iter().map(|point| point.band_power_dbfs).collect();
    powers.sort_unstable_by(|left, right| left.partial_cmp(right).unwrap_or(Ordering::Equal));
    powers
        .get(powers.len() / 2)
        .copied()
        .ok_or_else(|| SweepError::new("noise_floor", "sweep returned no powers"))
}

fn merge_candidates(
    plan: &ValidatedSweepPlan,
    points: &[SweepPoint],
    noise_floor_dbfs: f32,
) -> Vec<SweepCandidate> {
    let active: Vec<usize> = points
        .iter()
        .enumerate()
        .filter_map(|(index, point)| {
            (point.band_power_dbfs >= noise_floor_dbfs + plan.detection_threshold_db)
                .then_some(index)
        })
        .collect();
    if active.is_empty() {
        return Vec::new();
    }
    let mut ranges = Vec::new();
    let mut start = active[0];
    let mut stop = active[0];
    for &index in active.iter().skip(1) {
        if index == stop + 1 {
            stop = index;
        } else {
            ranges.push((start, stop));
            start = index;
            stop = index;
        }
    }
    ranges.push((start, stop));
    ranges
        .into_iter()
        .take(crate::protocol::MAX_CANDIDATES)
        .enumerate()
        .map(|(candidate_index, (start, stop))| {
            let peak = points[start..=stop]
                .iter()
                .max_by(|left, right| {
                    left.band_power_dbfs
                        .partial_cmp(&right.band_power_dbfs)
                        .unwrap_or(Ordering::Equal)
                })
                .expect("candidate range is non-empty");
            let edge = plan.rf_bandwidth_hz / 2;
            let start_hz = points[start].actual_center_hz.saturating_sub(edge);
            let stop_hz = points[stop].actual_center_hz.saturating_add(edge);
            SweepCandidate {
                id: format!("{}-{}", plan.sweep_id, candidate_index + 1),
                start_hz,
                stop_hz,
                center_hz: peak.actual_center_hz,
                bandwidth_hz: stop_hz.saturating_sub(start_hz),
                peak_dbfs: peak.band_power_dbfs,
                snr_db: peak.band_power_dbfs - noise_floor_dbfs,
                point_count: stop - start + 1,
            }
        })
        .collect()
}

fn u96_power_dbfs(lo: u32, mid: u32, hi: u32, samples: u64) -> Result<f32, SweepError> {
    if samples == 0 {
        return Err(SweepError::new("summary_shape", "summary has zero samples"));
    }
    let sum = f64::from(hi) * 2_f64.powi(64) + f64::from(mid) * 2_f64.powi(32) + f64::from(lo);
    let normalized = sum / (samples as f64 * ADC_FULL_SCALE * ADC_FULL_SCALE);
    Ok((10.0 * normalized.max(MIN_POWER).log10()) as f32)
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct SweepError {
    pub code: &'static str,
    pub message: String,
    pub details: Option<serde_json::Value>,
}

impl SweepError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            details: None,
        }
    }
}

impl From<SdrError> for SweepError {
    fn from(error: SdrError) -> Self {
        Self {
            code: error.code,
            message: error.message,
            details: error.details,
        }
    }
}

impl fmt::Display for SweepError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)?;
        if let Some(details) = &self.details {
            write!(formatter, " metadata={details}")?;
        }
        Ok(())
    }
}

impl Error for SweepError {}

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
    #[serde(rename = "mode")]
    _mode: String,
    iio_visible: bool,
    radio_control: bool,
    raw_iq_capture: bool,
    #[serde(default)]
    #[serde(rename = "software_summary")]
    _software_summary: bool,
    #[serde(rename = "max_capture_bytes")]
    _max_capture_bytes: u64,
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
    #[serde(rename = "session_state")]
    _session_state: String,
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
    #[serde(default)]
    hardware_gain_db: Option<i16>,
    #[serde(rename = "enabled_channels")]
    _enabled_channels: u32,
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
    use std::io::{BufRead, BufReader, Write};
    use std::net::TcpListener;

    fn temporary_test_directory(label: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        std::env::temp_dir().join(format!("sdrharness-{label}-{}-{nonce}", std::process::id()))
    }

    #[test]
    fn preserves_remote_execution_metadata_in_sweep_errors() {
        let details = json!({
            "request_id": 41,
            "session_generation": 9,
            "sequence": 12,
            "dropped_samples": 0,
            "overflow": false,
            "timeout": {"limit_ms": 1, "elapsed_us": 2_048, "timed_out": true},
            "health": {"healthy": false, "flags": 4, "source": "iio_adapter"}
        });
        let error = SweepError::from(SdrError::with_details(
            "remote_error",
            "capture_failed_restored",
            details.clone(),
        ));
        assert_eq!(error.details, Some(details));
        assert!(error.to_string().contains("\"timed_out\":true"));
    }

    fn test_base64(bytes: &[u8]) -> String {
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

    fn with_fixed_rx_input(response: &str) -> String {
        let mut value: serde_json::Value = serde_json::from_str(response).unwrap();
        let object = value.as_object_mut().unwrap();
        let carries_rx_contract = object.get("status").and_then(serde_json::Value::as_str)
            == Some("ok")
            && [
                "radio_control",
                "session_state",
                "center_hz",
                "bytes_transferred",
                "stopped",
            ]
            .iter()
            .any(|field| object.contains_key(*field));
        if carries_rx_contract {
            object.insert(
                "rx_input".to_owned(),
                serde_json::to_value(RxInputIdentity::fixed_p201_rx1_fixture()).unwrap(),
            );
        }
        format!("{}\n", serde_json::to_string(&value).unwrap())
    }

    fn plan() -> SweepPlan {
        SweepPlan {
            sweep_id: "survey-24g".to_owned(),
            session_generation: 9,
            frequencies: SweepFrequencies::Range {
                start_hz: 2_440_000_000,
                stop_hz: 2_448_000_000,
                step_hz: 2_000_000,
            },
            sample_rate_hz: 3_000_000,
            rf_bandwidth_hz: 2_500_000,
            settle_ms: 5,
            frame_samples: 2_048,
            aggregate_frames: 16,
            point_timeout_ms: 500,
            detection_threshold_db: 6.0,
            gain_db: None,
        }
    }

    #[test]
    fn sigmf_writer_keeps_one_dataset_pair_for_all_sweep_windows() {
        let directory = temporary_test_directory("sigmf-pair");
        let validated = validate_plan(&plan()).unwrap();
        let mut writer = SigmfWriter::create(&directory, &validated).unwrap();
        for (index, center_hz) in validated.centers_hz.iter().copied().enumerate() {
            writer
                .append(index, center_hz, &[1, 0, 2, 0, 3, 0, 4, 0])
                .unwrap();
        }
        let dataset = writer.finish().unwrap();
        let entries: Vec<_> = fs::read_dir(&directory).unwrap().collect();
        assert_eq!(entries.len(), 2);
        assert_eq!(dataset.format, "sigmf");
        assert_eq!(dataset.datatype, "ci16_le");
        assert_eq!(dataset.bytes, validated.centers_hz.len() as u64 * 8);
        assert_eq!(
            fs::metadata(&dataset.data_path).unwrap().len(),
            dataset.bytes
        );
        let metadata: serde_json::Value =
            serde_json::from_slice(&fs::read(&dataset.metadata_path).unwrap()).unwrap();
        let captures = metadata["captures"].as_array().unwrap();
        assert_eq!(captures.len(), validated.centers_hz.len());
        for (index, capture) in captures.iter().enumerate() {
            assert_eq!(capture["core:sample_start"], (index as u64) * 2);
            assert_eq!(capture["core:frequency"], validated.centers_hz[index]);
        }
        fs::remove_file(dataset.data_path).unwrap();
        fs::remove_file(dataset.metadata_path).unwrap();
        fs::remove_dir(directory).unwrap();
    }

    #[test]
    fn incomplete_sigmf_writer_removes_partial_files() {
        let directory = temporary_test_directory("sigmf-drop");
        let validated = validate_plan(&plan()).unwrap();
        {
            let mut writer = SigmfWriter::create(&directory, &validated).unwrap();
            assert!(writer.append(0, validated.centers_hz[0], &[]).is_err());
        }
        assert_eq!(fs::read_dir(&directory).unwrap().count(), 0);
        fs::remove_dir(directory).unwrap();
    }

    fn point(index: usize, center: u64, power: f32) -> SweepPoint {
        SweepPoint {
            point_index: index,
            request_id: index as u64 + 1,
            session_generation: 9,
            requested_center_hz: center,
            actual_center_hz: center,
            sample_rate_hz: 3_000_000,
            rf_bandwidth_hz: 2_500_000,
            sequence: index as u64 + 1,
            dropped_samples: 0,
            overflow: false,
            captured_samples: 32_768,
            band_power_dbfs: power,
            spectral: SpectralSummary {
                schema_version: SPECTRAL_SUMMARY_SCHEMA_VERSION,
                algorithm_id: SPECTRAL_SUMMARY_ALGORITHM_ID.into(),
                fft_size: 1_024,
                segment_count: 32,
                bin_width_hz: 3_000_000.0 / 1_024.0,
                peak_frequency_hz: center,
                peak_power_dbfs: power,
                noise_floor_dbfs: power - 10.0,
                measured_snr_db: 10.0,
                estimated_center_hz: center,
                occupied_start_hz: center - 250_000,
                occupied_stop_hz: center + 250_000,
                occupied_bandwidth_hz: 500_000,
            },
            clipped_samples: 0,
            status_flags: 0,
            elapsed_us: 10_000,
            timeout: ExecutionTimeoutMetadata {
                limit_ms: 500,
                elapsed_us: 10_000,
                timed_out: false,
            },
            health: ExecutionHealthMetadata {
                healthy: true,
                flags: 0,
                source: "replay".into(),
            },
            rx_input: RxInputIdentity::fixed_p201_rx1_fixture(),
        }
    }

    #[test]
    fn completed_sweep_revalidates_plan_identity_and_aggregate() {
        let plan = plan();
        let validated = validate_plan(&plan).unwrap();
        let points: Vec<_> = validated
            .centers_hz
            .iter()
            .copied()
            .enumerate()
            .map(|(index, center)| point(index, center, -70.0 + index as f32 * 2.0))
            .collect();
        let backend = BackendSweep {
            backend: "replay".into(),
            backend_version: 1,
            points,
            dataset: None,
        };
        let report = SweepEngine::new(ReplaySweepAdapter::new([Ok(backend)]))
            .run(&plan)
            .unwrap();
        assert_eq!(
            validate_completed_sweep(&plan, &report)
                .unwrap()
                .maximum_iq_bytes,
            validated.maximum_iq_bytes
        );

        let mut tampered = report.clone();
        tampered.noise_floor_dbfs += 1.0;
        assert_eq!(
            validate_completed_sweep(&plan, &tampered).unwrap_err().code,
            "report_aggregate"
        );
    }

    #[test]
    fn spectral_summary_uses_the_same_iq_window_for_frequency_snr_and_bandwidth() {
        let center_hz = 433_920_000_u64;
        let sample_rate_hz = 2_100_000_u64;
        let fft_size = 4_096_usize;
        let tone_bin = 400_usize;
        let mut iq = Vec::with_capacity(fft_size * 4);
        for index in 0..fft_size {
            let phase =
                2.0 * std::f64::consts::PI * tone_bin as f64 * index as f64 / fft_size as f64;
            let i = (1_000.0 * phase.cos()).round() as i16;
            let q = (1_000.0 * phase.sin()).round() as i16;
            iq.extend_from_slice(&i.to_le_bytes());
            iq.extend_from_slice(&q.to_le_bytes());
        }
        let summary =
            spectral_summary_ci16(&iq, fft_size as u64, center_hz, sample_rate_hz).unwrap();
        let expected_peak =
            center_hz + (tone_bin as f64 * sample_rate_hz as f64 / fft_size as f64).round() as u64;
        assert_eq!(summary.fft_size, 4_096);
        assert_eq!(summary.segment_count, 1);
        assert!(summary.peak_frequency_hz.abs_diff(expected_peak) <= 1);
        assert!(summary.measured_snr_db > 40.0);
        assert!(summary.estimated_center_hz.abs_diff(expected_peak) <= 2_000);
        assert!(summary.occupied_bandwidth_hz < 10_000);
    }

    #[test]
    fn validates_and_merges_adjacent_active_points() {
        let points = vec![
            point(0, 2_440_000_000, -70.0),
            point(1, 2_442_000_000, -69.0),
            point(2, 2_444_000_000, -40.0),
            point(3, 2_446_000_000, -38.0),
            point(4, 2_448_000_000, -68.0),
        ];
        let replay = ReplaySweepAdapter::new([Ok(BackendSweep {
            backend: "replay".to_owned(),
            backend_version: 1,
            points,
            dataset: None,
        })]);
        let mut engine = SweepEngine::new(replay);
        let report = engine.run(&plan()).unwrap();
        assert_eq!(report.candidates.len(), 1);
        assert_eq!(report.candidates[0].center_hz, 2_446_000_000);
        assert_eq!(report.candidates[0].point_count, 2);
        let observation = report.planner_observation(
            5,
            HealthSummary {
                sdr_online: true,
                can_retune: true,
                can_capture_iq: true,
                recognizer_available: false,
                dropped_observations: 0,
            },
            20,
        );
        assert_eq!(observation.candidates.len(), 1);
        assert_eq!(observation.candidates[0].id, "survey-24g-1");
        assert_eq!(observation.candidates[0].bandwidth_hz, 4_500_000);
        let latest = observation.latest_sweep.as_ref().unwrap();
        assert_eq!(latest.sweep_id, "survey-24g");
        assert_eq!(latest.fixed_gain_db, 20);
        assert_eq!(latest.points.len(), 5);
        assert_eq!(latest.points[3], (2_446_000_000, -38.0));
    }

    #[test]
    fn planner_observation_bounds_a_wide_contiguous_region() {
        let report = SweepReport {
            sweep_id: "wide".into(),
            session_generation: 1,
            backend: "replay".into(),
            backend_version: 1,
            estimated_duration_ms: 1,
            elapsed_ms: 1,
            noise_floor_dbfs: -50.0,
            points: Vec::new(),
            candidates: vec![SweepCandidate {
                id: "wide-1".into(),
                start_hz: 100_000_000,
                stop_hz: 254_000_000,
                center_hz: 150_000_000,
                bandwidth_hz: 154_000_000,
                peak_dbfs: -10.0,
                snr_db: 40.0,
                point_count: 19,
            }],
            dataset: None,
        };
        let observation = report.planner_observation(
            0,
            HealthSummary {
                sdr_online: true,
                can_retune: true,
                can_capture_iq: true,
                recognizer_available: false,
                dropped_observations: 0,
            },
            20,
        );
        assert_eq!(observation.candidates[0].center_hz, 150_000_000);
        assert_eq!(
            observation.candidates[0].bandwidth_hz,
            MAX_PLANNER_CANDIDATE_BANDWIDTH_HZ
        );
    }

    #[test]
    fn candidate_inspection_updates_only_the_selected_candidate() {
        let report = SweepReport {
            sweep_id: "inspect-7".into(),
            session_generation: 1,
            backend: "replay".into(),
            backend_version: 1,
            estimated_duration_ms: 1_250,
            elapsed_ms: 1_100,
            noise_floor_dbfs: -33.0,
            points: vec![SweepPoint {
                point_index: 0,
                request_id: 1,
                session_generation: 1,
                requested_center_hz: 2_454_000_000,
                actual_center_hz: 2_454_000_000,
                sample_rate_hz: 10_000_000,
                rf_bandwidth_hz: 10_000_000,
                sequence: 8,
                dropped_samples: 0,
                overflow: false,
                captured_samples: 4_096,
                band_power_dbfs: -25.0,
                spectral: SpectralSummary {
                    schema_version: SPECTRAL_SUMMARY_SCHEMA_VERSION,
                    algorithm_id: SPECTRAL_SUMMARY_ALGORITHM_ID.into(),
                    fft_size: 4_096,
                    segment_count: 1,
                    bin_width_hz: 10_000_000.0 / 4_096.0,
                    peak_frequency_hz: 2_455_100_000,
                    peak_power_dbfs: -25.0,
                    noise_floor_dbfs: -53.0,
                    measured_snr_db: 28.0,
                    estimated_center_hz: 2_455_000_000,
                    occupied_start_hz: 2_454_500_000,
                    occupied_stop_hz: 2_455_500_000,
                    occupied_bandwidth_hz: 1_002_442,
                },
                clipped_samples: 0,
                status_flags: 0,
                elapsed_us: 500,
                timeout: ExecutionTimeoutMetadata {
                    limit_ms: 500,
                    elapsed_us: 500,
                    timed_out: false,
                },
                health: ExecutionHealthMetadata {
                    healthy: true,
                    flags: 0,
                    source: "replay".into(),
                },
                rx_input: RxInputIdentity::fixed_p201_rx1_fixture(),
            }],
            candidates: Vec::new(),
            dataset: None,
        };
        let health = HealthSummary {
            sdr_online: true,
            can_retune: true,
            can_capture_iq: true,
            recognizer_available: false,
            dropped_observations: 0,
        };
        let previous = ObservationSummary {
            age_ms: 0,
            health: health.clone(),
            candidates: vec![
                CandidateSummary {
                    id: "selected".into(),
                    center_hz: 2_454_000_000,
                    bandwidth_hz: 10_000_000,
                    peak_dbfs: -24.0,
                    snr_db: 29.0,
                    age_ms: 0,
                },
                CandidateSummary {
                    id: "other".into(),
                    center_hz: 94_000_000,
                    bandwidth_hz: 10_000_000,
                    peak_dbfs: -40.0,
                    snr_db: 13.0,
                    age_ms: 50,
                },
            ],
            latest_sweep: None,
            recognition: None,
        };
        let observation = report
            .planner_inspection_observation(&previous, "selected", health)
            .unwrap();
        assert_eq!(observation.candidates[0].peak_dbfs, -25.0);
        assert_eq!(observation.candidates[0].snr_db, 28.0);
        assert_eq!(observation.candidates[0].center_hz, 2_455_000_000);
        assert_eq!(observation.candidates[0].bandwidth_hz, 1_002_442);
        assert_eq!(observation.candidates[0].age_ms, 0);
        assert_eq!(observation.candidates[1].age_ms, 1_150);
    }

    #[test]
    fn rejects_gap_larger_than_usable_bandwidth() {
        let mut invalid = plan();
        invalid.frequencies = SweepFrequencies::Centers {
            centers_hz: vec![2_400_000_000, 2_410_000_000],
        };
        assert_eq!(validate_plan(&invalid).unwrap_err().code, "coverage_gap");
    }

    #[test]
    fn derives_finite_iq_bounds_and_rejects_point_overload_before_backend() {
        struct MustNotRunBackend;

        impl SweepBackend for MustNotRunBackend {
            fn run_points(
                &mut self,
                _plan: &ValidatedSweepPlan,
            ) -> Result<BackendSweep, SweepError> {
                panic!("an oversized plan must be rejected before the backend is called");
            }
        }

        let mut boundary = plan();
        boundary.frame_samples = 4_096;
        boundary.aggregate_frames = 16;
        let validated = validate_plan(&boundary).unwrap();
        assert_eq!(validated.samples_per_point, 65_536);
        assert_eq!(validated.iq_bytes_per_point, MAX_INLINE_IQ_BYTES_PER_POINT);
        assert_eq!(
            validated.maximum_iq_bytes,
            validated.centers_hz.len() as u64 * MAX_INLINE_IQ_BYTES_PER_POINT
        );

        boundary.aggregate_frames = 17;
        let error = SweepEngine::new(MustNotRunBackend)
            .run(&boundary)
            .unwrap_err();
        assert_eq!(error.code, "agx_capture_size");
    }

    #[test]
    fn software_adapter_transfers_iq_for_agx_aggregation_and_restores() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let iq = vec![0_u8; 64 * 4];
            let inline = format!("{{\"schema_version\":1,\"request_id\":5,\"status\":\"ok\",\"generation\":9,\"session_generation\":9,\"samples_captured\":64,\"bytes_transferred\":256,\"sequence\":45,\"dropped_samples\":0,\"overflow\":false,\"timeout\":{{\"limit_ms\":500,\"elapsed_us\":500,\"timed_out\":false}},\"health\":{{\"healthy\":true,\"flags\":0,\"source\":\"iio_adapter\"}},\"iq_base64\":\"{}\"}}\n", test_base64(&iq));
            let responses = [
                "{\"schema_version\":1,\"request_id\":1,\"status\":\"ok\",\"server\":\"p201-sdrd\",\"protocol\":\"SDRD/1\",\"mode\":\"controlled\",\"mutating_commands\":true}\n",
                "{\"schema_version\":1,\"request_id\":2,\"status\":\"ok\",\"mode\":\"controlled\",\"iio_visible\":true,\"radio_control\":true,\"raw_iq_capture\":true,\"software_summary\":true,\"max_capture_bytes\":67108864,\"fpga_backend\":\"disabled\",\"fpga_identity_valid\":false,\"fpga_summary_version\":0,\"fpga_abi_version\":0,\"fpga_capability\":0,\"fpga_aggregate\":false}\n",
                "{\"schema_version\":1,\"request_id\":3,\"status\":\"ok\",\"generation\":9,\"session_generation\":9,\"session_state\":\"owned\",\"restore_armed\":true}\n",
                "{\"schema_version\":1,\"request_id\":4,\"status\":\"ok\",\"generation\":9,\"session_generation\":9,\"center_hz\":2440000000,\"sample_rate_hz\":3000000,\"rf_bandwidth_hz\":2500000,\"gain_mode\":\"manual\",\"hardware_gain_db\":30,\"enabled_channels\":1}\n",
                inline.as_str(),
                "{\"schema_version\":1,\"request_id\":6,\"status\":\"ok\",\"generation\":9,\"session_generation\":9,\"stopped\":true,\"restored\":true}\n",
                "{\"schema_version\":1,\"request_id\":7,\"status\":\"ok\",\"closing\":true}\n",
            ];
            let (mut stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            for (index, response) in responses.into_iter().enumerate() {
                let mut request = String::new();
                reader.read_line(&mut request).unwrap();
                if index == 3 {
                    assert!(request.contains(" manual 30 1"));
                }
                if index == 4 {
                    assert!(request.starts_with("SDRD/1 CAPTURE_IQ_INLINE 5 9 64 256 "));
                }
                let response = with_fixed_rx_input(response);
                stream.write_all(response.as_bytes()).unwrap();
                stream.flush().unwrap();
            }
        });
        let mut one_point = plan();
        one_point.frequencies = SweepFrequencies::Centers {
            centers_hz: vec![2_440_000_000],
        };
        one_point.gain_db = Some(30);
        one_point.frame_samples = 64;
        one_point.aggregate_frames = 1;
        let report = SweepEngine::new(SdrdSoftwareSweepAdapter::new(
            address,
            Duration::from_secs(1),
        ))
        .run(&one_point)
        .unwrap();
        assert_eq!(report.backend, "agx_iq_software_aggregate");
        assert_eq!(report.points[0].sequence, 45);
        server.join().unwrap();
    }

    #[test]
    fn software_adapter_fails_closed_without_capability() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let responses = [
                "{\"schema_version\":1,\"request_id\":1,\"status\":\"ok\",\"server\":\"p201-sdrd\",\"protocol\":\"SDRD/1\",\"mode\":\"controlled\",\"mutating_commands\":true}\n",
                "{\"schema_version\":1,\"request_id\":2,\"status\":\"ok\",\"mode\":\"controlled\",\"iio_visible\":true,\"radio_control\":true,\"raw_iq_capture\":false,\"software_summary\":true,\"max_capture_bytes\":67108864,\"fpga_backend\":\"disabled\",\"fpga_identity_valid\":false,\"fpga_summary_version\":0,\"fpga_abi_version\":0,\"fpga_capability\":0,\"fpga_aggregate\":false}\n",
                "{\"schema_version\":1,\"request_id\":3,\"status\":\"ok\",\"closing\":true}\n",
            ];
            let (mut stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            for response in responses {
                let mut request = String::new();
                reader.read_line(&mut request).unwrap();
                assert!(!request.contains("START_SESSION"));
                let response = with_fixed_rx_input(response);
                stream.write_all(response.as_bytes()).unwrap();
                stream.flush().unwrap();
            }
        });
        let error = SweepEngine::new(SdrdSoftwareSweepAdapter::new(
            address,
            Duration::from_secs(1),
        ))
        .run(&plan())
        .unwrap_err();
        assert_eq!(error.code, "raw_iq_transport_unavailable");
        server.join().unwrap();
    }

    #[test]
    fn software_summary_failure_stops_and_restores_session() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let responses = [
                "{\"schema_version\":1,\"request_id\":1,\"status\":\"ok\",\"server\":\"p201-sdrd\",\"protocol\":\"SDRD/1\",\"mode\":\"controlled\",\"mutating_commands\":true}\n",
                "{\"schema_version\":1,\"request_id\":2,\"status\":\"ok\",\"mode\":\"controlled\",\"iio_visible\":true,\"radio_control\":true,\"raw_iq_capture\":true,\"software_summary\":true,\"max_capture_bytes\":67108864,\"fpga_backend\":\"disabled\",\"fpga_identity_valid\":false,\"fpga_summary_version\":0,\"fpga_abi_version\":0,\"fpga_capability\":0,\"fpga_aggregate\":false}\n",
                "{\"schema_version\":1,\"request_id\":3,\"status\":\"ok\",\"generation\":9,\"session_generation\":9,\"session_state\":\"owned\",\"restore_armed\":true}\n",
                "{\"schema_version\":1,\"request_id\":4,\"status\":\"ok\",\"generation\":9,\"session_generation\":9,\"center_hz\":2440000000,\"sample_rate_hz\":3000000,\"rf_bandwidth_hz\":2500000,\"gain_mode\":\"slow_attack\",\"enabled_channels\":1}\n",
                "{\"schema_version\":1,\"request_id\":5,\"status\":\"error\",\"error\":\"capture_timeout\"}\n",
                "{\"schema_version\":1,\"request_id\":6,\"status\":\"ok\",\"generation\":9,\"session_generation\":9,\"stopped\":true,\"restored\":true}\n",
                "{\"schema_version\":1,\"request_id\":7,\"status\":\"ok\",\"closing\":true}\n",
            ];
            let (mut stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            for (index, response) in responses.into_iter().enumerate() {
                let mut request = String::new();
                reader.read_line(&mut request).unwrap();
                if index == 5 {
                    assert!(request.starts_with("SDRD/1 STOP_SESSION 6 9"));
                }
                let response = with_fixed_rx_input(response);
                stream.write_all(response.as_bytes()).unwrap();
                stream.flush().unwrap();
            }
        });
        let mut one_point = plan();
        one_point.frequencies = SweepFrequencies::Centers {
            centers_hz: vec![2_440_000_000],
        };
        let error = SweepEngine::new(SdrdSoftwareSweepAdapter::new(
            address,
            Duration::from_secs(1),
        ))
        .run(&one_point)
        .unwrap_err();
        assert_eq!(error.code, "remote_error");
        server.join().unwrap();
    }

    #[test]
    fn clipped_fixed_gain_agx_iq_fails_and_restores_session() {
        inline_failure_restores(false, "summary_clipped");
    }

    #[test]
    fn transport_overflow_fails_and_restores_session() {
        inline_failure_restores(true, "agx_capture_shape");
    }

    fn inline_failure_restores(overflow: bool, expected_code: &str) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let mut iq = vec![0_u8; 64 * 4];
            if !overflow {
                iq[..2].copy_from_slice(&2047_i16.to_le_bytes());
            }
            let inline = format!("{{\"schema_version\":1,\"request_id\":5,\"status\":\"ok\",\"generation\":9,\"session_generation\":9,\"samples_captured\":64,\"bytes_transferred\":256,\"sequence\":46,\"dropped_samples\":0,\"overflow\":false,\"timeout\":{{\"limit_ms\":500,\"elapsed_us\":500,\"timed_out\":false}},\"health\":{{\"healthy\":true,\"flags\":0,\"source\":\"iio_adapter\"}},\"iq_base64\":\"{}\"}}\n", test_base64(&iq));
            let mut payload: serde_json::Value = serde_json::from_str(&inline).unwrap();
            payload["overflow"] = serde_json::json!(overflow);
            let inline = serde_json::to_string(&payload).unwrap() + "\n";
            let responses = [
                "{\"schema_version\":1,\"request_id\":1,\"status\":\"ok\",\"server\":\"p201-sdrd\",\"protocol\":\"SDRD/1\",\"mode\":\"controlled\",\"mutating_commands\":true}\n",
                "{\"schema_version\":1,\"request_id\":2,\"status\":\"ok\",\"mode\":\"controlled\",\"iio_visible\":true,\"radio_control\":true,\"raw_iq_capture\":true,\"software_summary\":true,\"max_capture_bytes\":67108864,\"fpga_backend\":\"disabled\",\"fpga_identity_valid\":false,\"fpga_summary_version\":0,\"fpga_abi_version\":0,\"fpga_capability\":0,\"fpga_aggregate\":false}\n",
                "{\"schema_version\":1,\"request_id\":3,\"status\":\"ok\",\"generation\":9,\"session_generation\":9,\"session_state\":\"owned\",\"restore_armed\":true}\n",
                "{\"schema_version\":1,\"request_id\":4,\"status\":\"ok\",\"generation\":9,\"session_generation\":9,\"center_hz\":2440000000,\"sample_rate_hz\":3000000,\"rf_bandwidth_hz\":2500000,\"gain_mode\":\"manual\",\"hardware_gain_db\":20,\"enabled_channels\":1}\n",
                inline.as_str(),
                "{\"schema_version\":1,\"request_id\":6,\"status\":\"ok\",\"generation\":9,\"session_generation\":9,\"stopped\":true,\"restored\":true}\n",
                "{\"schema_version\":1,\"request_id\":7,\"status\":\"ok\",\"closing\":true}\n",
            ];
            let (mut stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            for (index, response) in responses.into_iter().enumerate() {
                let mut request = String::new();
                reader.read_line(&mut request).unwrap();
                if index == 3 {
                    assert!(request.contains(" manual 20 1"));
                }
                if index == 5 {
                    assert!(request.starts_with("SDRD/1 STOP_SESSION 6 9"));
                }
                let response = with_fixed_rx_input(response);
                stream.write_all(response.as_bytes()).unwrap();
                stream.flush().unwrap();
            }
        });
        let mut one_point = plan();
        one_point.frequencies = SweepFrequencies::Centers {
            centers_hz: vec![2_440_000_000],
        };
        one_point.gain_db = Some(20);
        one_point.frame_samples = 64;
        one_point.aggregate_frames = 1;
        let error = SweepEngine::new(SdrdSoftwareSweepAdapter::new(
            address,
            Duration::from_secs(1),
        ))
        .run(&one_point)
        .unwrap_err();
        assert_eq!(error.code, expected_code);
        server.join().unwrap();
    }

    #[test]
    fn accepts_768_non_divisible_range_points_and_rejects_769() {
        let mut boundary = plan();
        boundary.sample_rate_hz = 10_000_000;
        boundary.rf_bandwidth_hz = 10_000_000;
        boundary.frame_samples = 4_096;
        boundary.aggregate_frames = 1;
        boundary.point_timeout_ms = 250;
        boundary.frequencies = SweepFrequencies::Range {
            start_hz: 70_000_000,
            stop_hz: 5_432_000_001,
            step_hz: 7_000_000,
        };
        let validated = validate_plan(&boundary).unwrap();
        assert_eq!(validated.centers_hz.len(), 768);
        assert_eq!(validated.centers_hz.last(), Some(&5_432_000_001));

        boundary.frequencies = SweepFrequencies::Range {
            start_hz: 70_000_000,
            stop_hz: 5_439_000_001,
            step_hz: 7_000_000,
        };
        assert_eq!(validate_plan(&boundary).unwrap_err().code, "point_count");
    }
}
