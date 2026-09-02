use axum::{
    extract::{Path, State},
    http::{header, StatusCode},
    response::{sse::Event as SseEvent, sse::KeepAlive, Html, IntoResponse, Response, Sse},
    routing::{get, post},
    Json, Router,
};
use rusqlite::{params, Connection, OptionalExtension};
use sdr_agent_controller::{
    policy::ControllerPolicy,
    protocol::{
        ObservationSummary, PlanRequest, MAX_CANDIDATES, MAX_FRAME_BYTES, MAX_INSTRUCTION_BYTES,
        MAX_SWEEP_POINTS,
    },
};
use serde::{Deserialize, Serialize};
use std::{
    collections::{HashSet, VecDeque},
    convert::Infallible,
    env, fs,
    io::Write,
    net::SocketAddr,
    os::unix::fs::{OpenOptionsExt, PermissionsExt},
    path::{Path as FsPath, PathBuf},
    process::Stdio,
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWriteExt},
    process::Command,
    sync::{broadcast, mpsc, Mutex},
};
use tokio_stream::{wrappers::BroadcastStream, Stream, StreamExt};

const MAX_SESSIONS: usize = 2;
const MAX_EVENTS: usize = 240;
const COMPACT_AT_EVENTS: usize = 160;
const RETAIN_AFTER_COMPACT: usize = 48;
const MAX_SUMMARY_BYTES: usize = 6_144;
const MAX_COMMAND_BYTES: usize = MAX_INSTRUCTION_BYTES;
const MAX_PROVIDER_CONFIG_BYTES: u64 = 8 * 1024;
const MAX_PROVIDER_MODELS_BYTES: usize = 512 * 1024;
const MAX_PROVIDER_MODELS: usize = 512;
const DEFAULT_CONTEXT_WINDOW: u64 = 196_608;
const MIN_CONTEXT_WINDOW: u64 = 8_192;
const MAX_CONTEXT_WINDOW: u64 = 1_000_000;
const DEFAULT_COMPRESSION_THRESHOLD_PERCENT: u8 = 90;
const MIN_COMPRESSION_THRESHOLD_PERCENT: u8 = 50;
const MAX_COMPRESSION_THRESHOLD_PERCENT: u8 = 95;
const DEFAULT_SURVEY_START_HZ: u64 = 70_000_000;
const DEFAULT_SURVEY_STOP_HZ: u64 = 6_000_000_000;
const DEFAULT_SURVEY_STEP_HZ: u64 = 8_000_000;
const DEFAULT_SURVEY_DWELL_MS: u64 = 5;
const DEFAULT_SURVEY_GAIN_DB: i16 = 20;
const MAX_SURVEY_POINTS: u64 = 768;

#[derive(Clone)]
struct Config {
    listen: SocketAddr,
    state_path: PathBuf,
    agent_binary: PathBuf,
    request_path: PathBuf,
    session_socket: PathBuf,
    sdrd_address: String,
    provider_config_path: PathBuf,
    result_db_path: PathBuf,
    capture_root: PathBuf,
}

#[derive(Clone)]
struct AppState {
    config: Config,
    inner: Arc<Mutex<Inner>>,
    process_gate: Arc<Mutex<()>>,
    model_query_gate: Arc<Mutex<()>>,
    shutdown: broadcast::Sender<()>,
    updates: broadcast::Sender<UiUpdate>,
}

struct Inner {
    persisted: PersistedState,
    runtime: Option<RuntimeHandle>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct PersistedState {
    active_session_id: Option<String>,
    sessions: Vec<Session>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Session {
    id: String,
    title: String,
    created_at_ms: u64,
    last_used_at_ms: u64,
    generation: u64,
    #[serde(default)]
    compaction_count: u64,
    status: String,
    compacted_summary: String,
    summary_pending: bool,
    events_since_compaction: usize,
    #[serde(default)]
    initial_survey: Option<InitialSurveyConfig>,
    #[serde(default = "default_initial_survey_status")]
    initial_survey_status: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    observation: Option<ObservationSummary>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    sweep_plot: Option<SweepPlot>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    model_input: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    thinking: Option<ThinkingTrace>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    decision_basis: Option<String>,
    #[serde(default)]
    save_iq: bool,
    events: VecDeque<TerminalEvent>,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct SweepPlot {
    schema_version: u8,
    sweep_id: String,
    kind: String,
    elapsed_ms: u64,
    gain_db: i16,
    noise_floor_dbfs: f32,
    points: Vec<(u64, f32)>,
    candidates: Vec<SweepPlotCandidate>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    dataset: Option<SweepDatasetView>,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct SweepDatasetView {
    format: String,
    datatype: String,
    data_path: String,
    metadata_path: String,
    bytes: u64,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct SweepPlotCandidate {
    id: String,
    start_hz: u64,
    stop_hz: u64,
    center_hz: u64,
    bandwidth_hz: u64,
    peak_dbfs: f32,
    snr_db: f32,
    point_count: usize,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
struct ThinkingTrace {
    request_id: u64,
    active: bool,
    text: String,
}

#[derive(Debug, Serialize)]
struct CaptureResultSummary {
    id: i64,
    session_id: String,
    sweep_id: String,
    kind: String,
    created_at_ms: u64,
    point_count: usize,
    candidate_count: usize,
    elapsed_ms: u64,
    gain_db: i16,
    noise_floor_dbfs: f32,
    iq_bytes: u64,
}

#[derive(Debug, Serialize)]
struct CaptureResultDetail {
    summary: CaptureResultSummary,
    sweep_plot: SweepPlot,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct TerminalEvent {
    id: u64,
    timestamp_ms: u64,
    kind: String,
    text: String,
}

#[derive(Debug, Clone, Serialize)]
struct UiUpdate {
    update_type: String,
    session_id: Option<String>,
    event: Option<TerminalEvent>,
}

#[derive(Clone)]
struct RuntimeHandle {
    session_id: String,
    tx: mpsc::Sender<ProcessCommand>,
}

enum ProcessCommand {
    Input(String),
    Shutdown,
}

#[derive(Deserialize)]
struct CreateSessionRequest {
    title: Option<String>,
}

#[derive(Deserialize)]
struct CommandRequest {
    command: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ProviderConfigFile {
    schema_version: u8,
    api: String,
    base_url: String,
    provider: String,
    model: String,
    api_key: String,
    #[serde(default = "default_context_window")]
    context_window: u64,
    #[serde(default = "default_compression_threshold_percent")]
    compression_threshold_percent: u8,
    #[serde(default = "default_initial_survey")]
    initial_survey: InitialSurveyConfig,
    #[serde(default)]
    result_storage: ResultStorageConfig,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProviderConfigRequest {
    api: String,
    base_url: String,
    provider: String,
    model: String,
    api_key: String,
    context_window: u64,
    compression_threshold_percent: u8,
    initial_survey: InitialSurveyConfig,
    result_storage: ResultStorageConfig,
}

#[derive(Debug, Serialize)]
struct ProviderConfigView {
    configured: bool,
    api: String,
    base_url: String,
    provider: String,
    model: String,
    context_window: u64,
    compression_threshold_percent: u8,
    initial_survey: InitialSurveyConfig,
    result_storage: ResultStorageConfig,
}

#[derive(Debug, Clone, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct ResultStorageConfig {
    #[serde(default)]
    save_iq: bool,
}

#[derive(Debug, Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct InitialSurveyConfig {
    mode: String,
    start_hz: u64,
    stop_hz: u64,
    step_hz: u64,
    dwell_ms: u64,
    #[serde(default = "default_survey_gain_db")]
    gain_db: i16,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProviderModelsRequest {
    base_url: String,
    #[serde(default)]
    api_key: String,
}

#[derive(Debug, Serialize)]
struct ProviderModelsView {
    models: Vec<ProviderModelView>,
}

#[derive(Debug, Clone, Eq, PartialEq, Serialize)]
struct ProviderModelView {
    id: String,
    context_window: Option<u64>,
}

#[derive(Debug)]
struct ApiError(StatusCode, String);

impl std::fmt::Display for ApiError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{}: {}", self.0, self.1)
    }
}

impl std::error::Error for ApiError {}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.0, Json(serde_json::json!({ "error": self.1 }))).into_response()
    }
}

type ApiResult<T> = Result<T, ApiError>;

#[tokio::main]
async fn main() {
    if let Err(error) = run().await {
        eprintln!("sdr_web_error={error}");
        std::process::exit(1);
    }
}

async fn run() -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::from_env()?;
    initialize_result_database(&config.result_db_path)?;
    initialize_capture_root(&config.capture_root)?;
    let persisted = load_state(&config.state_path)?;
    let (updates, _) = broadcast::channel(512);
    let (shutdown, _) = broadcast::channel(4);
    let state = AppState {
        config: config.clone(),
        inner: Arc::new(Mutex::new(Inner {
            persisted,
            runtime: None,
        })),
        process_gate: Arc::new(Mutex::new(())),
        model_query_gate: Arc::new(Mutex::new(())),
        shutdown,
        updates,
    };

    restore_active_runtime(&state).await;
    let app = Router::new()
        .route("/", get(index))
        .route("/app.js", get(app_js))
        .route("/styles.css", get(styles_css))
        .route("/api/state", get(get_state))
        .route(
            "/api/provider",
            get(get_provider_config)
                .put(save_provider_config)
                .delete(delete_provider_config),
        )
        .route("/api/provider/models", post(discover_provider_models))
        .route("/api/results", get(list_capture_results))
        .route(
            "/api/results/{id}",
            get(get_capture_result).delete(delete_capture_result),
        )
        .route("/api/events", get(events))
        .route("/api/sessions", post(create_session))
        .route("/api/sessions/{id}/activate", post(activate_session))
        .route("/api/sessions/{id}/command", post(send_command))
        .with_state(state.clone());

    println!("SDR Web Console listening on http://{}", config.listen);
    let listener = tokio::net::TcpListener::bind(config.listen).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal(state.clone()))
        .await?;
    begin_runtime_shutdown(&state).await;
    // The process actor bounds child shutdown at four seconds. Keep the Rust
    // supervisor alive long enough for that cleanup after HTTP has drained.
    tokio::time::sleep(Duration::from_secs(5)).await;
    Ok(())
}

impl Config {
    fn from_env() -> Result<Self, Box<dyn std::error::Error>> {
        let host = env::var("SDR_WEB_LISTEN_HOST").unwrap_or_else(|_| "100.102.130.52".into());
        let port = env::var("SDR_WEB_LISTEN_PORT").unwrap_or_else(|_| "8787".into());
        Ok(Self {
            listen: format!("{host}:{port}").parse()?,
            state_path: env_path(
                "SDR_WEB_STATE_PATH",
                "/var/lib/sdr-agent/web-console/state.json",
            ),
            agent_binary: env_path(
                "SDR_WEB_AGENT_BINARY",
                "/opt/sdr-agent/current/bin/sdr-agent",
            ),
            request_path: env_path("SDR_WEB_REQUEST_PATH", "/etc/sdr-agent/request.json"),
            session_socket: env_path("SDR_WEB_SESSION_SOCKET", "/run/sdr-agent/session.sock"),
            sdrd_address: env::var("SDR_WEB_SDRD_ADDRESS")
                .unwrap_or_else(|_| "192.168.1.10:43110".into()),
            provider_config_path: env_path(
                "SDR_WEB_PROVIDER_CONFIG_PATH",
                "/var/lib/sdrharness/web-console/provider.json",
            ),
            result_db_path: env_path(
                "SDR_WEB_RESULT_DB_PATH",
                "/var/lib/sdrharness/web-console/capture-results.sqlite3",
            ),
            capture_root: env_path(
                "SDR_WEB_CAPTURE_ROOT",
                "/var/lib/sdrharness/web-console/captures",
            ),
        })
    }
}

fn env_path(name: &str, default: &str) -> PathBuf {
    PathBuf::from(env::var(name).unwrap_or_else(|_| default.into()))
}

async fn index() -> Html<&'static str> {
    Html(include_str!("../public/index.html"))
}

async fn app_js() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/javascript; charset=utf-8")],
        include_str!("../public/app.js"),
    )
}

async fn styles_css() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/css; charset=utf-8")],
        include_str!("../public/styles.css"),
    )
}

async fn get_state(State(state): State<AppState>) -> Json<PersistedState> {
    Json(state.inner.lock().await.persisted.clone())
}

async fn list_capture_results(
    State(state): State<AppState>,
) -> ApiResult<Json<Vec<CaptureResultSummary>>> {
    Ok(Json(load_capture_result_summaries(
        &state.config.result_db_path,
    )?))
}

async fn get_capture_result(
    State(state): State<AppState>,
    Path(id): Path<i64>,
) -> ApiResult<Json<CaptureResultDetail>> {
    if id <= 0 {
        return Err(ApiError(StatusCode::BAD_REQUEST, "采集结果 ID 无效".into()));
    }
    Ok(Json(load_capture_result(&state.config.result_db_path, id)?))
}

async fn delete_capture_result(
    State(state): State<AppState>,
    Path(id): Path<i64>,
) -> ApiResult<Json<serde_json::Value>> {
    if id <= 0 {
        return Err(ApiError(StatusCode::BAD_REQUEST, "采集结果 ID 无效".into()));
    }
    let mut connection = open_result_database(&state.config.result_db_path)?;
    let transaction = connection.transaction().map_err(internal_error)?;
    let payload: Option<String> = transaction
        .query_row(
            "SELECT payload_json FROM capture_results WHERE id = ?1",
            params![id],
            |row| row.get(0),
        )
        .optional()
        .map_err(internal_error)?;
    let payload =
        payload.ok_or_else(|| ApiError(StatusCode::NOT_FOUND, "采集结果不存在".into()))?;
    let plot: SweepPlot = serde_json::from_str(&payload).map_err(internal_error)?;
    let (files_deleted, bytes_deleted) = if let Some(dataset) = plot.dataset.as_ref() {
        delete_managed_dataset(dataset, &state.config.capture_root)?
    } else {
        (0_u64, 0_u64)
    };
    transaction
        .execute("DELETE FROM capture_results WHERE id = ?1", params![id])
        .map_err(internal_error)?;
    transaction.commit().map_err(internal_error)?;
    Ok(Json(serde_json::json!({
        "deleted": id,
        "files_deleted": files_deleted,
        "bytes_deleted": bytes_deleted,
    })))
}

fn initialize_result_database(path: &FsPath) -> Result<(), Box<dyn std::error::Error>> {
    let connection = open_result_database(path)?;
    connection.execute_batch(
        "PRAGMA journal_mode = WAL;
         PRAGMA synchronous = FULL;
         CREATE TABLE IF NOT EXISTS capture_results (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           session_id TEXT NOT NULL,
           sweep_id TEXT NOT NULL,
           kind TEXT NOT NULL,
           created_at_ms INTEGER NOT NULL,
           point_count INTEGER NOT NULL,
           candidate_count INTEGER NOT NULL,
           elapsed_ms INTEGER NOT NULL,
           gain_db INTEGER NOT NULL,
           noise_floor_dbfs REAL NOT NULL,
           iq_bytes INTEGER NOT NULL,
           payload_json TEXT NOT NULL,
           UNIQUE(session_id, sweep_id)
         );
         CREATE INDEX IF NOT EXISTS capture_results_created
           ON capture_results(created_at_ms DESC);",
    )?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    Ok(())
}

fn initialize_capture_root(path: &FsPath) -> Result<(), Box<dyn std::error::Error>> {
    ensure_real_directory(path)?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
    Ok(())
}

fn ensure_real_directory(path: &FsPath) -> ApiResult<()> {
    if !path.exists() {
        fs::create_dir_all(path).map_err(internal_error)?;
    }
    let metadata = fs::symlink_metadata(path).map_err(internal_error)?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("受管目录必须是真实目录：{}", path.display()),
        ));
    }
    Ok(())
}

fn open_result_database(path: &FsPath) -> ApiResult<Connection> {
    let parent = path.parent().ok_or_else(|| {
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "结果数据库路径无父目录".into(),
        )
    })?;
    ensure_real_directory(parent)?;
    if path.exists() {
        let metadata = fs::symlink_metadata(path).map_err(internal_error)?;
        if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
            return Err(ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "结果数据库必须是普通文件".into(),
            ));
        }
    }
    Connection::open(path).map_err(internal_error)
}

fn load_capture_result_summaries(path: &FsPath) -> ApiResult<Vec<CaptureResultSummary>> {
    let connection = open_result_database(path)?;
    let mut statement = connection
        .prepare(
            "SELECT id, session_id, sweep_id, kind, created_at_ms, point_count,
                    candidate_count, elapsed_ms, gain_db, noise_floor_dbfs, iq_bytes
             FROM capture_results ORDER BY created_at_ms DESC, id DESC",
        )
        .map_err(internal_error)?;
    let rows = statement
        .query_map([], capture_result_summary_from_row)
        .map_err(internal_error)?;
    rows.collect::<Result<Vec<_>, _>>().map_err(internal_error)
}

fn load_capture_result(path: &FsPath, id: i64) -> ApiResult<CaptureResultDetail> {
    let connection = open_result_database(path)?;
    let result = connection
        .query_row(
            "SELECT id, session_id, sweep_id, kind, created_at_ms, point_count,
                    candidate_count, elapsed_ms, gain_db, noise_floor_dbfs, iq_bytes,
                    payload_json
             FROM capture_results WHERE id = ?1",
            params![id],
            |row| {
                let summary = capture_result_summary_from_row(row)?;
                let payload: String = row.get(11)?;
                Ok((summary, payload))
            },
        )
        .optional()
        .map_err(internal_error)?;
    let (summary, payload) =
        result.ok_or_else(|| ApiError(StatusCode::NOT_FOUND, "采集结果不存在".into()))?;
    let sweep_plot = serde_json::from_str(&payload).map_err(internal_error)?;
    Ok(CaptureResultDetail {
        summary,
        sweep_plot,
    })
}

fn capture_result_summary_from_row(
    row: &rusqlite::Row<'_>,
) -> rusqlite::Result<CaptureResultSummary> {
    Ok(CaptureResultSummary {
        id: row.get(0)?,
        session_id: row.get(1)?,
        sweep_id: row.get(2)?,
        kind: row.get(3)?,
        created_at_ms: row.get::<_, i64>(4)?.max(0) as u64,
        point_count: row.get::<_, i64>(5)?.max(0) as usize,
        candidate_count: row.get::<_, i64>(6)?.max(0) as usize,
        elapsed_ms: row.get::<_, i64>(7)?.max(0) as u64,
        gain_db: row
            .get::<_, i64>(8)?
            .clamp(i16::MIN as i64, i16::MAX as i64) as i16,
        noise_floor_dbfs: row.get::<_, f64>(9)? as f32,
        iq_bytes: row.get::<_, i64>(10)?.max(0) as u64,
    })
}

fn persist_capture_result(path: &FsPath, session_id: &str, plot: &SweepPlot) -> ApiResult<()> {
    let connection = open_result_database(path)?;
    let payload = serde_json::to_string(plot).map_err(internal_error)?;
    let iq_bytes = plot.dataset.as_ref().map_or(0, |dataset| dataset.bytes);
    connection
        .execute(
            "INSERT INTO capture_results (
               session_id, sweep_id, kind, created_at_ms, point_count, candidate_count,
               elapsed_ms, gain_db, noise_floor_dbfs, iq_bytes, payload_json
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)
             ON CONFLICT(session_id, sweep_id) DO UPDATE SET
               kind = excluded.kind,
               point_count = excluded.point_count,
               candidate_count = excluded.candidate_count,
               elapsed_ms = excluded.elapsed_ms,
               gain_db = excluded.gain_db,
               noise_floor_dbfs = excluded.noise_floor_dbfs,
               iq_bytes = excluded.iq_bytes,
               payload_json = excluded.payload_json",
            params![
                session_id,
                plot.sweep_id,
                plot.kind,
                i64::try_from(now_ms()).map_err(internal_error)?,
                i64::try_from(plot.points.len()).map_err(internal_error)?,
                i64::try_from(plot.candidates.len()).map_err(internal_error)?,
                i64::try_from(plot.elapsed_ms).map_err(internal_error)?,
                i64::from(plot.gain_db),
                f64::from(plot.noise_floor_dbfs),
                i64::try_from(iq_bytes).map_err(internal_error)?,
                payload,
            ],
        )
        .map_err(internal_error)?;
    Ok(())
}

fn validate_sweep_plot(plot: &SweepPlot, capture_root: &FsPath) -> ApiResult<()> {
    if plot.schema_version != 1
        || !matches!(plot.kind.as_str(), "initial" | "planned")
        || plot.sweep_id.is_empty()
        || plot.sweep_id.len() > 128
        || plot.sweep_id.chars().any(char::is_control)
        || plot.points.is_empty()
        || plot.points.len() > MAX_SURVEY_POINTS as usize
        || plot.candidates.len() > MAX_CANDIDATES
        || plot.elapsed_ms > 300_000
        || !(0..=60).contains(&plot.gain_db)
        || !valid_dbfs(plot.noise_floor_dbfs)
    {
        return Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "扫频结果头部或数量超出受支持范围".into(),
        ));
    }
    let mut prior_frequency = None;
    for &(frequency, power) in &plot.points {
        if !(DEFAULT_SURVEY_START_HZ..=DEFAULT_SURVEY_STOP_HZ).contains(&frequency)
            || prior_frequency.is_some_and(|prior| frequency <= prior)
            || !valid_dbfs(power)
        {
            return Err(ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "扫频频点必须严格递增，且频率和功率必须有效".into(),
            ));
        }
        prior_frequency = Some(frequency);
    }
    let mut ids = HashSet::new();
    for candidate in &plot.candidates {
        if candidate.id.is_empty()
            || candidate.id.len() > 128
            || candidate.id.chars().any(char::is_control)
            || !ids.insert(candidate.id.as_str())
            || candidate.start_hz > candidate.center_hz
            || candidate.center_hz > candidate.stop_hz
            || candidate.stop_hz.saturating_sub(candidate.start_hz) != candidate.bandwidth_hz
            || candidate.stop_hz > DEFAULT_SURVEY_STOP_HZ.saturating_add(56_000_000)
            || candidate.point_count == 0
            || candidate.point_count > plot.points.len()
            || !valid_dbfs(candidate.peak_dbfs)
            || !candidate.snr_db.is_finite()
            || !(0.0..=360.0).contains(&candidate.snr_db)
        {
            return Err(ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "扫频候选边界、标识或数值无效".into(),
            ));
        }
    }
    if let Some(dataset) = plot.dataset.as_ref() {
        validate_managed_dataset(dataset, capture_root, plot.points.len(), true)?;
    }
    Ok(())
}

fn valid_dbfs(value: f32) -> bool {
    value.is_finite() && (-360.0..=6.1).contains(&value)
}

fn validate_managed_dataset(
    dataset: &SweepDatasetView,
    capture_root: &FsPath,
    expected_captures: usize,
    require_files: bool,
) -> ApiResult<(PathBuf, PathBuf)> {
    if dataset.format != "sigmf" || dataset.datatype != "ci16_le" || dataset.bytes % 4 != 0 {
        return Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "只接受 ci16_le SigMF 扫频数据集".into(),
        ));
    }
    let data_path = managed_capture_path(
        capture_root,
        FsPath::new(&dataset.data_path),
        "sigmf-data",
        require_files,
    )?;
    let metadata_path = managed_capture_path(
        capture_root,
        FsPath::new(&dataset.metadata_path),
        "sigmf-meta",
        require_files,
    )?;
    if data_path == metadata_path || data_path.parent() != metadata_path.parent() {
        return Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "SigMF 数据和元数据必须位于同一受管目录".into(),
        ));
    }
    if data_path.exists() {
        let bytes = fs::metadata(&data_path).map_err(internal_error)?.len();
        if bytes != dataset.bytes {
            return Err(ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "SigMF 数据文件大小与结果索引不一致".into(),
            ));
        }
    }
    if require_files {
        let metadata_bytes = fs::read(&metadata_path).map_err(internal_error)?;
        if metadata_bytes.len() > 8 * 1024 * 1024 {
            return Err(ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "SigMF 元数据超过 8 MiB 安全边界".into(),
            ));
        }
        let metadata: serde_json::Value =
            serde_json::from_slice(&metadata_bytes).map_err(internal_error)?;
        let datatype = metadata
            .pointer("/global/core:datatype")
            .and_then(serde_json::Value::as_str);
        let captures = metadata
            .get("captures")
            .and_then(serde_json::Value::as_array);
        if datatype != Some("ci16_le") || captures.map(Vec::len) != Some(expected_captures) {
            return Err(ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "SigMF 元数据与扫频窗口数量不一致".into(),
            ));
        }
    }
    Ok((data_path, metadata_path))
}

fn managed_capture_path(
    capture_root: &FsPath,
    path: &FsPath,
    extension: &str,
    require_file: bool,
) -> ApiResult<PathBuf> {
    ensure_real_directory(capture_root)?;
    if !path.is_absolute() || path.extension().and_then(|value| value.to_str()) != Some(extension) {
        return Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "采集文件路径或扩展名无效".into(),
        ));
    }
    let root = fs::canonicalize(capture_root).map_err(internal_error)?;
    if path.exists() {
        let metadata = fs::symlink_metadata(path).map_err(internal_error)?;
        if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
            return Err(ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "采集文件必须是普通文件且不能是符号链接".into(),
            ));
        }
        let canonical = fs::canonicalize(path).map_err(internal_error)?;
        if !canonical.starts_with(&root) {
            return Err(ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "采集文件不属于 AGX 受管目录".into(),
            ));
        }
        Ok(canonical)
    } else if require_file {
        Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "采集文件不存在".into(),
        ))
    } else {
        let parent = path.parent().ok_or_else(|| {
            ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "采集文件路径无父目录".into(),
            )
        })?;
        let canonical_parent = fs::canonicalize(parent).map_err(internal_error)?;
        if !canonical_parent.starts_with(&root) {
            return Err(ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "采集文件不属于 AGX 受管目录".into(),
            ));
        }
        Ok(path.to_path_buf())
    }
}

fn delete_managed_dataset(
    dataset: &SweepDatasetView,
    capture_root: &FsPath,
) -> ApiResult<(u64, u64)> {
    let (data_path, metadata_path) = validate_managed_dataset(dataset, capture_root, 0, false)?;
    let mut files_deleted = 0_u64;
    let mut bytes_deleted = 0_u64;
    for path in [data_path, metadata_path] {
        if path.exists() {
            bytes_deleted =
                bytes_deleted.saturating_add(fs::metadata(&path).map_err(internal_error)?.len());
            fs::remove_file(&path).map_err(internal_error)?;
            files_deleted += 1;
        }
    }
    Ok((files_deleted, bytes_deleted))
}

async fn get_provider_config(State(state): State<AppState>) -> ApiResult<Json<ProviderConfigView>> {
    Ok(Json(load_provider_config_view(
        &state.config.provider_config_path,
    )?))
}

async fn save_provider_config(
    State(state): State<AppState>,
    Json(mut request): Json<ProviderConfigRequest>,
) -> ApiResult<Json<ProviderConfigView>> {
    if request.api_key.trim().is_empty() {
        let saved = load_provider_config_file(&state.config.provider_config_path)?;
        reuse_saved_provider_key(&mut request, saved.as_ref())?;
    }
    let config = validate_provider_request(request)?;
    persist_provider_config(&state.config.provider_config_path, &config)?;
    Ok(Json(provider_config_view(&config)))
}

async fn delete_provider_config(
    State(state): State<AppState>,
) -> ApiResult<Json<ProviderConfigView>> {
    let inner = state.inner.lock().await;
    if inner.runtime.is_some() {
        return Err(ApiError(
            StatusCode::CONFLICT,
            "请先停止当前对话，再清除上游模型配置".into(),
        ));
    }
    if state.config.provider_config_path.exists() {
        let metadata =
            fs::symlink_metadata(&state.config.provider_config_path).map_err(internal_error)?;
        if !metadata.file_type().is_file() {
            return Err(ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "拒绝删除非普通上游配置文件".into(),
            ));
        }
        fs::remove_file(&state.config.provider_config_path).map_err(internal_error)?;
    }
    drop(inner);
    Ok(Json(ProviderConfigView {
        configured: false,
        api: String::new(),
        base_url: String::new(),
        provider: String::new(),
        model: String::new(),
        context_window: DEFAULT_CONTEXT_WINDOW,
        compression_threshold_percent: DEFAULT_COMPRESSION_THRESHOLD_PERCENT,
        initial_survey: default_initial_survey(),
        result_storage: ResultStorageConfig::default(),
    }))
}

async fn discover_provider_models(
    State(state): State<AppState>,
    Json(request): Json<ProviderModelsRequest>,
) -> ApiResult<Json<ProviderModelsView>> {
    let base_url = validate_provider_url(&request.base_url)?;
    let api_key = if request.api_key.trim().is_empty() {
        let saved =
            load_provider_config_file(&state.config.provider_config_path)?.ok_or_else(|| {
                ApiError(
                    StatusCode::BAD_REQUEST,
                    "请输入 API Key，或先保存同一 Base URL 的上游配置".into(),
                )
            })?;
        if saved.base_url != base_url {
            return Err(ApiError(
                StatusCode::BAD_REQUEST,
                "当前私密配置属于另一个 Base URL，请重新输入 API Key".into(),
            ));
        }
        saved.api_key
    } else {
        bounded_printable(&request.api_key, "API Key", 4_096)?
    };
    let _query_guard = state.model_query_gate.try_lock().map_err(|_| {
        ApiError(
            StatusCode::TOO_MANY_REQUESTS,
            "已有一个上游模型查询正在进行".into(),
        )
    })?;
    let models = fetch_provider_models(&base_url, &api_key).await?;
    Ok(Json(ProviderModelsView { models }))
}

async fn events(
    State(state): State<AppState>,
) -> Sse<impl Stream<Item = Result<SseEvent, Infallible>>> {
    let mut shutdown = state.shutdown.subscribe();
    let stream = BroadcastStream::new(state.updates.subscribe()).filter_map(|item| match item {
        Ok(update) => serde_json::to_string(&update)
            .ok()
            .map(|json| Ok(SseEvent::default().data(json))),
        Err(_) => None,
    });
    let stream = futures_util::StreamExt::take_until(stream, async move {
        let _ = shutdown.recv().await;
    });
    Sse::new(stream).keep_alive(KeepAlive::new().interval(Duration::from_secs(15)))
}

async fn create_session(
    State(state): State<AppState>,
    Json(request): Json<CreateSessionRequest>,
) -> ApiResult<Json<PersistedState>> {
    let now = now_ms();
    let id = format!("session-{now}");
    let title = bounded_title(request.title.as_deref(), now);
    let saved_config = load_provider_config_file(&state.config.provider_config_path)?;
    let initial_survey = saved_config
        .as_ref()
        .map(|config| config.initial_survey.clone())
        .unwrap_or_else(default_initial_survey);
    let save_iq = saved_config
        .as_ref()
        .is_some_and(|config| config.result_storage.save_iq);
    let initial_survey_status = if initial_survey.mode == "disabled" {
        "skipped"
    } else {
        "pending"
    };
    let mut inner = state.inner.lock().await;

    if inner.persisted.sessions.len() >= MAX_SESSIONS {
        let evict = select_evict_id(&inner.persisted)
            .ok_or_else(|| ApiError(StatusCode::CONFLICT, "没有可丢弃的非活动对话".into()))?;
        inner
            .persisted
            .sessions
            .retain(|session| session.id != evict);
    }
    deactivate_current(&mut inner);
    inner.persisted.sessions.push(Session {
        id: id.clone(),
        title,
        created_at_ms: now,
        last_used_at_ms: now,
        generation: 1,
        compaction_count: 0,
        status: "starting".into(),
        compacted_summary: String::new(),
        summary_pending: false,
        events_since_compaction: 0,
        initial_survey: Some(initial_survey),
        initial_survey_status: initial_survey_status.into(),
        observation: None,
        sweep_plot: None,
        model_input: None,
        thinking: None,
        decision_basis: None,
        save_iq,
        events: VecDeque::new(),
    });
    inner.persisted.active_session_id = Some(id.clone());
    inner.runtime = Some(spawn_agent_process(state.clone(), id));
    persist_locked(&state.config, &inner.persisted)?;
    let snapshot = inner.persisted.clone();
    drop(inner);
    publish_state(&state);
    Ok(Json(snapshot))
}

async fn activate_session(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> ApiResult<Json<PersistedState>> {
    let mut inner = state.inner.lock().await;
    if !inner
        .persisted
        .sessions
        .iter()
        .any(|session| session.id == id)
    {
        return Err(ApiError(StatusCode::NOT_FOUND, "对话不存在".into()));
    }
    if inner.persisted.active_session_id.as_deref() != Some(&id) {
        deactivate_current(&mut inner);
        inner.persisted.active_session_id = Some(id.clone());
        if let Some(session) = find_session_mut(&mut inner.persisted, &id) {
            session.status = "starting".into();
            session.last_used_at_ms = now_ms();
        }
        inner.runtime = Some(spawn_agent_process(state.clone(), id));
        persist_locked(&state.config, &inner.persisted)?;
    }
    let snapshot = inner.persisted.clone();
    drop(inner);
    publish_state(&state);
    Ok(Json(snapshot))
}

async fn send_command(
    State(state): State<AppState>,
    Path(id): Path<String>,
    Json(request): Json<CommandRequest>,
) -> ApiResult<Json<PersistedState>> {
    let command = single_line(&request.command);
    if command.is_empty() || command.len() > MAX_COMMAND_BYTES {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "输入必须为 1–1024 字节".into(),
        ));
    }
    let mut inner = state.inner.lock().await;
    if inner.persisted.active_session_id.as_deref() != Some(&id) {
        return Err(ApiError(
            StatusCode::CONFLICT,
            "只有当前活动对话可以输入".into(),
        ));
    }
    if inner
        .runtime
        .as_ref()
        .map(|runtime| runtime.session_id.as_str())
        != Some(&id)
    {
        inner.runtime = Some(spawn_agent_process(state.clone(), id.clone()));
    }

    let should_compact = find_session_mut(&mut inner.persisted, &id)
        .is_some_and(|session| session.events_since_compaction >= COMPACT_AT_EVENTS);
    if should_compact {
        compact_session(
            find_session_mut(&mut inner.persisted, &id).expect("session exists"),
            true,
        );
        if let Some(runtime) = inner.runtime.take() {
            let _ = runtime.tx.try_send(ProcessCommand::Shutdown);
        }
        inner.runtime = Some(spawn_agent_process(state.clone(), id.clone()));
    }

    let outgoing = {
        let session = find_session_mut(&mut inner.persisted, &id)
            .ok_or_else(|| ApiError(StatusCode::NOT_FOUND, "对话不存在".into()))?;
        session.last_used_at_ms = now_ms();
        let text = if !command.starts_with('/')
            && session.summary_pending
            && !session.compacted_summary.is_empty()
        {
            session.summary_pending = false;
            carry_forward_instruction(&session.compacted_summary, &command)
        } else {
            command.clone()
        };
        push_event(session, "operator", format!("Operator> {command}")).map(|event| {
            state.updates.send(UiUpdate {
                update_type: "terminal".into(),
                session_id: Some(id.clone()),
                event: Some(event),
            })
        });
        text
    };
    let runtime = inner.runtime.as_ref().expect("runtime exists").clone();
    runtime
        .tx
        .try_send(ProcessCommand::Input(outgoing))
        .map_err(|_| {
            ApiError(
                StatusCode::SERVICE_UNAVAILABLE,
                "终端进程暂不可写，请稍后重试".into(),
            )
        })?;
    persist_locked(&state.config, &inner.persisted)?;
    let snapshot = inner.persisted.clone();
    drop(inner);
    Ok(Json(snapshot))
}

fn single_line(value: &str) -> String {
    value
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .trim()
        .to_owned()
}

fn carry_forward_instruction(summary: &str, command: &str) -> String {
    const PREFIX: &str = "前序压缩摘要：";
    const CURRENT: &str = "；当前指令：";
    let summary = single_line(summary);
    let command = single_line(command);
    let fixed_bytes = PREFIX.len() + CURRENT.len() + command.len();
    if summary.is_empty() || fixed_bytes >= MAX_COMMAND_BYTES {
        return command;
    }
    let summary_budget = MAX_COMMAND_BYTES - fixed_bytes;
    if summary_budget <= '…'.len_utf8() {
        return command;
    }
    let summary = if summary.len() > summary_budget {
        tail_utf8(&summary, summary_budget - '…'.len_utf8())
    } else {
        summary
    };
    format!("{PREFIX}{summary}{CURRENT}{command}")
}

fn deactivate_current(inner: &mut Inner) {
    if let Some(active_id) = inner.persisted.active_session_id.clone() {
        if let Some(session) = find_session_mut(&mut inner.persisted, &active_id) {
            compact_session(session, false);
            session.status = "stored".into();
        }
    }
    if let Some(runtime) = inner.runtime.take() {
        let _ = runtime.tx.try_send(ProcessCommand::Shutdown);
    }
}

fn spawn_agent_process(state: AppState, session_id: String) -> RuntimeHandle {
    let (tx, rx) = mpsc::channel(16);
    let actor_session_id = session_id.clone();
    tokio::spawn(async move {
        process_actor(state, actor_session_id, rx).await;
    });
    RuntimeHandle { session_id, tx }
}

async fn claim_initial_survey(state: &AppState, session_id: &str) -> Option<InitialSurveyConfig> {
    let mut inner = state.inner.lock().await;
    let survey = find_session_mut(&mut inner.persisted, session_id).and_then(|session| {
        if session.initial_survey_status != "pending" {
            return None;
        }
        let survey = session.initial_survey.clone()?;
        if survey.mode == "disabled" {
            session.initial_survey_status = "skipped".into();
            return None;
        }
        session.initial_survey_status = "running".into();
        Some(survey)
    });
    if survey.is_some() {
        let _ = persist_locked(&state.config, &inner.persisted);
    }
    drop(inner);
    if survey.is_some() {
        publish_state(state);
    }
    survey
}

async fn process_actor(
    state: AppState,
    session_id: String,
    mut rx: mpsc::Receiver<ProcessCommand>,
) {
    // The Planner Worker deliberately permits one interactive socket owner.
    // Holding this gate for the complete child lifetime makes a replacement
    // wait until the previous terminal has stopped and released session.sock.
    let _process_guard = state.process_gate.lock().await;
    let (survey_gain_db, persisted_observation, save_iq) = {
        let inner = state.inner.lock().await;
        let session = inner
            .persisted
            .sessions
            .iter()
            .find(|session| session.id == session_id);
        (
            session
                .and_then(|session| session.initial_survey.as_ref())
                .map_or(DEFAULT_SURVEY_GAIN_DB, |survey| survey.gain_db),
            session.and_then(|session| session.observation.clone()),
            session.is_some_and(|session| session.save_iq),
        )
    };
    let initial_survey = claim_initial_survey(&state, &session_id).await;
    let mut planner_socket_ready = false;
    for _ in 0..50 {
        if tokio::fs::metadata(&state.config.session_socket)
            .await
            .is_ok()
        {
            planner_socket_ready = true;
            break;
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    if !planner_socket_ready {
        record_process_output(
            &state,
            &session_id,
            "system",
            "Planner 会话 socket 在 5 秒内未就绪，终端没有启动。".into(),
        )
        .await;
        return;
    }
    let (request_path, temporary_request) =
        match prepare_runtime_request(&state.config, persisted_observation.as_ref()) {
            Ok(result) => result,
            Err(error) => {
                record_process_output(
                    &state,
                    &session_id,
                    "system",
                    format!("无法恢复结构化 SDR 观测：{}", error.1),
                )
                .await;
                return;
            }
        };
    let mut command = Command::new(&state.config.agent_binary);
    command
        .arg("--socket")
        .arg(&state.config.session_socket)
        .arg("--request")
        .arg(&request_path)
        .arg("--sdrd")
        .arg(&state.config.sdrd_address)
        .arg("--survey-gain-db")
        .arg(survey_gain_db.to_string());
    if save_iq {
        if !valid_session_id(&session_id) {
            cleanup_runtime_request(temporary_request.as_deref());
            record_process_output(
                &state,
                &session_id,
                "system",
                "对话 ID 无法安全映射到采集目录，终端没有启动。".into(),
            )
            .await;
            return;
        }
        command
            .arg("--sigmf-directory")
            .arg(state.config.capture_root.join(&session_id));
    }
    if let Some(survey) = initial_survey {
        command
            .arg("--initial-survey-start-hz")
            .arg(survey.start_hz.to_string())
            .arg("--initial-survey-stop-hz")
            .arg(survey.stop_hz.to_string())
            .arg("--initial-survey-step-hz")
            .arg(survey.step_hz.to_string())
            .arg("--initial-survey-dwell-ms")
            .arg(survey.dwell_ms.to_string())
            .arg("--initial-survey-gain-db")
            .arg(survey.gain_db.to_string());
    }
    let mut child = match command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()
    {
        Ok(child) => child,
        Err(error) => {
            cleanup_runtime_request(temporary_request.as_deref());
            record_process_output(
                &state,
                &session_id,
                "system",
                format!("无法启动 sdr-agent：{error}"),
            )
            .await;
            return;
        }
    };
    let stdout = child.stdout.take().expect("stdout piped");
    let stderr = child.stderr.take().expect("stderr piped");
    let mut stdin = child.stdin.take().expect("stdin piped");
    tokio::spawn(read_process_stream(
        state.clone(),
        session_id.clone(),
        stdout,
        false,
    ));
    tokio::spawn(read_process_stream(
        state.clone(),
        session_id.clone(),
        stderr,
        true,
    ));
    record_process_output(
        &state,
        &session_id,
        "system",
        "终端进程已启动，等待控制器提示。".into(),
    )
    .await;

    loop {
        tokio::select! {
            status = child.wait() => {
                record_runtime_exit(&state, &session_id, format!("终端进程已退出：{status:?}")).await;
                break;
            }
            command = rx.recv() => match command {
                Some(ProcessCommand::Input(input)) => {
                    if let Err(error) = stdin.write_all(format!("{input}\n").as_bytes()).await {
                        record_process_output(&state, &session_id, "system", format!("写入终端失败：{error}")).await;
                    } else if let Err(error) = stdin.flush().await {
                        record_process_output(&state, &session_id, "system", format!("刷新终端输入失败：{error}")).await;
                    }
                }
                Some(ProcessCommand::Shutdown) | None => {
                    let _ = stdin.write_all(b"/stop\n/quit\n").await;
                    let _ = stdin.flush().await;
                    if tokio::time::timeout(Duration::from_secs(4), child.wait()).await.is_err() {
                        let _ = child.kill().await;
                    }
                    break;
                }
            }
        }
    }
    cleanup_runtime_request(temporary_request.as_deref());
}

fn prepare_runtime_request(
    config: &Config,
    observation: Option<&ObservationSummary>,
) -> ApiResult<(PathBuf, Option<PathBuf>)> {
    let Some(observation) = observation else {
        return Ok((config.request_path.clone(), None));
    };
    let base = fs::read(&config.request_path).map_err(internal_error)?;
    if base.len() > MAX_FRAME_BYTES {
        return Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "基础 PlanningContext 超过 32 KiB".into(),
        ));
    }
    let bytes = runtime_request_bytes(&base, observation)?;
    let parent = config
        .state_path
        .parent()
        .ok_or_else(|| ApiError(StatusCode::INTERNAL_SERVER_ERROR, "状态路径无父目录".into()))?;
    fs::create_dir_all(parent).map_err(internal_error)?;
    let path = parent.join("runtime-request.json");
    let temporary = parent.join(format!("runtime-request.tmp-{}", now_ms()));
    let mut file = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&temporary)
        .map_err(internal_error)?;
    file.write_all(&bytes).map_err(internal_error)?;
    file.sync_all().map_err(internal_error)?;
    drop(file);
    fs::rename(&temporary, &path).map_err(internal_error)?;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).map_err(internal_error)?;
    Ok((path.clone(), Some(path)))
}

fn runtime_request_bytes(base: &[u8], observation: &ObservationSummary) -> ApiResult<Vec<u8>> {
    validate_persisted_observation(observation)?;
    let mut request: PlanRequest = serde_json::from_slice(base).map_err(internal_error)?;
    request.observation = observation.clone();
    ControllerPolicy
        .validate_request(&request)
        .map_err(internal_error)?;
    // latest_sweep intentionally carries all bounded measured points. Compact
    // encoding keeps the complete 768-point result inside the 32 KiB Planner
    // frame while preserving exact numeric values.
    let bytes = serde_json::to_vec(&request).map_err(internal_error)?;
    if bytes.len() > MAX_FRAME_BYTES {
        return Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "恢复后的 PlanningContext 超过 32 KiB".into(),
        ));
    }
    Ok(bytes)
}

fn cleanup_runtime_request(path: Option<&FsPath>) {
    if let Some(path) = path {
        let _ = fs::remove_file(path);
    }
}

async fn record_runtime_exit(state: &AppState, session_id: &str, text: String) {
    let mut inner = state.inner.lock().await;
    let is_current = inner
        .runtime
        .as_ref()
        .map(|runtime| runtime.session_id.as_str())
        == Some(session_id);
    if let Some(session) = find_session_mut(&mut inner.persisted, session_id) {
        if is_current {
            session.status = "exited".into();
        }
        if session.initial_survey_status == "running" {
            session.initial_survey_status = "failed".into();
        }
        if let Some(event) = push_event(session, "system", text) {
            let _ = state.updates.send(UiUpdate {
                update_type: "terminal".into(),
                session_id: Some(session_id.to_owned()),
                event: Some(event),
            });
        }
    }
    if is_current {
        inner.runtime = None;
    }
    let _ = persist_locked(&state.config, &inner.persisted);
}

async fn read_process_stream<R: AsyncRead + Unpin>(
    state: AppState,
    session_id: String,
    mut reader: R,
    stderr: bool,
) {
    let mut chunk = [0_u8; 1024];
    let mut pending = String::new();
    loop {
        match reader.read(&mut chunk).await {
            Ok(0) => break,
            Ok(count) => {
                pending.push_str(&String::from_utf8_lossy(&chunk[..count]));
                while let Some(index) = pending.find('\n') {
                    let line = pending[..index].trim_end_matches('\r').to_owned();
                    pending.drain(..=index);
                    if !line.is_empty() && !is_empty_agent_line(&line) {
                        let kind = classify_output(&line, stderr);
                        record_process_output(&state, &session_id, kind, line).await;
                    }
                }
                if pending.ends_with("SDR Agent> ") {
                    let prompt = std::mem::take(&mut pending);
                    record_process_output(&state, &session_id, "prompt", prompt).await;
                }
            }
            Err(error) => {
                record_process_output(
                    &state,
                    &session_id,
                    "system",
                    format!("读取终端输出失败：{error}"),
                )
                .await;
                break;
            }
        }
    }
    if !pending.trim().is_empty() && !is_empty_agent_line(&pending) {
        let kind = classify_output(&pending, stderr);
        record_process_output(&state, &session_id, kind, pending).await;
    }
}

fn is_empty_agent_line(line: &str) -> bool {
    line.strip_prefix("Agent>")
        .is_some_and(|text| text.trim().is_empty())
}

fn classify_output(line: &str, stderr: bool) -> &'static str {
    if stderr {
        "error"
    } else if line.starts_with("Agent>") {
        "qwen"
    } else if line.starts_with("Validated plan>") || line.starts_with("已验证计划：") {
        "plan"
    } else if line.starts_with("决策依据> ") {
        "decision"
    } else if line.starts_with("搜索> ") || line.starts_with("搜索来源> ") {
        "search"
    } else if line.starts_with("巡航状态：")
        || line.starts_with("SDR 连通性重试：")
        || line.starts_with("上游下一步重试：")
    {
        "cruise"
    } else if line.starts_with("Execution>")
        || line.starts_with("执行结果：")
        || line.starts_with("候选复查")
        || line.contains("硬件动作")
        || line.contains("执行失败")
    {
        "execution"
    } else if line.contains("扫频") || line.to_ascii_lowercase().contains("sweep") {
        "sweep"
    } else {
        "system"
    }
}

async fn record_process_output(state: &AppState, session_id: &str, kind: &str, text: String) {
    let mut inner = state.inner.lock().await;
    let is_current_runtime = inner
        .runtime
        .as_ref()
        .map(|runtime| runtime.session_id.as_str())
        == Some(session_id);
    if let Some(session) = find_session_mut(&mut inner.persisted, session_id) {
        if let Some(payload) = text.strip_prefix("SweepPlot> ") {
            match serde_json::from_str::<SweepPlot>(payload)
                .map_err(internal_error)
                .and_then(|plot| {
                    validate_sweep_plot(&plot, &state.config.capture_root)?;
                    persist_capture_result(&state.config.result_db_path, session_id, &plot)?;
                    Ok(plot)
                }) {
                Ok(plot) => {
                    session.sweep_plot = Some(plot);
                    let _ = persist_locked(&state.config, &inner.persisted);
                    drop(inner);
                    publish_state(state);
                    return;
                }
                Err(error) => {
                    if let Some(event) = push_event(
                        session,
                        "error",
                        format!("拒绝保存无效的扫频结果：{}", error.1),
                    ) {
                        let _ = state.updates.send(UiUpdate {
                            update_type: "terminal".into(),
                            session_id: Some(session_id.to_owned()),
                            event: Some(event),
                        });
                    }
                    let _ = persist_locked(&state.config, &inner.persisted);
                    return;
                }
            }
        }
        if let Some(payload) = text.strip_prefix("模型输入> ") {
            match serde_json::from_str::<serde_json::Value>(payload) {
                Ok(value) if value.is_object() => session.model_input = Some(value),
                _ => {
                    if let Some(event) =
                        push_event(session, "error", "拒绝无效的模型输入记录".into())
                    {
                        let _ = state.updates.send(UiUpdate {
                            update_type: "terminal".into(),
                            session_id: Some(session_id.to_owned()),
                            event: Some(event),
                        });
                    }
                }
            }
            let _ = persist_locked(&state.config, &inner.persisted);
            drop(inner);
            publish_state(state);
            return;
        }
        if let Some(payload) = text.strip_prefix("ThinkingStart> ") {
            if let Ok(value) = serde_json::from_str::<serde_json::Value>(payload) {
                if let Some(request_id) =
                    value.get("request_id").and_then(serde_json::Value::as_u64)
                {
                    session.thinking = Some(ThinkingTrace {
                        request_id,
                        active: true,
                        text: String::new(),
                    });
                }
            }
            let _ = persist_locked(&state.config, &inner.persisted);
            drop(inner);
            publish_state(state);
            return;
        }
        if let Some(payload) = text.strip_prefix("ThinkingDelta> ") {
            if let Ok(value) = serde_json::from_str::<serde_json::Value>(payload) {
                let request_id = value.get("request_id").and_then(serde_json::Value::as_u64);
                let delta = value.get("delta").and_then(serde_json::Value::as_str);
                if let (Some(request_id), Some(delta), Some(thinking)) =
                    (request_id, delta, session.thinking.as_mut())
                {
                    if thinking.request_id == request_id {
                        thinking.text.push_str(delta);
                    }
                }
            }
            let _ = persist_locked(&state.config, &inner.persisted);
            drop(inner);
            publish_state(state);
            return;
        }
        if let Some(payload) = text.strip_prefix("ThinkingEnd> ") {
            if let Ok(value) = serde_json::from_str::<serde_json::Value>(payload) {
                let request_id = value.get("request_id").and_then(serde_json::Value::as_u64);
                if session
                    .thinking
                    .as_ref()
                    .is_some_and(|thinking| Some(thinking.request_id) == request_id)
                {
                    if session
                        .thinking
                        .as_ref()
                        .is_some_and(|thinking| thinking.text.is_empty())
                    {
                        session.thinking = None;
                    } else if let Some(thinking) = session.thinking.as_mut() {
                        thinking.active = false;
                    }
                }
            }
            let _ = persist_locked(&state.config, &inner.persisted);
            drop(inner);
            publish_state(state);
            return;
        }
        if let Some(payload) = text.strip_prefix("Observation> ") {
            match serde_json::from_str::<ObservationSummary>(payload)
                .map_err(internal_error)
                .and_then(|observation| {
                    validate_persisted_observation(&observation)?;
                    Ok(observation)
                }) {
                Ok(observation) => session.observation = Some(observation),
                Err(error) => {
                    if let Some(event) = push_event(
                        session,
                        "error",
                        format!("拒绝持久化无效的结构化 SDR 观测：{}", error.1),
                    ) {
                        let _ = state.updates.send(UiUpdate {
                            update_type: "terminal".into(),
                            session_id: Some(session_id.to_owned()),
                            event: Some(event),
                        });
                    }
                }
            }
            let _ = persist_locked(&state.config, &inner.persisted);
            return;
        }
        if is_current_runtime {
            session.status = if kind == "error" {
                "error".into()
            } else {
                "connected".into()
            };
        }
        if let Some(basis) = text.strip_prefix("决策依据> ") {
            session.decision_basis = Some(basis.to_owned());
        }
        update_initial_survey_status(session, &text);
        if let Some(event) = push_event(session, kind, text) {
            let _ = state.updates.send(UiUpdate {
                update_type: "terminal".into(),
                session_id: Some(session_id.to_owned()),
                event: Some(event),
            });
        }
        let _ = persist_locked(&state.config, &inner.persisted);
    }
}

fn validate_persisted_observation(observation: &ObservationSummary) -> ApiResult<()> {
    if observation.candidates.len() > MAX_CANDIDATES {
        return Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "结构化观测候选数量超过 32".into(),
        ));
    }
    let mut ids = HashSet::new();
    for candidate in &observation.candidates {
        if candidate.id.is_empty()
            || candidate.id.len() >= 64
            || !ids.insert(candidate.id.as_str())
            || !(DEFAULT_SURVEY_START_HZ..=DEFAULT_SURVEY_STOP_HZ).contains(&candidate.center_hz)
            || candidate.bandwidth_hz == 0
            || candidate.bandwidth_hz > 56_000_000
            || !candidate.peak_dbfs.is_finite()
            || !candidate.snr_db.is_finite()
            || candidate.snr_db < 0.0
        {
            return Err(ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "结构化观测包含无效或重复候选".into(),
            ));
        }
    }
    if let Some(sweep) = &observation.latest_sweep {
        let mut previous_center_hz = None;
        if sweep.sweep_id.is_empty()
            || sweep.sweep_id.len() >= 64
            || sweep.points.is_empty()
            || sweep.points.len() > MAX_SWEEP_POINTS
            || !(2_100_000..=30_720_000).contains(&sweep.sample_rate_hz)
            || !(200_000..=sweep.sample_rate_hz).contains(&sweep.rf_bandwidth_hz)
            || !(0..=60).contains(&sweep.fixed_gain_db)
            || !sweep.noise_floor_dbfs.is_finite()
            || sweep.points.iter().any(|(center_hz, power_dbfs)| {
                let invalid = !(DEFAULT_SURVEY_START_HZ..=DEFAULT_SURVEY_STOP_HZ)
                    .contains(center_hz)
                    || !power_dbfs.is_finite()
                    || previous_center_hz.is_some_and(|previous| previous >= *center_hz);
                previous_center_hz = Some(*center_hz);
                invalid
            })
        {
            return Err(ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "结构化观测包含无效扫频点".into(),
            ));
        }
    }
    if observation.recognition.as_ref().is_some_and(|recognition| {
        recognition.candidate_id.is_empty()
            || recognition.candidate_id.len() >= 64
            || recognition.label.is_empty()
            || recognition.label.len() > 128
            || !recognition.confidence.is_finite()
            || !(0.0..=1.0).contains(&recognition.confidence)
    }) {
        return Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "结构化观测包含无效识别结果".into(),
        ));
    }
    Ok(())
}

fn update_initial_survey_status(session: &mut Session, text: &str) {
    if text.starts_with("首次扫频完成：") {
        session.initial_survey_status = "complete".into();
    } else if text.starts_with("首次扫频失败：")
        || text.starts_with("首次扫频已取消")
        || text.starts_with("取消到达前扫频已完成：")
    {
        session.initial_survey_status = if text.starts_with("取消到达前扫频已完成：") {
            "complete"
        } else {
            "failed"
        }
        .into();
    }
}

fn push_event(session: &mut Session, kind: &str, text: String) -> Option<TerminalEvent> {
    if text.is_empty() {
        return None;
    }
    let event = TerminalEvent {
        id: session
            .events
            .back()
            .map_or(1, |event| event.id.saturating_add(1)),
        timestamp_ms: now_ms(),
        kind: kind.into(),
        text,
    };
    if session.events.len() == MAX_EVENTS {
        session.events.pop_front();
    }
    session.events.push_back(event.clone());
    session.events_since_compaction = session.events_since_compaction.saturating_add(1);
    Some(event)
}

fn compact_session(session: &mut Session, automatic: bool) {
    if session.events.is_empty() {
        return;
    }
    let mut parts = Vec::new();
    if !session.compacted_summary.is_empty() {
        parts.push(session.compacted_summary.clone());
    }
    for event in session.events.iter().filter(|event| event.kind != "prompt") {
        parts.push(format!(
            "[{}] {}",
            event.kind,
            event.text.replace('\n', " ")
        ));
    }
    session.compacted_summary = tail_utf8(&parts.join("\n"), MAX_SUMMARY_BYTES);
    while session.events.len() > RETAIN_AFTER_COMPACT {
        session.events.pop_front();
    }
    session.events_since_compaction = 0;
    session.summary_pending = !session.compacted_summary.is_empty();
    session.generation = session.generation.saturating_add(1);
    if automatic {
        session.compaction_count = session.compaction_count.saturating_add(1);
    }
}

fn select_evict_id(state: &PersistedState) -> Option<String> {
    state
        .sessions
        .iter()
        .filter(|session| Some(session.id.as_str()) != state.active_session_id.as_deref())
        .min_by_key(|session| session.last_used_at_ms)
        .map(|session| session.id.clone())
}

fn find_session_mut<'a>(state: &'a mut PersistedState, id: &str) -> Option<&'a mut Session> {
    state.sessions.iter_mut().find(|session| session.id == id)
}

fn valid_session_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
}

fn bounded_title(title: Option<&str>, now: u64) -> String {
    let cleaned = title.unwrap_or("").trim();
    if cleaned.is_empty() {
        format!("对话 {}", now % 100_000)
    } else {
        cleaned.chars().take(40).collect()
    }
}

fn tail_utf8(value: &str, max_bytes: usize) -> String {
    if value.len() <= max_bytes {
        return value.to_owned();
    }
    let mut start = value.len() - max_bytes;
    while !value.is_char_boundary(start) {
        start += 1;
    }
    format!("…{}", &value[start..])
}

fn validate_provider_request(request: ProviderConfigRequest) -> ApiResult<ProviderConfigFile> {
    if !matches!(
        request.api.as_str(),
        "openai-completions" | "openai-responses"
    ) {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "API 协议必须为 OpenAI Completions 或 Responses".into(),
        ));
    }
    let base_url = validate_provider_url(&request.base_url)?;
    let provider = bounded_provider_id(&request.provider)?;
    let model = bounded_printable(&request.model, "Model ID", 256)?;
    let api_key = bounded_printable(&request.api_key, "API Key", 4_096)?;
    validate_context_settings(
        request.context_window,
        request.compression_threshold_percent,
    )?;
    validate_initial_survey(&request.initial_survey)?;
    Ok(ProviderConfigFile {
        schema_version: 1,
        api: request.api,
        base_url,
        provider,
        model,
        api_key,
        context_window: request.context_window,
        compression_threshold_percent: request.compression_threshold_percent,
        initial_survey: request.initial_survey,
        result_storage: request.result_storage,
    })
}

fn reuse_saved_provider_key(
    request: &mut ProviderConfigRequest,
    saved: Option<&ProviderConfigFile>,
) -> ApiResult<()> {
    let saved = saved.ok_or_else(|| {
        ApiError(
            StatusCode::BAD_REQUEST,
            "首次保存上游配置时必须填写 API Key".into(),
        )
    })?;
    let requested_base_url = validate_provider_url(&request.base_url)?;
    if saved.base_url != requested_base_url {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "Base URL 已改变，请重新输入 API Key".into(),
        ));
    }
    request.api_key.clone_from(&saved.api_key);
    Ok(())
}

const fn default_context_window() -> u64 {
    DEFAULT_CONTEXT_WINDOW
}

const fn default_compression_threshold_percent() -> u8 {
    DEFAULT_COMPRESSION_THRESHOLD_PERCENT
}

fn default_initial_survey() -> InitialSurveyConfig {
    InitialSurveyConfig {
        mode: "full_band".into(),
        start_hz: DEFAULT_SURVEY_START_HZ,
        stop_hz: DEFAULT_SURVEY_STOP_HZ,
        step_hz: DEFAULT_SURVEY_STEP_HZ,
        dwell_ms: DEFAULT_SURVEY_DWELL_MS,
        gain_db: DEFAULT_SURVEY_GAIN_DB,
    }
}

const fn default_survey_gain_db() -> i16 {
    DEFAULT_SURVEY_GAIN_DB
}

fn default_initial_survey_status() -> String {
    "skipped".into()
}

fn validate_initial_survey(survey: &InitialSurveyConfig) -> ApiResult<()> {
    if !matches!(
        survey.mode.as_str(),
        "full_band" | "custom_band" | "disabled"
    ) {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "首次扫描模式必须为全频段、手动频段或关闭".into(),
        ));
    }
    if survey.mode == "disabled" {
        return Ok(());
    }
    if !(DEFAULT_SURVEY_START_HZ..=DEFAULT_SURVEY_STOP_HZ).contains(&survey.start_hz)
        || !(DEFAULT_SURVEY_START_HZ..=DEFAULT_SURVEY_STOP_HZ).contains(&survey.stop_hz)
        || survey.start_hz > survey.stop_hz
        || survey.step_hz == 0
        || survey.step_hz > DEFAULT_SURVEY_STEP_HZ
        || survey.dwell_ms > 1_000
        || !(0..=60).contains(&survey.gain_db)
    {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "首次扫描必须位于 70 MHz–6 GHz，起点不高于终点，步进为 1–8 MHz，每点停留不超过 1000 ms，固定增益为 0–60 dB"
                .into(),
        ));
    }
    let span = survey.stop_hz.saturating_sub(survey.start_hz);
    let points = span
        .checked_add(survey.step_hz - 1)
        .and_then(|value| value.checked_div(survey.step_hz))
        .and_then(|value| value.checked_add(1))
        .ok_or_else(|| ApiError(StatusCode::BAD_REQUEST, "首次扫描点数溢出".into()))?;
    let duration_ms = points
        .checked_mul(survey.dwell_ms.saturating_add(250))
        .ok_or_else(|| ApiError(StatusCode::BAD_REQUEST, "首次扫描时长溢出".into()))?;
    if points > MAX_SURVEY_POINTS || duration_ms > 300_000 {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "首次扫描不得超过 768 个频点或 300 秒保守时长".into(),
        ));
    }
    Ok(())
}

fn validate_context_settings(context_window: u64, threshold_percent: u8) -> ApiResult<()> {
    if !(MIN_CONTEXT_WINDOW..=MAX_CONTEXT_WINDOW).contains(&context_window) {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            format!("上下文窗口必须在 {MIN_CONTEXT_WINDOW}–{MAX_CONTEXT_WINDOW} tokens 之间"),
        ));
    }
    if !(MIN_COMPRESSION_THRESHOLD_PERCENT..=MAX_COMPRESSION_THRESHOLD_PERCENT)
        .contains(&threshold_percent)
    {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            format!(
                "自动压缩阈值必须在 {MIN_COMPRESSION_THRESHOLD_PERCENT}%–{MAX_COMPRESSION_THRESHOLD_PERCENT}% 之间"
            ),
        ));
    }
    Ok(())
}

fn validate_provider_url(value: &str) -> ApiResult<String> {
    let text = bounded_printable(value, "Base URL", 2_048)?;
    let uri: axum::http::Uri = text.parse().map_err(|_| {
        ApiError(
            StatusCode::BAD_REQUEST,
            "Base URL 必须是完整的 HTTP(S) URL".into(),
        )
    })?;
    let scheme = uri
        .scheme_str()
        .ok_or_else(|| ApiError(StatusCode::BAD_REQUEST, "Base URL 缺少协议".into()))?;
    let authority = uri
        .authority()
        .ok_or_else(|| ApiError(StatusCode::BAD_REQUEST, "Base URL 缺少主机".into()))?;
    if authority.as_str().contains('@') || uri.query().is_some() {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "Base URL 不能包含账号信息或查询参数".into(),
        ));
    }
    let host = authority.host().to_ascii_lowercase();
    let loopback = matches!(host.as_str(), "localhost" | "127.0.0.1" | "[::1]");
    if scheme != "https" && !(scheme == "http" && loopback) {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "非 loopback 上游必须使用 HTTPS".into(),
        ));
    }
    Ok(text.trim_end_matches('/').to_owned())
}

fn bounded_provider_id(value: &str) -> ApiResult<String> {
    let text = bounded_printable(value, "Provider ID", 64)?;
    if !text
        .bytes()
        .enumerate()
        .all(|(index, byte)| byte.is_ascii_alphanumeric() || (index > 0 && b"._-".contains(&byte)))
    {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "Provider ID 只能包含字母、数字、点、下划线和连字符".into(),
        ));
    }
    Ok(text)
}

fn bounded_printable(value: &str, label: &str, maximum_bytes: usize) -> ApiResult<String> {
    let text = value.trim();
    if text.is_empty() || text.len() > maximum_bytes || text.chars().any(char::is_control) {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            format!("{label} 必须为 1–{maximum_bytes} 字节可打印文本"),
        ));
    }
    Ok(text.to_owned())
}

fn provider_config_view(config: &ProviderConfigFile) -> ProviderConfigView {
    ProviderConfigView {
        configured: true,
        api: config.api.clone(),
        base_url: config.base_url.clone(),
        provider: config.provider.clone(),
        model: config.model.clone(),
        context_window: config.context_window,
        compression_threshold_percent: config.compression_threshold_percent,
        initial_survey: config.initial_survey.clone(),
        result_storage: config.result_storage.clone(),
    }
}

fn load_provider_config_view(path: &FsPath) -> ApiResult<ProviderConfigView> {
    let Some(config) = load_provider_config_file(path)? else {
        return Ok(ProviderConfigView {
            configured: false,
            api: String::new(),
            base_url: String::new(),
            provider: String::new(),
            model: String::new(),
            context_window: DEFAULT_CONTEXT_WINDOW,
            compression_threshold_percent: DEFAULT_COMPRESSION_THRESHOLD_PERCENT,
            initial_survey: default_initial_survey(),
            result_storage: ResultStorageConfig::default(),
        });
    };
    Ok(provider_config_view(&config))
}

fn load_provider_config_file(path: &FsPath) -> ApiResult<Option<ProviderConfigFile>> {
    if !path.exists() {
        return Ok(None);
    }
    let metadata = fs::symlink_metadata(path).map_err(internal_error)?;
    if !metadata.file_type().is_file() || metadata.len() > MAX_PROVIDER_CONFIG_BYTES {
        return Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "上游配置必须是不超过 8 KiB 的普通文件".into(),
        ));
    }
    if metadata.permissions().mode() & 0o077 != 0 {
        return Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "上游配置权限必须为 0600".into(),
        ));
    }
    let config: ProviderConfigFile =
        serde_json::from_slice(&fs::read(path).map_err(internal_error)?).map_err(internal_error)?;
    if config.schema_version != 1 {
        return Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "不支持的上游配置版本".into(),
        ));
    }
    validate_context_settings(config.context_window, config.compression_threshold_percent)
        .map_err(|error| ApiError(StatusCode::INTERNAL_SERVER_ERROR, error.1))?;
    validate_initial_survey(&config.initial_survey)
        .map_err(|error| ApiError(StatusCode::INTERNAL_SERVER_ERROR, error.1))?;
    Ok(Some(config))
}

async fn fetch_provider_models(base_url: &str, api_key: &str) -> ApiResult<Vec<ProviderModelView>> {
    let endpoint = format!("{}/models", base_url.trim_end_matches('/'));
    let mut child = Command::new("curl")
        .args([
            "--silent",
            "--show-error",
            "--no-progress-meter",
            "--connect-timeout",
            "4",
            "--max-time",
            "8",
            "--max-filesize",
            "524288",
            "--proto",
            "=http,https",
            "--proto-redir",
            "=https",
            "--header",
            "Accept: application/json",
            "--header",
            "@-",
            "--write-out",
            "\n%{http_code}",
            "--url",
            &endpoint,
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true)
        .spawn()
        .map_err(|_| {
            ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "无法启动受限的 curl 上游查询".into(),
            )
        })?;

    let mut stdin = child.stdin.take().ok_or_else(|| {
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "无法建立上游查询的私密输入管道".into(),
        )
    })?;
    stdin
        .write_all(format!("Authorization: Bearer {api_key}\n").as_bytes())
        .await
        .map_err(|_| {
            ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "无法写入上游认证管道".into(),
            )
        })?;
    drop(stdin);

    let output = tokio::time::timeout(Duration::from_secs(10), child.wait_with_output())
        .await
        .map_err(|_| {
            ApiError(
                StatusCode::BAD_GATEWAY,
                "连接上游超过 8 秒，请检查 Base URL 和网络".into(),
            )
        })?
        .map_err(|_| ApiError(StatusCode::BAD_GATEWAY, "上游查询进程异常退出".into()))?;
    if !output.status.success() {
        return Err(ApiError(
            StatusCode::BAD_GATEWAY,
            "上游连接失败、超时或响应超过 512 KiB".into(),
        ));
    }
    if output.stdout.len() < 4 || output.stdout[output.stdout.len() - 4] != b'\n' {
        return Err(ApiError(
            StatusCode::BAD_GATEWAY,
            "上游查询缺少 HTTP 状态".into(),
        ));
    }
    let split_at = output.stdout.len() - 4;
    let status = std::str::from_utf8(&output.stdout[split_at + 1..])
        .ok()
        .and_then(|value| value.parse::<u16>().ok())
        .ok_or_else(|| ApiError(StatusCode::BAD_GATEWAY, "上游 HTTP 状态无效".into()))?;
    if (300..400).contains(&status) {
        return Err(ApiError(
            StatusCode::BAD_GATEWAY,
            "上游模型接口返回重定向；请直接填写最终 HTTPS Base URL".into(),
        ));
    }
    if !(200..300).contains(&status) {
        return Err(ApiError(
            StatusCode::BAD_GATEWAY,
            format!("上游模型接口返回 HTTP {status}"),
        ));
    }
    let body = &output.stdout[..split_at];
    if body.len() > MAX_PROVIDER_MODELS_BYTES {
        return Err(ApiError(
            StatusCode::BAD_GATEWAY,
            "上游模型列表超过 512 KiB 限制".into(),
        ));
    }
    parse_provider_models(body)
}

fn parse_provider_models(body: &[u8]) -> ApiResult<Vec<ProviderModelView>> {
    let payload: serde_json::Value = serde_json::from_slice(body).map_err(|_| {
        ApiError(
            StatusCode::BAD_GATEWAY,
            "上游模型接口没有返回有效 JSON".into(),
        )
    })?;
    let items = payload
        .get("data")
        .and_then(serde_json::Value::as_array)
        .or_else(|| payload.get("models").and_then(serde_json::Value::as_array))
        .or_else(|| payload.as_array())
        .ok_or_else(|| {
            ApiError(
                StatusCode::BAD_GATEWAY,
                "上游模型 JSON 缺少 data 或 models 数组".into(),
            )
        })?;

    let mut models = items
        .iter()
        .filter_map(parse_provider_model)
        .collect::<Vec<_>>();
    models.sort_unstable_by(|left, right| left.id.cmp(&right.id));
    models.dedup_by(|left, right| {
        if left.id != right.id {
            return false;
        }
        if left.context_window.is_none() {
            left.context_window = right.context_window;
        }
        true
    });
    models.truncate(MAX_PROVIDER_MODELS);
    if models.is_empty() {
        return Err(ApiError(
            StatusCode::BAD_GATEWAY,
            "上游没有返回可用的模型 ID".into(),
        ));
    }
    Ok(models)
}

fn parse_provider_model(item: &serde_json::Value) -> Option<ProviderModelView> {
    let id = item
        .as_str()
        .or_else(|| {
            item.get("id")
                .or_else(|| item.get("model"))
                .and_then(serde_json::Value::as_str)
        })
        .and_then(valid_remote_model_id)?;
    let context_window = [
        item.get("context_window"),
        item.get("context_length"),
        item.get("max_context_length"),
        item.get("max_model_len"),
        item.pointer("/limits/context_window"),
        item.pointer("/top_provider/context_length"),
    ]
    .into_iter()
    .flatten()
    .filter_map(serde_json::Value::as_u64)
    .find(|value| (MIN_CONTEXT_WINDOW..=MAX_CONTEXT_WINDOW).contains(value));
    Some(ProviderModelView { id, context_window })
}

fn valid_remote_model_id(value: &str) -> Option<String> {
    let value = value.trim();
    if value.is_empty() || value.len() > 256 || value.chars().any(char::is_control) {
        return None;
    }
    Some(value.to_owned())
}

fn persist_provider_config(path: &FsPath, config: &ProviderConfigFile) -> ApiResult<()> {
    let parent = path.parent().ok_or_else(|| {
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "上游配置路径无父目录".into(),
        )
    })?;
    fs::create_dir_all(parent).map_err(internal_error)?;
    let bytes = serde_json::to_vec_pretty(config).map_err(internal_error)?;
    if bytes.len() as u64 > MAX_PROVIDER_CONFIG_BYTES {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "上游配置超过 8 KiB".into(),
        ));
    }
    let temporary = path.with_extension(format!("json.tmp-{}", now_ms()));
    let mut file = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&temporary)
        .map_err(internal_error)?;
    file.write_all(&bytes).map_err(internal_error)?;
    file.sync_all().map_err(internal_error)?;
    drop(file);
    fs::rename(&temporary, path).map_err(internal_error)?;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).map_err(internal_error)?;
    Ok(())
}

fn load_state(path: &FsPath) -> Result<PersistedState, Box<dyn std::error::Error>> {
    if !path.exists() {
        return Ok(PersistedState::default());
    }
    let mut state: PersistedState = serde_json::from_slice(&fs::read(path)?)?;
    for session in &mut state.sessions {
        if session.initial_survey_status == "running" {
            // A persisted running state means the prior process disappeared
            // without a terminal result. Fail closed and never repeat a radio
            // sweep merely because the Web service restarted.
            session.initial_survey_status = "failed".into();
        }
    }
    state
        .sessions
        .sort_by_key(|session| session.last_used_at_ms);
    while state.sessions.len() > MAX_SESSIONS {
        state.sessions.remove(0);
    }
    Ok(state)
}

fn persist_locked(config: &Config, state: &PersistedState) -> ApiResult<()> {
    let parent = config
        .state_path
        .parent()
        .ok_or_else(|| ApiError(StatusCode::INTERNAL_SERVER_ERROR, "状态路径无父目录".into()))?;
    fs::create_dir_all(parent).map_err(internal_error)?;
    let temporary = config.state_path.with_extension("json.tmp");
    fs::write(
        &temporary,
        serde_json::to_vec_pretty(state).map_err(internal_error)?,
    )
    .map_err(internal_error)?;
    fs::rename(temporary, &config.state_path).map_err(internal_error)?;
    Ok(())
}

async fn restore_active_runtime(state: &AppState) {
    let mut inner = state.inner.lock().await;
    let active = inner.persisted.active_session_id.clone().filter(|id| {
        inner
            .persisted
            .sessions
            .iter()
            .any(|session| &session.id == id)
    });
    if let Some(id) = active {
        if let Some(session) = find_session_mut(&mut inner.persisted, &id) {
            compact_session(session, false);
            session.status = "starting".into();
        }
        inner.runtime = Some(spawn_agent_process(state.clone(), id));
    }
}

fn publish_state(state: &AppState) {
    let _ = state.updates.send(UiUpdate {
        update_type: "state".into(),
        session_id: None,
        event: None,
    });
}

fn internal_error(error: impl std::fmt::Display) -> ApiError {
    ApiError(StatusCode::INTERNAL_SERVER_ERROR, error.to_string())
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

async fn shutdown_signal(state: AppState) {
    #[cfg(unix)]
    {
        let mut terminate =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                .expect("install SIGTERM handler");
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {}
            _ = terminate.recv() => {}
        }
    }
    #[cfg(not(unix))]
    let _ = tokio::signal::ctrl_c().await;
    let _ = state.shutdown.send(());
    begin_runtime_shutdown(&state).await;
}

async fn begin_runtime_shutdown(state: &AppState) {
    let runtime = state.inner.lock().await.runtime.take();
    if let Some(runtime) = runtime {
        let _ = runtime.tx.send(ProcessCommand::Shutdown).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temporary_test_directory(label: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "sdrharness-web-{label}-{}-{nonce}",
            std::process::id()
        ))
    }

    fn sweep_plot() -> SweepPlot {
        SweepPlot {
            schema_version: 1,
            sweep_id: "initial-1".into(),
            kind: "initial".into(),
            elapsed_ms: 1_200,
            gain_db: 20,
            noise_floor_dbfs: -53.0,
            points: vec![(100_000_000, -52.0), (108_000_000, -35.0)],
            candidates: vec![SweepPlotCandidate {
                id: "initial-1-1".into(),
                start_hz: 103_000_000,
                stop_hz: 113_000_000,
                center_hz: 108_000_000,
                bandwidth_hz: 10_000_000,
                peak_dbfs: -35.0,
                snr_db: 18.0,
                point_count: 1,
            }],
            dataset: None,
        }
    }

    fn session(id: &str, last_used_at_ms: u64) -> Session {
        Session {
            id: id.into(),
            title: id.into(),
            created_at_ms: 1,
            last_used_at_ms,
            generation: 1,
            compaction_count: 0,
            status: "stored".into(),
            compacted_summary: String::new(),
            summary_pending: false,
            events_since_compaction: 0,
            initial_survey: None,
            initial_survey_status: "skipped".into(),
            observation: None,
            sweep_plot: None,
            model_input: None,
            thinking: None,
            decision_basis: None,
            save_iq: false,
            events: VecDeque::new(),
        }
    }

    fn observation() -> ObservationSummary {
        serde_json::from_value(serde_json::json!({
            "age_ms": 0,
            "health": {
                "sdr_online": true,
                "can_retune": true,
                "can_capture_iq": true,
                "fpga_available": false,
                "recognizer_available": false,
                "dropped_observations": 0
            },
            "candidates": [{
                "id": "initial-1-7",
                "center_hz": 2454000000_u64,
                "bandwidth_hz": 10000000,
                "peak_dbfs": -24.2,
                "snr_db": 28.8,
                "age_ms": 0
            }]
        }))
        .unwrap()
    }

    #[test]
    fn evicts_oldest_inactive_session() {
        let state = PersistedState {
            active_session_id: Some("active".into()),
            sessions: vec![session("active", 1), session("old", 2)],
        };
        assert_eq!(select_evict_id(&state).as_deref(), Some("old"));
    }

    #[test]
    fn compaction_is_bounded_and_keeps_recent_terminal_events() {
        let mut item = session("one", 1);
        for index in 0..200 {
            push_event(
                &mut item,
                "qwen",
                format!("Agent> 第 {index} 条输出 {}", "x".repeat(80)),
            );
        }
        compact_session(&mut item, true);
        assert!(item.compacted_summary.len() <= MAX_SUMMARY_BYTES + 3);
        assert_eq!(item.events.len(), RETAIN_AFTER_COMPACT);
        assert!(item.summary_pending);
        assert_eq!(item.events_since_compaction, 0);
        assert_eq!(item.compaction_count, 1);
    }

    #[test]
    fn carry_forward_on_switch_does_not_increment_automatic_count() {
        let mut item = session("one", 1);
        push_event(&mut item, "operator", "Operator> hello".into());
        compact_session(&mut item, false);
        assert_eq!(item.generation, 2);
        assert_eq!(item.compaction_count, 0);
    }

    #[test]
    fn carry_forward_is_one_bounded_terminal_command() {
        let summary = format!("第一行\n第二行 {}", "历史".repeat(1_000));
        let instruction = "复查候选\ninitial-1-7";
        let outgoing = carry_forward_instruction(&summary, instruction);
        assert!(outgoing.len() <= MAX_COMMAND_BYTES);
        assert!(!outgoing.contains('\n'));
        assert!(outgoing.ends_with("当前指令：复查候选 initial-1-7"));
    }

    #[test]
    fn validates_default_and_custom_initial_survey_budgets() {
        assert!(validate_initial_survey(&default_initial_survey()).is_ok());
        let mut custom = default_initial_survey();
        custom.mode = "custom_band".into();
        custom.start_hz = 100_000_000;
        custom.stop_hz = 108_100_000;
        custom.step_hz = 8_000_000;
        assert!(validate_initial_survey(&custom).is_ok());
        custom.step_hz = 8_000_001;
        assert!(validate_initial_survey(&custom).is_err());
        custom.step_hz = 8_000_000;
        custom.gain_db = 61;
        assert!(validate_initial_survey(&custom).is_err());
    }

    #[test]
    fn processed_sweep_results_round_trip_through_sqlite() {
        let root = temporary_test_directory("result-db");
        let capture_root = root.join("captures");
        let database = root.join("results.sqlite3");
        fs::create_dir_all(&root).unwrap();
        initialize_capture_root(&capture_root).unwrap();
        initialize_result_database(&database).unwrap();
        let plot = sweep_plot();
        validate_sweep_plot(&plot, &capture_root).unwrap();
        persist_capture_result(&database, "session-1", &plot).unwrap();
        let summaries = load_capture_result_summaries(&database).unwrap();
        assert_eq!(summaries.len(), 1);
        assert_eq!(summaries[0].point_count, 2);
        assert_eq!(summaries[0].iq_bytes, 0);
        let detail = load_capture_result(&database, summaries[0].id).unwrap();
        assert_eq!(detail.sweep_plot, plot);
        fs::remove_file(&database).unwrap();
        let _ = fs::remove_file(database.with_extension("sqlite3-shm"));
        let _ = fs::remove_file(database.with_extension("sqlite3-wal"));
        fs::remove_dir(capture_root).unwrap();
        fs::remove_dir(root).unwrap();
    }

    #[test]
    fn managed_sigmf_validation_and_delete_stay_inside_capture_root() {
        let root = temporary_test_directory("managed-dataset");
        let capture_root = root.join("captures");
        let session_root = capture_root.join("session-1");
        fs::create_dir_all(&session_root).unwrap();
        let data_path = session_root.join("scan.sigmf-data");
        let metadata_path = session_root.join("scan.sigmf-meta");
        fs::write(&data_path, [1_u8, 0, 2, 0, 3, 0, 4, 0]).unwrap();
        fs::write(
            &metadata_path,
            br#"{"global":{"core:datatype":"ci16_le"},"captures":[{},{}]}"#,
        )
        .unwrap();
        let dataset = SweepDatasetView {
            format: "sigmf".into(),
            datatype: "ci16_le".into(),
            data_path: data_path.to_string_lossy().into_owned(),
            metadata_path: metadata_path.to_string_lossy().into_owned(),
            bytes: 8,
        };
        validate_managed_dataset(&dataset, &capture_root, 2, true).unwrap();

        let outside = root.join("outside.sigmf-data");
        fs::write(&outside, [0_u8; 8]).unwrap();
        let mut escaped = dataset.clone();
        escaped.data_path = outside.to_string_lossy().into_owned();
        assert!(validate_managed_dataset(&escaped, &capture_root, 2, true).is_err());

        assert_eq!(
            delete_managed_dataset(&dataset, &capture_root).unwrap().0,
            2
        );
        assert!(!data_path.exists());
        assert!(!metadata_path.exists());
        fs::remove_file(outside).unwrap();
        fs::remove_dir(session_root).unwrap();
        fs::remove_dir(capture_root).unwrap();
        fs::remove_dir(root).unwrap();
    }

    #[test]
    fn output_classification_exposes_control_plane_events() {
        assert!(is_empty_agent_line("Agent> "));
        assert!(!is_empty_agent_line("Agent> hello"));
        assert_eq!(classify_output("Agent> hello", false), "qwen");
        assert_eq!(classify_output("Validated plan> {}", false), "plan");
        assert_eq!(classify_output("已验证计划：保持当前状态", false), "plan");
        assert_eq!(classify_output("Execution> {}", false), "execution");
        assert_eq!(
            classify_output("候选复查结果：安全完成", false),
            "execution"
        );
        assert_eq!(classify_output("巡航状态：正在检查 SDR", false), "cruise");
        assert_eq!(classify_output("搜索> 正在查询 \"Spark\"", false), "search");
        assert_eq!(
            classify_output("搜索来源> \"来源\" — \"https://example.com\"", false),
            "search"
        );
        assert_eq!(classify_output("正在扫频 100MHz", false), "sweep");
    }

    #[test]
    fn restores_validated_structured_observation_into_runtime_request() {
        let base = serde_json::to_vec(&serde_json::json!({
            "protocol_version": 1,
            "request_id": 1,
            "session_generation": 1,
            "instruction": "status",
            "state": "idle",
            "observation": {
                "age_ms": 0,
                "health": {
                    "sdr_online": true,
                    "can_retune": true,
                    "can_capture_iq": true,
                    "fpga_available": false,
                    "recognizer_available": false,
                    "dropped_observations": 0
                },
                "candidates": []
            },
            "limits": {
                "min_freq_hz": 70000000,
                "max_freq_hz": 6000000000_u64,
                "max_span_hz": 20000000,
                "max_bandwidth_hz": 10000000,
                "max_dwell_ms": 5000,
                "max_iq_samples": 1048576,
                "max_iq_bytes": 4194304,
                "auto_approve_iq_bytes": 262144,
                "max_observation_age_ms": 120000
            }
        }))
        .unwrap();
        let restored = runtime_request_bytes(&base, &observation()).unwrap();
        let request: PlanRequest = serde_json::from_slice(&restored).unwrap();
        assert_eq!(request.observation.candidates[0].id, "initial-1-7");
    }

    #[test]
    fn rejects_duplicate_persisted_candidate_ids() {
        let mut invalid = observation();
        invalid.candidates.push(invalid.candidates[0].clone());
        assert!(validate_persisted_observation(&invalid).is_err());
    }

    #[test]
    fn provider_config_accepts_responses_and_never_serializes_the_key() {
        let config = validate_provider_request(ProviderConfigRequest {
            api: "openai-responses".into(),
            base_url: "https://opencode.ai/zen/v1".into(),
            provider: "opencode".into(),
            model: "gpt-5.6-sol".into(),
            api_key: "test-secret".into(),
            context_window: 200_000,
            compression_threshold_percent: 90,
            initial_survey: default_initial_survey(),
            result_storage: ResultStorageConfig::default(),
        })
        .unwrap();
        let public = serde_json::to_string(&provider_config_view(&config)).unwrap();
        assert!(public.contains("gpt-5.6-sol"));
        assert!(!public.contains("test-secret"));
        assert!(!public.contains("api_key"));
    }

    #[test]
    fn saved_key_can_be_reused_only_for_the_same_base_url() {
        let saved = validate_provider_request(ProviderConfigRequest {
            api: "openai-completions".into(),
            base_url: "https://opencode.ai/zen/go/v1".into(),
            provider: "opencode-go".into(),
            model: "deepseek-v4-flash".into(),
            api_key: "test-secret".into(),
            context_window: 196_608,
            compression_threshold_percent: 90,
            initial_survey: default_initial_survey(),
            result_storage: ResultStorageConfig::default(),
        })
        .unwrap();
        let mut request = ProviderConfigRequest {
            api: "openai-completions".into(),
            base_url: "https://opencode.ai/zen/go/v1".into(),
            provider: "opencode-go".into(),
            model: "glm-5.2".into(),
            api_key: String::new(),
            context_window: 200_000,
            compression_threshold_percent: 90,
            initial_survey: default_initial_survey(),
            result_storage: ResultStorageConfig::default(),
        };
        reuse_saved_provider_key(&mut request, Some(&saved)).unwrap();
        assert_eq!(request.api_key, "test-secret");

        request.api_key.clear();
        request.base_url = "https://api.example.com/v1".into();
        assert!(reuse_saved_provider_key(&mut request, Some(&saved)).is_err());
    }

    #[test]
    fn provider_config_requires_https_away_from_loopback() {
        assert!(validate_provider_url("http://127.0.0.1:8000/v1").is_ok());
        let error = validate_provider_url("http://api.example.com/v1").unwrap_err();
        assert_eq!(error.0, StatusCode::BAD_REQUEST);
    }

    #[test]
    fn parses_and_bounds_common_provider_model_lists() {
        let models = parse_provider_models(
            br#"{"data":[{"id":"z-model"},{"id":"a-model","context_window":131072},{"id":"a-model"}]}"#,
        )
        .unwrap();
        assert_eq!(
            models,
            vec![
                ProviderModelView {
                    id: "a-model".into(),
                    context_window: Some(131_072),
                },
                ProviderModelView {
                    id: "z-model".into(),
                    context_window: None,
                },
            ]
        );

        let models = parse_provider_models(br#"{"models":["one",{"model":"two"}]}"#).unwrap();
        assert_eq!(models[0].id, "one");
        assert_eq!(models[1].id, "two");
    }

    #[tokio::test]
    async fn discovers_models_with_bearer_auth_without_returning_the_key() {
        async fn mock_models(headers: axum::http::HeaderMap) -> Response {
            if headers
                .get(header::AUTHORIZATION)
                .and_then(|value| value.to_str().ok())
                != Some("Bearer test-secret")
            {
                return StatusCode::UNAUTHORIZED.into_response();
            }
            Json(serde_json::json!({
                "object": "list",
                "data": [{"id": "gpt-test"}]
            }))
            .into_response()
        }

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            axum::serve(
                listener,
                Router::new().route("/v1/models", get(mock_models)),
            )
            .await
            .unwrap();
        });
        let models = fetch_provider_models(&format!("http://{address}/v1"), "test-secret")
            .await
            .unwrap();
        server.abort();
        assert_eq!(models[0].id, "gpt-test");
        let public = serde_json::to_string(&ProviderModelsView { models }).unwrap();
        assert!(!public.contains("test-secret"));
    }
}
