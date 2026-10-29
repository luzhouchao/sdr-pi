//! Derived statistics and bounded offline IQ analysis for saved sweeps; no radio access.
use super::{
    internal_error, load_capture_result, open_result_database, validate_managed_dataset, ApiError,
    ApiResult, AppState, SweepPlot,
};
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::Html,
    Json,
};
use rusqlite::params;
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, VecDeque},
    fs,
    io::{Read, Seek, SeekFrom},
    os::unix::fs::OpenOptionsExt,
    process::Stdio,
    time::Duration,
};
use tokio::{io::AsyncWriteExt, process::Command, sync::Semaphore};

const MAX_SWEEPS: usize = 128;
const MAX_GROUPS: usize = 2_048;
const MAX_ALERTS: usize = 200;
static ANALYSIS_GATE: Semaphore = Semaphore::const_new(1);

#[derive(Deserialize)]
pub(super) struct Request {
    session_id: String,
    threshold_db: Option<f32>,
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize)]
struct Profile {
    center_hz: u64,
    sample_rate_hz: u64,
    rf_bandwidth_hz: u64,
    gain_db: i16,
    samples: u64,
    algorithm_id: String,
    fft_size: u32,
}

#[derive(Serialize)]
struct FrequencyStats {
    profile: Profile,
    observations: u32,
    above_threshold: u32,
    last_power_dbfs: f32,
    last_reference_dbfs: f32,
    last_saved_at_ms: u64,
    result_id: i64,
    point_index: usize,
    spectral: sdr_agent_controller::sweep::SpectralSummary,
    #[serde(skip)]
    previous_above: bool,
}

#[derive(Serialize)]
struct Alert {
    result_id: i64,
    saved_at_ms: u64,
    center_hz: u64,
    gain_db: i16,
    power_dbfs: f32,
    reference_dbfs: f32,
    first_observation: bool,
}

#[derive(Serialize)]
pub(super) struct Report {
    session_id: String,
    threshold_db: f32,
    sweeps_considered: usize,
    legacy_sweeps_excluded: usize,
    clipped_points_excluded: usize,
    truncated_sweeps: bool,
    truncated_groups: bool,
    alerts_truncated: bool,
    groups: Vec<FrequencyStats>,
    alerts: Vec<Alert>,
}

pub(super) async fn page() -> Html<&'static str> {
    Html(include_str!("../public/monitoring.html"))
}

pub(super) async fn license() -> &'static str {
    include_str!("../vendor/rfobserver/LICENSE")
}

pub(super) async fn query(
    State(state): State<AppState>,
    Query(request): Query<Request>,
) -> ApiResult<Json<Report>> {
    let configured_threshold = {
        let inner = state.inner.lock().await;
        inner
            .persisted
            .sessions
            .iter()
            .find(|session| session.id == request.session_id)
            .and_then(|session| session.monitor_threshold_db)
            .unwrap_or(12) as f32
    };
    let threshold_db = request.threshold_db.unwrap_or(configured_threshold);
    if request.session_id.is_empty()
        || request.session_id.len() > 128
        || request.session_id.chars().any(char::is_control)
        || !threshold_db.is_finite()
        || !(1.0..=60.0).contains(&threshold_db)
    {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "无效的会话或阈值（1–60 dB）".into(),
        ));
    }
    let conn = open_result_database(&state.config.result_db_path)?;
    let mut stmt = conn.prepare("SELECT id, created_at_ms FROM capture_results WHERE session_id = ?1 ORDER BY created_at_ms DESC, id DESC LIMIT ?2").map_err(internal_error)?;
    let mut rows = stmt
        .query_map(
            params![request.session_id, (MAX_SWEEPS + 1) as i64],
            |row| Ok((row.get::<_, i64>(0)?, row.get::<_, i64>(1)?)),
        )
        .map_err(internal_error)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(internal_error)?;
    let truncated = rows.len() > MAX_SWEEPS;
    rows.truncate(MAX_SWEEPS);
    rows.reverse();
    let mut payload_query = conn
        .prepare("SELECT payload_json FROM capture_results WHERE id = ?1 AND session_id = ?2")
        .map_err(internal_error)?;
    let mut accumulator = Accumulator::default();
    for (id, saved_at) in rows {
        let payload: String = payload_query
            .query_row(params![id, request.session_id], |row| row.get(0))
            .map_err(internal_error)?;
        let plot: SweepPlot = serde_json::from_str(&payload).map_err(internal_error)?;
        accumulator.push(id, saved_at.max(0) as u64, &plot, threshold_db);
    }
    Ok(Json(accumulator.finish(
        request.session_id,
        threshold_db,
        truncated,
    )))
}

#[derive(Default)]
struct Accumulator {
    groups: BTreeMap<Profile, FrequencyStats>,
    alerts: VecDeque<Alert>,
    scans: usize,
    legacy: usize,
    clipped: usize,
    truncated_groups: bool,
    alerts_truncated: bool,
}

impl Accumulator {
    fn push(&mut self, id: i64, timestamp: u64, plot: &SweepPlot, threshold_db: f32) {
        self.scans += 1;
        if plot.point_analysis.len() != plot.points.len() || plot.point_analysis.is_empty() {
            self.legacy += 1;
            return;
        }
        for (point_index, (point, analysis)) in
            plot.points.iter().zip(&plot.point_analysis).enumerate()
        {
            if analysis.clipped_samples > 0
                || analysis.center_hz != point.0
                || !point.1.is_finite()
                || !plot.noise_floor_dbfs.is_finite()
            {
                self.clipped += 1;
                continue;
            }
            let profile = Profile {
                center_hz: point.0,
                sample_rate_hz: analysis.sample_rate_hz,
                rf_bandwidth_hz: analysis.rf_bandwidth_hz,
                gain_db: plot.gain_db,
                samples: analysis.captured_samples,
                algorithm_id: analysis.spectral.algorithm_id.clone(),
                fft_size: analysis.spectral.fft_size,
            };
            if !self.groups.contains_key(&profile) && self.groups.len() >= MAX_GROUPS {
                self.truncated_groups = true;
                continue;
            }
            let above = analysis.spectral.measured_snr_db >= threshold_db;
            let group = self
                .groups
                .entry(profile.clone())
                .or_insert_with(|| FrequencyStats {
                    profile,
                    observations: 0,
                    above_threshold: 0,
                    last_power_dbfs: point.1,
                    last_reference_dbfs: plot.noise_floor_dbfs,
                    last_saved_at_ms: timestamp,
                    result_id: id,
                    point_index,
                    spectral: analysis.spectral.clone(),
                    previous_above: false,
                });
            let first = group.observations == 0;
            if above && (first || !group.previous_above) {
                if self.alerts.len() == MAX_ALERTS {
                    self.alerts.pop_front();
                    self.alerts_truncated = true;
                }
                self.alerts.push_back(Alert {
                    result_id: id,
                    saved_at_ms: timestamp,
                    center_hz: point.0,
                    gain_db: plot.gain_db,
                    power_dbfs: analysis.spectral.peak_power_dbfs,
                    reference_dbfs: analysis.spectral.noise_floor_dbfs,
                    first_observation: first,
                });
            }
            group.observations += 1;
            group.above_threshold += u32::from(above);
            group.previous_above = above;
            group.last_power_dbfs = point.1;
            group.last_reference_dbfs = plot.noise_floor_dbfs;
            group.last_saved_at_ms = timestamp;
            group.result_id = id;
            group.point_index = point_index;
            group.spectral = analysis.spectral.clone();
        }
    }
    fn finish(self, session_id: String, threshold_db: f32, truncated_sweeps: bool) -> Report {
        Report {
            session_id,
            threshold_db,
            sweeps_considered: self.scans,
            legacy_sweeps_excluded: self.legacy,
            clipped_points_excluded: self.clipped,
            truncated_sweeps,
            truncated_groups: self.truncated_groups,
            alerts_truncated: self.alerts_truncated,
            groups: self.groups.into_values().collect(),
            alerts: self.alerts.into_iter().rev().collect(),
        }
    }
}

pub(super) async fn spectrogram(
    State(state): State<AppState>,
    Path((id, index)): Path<(i64, usize)>,
) -> ApiResult<Json<serde_json::Value>> {
    if id <= 0 {
        return Err(ApiError(StatusCode::BAD_REQUEST, "采集结果 ID 无效".into()));
    }
    let _permit = ANALYSIS_GATE.try_acquire().map_err(|_| {
        ApiError(
            StatusCode::TOO_MANY_REQUESTS,
            "分析正在进行，请稍后重试".into(),
        )
    })?;
    let result = load_capture_result(&state.config.result_db_path, id)?;
    let plot = result.sweep_plot;
    let dataset = plot
        .dataset
        .as_ref()
        .ok_or_else(|| ApiError(StatusCode::BAD_REQUEST, "此扫描未保存 IQ".into()))?;
    if plot.point_analysis.len() != plot.points.len() || index >= plot.points.len() {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "此扫描没有可用的逐点分析数据".into(),
        ));
    }
    let selected = &plot.point_analysis[index];
    if !(256..=65_536).contains(&selected.captured_samples) || selected.clipped_samples != 0 {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "此窗口的样本数量或质量不适合分析".into(),
        ));
    }
    let (data_path, meta_path) =
        validate_managed_dataset(dataset, &state.config.capture_root, plot.points.len(), true)?;
    let metadata: serde_json::Value =
        serde_json::from_slice(&fs::read(meta_path).map_err(internal_error)?)
            .map_err(internal_error)?;
    let rate = metadata
        .pointer("/global/core:sample_rate")
        .and_then(serde_json::Value::as_u64)
        .ok_or_else(|| ApiError(StatusCode::BAD_REQUEST, "SigMF 采样率缺失".into()))?;
    let captures = metadata
        .get("captures")
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| ApiError(StatusCode::BAD_REQUEST, "SigMF 频点缺失".into()))?;
    let mut offset = 0_u64;
    let mut selected_offset = 0_u64;
    for (position, (capture, analysis)) in captures.iter().zip(&plot.point_analysis).enumerate() {
        if capture
            .get("core:sample_start")
            .and_then(serde_json::Value::as_u64)
            != Some(offset)
            || capture
                .get("core:frequency")
                .and_then(serde_json::Value::as_u64)
                != Some(analysis.center_hz)
            || capture
                .get("sdrharness:point_index")
                .and_then(serde_json::Value::as_u64)
                != Some(position as u64)
            || analysis.center_hz != plot.points[position].0
            || analysis.sample_rate_hz != rate
        {
            return Err(ApiError(
                StatusCode::BAD_REQUEST,
                "SigMF 分段与扫描记录不一致".into(),
            ));
        }
        if position == index {
            selected_offset = offset;
        }
        offset = offset
            .checked_add(analysis.captured_samples)
            .ok_or_else(|| ApiError(StatusCode::BAD_REQUEST, "样本偏移无效".into()))?;
    }
    if offset.checked_mul(4) != Some(dataset.bytes) {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "SigMF 样本长度不一致".into(),
        ));
    }
    let mut file = fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(data_path)
        .map_err(internal_error)?;
    if !file.metadata().map_err(internal_error)?.is_file()
        || file.metadata().map_err(internal_error)?.len() != dataset.bytes
    {
        return Err(ApiError(StatusCode::BAD_REQUEST, "IQ 文件已改变".into()));
    }
    file.seek(SeekFrom::Start(selected_offset * 4))
        .map_err(internal_error)?;
    let mut iq = vec![0_u8; selected.captured_samples as usize * 4];
    file.read_exact(&mut iq).map_err(internal_error)?;
    let worker = async {
        let mut child = Command::new("/usr/bin/python3")
            .arg("-c")
            .arg(include_str!("rfobserver_worker.py"))
            .arg(selected.captured_samples.to_string())
            .arg(rate.to_string())
            .arg(selected.center_hz.to_string())
            .env_clear()
            .env(
                "SDR_RFOBS_SPECTRAL",
                include_str!("../vendor/rfobserver/spectral.py"),
            )
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .env("OPENBLAS_NUM_THREADS", "1")
            .env("OMP_NUM_THREADS", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .map_err(internal_error)?;
        let mut input = child.stdin.take().ok_or_else(|| {
            ApiError(StatusCode::INTERNAL_SERVER_ERROR, "分析器输入不可用".into())
        })?;
        input.write_all(&iq).await.map_err(internal_error)?;
        input.shutdown().await.map_err(internal_error)?;
        drop(input);
        let output = child.wait_with_output().await.map_err(internal_error)?;
        if !output.status.success() || output.stdout.len() > 1024 * 1024 {
            return Err(ApiError(
                StatusCode::SERVICE_UNAVAILABLE,
                "频谱分析失败，请检查分析运行环境".into(),
            ));
        }
        let value: serde_json::Value =
            serde_json::from_slice(&output.stdout).map_err(internal_error)?;
        Ok(Json(value))
    };
    tokio::time::timeout(Duration::from_secs(15), worker)
        .await
        .map_err(|_| ApiError(StatusCode::GATEWAY_TIMEOUT, "频谱分析超时".into()))?
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::SweepPointAnalysis;
    use sdr_agent_controller::sweep::SpectralSummary;

    fn plot(power: f32, gain: i16, clipped: u64) -> SweepPlot {
        SweepPlot {
            schema_version: 1,
            sweep_id: "test".into(),
            kind: "planned".into(),
            elapsed_ms: 1,
            gain_db: gain,
            noise_floor_dbfs: -60.0,
            points: vec![(100_000_000, power)],
            candidates: vec![],
            dataset: None,
            point_analysis: vec![SweepPointAnalysis {
                center_hz: 100_000_000,
                sample_rate_hz: 1_000_000,
                rf_bandwidth_hz: 800_000,
                captured_samples: 4096,
                clipped_samples: clipped,
                spectral: SpectralSummary {
                    schema_version: 1,
                    algorithm_id: "welch".into(),
                    fft_size: 1024,
                    segment_count: 4,
                    bin_width_hz: 976.5625,
                    peak_frequency_hz: 100_000_000,
                    peak_power_dbfs: power,
                    noise_floor_dbfs: -60.0,
                    measured_snr_db: (power + 60.0).max(0.0),
                    estimated_center_hz: 100_000_000,
                    occupied_start_hz: 99_999_500,
                    occupied_stop_hz: 100_000_500,
                    occupied_bandwidth_hz: 1953,
                },
            }],
        }
    }

    #[test]
    fn observations_are_profile_scoped_and_alerts_rearm_after_a_low_observation() {
        let mut legacy = plot(-30.0, 20, 0);
        legacy.point_analysis.clear();
        let scans = vec![
            (1, 1, legacy),
            (2, 2, plot(-50.0, 20, 0)),
            (3, 3, plot(-40.0, 20, 0)),
            (4, 4, plot(-39.0, 20, 0)),
            (5, 5, plot(-50.0, 20, 0)),
            (6, 6, plot(-40.0, 20, 0)),
            (7, 7, plot(-40.0, 30, 0)),
            (8, 8, plot(-40.0, 20, 1)),
        ];
        let mut accumulator = Accumulator::default();
        for (id, timestamp, plot) in &scans {
            accumulator.push(*id, *timestamp, plot, 12.0);
        }
        let result = accumulator.finish("s".into(), 12.0, false);
        assert_eq!(result.legacy_sweeps_excluded, 1);
        assert_eq!(result.clipped_points_excluded, 1);
        assert_eq!(result.groups.len(), 2);
        assert_eq!(
            (
                result.groups[0].observations,
                result.groups[0].above_threshold
            ),
            (5, 3)
        );
        assert_eq!(
            result
                .alerts
                .iter()
                .map(|a| a.result_id)
                .collect::<Vec<_>>(),
            vec![7, 6, 3]
        );
        assert!(result.alerts[0].first_observation);
    }
}
