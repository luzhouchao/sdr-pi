use crate::protocol::{CandidateSummary, HealthSummary, ObservationSummary};
use crate::sdr::{SdrError, SdrdWire};
use serde::{Deserialize, Serialize};
use std::cmp::Ordering;
use std::collections::VecDeque;
use std::error::Error;
use std::fmt;
use std::net::SocketAddr;
use std::thread;
use std::time::{Duration, Instant};

pub const MAX_POINTS: usize = 768;
const MAX_DURATION_MS: u64 = 300_000;
const ADC_FULL_SCALE: f64 = 2_048.0;
const MIN_POWER: f64 = 1.0e-20;
const MAX_PLANNER_CANDIDATE_BANDWIDTH_HZ: u64 = 10_000_000;

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
    pub estimated_duration_ms: u64,
    pub maximum_summary_bytes: u64,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SweepPoint {
    pub point_index: usize,
    pub requested_center_hz: u64,
    pub actual_center_hz: u64,
    pub sample_rate_hz: u64,
    pub rf_bandwidth_hz: u64,
    pub sequence: u64,
    pub captured_samples: u64,
    pub band_power_dbfs: f32,
    pub clipped_samples: u64,
    pub status_flags: u32,
    pub elapsed_us: u64,
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
}

impl SweepReport {
    pub fn planner_observation(&self, age_ms: u64, health: HealthSummary) -> ObservationSummary {
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
            recognition: None,
        }
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
        })
    }
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
pub struct SdrdFpgaSweepAdapter {
    address: SocketAddr,
    timeout: Duration,
}

impl SdrdFpgaSweepAdapter {
    pub fn new(address: SocketAddr, timeout: Duration) -> Self {
        Self { address, timeout }
    }
}

impl SweepBackend for SdrdFpgaSweepAdapter {
    fn run_points(&mut self, plan: &ValidatedSweepPlan) -> Result<BackendSweep, SweepError> {
        run_sdrd_points(self.address, self.timeout, plan, SummarySource::Fpga)
    }
}

#[derive(Clone)]
pub struct SdrdSoftwareSweepAdapter {
    address: SocketAddr,
    timeout: Duration,
}

impl SdrdSoftwareSweepAdapter {
    pub fn new(address: SocketAddr, timeout: Duration) -> Self {
        Self { address, timeout }
    }
}

impl SweepBackend for SdrdSoftwareSweepAdapter {
    fn run_points(&mut self, plan: &ValidatedSweepPlan) -> Result<BackendSweep, SweepError> {
        run_sdrd_points(self.address, self.timeout, plan, SummarySource::Software)
    }
}

#[derive(Clone, Copy)]
enum SummarySource {
    Fpga,
    Software,
}

fn run_sdrd_points(
    address: SocketAddr,
    timeout: Duration,
    plan: &ValidatedSweepPlan,
    source: SummarySource,
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
    if !capabilities.iio_visible || !capabilities.radio_control {
        return Err(SweepError::new(
            "radio_capability",
            "SDRD cannot own and retune the receive path",
        ));
    }
    if matches!(source, SummarySource::Fpga)
        && (!capabilities.fpga_identity_valid || !capabilities.fpga_aggregate)
    {
        let _: Result<QuitResponse, _> = wire.request("QUIT", "");
        return Err(SweepError::new(
            "fpga_aggregate_unavailable",
            "the loaded FPGA image does not expose a validated aggregate summary",
        ));
    }
    if matches!(source, SummarySource::Software) && !capabilities.software_summary {
        let _: Result<QuitResponse, _> = wire.request("QUIT", "");
        return Err(SweepError::new(
            "software_summary_unavailable",
            "SDRD does not expose the bounded receive-only software power summary",
        ));
    }

    let generation = plan.session_generation;
    let mut session_started = false;
    let execution = (|| {
        let start: StartResponse = wire.request("START_SESSION", &generation.to_string())?;
        if start.generation != generation || !start.restore_armed {
            return Err(SweepError::new(
                "session_start",
                "SDRD did not arm sweep restoration",
            ));
        }
        session_started = true;
        let mut points = Vec::with_capacity(plan.centers_hz.len());
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
            {
                return Err(SweepError::new(
                    "profile_response",
                    "SDRD sweep profile readback is inconsistent",
                ));
            }
            thread::sleep(Duration::from_millis(plan.settle_ms));
            let summary_args = format!(
                "{generation} {} {} {}",
                plan.frame_samples, plan.aggregate_frames, plan.point_timeout_ms
            );
            let command = match source {
                SummarySource::Fpga => "CAPTURE_SUMMARY",
                SummarySource::Software => "CAPTURE_POWER",
            };
            let summary: SummaryResponse = wire.request(command, &summary_args)?;
            if summary.generation != generation || summary.status_flags != 0 {
                return Err(SweepError::new(
                    "summary_quality",
                    "SDR summary reported invalid, stale, overflow, or shape flags",
                ));
            }
            if summary.rx0_clip_count != 0 {
                return Err(SweepError::new(
                    "summary_clipped",
                    "SDR summary clipped at the configured fixed gain; lower survey gain and retry",
                ));
            }
            let captured_samples = u64::from(plan.frame_samples)
                .checked_mul(u64::from(plan.aggregate_frames))
                .ok_or_else(|| SweepError::new("sample_count", "sample count overflow"))?;
            if summary.aggregate_samples != captured_samples {
                return Err(SweepError::new(
                    "summary_shape",
                    "FPGA summary sample count does not match the plan",
                ));
            }
            points.push(SweepPoint {
                point_index,
                requested_center_hz: center_hz,
                actual_center_hz: profile.center_hz,
                sample_rate_hz: profile.sample_rate_hz,
                rf_bandwidth_hz: profile.rf_bandwidth_hz,
                sequence: summary.sequence,
                captured_samples,
                band_power_dbfs: u96_power_dbfs(
                    summary.rx0_power_lo,
                    summary.rx0_power_mid,
                    summary.rx0_power_hi,
                    captured_samples,
                )?,
                clipped_samples: summary.rx0_clip_count,
                status_flags: summary.status_flags,
                elapsed_us: summary.elapsed_us,
            });
        }
        let stop: StopResponse = wire.request("STOP_SESSION", &generation.to_string())?;
        if stop.generation != generation || !stop.stopped || !stop.restored {
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
        Ok(BackendSweep {
            backend: match source {
                SummarySource::Fpga => "sdr_fpga_summary",
                SummarySource::Software => "sdr_iio_power_summary",
            }
            .to_owned(),
            backend_version: match source {
                SummarySource::Fpga => capabilities.fpga_summary_version,
                SummarySource::Software => 1,
            },
            points,
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
    if !(2_083_333..=30_720_000).contains(&plan.sample_rate_hz)
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
    for (index, point) in points.iter().enumerate() {
        if point.point_index != index
            || point.requested_center_hz != plan.centers_hz[index]
            || point.actual_center_hz.abs_diff(plan.centers_hz[index]) > 2
            || point.sample_rate_hz != plan.sample_rate_hz
            || point.rf_bandwidth_hz != plan.rf_bandwidth_hz
            || !point.band_power_dbfs.is_finite()
            || point.status_flags != 0
        {
            return Err(SweepError::new(
                "point_contract",
                "backend point violates the sweep result contract",
            ));
        }
    }
    Ok(())
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
}

impl SweepError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl From<SdrError> for SweepError {
    fn from(error: SdrError) -> Self {
        Self::new(error.code, error.message)
    }
}

impl fmt::Display for SweepError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)
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
    #[serde(rename = "raw_iq_capture")]
    _raw_iq_capture: bool,
    #[serde(default)]
    software_summary: bool,
    #[serde(rename = "max_capture_bytes")]
    _max_capture_bytes: u64,
    #[serde(rename = "fpga_backend")]
    _fpga_backend: String,
    fpga_identity_valid: bool,
    fpga_summary_version: u32,
    #[serde(rename = "fpga_abi_version")]
    _fpga_abi_version: u32,
    #[serde(rename = "fpga_capability")]
    _fpga_capability: u32,
    fpga_aggregate: bool,
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
    #[serde(rename = "session_state")]
    _session_state: String,
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
    #[serde(default)]
    hardware_gain_db: Option<i16>,
    #[serde(rename = "enabled_channels")]
    _enabled_channels: u32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SummaryResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    generation: u64,
    sequence: u64,
    aggregate_samples: u64,
    rx0_power_lo: u32,
    rx0_power_mid: u32,
    rx0_power_hi: u32,
    rx0_clip_count: u64,
    status_flags: u32,
    elapsed_us: u64,
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader, Write};
    use std::net::TcpListener;

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

    fn point(index: usize, center: u64, power: f32) -> SweepPoint {
        SweepPoint {
            point_index: index,
            requested_center_hz: center,
            actual_center_hz: center,
            sample_rate_hz: 3_000_000,
            rf_bandwidth_hz: 2_500_000,
            sequence: index as u64 + 1,
            captured_samples: 32_768,
            band_power_dbfs: power,
            clipped_samples: 0,
            status_flags: 0,
            elapsed_us: 10_000,
        }
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
                fpga_available: true,
                recognizer_available: false,
                dropped_observations: 0,
            },
        );
        assert_eq!(observation.candidates.len(), 1);
        assert_eq!(observation.candidates[0].id, "survey-24g-1");
        assert_eq!(observation.candidates[0].bandwidth_hz, 4_500_000);
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
        };
        let observation = report.planner_observation(
            0,
            HealthSummary {
                sdr_online: true,
                can_retune: true,
                can_capture_iq: true,
                fpga_available: false,
                recognizer_available: false,
                dropped_observations: 0,
            },
        );
        assert_eq!(observation.candidates[0].center_hz, 150_000_000);
        assert_eq!(
            observation.candidates[0].bandwidth_hz,
            MAX_PLANNER_CANDIDATE_BANDWIDTH_HZ
        );
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
    fn production_adapter_fails_before_start_when_fpga_is_unavailable() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let responses = [
                "{\"schema_version\":1,\"request_id\":1,\"status\":\"ok\",\"server\":\"p201-sdrd\",\"protocol\":\"SDRD/1\",\"mode\":\"controlled\",\"mutating_commands\":true}\n",
                "{\"schema_version\":1,\"request_id\":2,\"status\":\"ok\",\"mode\":\"controlled\",\"iio_visible\":true,\"radio_control\":true,\"raw_iq_capture\":true,\"max_capture_bytes\":67108864,\"fpga_backend\":\"disabled\",\"fpga_identity_valid\":false,\"fpga_summary_version\":0,\"fpga_abi_version\":0,\"fpga_capability\":0,\"fpga_aggregate\":false}\n",
                "{\"schema_version\":1,\"request_id\":3,\"status\":\"ok\",\"closing\":true}\n",
            ];
            let (mut stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            for response in responses {
                let mut request = String::new();
                reader.read_line(&mut request).unwrap();
                assert!(!request.contains("START_SESSION"));
                stream.write_all(response.as_bytes()).unwrap();
                stream.flush().unwrap();
            }
        });
        let adapter = SdrdFpgaSweepAdapter::new(address, Duration::from_secs(1));
        let error = SweepEngine::new(adapter).run(&plan()).unwrap_err();
        assert_eq!(error.code, "fpga_aggregate_unavailable");
        server.join().unwrap();
    }

    #[test]
    fn production_adapter_executes_one_summary_point_and_restores() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let responses = [
                "{\"schema_version\":1,\"request_id\":1,\"status\":\"ok\",\"server\":\"p201-sdrd\",\"protocol\":\"SDRD/1\",\"mode\":\"controlled\",\"mutating_commands\":true}\n",
                "{\"schema_version\":1,\"request_id\":2,\"status\":\"ok\",\"mode\":\"controlled\",\"iio_visible\":true,\"radio_control\":true,\"raw_iq_capture\":true,\"max_capture_bytes\":67108864,\"fpga_backend\":\"uio\",\"fpga_identity_valid\":true,\"fpga_summary_version\":1398099256,\"fpga_abi_version\":65538,\"fpga_capability\":1023,\"fpga_aggregate\":true}\n",
                "{\"schema_version\":1,\"request_id\":3,\"status\":\"ok\",\"generation\":9,\"session_state\":\"owned\",\"restore_armed\":true}\n",
                "{\"schema_version\":1,\"request_id\":4,\"status\":\"ok\",\"generation\":9,\"center_hz\":2440000000,\"sample_rate_hz\":3000000,\"rf_bandwidth_hz\":2500000,\"gain_mode\":\"slow_attack\",\"enabled_channels\":1}\n",
                "{\"schema_version\":1,\"request_id\":5,\"status\":\"ok\",\"generation\":9,\"sequence\":44,\"aggregate_samples\":32768,\"rx0_power_lo\":2147483648,\"rx0_power_mid\":0,\"rx0_power_hi\":0,\"rx0_clip_count\":0,\"status_flags\":0,\"elapsed_us\":900}\n",
                "{\"schema_version\":1,\"request_id\":6,\"status\":\"ok\",\"generation\":9,\"stopped\":true,\"restored\":true}\n",
                "{\"schema_version\":1,\"request_id\":7,\"status\":\"ok\",\"closing\":true}\n",
            ];
            let (mut stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            for response in responses {
                let mut request = String::new();
                reader.read_line(&mut request).unwrap();
                stream.write_all(response.as_bytes()).unwrap();
                stream.flush().unwrap();
            }
        });
        let mut one_point = plan();
        one_point.frequencies = SweepFrequencies::Centers {
            centers_hz: vec![2_440_000_000],
        };
        let report = SweepEngine::new(SdrdFpgaSweepAdapter::new(address, Duration::from_secs(1)))
            .run(&one_point)
            .unwrap();
        assert_eq!(report.backend, "sdr_fpga_summary");
        assert_eq!(report.points.len(), 1);
        assert_eq!(report.points[0].sequence, 44);
        server.join().unwrap();
    }

    #[test]
    fn software_adapter_uses_power_summary_and_restores() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let responses = [
                "{\"schema_version\":1,\"request_id\":1,\"status\":\"ok\",\"server\":\"p201-sdrd\",\"protocol\":\"SDRD/1\",\"mode\":\"controlled\",\"mutating_commands\":true}\n",
                "{\"schema_version\":1,\"request_id\":2,\"status\":\"ok\",\"mode\":\"controlled\",\"iio_visible\":true,\"radio_control\":true,\"raw_iq_capture\":true,\"software_summary\":true,\"max_capture_bytes\":67108864,\"fpga_backend\":\"disabled\",\"fpga_identity_valid\":false,\"fpga_summary_version\":0,\"fpga_abi_version\":0,\"fpga_capability\":0,\"fpga_aggregate\":false}\n",
                "{\"schema_version\":1,\"request_id\":3,\"status\":\"ok\",\"generation\":9,\"session_state\":\"owned\",\"restore_armed\":true}\n",
                "{\"schema_version\":1,\"request_id\":4,\"status\":\"ok\",\"generation\":9,\"center_hz\":2440000000,\"sample_rate_hz\":3000000,\"rf_bandwidth_hz\":2500000,\"gain_mode\":\"manual\",\"hardware_gain_db\":30,\"enabled_channels\":1}\n",
                "{\"schema_version\":1,\"request_id\":5,\"status\":\"ok\",\"generation\":9,\"sequence\":45,\"aggregate_samples\":32768,\"rx0_power_lo\":1073741824,\"rx0_power_mid\":0,\"rx0_power_hi\":0,\"rx0_clip_count\":0,\"status_flags\":0,\"elapsed_us\":800}\n",
                "{\"schema_version\":1,\"request_id\":6,\"status\":\"ok\",\"generation\":9,\"stopped\":true,\"restored\":true}\n",
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
                    assert!(request.starts_with("SDRD/1 CAPTURE_POWER 5 "));
                }
                stream.write_all(response.as_bytes()).unwrap();
                stream.flush().unwrap();
            }
        });
        let mut one_point = plan();
        one_point.frequencies = SweepFrequencies::Centers {
            centers_hz: vec![2_440_000_000],
        };
        one_point.gain_db = Some(30);
        let report = SweepEngine::new(SdrdSoftwareSweepAdapter::new(
            address,
            Duration::from_secs(1),
        ))
        .run(&one_point)
        .unwrap();
        assert_eq!(report.backend, "sdr_iio_power_summary");
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
                "{\"schema_version\":1,\"request_id\":2,\"status\":\"ok\",\"mode\":\"controlled\",\"iio_visible\":true,\"radio_control\":true,\"raw_iq_capture\":true,\"software_summary\":false,\"max_capture_bytes\":67108864,\"fpga_backend\":\"disabled\",\"fpga_identity_valid\":false,\"fpga_summary_version\":0,\"fpga_abi_version\":0,\"fpga_capability\":0,\"fpga_aggregate\":false}\n",
                "{\"schema_version\":1,\"request_id\":3,\"status\":\"ok\",\"closing\":true}\n",
            ];
            let (mut stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            for response in responses {
                let mut request = String::new();
                reader.read_line(&mut request).unwrap();
                assert!(!request.contains("START_SESSION"));
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
        assert_eq!(error.code, "software_summary_unavailable");
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
                "{\"schema_version\":1,\"request_id\":3,\"status\":\"ok\",\"generation\":9,\"session_state\":\"owned\",\"restore_armed\":true}\n",
                "{\"schema_version\":1,\"request_id\":4,\"status\":\"ok\",\"generation\":9,\"center_hz\":2440000000,\"sample_rate_hz\":3000000,\"rf_bandwidth_hz\":2500000,\"gain_mode\":\"slow_attack\",\"enabled_channels\":1}\n",
                "{\"schema_version\":1,\"request_id\":5,\"status\":\"error\",\"error\":\"capture_timeout\"}\n",
                "{\"schema_version\":1,\"request_id\":6,\"status\":\"ok\",\"generation\":9,\"stopped\":true,\"restored\":true}\n",
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
    fn clipped_fixed_gain_summary_fails_and_restores_session() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let responses = [
                "{\"schema_version\":1,\"request_id\":1,\"status\":\"ok\",\"server\":\"p201-sdrd\",\"protocol\":\"SDRD/1\",\"mode\":\"controlled\",\"mutating_commands\":true}\n",
                "{\"schema_version\":1,\"request_id\":2,\"status\":\"ok\",\"mode\":\"controlled\",\"iio_visible\":true,\"radio_control\":true,\"raw_iq_capture\":true,\"software_summary\":true,\"max_capture_bytes\":67108864,\"fpga_backend\":\"disabled\",\"fpga_identity_valid\":false,\"fpga_summary_version\":0,\"fpga_abi_version\":0,\"fpga_capability\":0,\"fpga_aggregate\":false}\n",
                "{\"schema_version\":1,\"request_id\":3,\"status\":\"ok\",\"generation\":9,\"session_state\":\"owned\",\"restore_armed\":true}\n",
                "{\"schema_version\":1,\"request_id\":4,\"status\":\"ok\",\"generation\":9,\"center_hz\":2440000000,\"sample_rate_hz\":3000000,\"rf_bandwidth_hz\":2500000,\"gain_mode\":\"manual\",\"hardware_gain_db\":20,\"enabled_channels\":1}\n",
                "{\"schema_version\":1,\"request_id\":5,\"status\":\"ok\",\"generation\":9,\"sequence\":46,\"aggregate_samples\":32768,\"rx0_power_lo\":1073741824,\"rx0_power_mid\":0,\"rx0_power_hi\":0,\"rx0_clip_count\":1,\"status_flags\":0,\"elapsed_us\":800}\n",
                "{\"schema_version\":1,\"request_id\":6,\"status\":\"ok\",\"generation\":9,\"stopped\":true,\"restored\":true}\n",
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
                stream.write_all(response.as_bytes()).unwrap();
                stream.flush().unwrap();
            }
        });
        let mut one_point = plan();
        one_point.frequencies = SweepFrequencies::Centers {
            centers_hz: vec![2_440_000_000],
        };
        one_point.gain_db = Some(20);
        let error = SweepEngine::new(SdrdSoftwareSweepAdapter::new(
            address,
            Duration::from_secs(1),
        ))
        .run(&one_point)
        .unwrap_err();
        assert_eq!(error.code, "summary_clipped");
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
