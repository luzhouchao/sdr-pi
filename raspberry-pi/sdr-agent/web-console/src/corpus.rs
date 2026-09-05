mod rf_v1;
use super::{
    ensure_real_directory, internal_error, now_ms, open_result_database, ApiError, ApiResult,
};
use axum::http::StatusCode;
pub(super) use rf_v1::{derive_rf_v1, RfV1DeriveRequest};
use rusqlite::{params, OptionalExtension};
use sdr_agent_controller::{
    recognition_input::sha256_hex,
    sweep::{
        analyze_ci16_window, available_storage_bytes, validate_completed_sweep, SweepPlan,
        SweepReport,
    },
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashSet,
    fs::{self, File, OpenOptions},
    io::Write,
    os::unix::fs::{OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
};

pub(super) const MAX_CORPUS_IQ_BYTES: u64 = 256 * 1024;
pub(super) const MAX_CORPUS_REQUEST_BYTES: usize = 384 * 1024;
const PACKAGE_OVERHEAD_BYTES: u64 = 1024 * 1024;
const PROFILE_BYTES: &[u8] = include_bytes!(
    "../../../../jetson-agx/sdrharness/config/amc/rml2018a-d8-current.integration-profile.json"
);
const PREPROCESS_BYTES: &[u8] =
    include_bytes!("../../../../jetson-agx/sdrharness/config/amc/legacy-adc-unit-rms-v0.json");
const LABEL_BYTES: &[u8] =
    include_bytes!("../../../../jetson-agx/sdrharness/config/amc/rml2018a-labels.json");
const PROFILE_SHA256: &str = "7d2347550939be13d3ccde84add514ca5b4e549783fbc8e724124b4f0f4358ba";
const PREPROCESS_SHA256: &str = "20f2f21b9d01a5163806a2b1e88c2e1ff0975647eb9da27071ea3f1d61a80303";
const LABEL_SHA256: &str = "0c269924bb74cf23584ad7584808d1bb263cdf03680f723f4cc40f165e6eafc8";
const PACKAGE_FILES: [&str; 10] = [
    "derivation.json",
    "annotation.json",
    "source-report.json",
    "capture-plan.json",
    "input-profile.json",
    "labels.json",
    "manifest.json",
    "preprocess.json",
    "raw.iq",
    "records.jsonl",
];

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CorpusPreflight {
    pub point_count: u16,
    pub samples_per_point: u64,
    pub maximum_iq_bytes: u64,
    pub estimated_duration_ms: u64,
    pub agx_available_bytes_before: u64,
    pub agx_temporary_directory: Option<String>,
    pub p201_transient_directory: String,
    pub direct_stop: String,
    pub radio_restored: bool,
    pub p201_transient_removed: bool,
    pub agx_temporary_removed: bool,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum UnknownLabelReason {
    NoIndependentLabel,
    NoiseOrIdle,
    AmbiguousAnnotation,
    OutOfLabelSpace,
    QualityFailure,
}

impl UnknownLabelReason {
    fn as_str(self) -> &'static str {
        match self {
            Self::NoIndependentLabel => "no_independent_label",
            Self::NoiseOrIdle => "noise_or_idle",
            Self::AmbiguousAnnotation => "ambiguous_annotation",
            Self::OutOfLabelSpace => "out_of_label_space",
            Self::QualityFailure => "quality_failure",
        }
    }
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct P201CorpusIngestRequest {
    pub schema_version: u16,
    pub capture_session_id: String,
    pub captured_at_utc: String,
    pub label_reason: UnknownLabelReason,
    pub plan: SweepPlan,
    pub preflight: CorpusPreflight,
    pub report: SweepReport,
    pub iq_base64: String,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub(super) struct CorpusResultSummary {
    pub result_id: String,
    pub capture_session_id: String,
    pub captured_at_utc: String,
    pub capture_day: String,
    pub plan_id: String,
    pub profile_id: String,
    pub profile_sha256: String,
    pub preprocess_id: String,
    pub preprocess_sha256: String,
    pub center_hz: u64,
    pub sample_rate_hz: u64,
    pub rf_bandwidth_hz: u64,
    pub gain_mode: String,
    pub rx_gain_db: f64,
    pub sequence: u64,
    pub samples: u64,
    pub iq_bytes: u64,
    pub iq_sha256: String,
    pub raw_rms_dbfs: f64,
    pub measured_snr_db: f64,
    pub clipped_samples: u64,
    pub dropped_samples: u64,
    pub overflow: bool,
    pub health_flags: u32,
    pub healthy: bool,
    pub label_provenance: String,
    pub label_reason: String,
    pub manual_delete_path: String,
    pub created_at_ms: u64,
}

#[derive(Debug, Serialize)]
pub(super) struct CorpusResultDetail {
    pub summary: CorpusResultSummary,
    pub manifest: Value,
    pub record: Value,
}

#[derive(Debug, Serialize)]
pub(super) struct CorpusDeleteResult {
    pub deleted: String,
    pub files_deleted: u64,
    pub bytes_deleted: u64,
}

struct ValidatedIngest {
    result_id: String,
    capture_day: String,
    iq: Vec<u8>,
}

pub(super) fn initialize_corpus_store(database: &Path, root: &Path) -> ApiResult<()> {
    ensure_real_directory(root)?;
    fs::set_permissions(root, fs::Permissions::from_mode(0o700)).map_err(internal_error)?;
    verify_embedded_contract()?;
    let connection = open_result_database(database)?;
    connection
        .execute_batch(
            "CREATE TABLE IF NOT EXISTS p201_corpus_results (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               result_id TEXT NOT NULL UNIQUE,
               capture_session_id TEXT NOT NULL,
               captured_at_utc TEXT NOT NULL,
               capture_day TEXT NOT NULL,
               plan_id TEXT NOT NULL,
               profile_id TEXT NOT NULL,
               profile_sha256 TEXT NOT NULL,
               preprocess_id TEXT NOT NULL,
               preprocess_sha256 TEXT NOT NULL,
               center_hz INTEGER NOT NULL,
               sample_rate_hz INTEGER NOT NULL,
               rf_bandwidth_hz INTEGER NOT NULL,
               gain_mode TEXT NOT NULL,
               rx_gain_db REAL NOT NULL,
               sequence INTEGER NOT NULL,
               samples INTEGER NOT NULL,
               iq_bytes INTEGER NOT NULL,
               iq_sha256 TEXT NOT NULL,
               raw_rms_dbfs REAL NOT NULL,
               measured_snr_db REAL NOT NULL,
               clipped_samples INTEGER NOT NULL,
               dropped_samples INTEGER NOT NULL,
               overflow INTEGER NOT NULL,
               health_flags INTEGER NOT NULL,
               healthy INTEGER NOT NULL,
               label_provenance TEXT NOT NULL,
               label_reason TEXT NOT NULL,
               manifest_json TEXT NOT NULL,
               record_json TEXT NOT NULL,
               created_at_ms INTEGER NOT NULL
             );
             CREATE INDEX IF NOT EXISTS p201_corpus_created
               ON p201_corpus_results(created_at_ms DESC);
             CREATE TABLE IF NOT EXISTS p201_corpus_partition_groups (
               group_kind TEXT NOT NULL, group_hash TEXT NOT NULL, split TEXT NOT NULL,
               PRIMARY KEY(group_kind, group_hash)
             );",
        )
        .map_err(internal_error)?;
    Ok(())
}

pub(super) fn list_corpus_results(database: &Path) -> ApiResult<Vec<CorpusResultSummary>> {
    let connection = open_result_database(database)?;
    let mut statement = connection
        .prepare(
            "SELECT result_id, capture_session_id, captured_at_utc, capture_day,
                    plan_id, profile_id, profile_sha256, preprocess_id,
                    preprocess_sha256, center_hz, sample_rate_hz,
                    rf_bandwidth_hz, gain_mode, rx_gain_db, sequence, samples,
                    iq_bytes, iq_sha256, raw_rms_dbfs, measured_snr_db,
                    clipped_samples, dropped_samples, overflow, health_flags,
                    healthy, label_provenance, label_reason, created_at_ms
             FROM p201_corpus_results ORDER BY created_at_ms DESC, id DESC",
        )
        .map_err(internal_error)?;
    let rows = statement
        .query_map([], corpus_summary_from_row)
        .map_err(internal_error)?;
    rows.collect::<Result<Vec<_>, _>>().map_err(internal_error)
}

pub(super) fn load_corpus_result(
    database: &Path,
    result_id: &str,
) -> ApiResult<CorpusResultDetail> {
    require_safe_id(result_id, 128, "语料结果 ID")?;
    let connection = open_result_database(database)?;
    let result = connection
        .query_row(
            "SELECT result_id, capture_session_id, captured_at_utc, capture_day,
                    plan_id, profile_id, profile_sha256, preprocess_id,
                    preprocess_sha256, center_hz, sample_rate_hz,
                    rf_bandwidth_hz, gain_mode, rx_gain_db, sequence, samples,
                    iq_bytes, iq_sha256, raw_rms_dbfs, measured_snr_db,
                    clipped_samples, dropped_samples, overflow, health_flags,
                    healthy, label_provenance, label_reason, created_at_ms,
                    manifest_json, record_json
             FROM p201_corpus_results WHERE result_id = ?1",
            params![result_id],
            |row| {
                let summary = corpus_summary_from_row(row)?;
                let manifest: String = row.get(28)?;
                let record: String = row.get(29)?;
                Ok((summary, manifest, record))
            },
        )
        .optional()
        .map_err(internal_error)?;
    let (summary, manifest, record) =
        result.ok_or_else(|| ApiError(StatusCode::NOT_FOUND, "接收语料不存在".into()))?;
    Ok(CorpusResultDetail {
        summary,
        manifest: serde_json::from_str(&manifest).map_err(internal_error)?,
        record: serde_json::from_str(&record).map_err(internal_error)?,
    })
}

pub(super) fn ingest_corpus_result(
    database: &Path,
    corpus_root: &Path,
    request: P201CorpusIngestRequest,
) -> ApiResult<CorpusResultDetail> {
    let validated = validate_ingest(corpus_root, &request)?;
    let final_directory = corpus_root.join(&validated.result_id);
    if final_directory.exists() {
        return Err(ApiError(
            StatusCode::CONFLICT,
            "同一 P201 capture session/sequence 已经入库".into(),
        ));
    }
    if corpus_result_exists(database, &validated.result_id)? {
        return Err(ApiError(
            StatusCode::CONFLICT,
            "同一 P201 capture session/sequence 已经入库".into(),
        ));
    }

    let point = &request.report.points[0];
    let result_id = validated.result_id.clone();
    let plan_asset_id = format!("{result_id}-plan");
    let iq_asset_id = format!("{result_id}-iq");
    let record_id = format!("{result_id}-window-0");
    let capture_plan = json!({
        "schema_version": 1,
        "schema_id": "p201_corpus_capture_plan_v1",
        "plan_id": request.plan.sweep_id,
        "capture_session_id": request.capture_session_id,
        "sweep": request.plan,
        "preflight": request.preflight,
    });
    let capture_plan_bytes = json_line(&capture_plan)?;
    let plan_sha256 = sha256_hex(&capture_plan_bytes);
    let iq_sha256 = sha256_hex(&validated.iq);
    let record = json!({
        "schema_version": 1,
        "schema_id": "amc_corpus_record_v1",
        "record_id": record_id,
        "split": "receive_domain",
        "lineage": {
            "source_sample_id": result_id,
            "capture_session_id": request.capture_session_id,
            "capture_day": validated.capture_day,
            "parent_record_id": null,
            "transforms": [],
        },
        "window": {
            "window_index": 0,
            "sample_offset": 0,
            "samples": point.captured_samples,
            "bytes": validated.iq.len(),
            "sample_format": "ci16_le",
            "layout": "interleaved_iq",
            "endianness": "little",
            "sha256": iq_sha256,
            "storage": {
                "kind": "managed_asset",
                "asset_id": iq_asset_id,
                "offset_bytes": 0,
            },
        },
        "label": {
            "provenance": "unknown",
            "reason": request.label_reason.as_str(),
        },
        "source": capture_source(&request, &result_id, &validated.capture_day, &plan_asset_id, &plan_sha256, validated.iq.len()),
    });
    let source_report_bytes =
        json_line(&serde_json::to_value(&request.report).map_err(internal_error)?)?;
    let record_bytes = json_line(&record)?;
    let manifest = json!({
        "schema_version": 1,
        "schema_id": "amc_corpus_manifest_v1",
        "manifest_id": result_id,
        "created_at_utc": request.captured_at_utc,
        "status": "frozen",
        "corpus_kind": "p201_receive",
        "contract": {
            "input_profile": {
                "id": "rml2018a-d8-current-integration-v1",
                "path": "input-profile.json",
                "sha256": PROFILE_SHA256,
                "admission": "integration_only",
            },
            "preprocessing": {
                "id": "legacy_adc_unit_rms_v0",
                "path": "preprocess.json",
                "sha256": PREPROCESS_SHA256,
                "status": "integration_only",
            },
            "label_space": {
                "id": "rml2018a-labels-provisional-v1",
                "path": "labels.json",
                "sha256": LABEL_SHA256,
                "numeric_ids_authoritative": true,
                "display_names_status": "provisional",
            },
        },
        "split_policy": {
            "strategy": "group_exclusive",
            "group_keys": ["source_sample_id", "capture_session_id", "capture_day"],
            "allowed_splits": ["receive_domain"],
            "frozen": true,
            "test_locked": true,
        },
        "assets": [
            asset("profile-integration-v1", "input-profile.json", "input_profile", PROFILE_BYTES, "repository_metadata", "not_applicable"),
            asset("preprocess-integration-v0", "preprocess.json", "preprocess_spec", PREPROCESS_BYTES, "repository_metadata", "not_applicable"),
            asset("labels-provisional-v1", "labels.json", "label_table", LABEL_BYTES, "repository_metadata", "not_applicable"),
            asset(&plan_asset_id, "capture-plan.json", "capture_plan", &capture_plan_bytes, "application_result", "required"),
            asset("original-source-report", "source-report.json", "capture_report", &source_report_bytes, "application_result", "required"),
            asset(&iq_asset_id, "raw.iq", "raw_iq", &validated.iq, "application_result", "required"),
        ],
        "record_index": {
            "schema_id": "amc_corpus_record_v1",
            "format": "jsonl",
            "path": "records.jsonl",
            "count": 1,
            "bytes": record_bytes.len(),
            "sha256": sha256_hex(&record_bytes),
        },
        "governance": {
            "bulk_iq_in_git": false,
            "model_prediction_is_ground_truth": false,
            "unlabeled_accuracy_allowed": false,
            "manual_delete_required_for_user_results": true,
        },
    });
    let connection = open_result_database(database)?;
    store_package(
        &connection,
        corpus_root,
        &result_id,
        &manifest,
        &record,
        &[
            ("input-profile.json", PROFILE_BYTES),
            ("preprocess.json", PREPROCESS_BYTES),
            ("labels.json", LABEL_BYTES),
            ("capture-plan.json", &capture_plan_bytes),
            ("raw.iq", &validated.iq),
            ("source-report.json", &source_report_bytes),
        ],
        None,
    )?;
    load_corpus_result(database, &result_id)
}

fn capture_source(
    request: &P201CorpusIngestRequest,
    result_id: &str,
    capture_day: &str,
    plan_asset_id: &str,
    plan_hash: &str,
    iq_bytes: usize,
) -> Value {
    let point = &request.report.points[0];
    json!({
        "kind": "p201_receive",
        "capture_session_id": request.capture_session_id,
        "captured_at_utc": request.captured_at_utc,
        "capture_day": capture_day,
        "plan_id": request.plan.sweep_id,
        "plan_asset_id": plan_asset_id,
        "plan_sha256": plan_hash,
        "center_hz": point.actual_center_hz,
        "sample_rate_hz": point.sample_rate_hz,
        "rf_bandwidth_hz": point.rf_bandwidth_hz,
        "gain_mode": "manual",
        "rx_gain_db": request.plan.gain_db.expect("validated fixed gain"),
        "sequence": point.sequence,
        "samples_captured": point.captured_samples,
        "bytes_transferred": iq_bytes,
        "rx_input": point.rx_input,
        "quality": {
            "raw_rms_dbfs": point.band_power_dbfs,
            "measured_snr_db": point.spectral.measured_snr_db,
            "clipped_samples": point.clipped_samples,
            "dropped_samples": point.dropped_samples,
            "overflow": point.overflow,
            "health_flags": point.health.flags,
            "healthy": point.health.healthy,
        },
        "retention": {
            "user_visible": true,
            "result_id": result_id,
            "manual_delete_available": true,
            "p201_transient_removed": true,
            "agx_temporary_removed": true,
        },
    })
}

// Shared legacy and RF-v1 persistence; one SQLite table and one package lifecycle.
fn store_package(
    connection: &rusqlite::Connection,
    corpus_root: &Path,
    result_id: &str,
    manifest: &Value,
    record: &Value,
    files: &[(&str, &[u8])],
    iq_link: Option<&Path>,
) -> ApiResult<()> {
    let staging = create_staging_directory(corpus_root, result_id)?;
    let final_directory = corpus_root.join(result_id);
    let mut renamed = false;
    let result = (|| -> ApiResult<()> {
        for (name, data) in files {
            write_private_file(&staging.join(name), data)?;
        }
        if let Some(parent_iq) = iq_link {
            fs::hard_link(parent_iq, staging.join("raw.iq")).map_err(internal_error)?;
        }
        write_private_file(&staging.join("manifest.json"), &pretty_json(manifest)?)?;
        write_private_file(&staging.join("records.jsonl"), &json_line(record)?)?;
        File::open(&staging)
            .and_then(|d| d.sync_all())
            .map_err(internal_error)?;
        // create_dir reserves the final name; never replace another result.
        fs::create_dir(&final_directory).map_err(internal_error)?;
        if let Err(error) = fs::rename(&staging, &final_directory) {
            fs::remove_dir(&final_directory).map_err(internal_error)?;
            return Err(internal_error(error));
        }
        renamed = true;
        File::open(corpus_root)
            .and_then(|d| d.sync_all())
            .map_err(internal_error)?;
        let source = &record["source"];
        let quality = &source["quality"];
        let contract = &manifest["contract"];
        let label = &record["label"];
        let manifest_json = serde_json::to_string(manifest).map_err(internal_error)?;
        let record_json = serde_json::to_string(record).map_err(internal_error)?;
        connection
            .execute(
                "INSERT INTO p201_corpus_results (
           result_id, capture_session_id, captured_at_utc, capture_day, plan_id,
           profile_id, profile_sha256, preprocess_id, preprocess_sha256,
           center_hz, sample_rate_hz, rf_bandwidth_hz, gain_mode, rx_gain_db,
           sequence, samples, iq_bytes, iq_sha256, raw_rms_dbfs,
           measured_snr_db, clipped_samples, dropped_samples, overflow,
           health_flags, healthy, label_provenance, label_reason, manifest_json,
           record_json, created_at_ms
         ) VALUES (
           ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10,
           ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18, ?19, ?20,
           ?21, ?22, ?23, ?24, ?25, ?26, ?27, ?28, ?29, ?30
         )",
                params![
                    result_id,
                    source["capture_session_id"].as_str(),
                    source["captured_at_utc"].as_str(),
                    source["capture_day"].as_str(),
                    source["plan_id"].as_str(),
                    contract["input_profile"]["id"].as_str(),
                    contract["input_profile"]["sha256"].as_str(),
                    contract["preprocessing"]["id"].as_str(),
                    contract["preprocessing"]["sha256"].as_str(),
                    source["center_hz"].as_i64(),
                    source["sample_rate_hz"].as_i64(),
                    source["rf_bandwidth_hz"].as_i64(),
                    source["gain_mode"].as_str(),
                    source["rx_gain_db"].as_f64(),
                    source["sequence"].as_i64(),
                    record["window"]["samples"].as_i64(),
                    record["window"]["bytes"].as_i64(),
                    record["window"]["sha256"].as_str(),
                    quality["raw_rms_dbfs"].as_f64(),
                    quality["measured_snr_db"].as_f64(),
                    quality["clipped_samples"].as_i64(),
                    quality["dropped_samples"].as_i64(),
                    quality["overflow"].as_bool(),
                    quality["health_flags"].as_i64(),
                    quality["healthy"].as_bool(),
                    label["provenance"].as_str(),
                    label["reason"]
                        .as_str()
                        .or(label["category"].as_str())
                        .unwrap_or("independent_annotation"),
                    manifest_json,
                    record_json,
                    to_i64(now_ms())?,
                ],
            )
            .map_err(internal_error)?;
        Ok(())
    })();
    if let Err(error) = result {
        cleanup_package_directory(
            corpus_root,
            if renamed { &final_directory } else { &staging },
            false,
        )?;
        return Err(error);
    }
    Ok(())
}

pub(super) fn delete_corpus_result(
    database: &Path,
    corpus_root: &Path,
    result_id: &str,
) -> ApiResult<CorpusDeleteResult> {
    require_safe_id(result_id, 128, "语料结果 ID")?;
    let mut connection = open_result_database(database)?;
    let transaction = connection
        .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .map_err(internal_error)?;
    let exists = transaction
        .query_row(
            "SELECT 1 FROM p201_corpus_results WHERE result_id = ?1",
            params![result_id],
            |_| Ok(()),
        )
        .optional()
        .map_err(internal_error)?;
    if exists.is_none() {
        return Err(ApiError(StatusCode::NOT_FOUND, "接收语料不存在".into()));
    }
    let directory = corpus_root.join(result_id);
    let (files_deleted, bytes_deleted) = cleanup_package_directory(corpus_root, &directory, true)?;
    transaction
        .execute(
            "DELETE FROM p201_corpus_results WHERE result_id = ?1",
            params![result_id],
        )
        .map_err(internal_error)?;
    transaction.commit().map_err(internal_error)?;
    Ok(CorpusDeleteResult {
        deleted: result_id.to_owned(),
        files_deleted,
        bytes_deleted,
    })
}

fn validate_ingest(
    corpus_root: &Path,
    request: &P201CorpusIngestRequest,
) -> ApiResult<ValidatedIngest> {
    let iq = decode_base64(&request.iq_base64)?;
    validate_ingest_iq(corpus_root, request, iq)
}

fn validate_ingest_iq(
    corpus_root: &Path,
    request: &P201CorpusIngestRequest,
    iq: Vec<u8>,
) -> ApiResult<ValidatedIngest> {
    if request.schema_version != 1 {
        return bad_request("只接受 p201 corpus ingest schema v1");
    }
    require_safe_id(&request.capture_session_id, 64, "capture session ID")?;
    let capture_day = validate_utc(&request.captured_at_utc)?;
    let validated =
        validate_completed_sweep(&request.plan, &request.report).map_err(bad_gateway)?;
    if validated.centers_hz.len() != 1
        || validated.sample_rate_hz != 2_100_000
        || validated.rf_bandwidth_hz != 1_500_000
        || validated.samples_per_point != 4_096
        || request.plan.settle_ms != 100
        || request.plan.point_timeout_ms != 1_000
        || request.plan.gain_db != Some(50)
        || validated.maximum_iq_bytes > MAX_CORPUS_IQ_BYTES
        || request.report.backend != "agx_iq_software_aggregate"
        || request.report.backend_version != 1
        || request.report.points.len() != 1
        || request.report.dataset.is_some()
    {
        return bad_request(
            "语料入口只接受当前 integration profile 的单点 2.1-MS/s、1.5-MHz、50-dB、4096-sample AGX software sweep",
        );
    }
    let preflight = &request.preflight;
    if preflight.point_count != 1
        || preflight.samples_per_point != validated.samples_per_point
        || preflight.maximum_iq_bytes != validated.maximum_iq_bytes
        || preflight.estimated_duration_ms != validated.estimated_duration_ms
        || preflight.agx_available_bytes_before
            < validated
                .maximum_iq_bytes
                .saturating_add(PACKAGE_OVERHEAD_BYTES)
        || preflight.direct_stop
            != format!("SDRD/1 STOP_SESSION {}", request.plan.session_generation)
        || !preflight.radio_restored
        || !preflight.p201_transient_removed
        || !preflight.agx_temporary_removed
    {
        return bad_request("语料 preflight、恢复或清理证据与计划不一致");
    }
    validate_p201_transient_path(
        &preflight.p201_transient_directory,
        request.plan.session_generation,
    )?;
    if let Some(path) = preflight.agx_temporary_directory.as_deref() {
        validate_removed_feature_path(path)?;
        if Path::new(path).exists() {
            return bad_request("AGX 临时目录仍然存在，拒绝把 cleanup 标记为完成");
        }
    }
    ensure_real_directory(corpus_root)?;
    let current_available = available_storage_bytes(corpus_root).map_err(internal_error)?;
    if current_available
        < validated
            .maximum_iq_bytes
            .saturating_add(PACKAGE_OVERHEAD_BYTES)
    {
        return Err(ApiError(
            StatusCode::INSUFFICIENT_STORAGE,
            "AGX 语料目录剩余空间不足".into(),
        ));
    }
    if iq.len() as u64 != validated.maximum_iq_bytes {
        return bad_request("IQ 字节数与有限计划不一致");
    }
    let point = &request.report.points[0];
    let (power, spectral, clipped) = analyze_ci16_window(
        &iq,
        point.captured_samples,
        point.actual_center_hz,
        point.sample_rate_hz,
    )
    .map_err(bad_gateway)?;
    if power != point.band_power_dbfs
        || spectral != point.spectral
        || clipped != point.clipped_samples
    {
        return bad_request("IQ 内容不能重现报告中的功率、频谱或削顶质量");
    }
    if !point.rx_input.is_fixed_p201_rx1()
        || point.health.source != "iio_adapter"
        || !point.health.healthy
        || point.health.flags != 0
        || point.dropped_samples != 0
        || point.overflow
        || point.timeout.limit_ms != request.plan.point_timeout_ms
        || point.timeout.timed_out
    {
        return bad_request("P201 RX1 身份或采集健康状态不满足语料入口");
    }
    let result_id = format!("p201-{}-{}", request.capture_session_id, point.sequence);
    require_safe_id(&result_id, 96, "派生语料结果 ID")?;
    Ok(ValidatedIngest {
        result_id,
        capture_day,
        iq,
    })
}

fn corpus_summary_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<CorpusResultSummary> {
    let result_id: String = row.get(0)?;
    Ok(CorpusResultSummary {
        manual_delete_path: format!("/api/corpus/{result_id}"),
        result_id,
        capture_session_id: row.get(1)?,
        captured_at_utc: row.get(2)?,
        capture_day: row.get(3)?,
        plan_id: row.get(4)?,
        profile_id: row.get(5)?,
        profile_sha256: row.get(6)?,
        preprocess_id: row.get(7)?,
        preprocess_sha256: row.get(8)?,
        center_hz: nonnegative_u64(row.get(9)?),
        sample_rate_hz: nonnegative_u64(row.get(10)?),
        rf_bandwidth_hz: nonnegative_u64(row.get(11)?),
        gain_mode: row.get(12)?,
        rx_gain_db: row.get(13)?,
        sequence: nonnegative_u64(row.get(14)?),
        samples: nonnegative_u64(row.get(15)?),
        iq_bytes: nonnegative_u64(row.get(16)?),
        iq_sha256: row.get(17)?,
        raw_rms_dbfs: row.get(18)?,
        measured_snr_db: row.get(19)?,
        clipped_samples: nonnegative_u64(row.get(20)?),
        dropped_samples: nonnegative_u64(row.get(21)?),
        overflow: row.get::<_, i64>(22)? != 0,
        health_flags: nonnegative_u64(row.get(23)?).min(u64::from(u32::MAX)) as u32,
        healthy: row.get::<_, i64>(24)? != 0,
        label_provenance: row.get(25)?,
        label_reason: row.get(26)?,
        created_at_ms: nonnegative_u64(row.get(27)?),
    })
}

fn corpus_result_exists(database: &Path, result_id: &str) -> ApiResult<bool> {
    let connection = open_result_database(database)?;
    connection
        .query_row(
            "SELECT 1 FROM p201_corpus_results WHERE result_id = ?1",
            params![result_id],
            |_| Ok(()),
        )
        .optional()
        .map(|value| value.is_some())
        .map_err(internal_error)
}

fn verify_embedded_contract() -> ApiResult<()> {
    for (name, bytes, expected) in [
        ("input profile", PROFILE_BYTES, PROFILE_SHA256),
        ("preprocessing", PREPROCESS_BYTES, PREPROCESS_SHA256),
        ("label space", LABEL_BYTES, LABEL_SHA256),
    ] {
        if sha256_hex(bytes) != expected {
            return Err(ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                format!("内嵌 AMC {name} 哈希与编译期合同不一致"),
            ));
        }
    }
    Ok(())
}

fn asset(
    asset_id: &str,
    path: &str,
    role: &str,
    bytes: &[u8],
    storage_class: &str,
    manual_delete: &str,
) -> Value {
    json!({
        "asset_id": asset_id,
        "path": path,
        "role": role,
        "bytes": bytes.len(),
        "sha256": sha256_hex(bytes),
        "storage_class": storage_class,
        "manual_delete": manual_delete,
    })
}

fn pretty_json(value: &Value) -> ApiResult<Vec<u8>> {
    let mut bytes = serde_json::to_vec_pretty(value).map_err(internal_error)?;
    bytes.push(b'\n');
    Ok(bytes)
}

fn json_line(value: &Value) -> ApiResult<Vec<u8>> {
    let mut bytes = serde_json::to_vec(value).map_err(internal_error)?;
    bytes.push(b'\n');
    Ok(bytes)
}

fn create_staging_directory(root: &Path, result_id: &str) -> ApiResult<PathBuf> {
    for attempt in 0..16_u8 {
        let path = root.join(format!(
            ".staging-{result_id}-{}-{}-{attempt}",
            std::process::id(),
            now_ms()
        ));
        match fs::create_dir(&path) {
            Ok(()) => {
                fs::set_permissions(&path, fs::Permissions::from_mode(0o700))
                    .map_err(internal_error)?;
                return Ok(path);
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(internal_error(error)),
        }
    }
    Err(ApiError(
        StatusCode::INTERNAL_SERVER_ERROR,
        "无法创建唯一语料暂存目录".into(),
    ))
}

fn write_private_file(path: &Path, bytes: &[u8]) -> ApiResult<()> {
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(path)
        .map_err(internal_error)?;
    file.write_all(bytes).map_err(internal_error)?;
    file.sync_all().map_err(internal_error)
}

fn cleanup_package_directory(
    root: &Path,
    path: &Path,
    require_final_name: bool,
) -> ApiResult<(u64, u64)> {
    ensure_real_directory(root)?;
    if !path.exists() {
        return Ok((0, 0));
    }
    let metadata = fs::symlink_metadata(path).map_err(internal_error)?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "语料包必须是真实目录".into(),
        ));
    }
    let canonical_root = fs::canonicalize(root).map_err(internal_error)?;
    let canonical_path = fs::canonicalize(path).map_err(internal_error)?;
    if canonical_path.parent() != Some(canonical_root.as_path()) {
        return Err(ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "语料包不属于 AGX 受管语料根目录".into(),
        ));
    }
    if require_final_name {
        let name = path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("");
        require_safe_id(name, 96, "语料包目录")?;
    }
    let allowed: HashSet<&str> = PACKAGE_FILES.into_iter().collect();
    let mut entries = Vec::new();
    for entry in fs::read_dir(path).map_err(internal_error)? {
        let entry = entry.map_err(internal_error)?;
        let name = entry.file_name();
        let name = name.to_str().ok_or_else(|| {
            ApiError(
                StatusCode::INTERNAL_SERVER_ERROR,
                "语料包含非 UTF-8 文件名".into(),
            )
        })?;
        let entry_metadata = fs::symlink_metadata(entry.path()).map_err(internal_error)?;
        if !allowed.contains(name)
            || !entry_metadata.file_type().is_file()
            || entry_metadata.file_type().is_symlink()
        {
            return Err(ApiError(
                StatusCode::CONFLICT,
                "语料包含未知文件或符号链接，已拒绝自动删除".into(),
            ));
        }
        entries.push((entry.path(), entry_metadata.len()));
    }
    let mut bytes_deleted = 0_u64;
    for (entry, bytes) in &entries {
        fs::remove_file(entry).map_err(internal_error)?;
        bytes_deleted = bytes_deleted.saturating_add(*bytes);
    }
    fs::remove_dir(path).map_err(internal_error)?;
    Ok((entries.len() as u64, bytes_deleted))
}

fn validate_p201_transient_path(path: &str, generation: u64) -> ApiResult<()> {
    let expected = format!("/tmp/sdr-agent-dev/agx-sweep-{generation}-0");
    if path != expected {
        return bad_request("P201 临时目录与受控 sweep feature ID 不一致");
    }
    Ok(())
}

fn validate_removed_feature_path(value: &str) -> ApiResult<()> {
    let path = Path::new(value);
    let base = Path::new("/var/tmp/sdrharness-dev");
    let components = path
        .strip_prefix(base)
        .ok()
        .map(|relative| relative.components().collect::<Vec<_>>())
        .unwrap_or_default();
    let safe_components = !components.is_empty()
        && components.len() <= 8
        && components.iter().all(|component| {
            matches!(component, std::path::Component::Normal(_))
                && component.as_os_str().to_str().is_some_and(|name| {
                    require_safe_id(name, 128, "AGX feature path component").is_ok()
                })
        });
    if !path.is_absolute() || !safe_components {
        return bad_request("AGX 临时目录必须位于 /var/tmp/sdrharness-dev 下且只含安全路径分量");
    }
    Ok(())
}

fn validate_utc(value: &str) -> ApiResult<String> {
    let bytes = value.as_bytes();
    let length_ok = (bytes.len() == 20)
        || ((22..=27).contains(&bytes.len())
            && bytes.get(19) == Some(&b'.')
            && bytes[20..bytes.len() - 1].iter().all(u8::is_ascii_digit));
    let fixed = [4, 7, 10, 13, 16];
    if !length_ok
        || bytes.last() != Some(&b'Z')
        || fixed
            .iter()
            .zip(*b"--T::")
            .any(|(index, expected)| bytes.get(*index) != Some(&expected))
        || bytes[..19]
            .iter()
            .enumerate()
            .any(|(index, byte)| !fixed.contains(&index) && !byte.is_ascii_digit())
    {
        return bad_request("captured_at_utc 必须是带 Z 的 UTC 时间");
    }
    Ok(value[..10].to_owned())
}

fn require_safe_id(value: &str, maximum: usize, field: &str) -> ApiResult<()> {
    if value.is_empty()
        || value.len() > maximum
        || !value.as_bytes()[0].is_ascii_alphanumeric()
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return bad_request(format!("{field} 不是安全标识符"));
    }
    Ok(())
}

fn decode_base64(input: &str) -> ApiResult<Vec<u8>> {
    if input.is_empty() || input.len() % 4 != 0 || input.len() > 352_000 {
        return bad_request("IQ base64 长度无效或超出上限");
    }
    let blocks = input.len() / 4;
    let mut output = Vec::with_capacity(blocks.saturating_mul(3));
    for (index, block) in input.as_bytes().chunks_exact(4).enumerate() {
        let last = index + 1 == blocks;
        let a = base64_value(block[0])?;
        let b = base64_value(block[1])?;
        let c_padding = block[2] == b'=';
        let d_padding = block[3] == b'=';
        if (c_padding && !d_padding) || (!last && (c_padding || d_padding)) {
            return bad_request("IQ base64 padding 无效");
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

fn base64_value(value: u8) -> ApiResult<u8> {
    match value {
        b'A'..=b'Z' => Ok(value - b'A'),
        b'a'..=b'z' => Ok(value - b'a' + 26),
        b'0'..=b'9' => Ok(value - b'0' + 52),
        b'+' => Ok(62),
        b'/' => Ok(63),
        _ => bad_request("IQ base64 含非法字符"),
    }
}

fn to_i64(value: u64) -> ApiResult<i64> {
    i64::try_from(value).map_err(internal_error)
}

fn nonnegative_u64(value: i64) -> u64 {
    value.max(0) as u64
}

fn bad_request<T>(message: impl Into<String>) -> ApiResult<T> {
    Err(ApiError(StatusCode::BAD_REQUEST, message.into()))
}

fn bad_gateway(error: impl std::fmt::Display) -> ApiError {
    ApiError(StatusCode::BAD_GATEWAY, error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use sdr_agent_controller::{
        execution::{ExecutionHealthMetadata, ExecutionTimeoutMetadata},
        sweep::{analyze_ci16_window, SweepFrequencies, SweepPoint, SPECTRAL_SUMMARY_ALGORITHM_ID},
    };
    use std::{process::Command, time::SystemTime};

    fn temporary_directory(label: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!("sdr-corpus-{label}-{}-{nonce}", std::process::id()))
    }

    fn base64(bytes: &[u8]) -> String {
        const ALPHABET: &[u8; 64] =
            b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        let mut output = String::new();
        for chunk in bytes.chunks(3) {
            let a = chunk[0];
            let b = *chunk.get(1).unwrap_or(&0);
            let c = *chunk.get(2).unwrap_or(&0);
            output.push(ALPHABET[(a >> 2) as usize] as char);
            output.push(ALPHABET[(((a & 0x03) << 4) | (b >> 4)) as usize] as char);
            output.push(if chunk.len() > 1 {
                ALPHABET[(((b & 0x0f) << 2) | (c >> 6)) as usize] as char
            } else {
                '='
            });
            output.push(if chunk.len() > 2 {
                ALPHABET[(c & 0x3f) as usize] as char
            } else {
                '='
            });
        }
        output
    }

    pub(super) fn request() -> P201CorpusIngestRequest {
        let samples = 4_096_u64;
        let center = 433_920_000_u64;
        let rate = 2_100_000_u64;
        let mut iq = Vec::with_capacity(samples as usize * 4);
        for index in 0..samples {
            let i = (index as i16 % 32) - 16;
            let q = 16 - (index as i16 % 32);
            iq.extend_from_slice(&i.to_le_bytes());
            iq.extend_from_slice(&q.to_le_bytes());
        }
        let (power, spectral, clipped) = analyze_ci16_window(&iq, samples, center, rate).unwrap();
        assert_eq!(spectral.algorithm_id, SPECTRAL_SUMMARY_ALGORITHM_ID);
        let plan = SweepPlan {
            sweep_id: "corpus-fixture-plan".into(),
            session_generation: 91,
            frequencies: SweepFrequencies::Centers {
                centers_hz: vec![center],
            },
            sample_rate_hz: rate,
            rf_bandwidth_hz: 1_500_000,
            settle_ms: 100,
            frame_samples: samples as u32,
            aggregate_frames: 1,
            point_timeout_ms: 1_000,
            detection_threshold_db: 6.0,
            gain_db: Some(50),
        };
        let point = SweepPoint {
            point_index: 0,
            request_id: 5,
            session_generation: 91,
            requested_center_hz: center,
            actual_center_hz: center,
            sample_rate_hz: rate,
            rf_bandwidth_hz: 1_500_000,
            sequence: 7,
            dropped_samples: 0,
            overflow: false,
            captured_samples: samples,
            band_power_dbfs: power,
            spectral,
            clipped_samples: clipped,
            status_flags: 0,
            elapsed_us: 2_000,
            timeout: ExecutionTimeoutMetadata {
                limit_ms: 1_000,
                elapsed_us: 2_000,
                timed_out: false,
            },
            health: ExecutionHealthMetadata {
                healthy: true,
                flags: 0,
                source: "iio_adapter".into(),
            },
            rx_input: serde_json::from_value(json!({
                "identity_version": 1,
                "verified": true,
                "front_panel_port": "RX1",
                "logical_channel": "RX0",
                "phy_channel": "voltage0",
                "scan_i_channel": "voltage0",
                "scan_q_channel": "voltage1",
                "rf_port_select": "A_BALANCED",
                "source": "iio_channel_attr"
            }))
            .unwrap(),
        };
        let report = SweepReport {
            sweep_id: plan.sweep_id.clone(),
            session_generation: plan.session_generation,
            backend: "agx_iq_software_aggregate".into(),
            backend_version: 1,
            estimated_duration_ms: 1_100,
            elapsed_ms: 12,
            noise_floor_dbfs: power,
            points: vec![point],
            candidates: vec![],
            dataset: None,
        };
        P201CorpusIngestRequest {
            schema_version: 1,
            capture_session_id: "fixture-session".into(),
            captured_at_utc: "2026-09-05T05:10:11Z".into(),
            label_reason: UnknownLabelReason::NoIndependentLabel,
            plan,
            preflight: CorpusPreflight {
                point_count: 1,
                samples_per_point: samples,
                maximum_iq_bytes: iq.len() as u64,
                estimated_duration_ms: 1_100,
                agx_available_bytes_before: 1024 * 1024 * 1024,
                agx_temporary_directory: None,
                p201_transient_directory: "/tmp/sdr-agent-dev/agx-sweep-91-0".into(),
                direct_stop: "SDRD/1 STOP_SESSION 91".into(),
                radio_restored: true,
                p201_transient_removed: true,
                agx_temporary_removed: true,
            },
            report,
            iq_base64: base64(&iq),
        }
    }

    #[test]
    fn p201_corpus_package_round_trips_and_reference_validator_accepts_it() {
        let root = temporary_directory("round-trip");
        let corpus = root.join("corpus");
        let database = root.join("results.sqlite3");
        fs::create_dir_all(&root).unwrap();
        initialize_corpus_store(&database, &corpus).unwrap();
        let detail = ingest_corpus_result(&database, &corpus, request()).unwrap();
        assert_eq!(detail.summary.result_id, "p201-fixture-session-7");
        assert_eq!(detail.summary.label_provenance, "unknown");
        assert_eq!(list_corpus_results(&database).unwrap().len(), 1);
        let package = corpus.join(&detail.summary.result_id);
        assert_eq!(fs::metadata(package.join("raw.iq")).unwrap().len(), 16_384);

        let repository = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let status = Command::new("python3")
            .arg(repository.join("jetson-agx/sdrharness/scripts/validate-amc-corpus-manifest.py"))
            .arg("--manifest")
            .arg(package.join("manifest.json"))
            .arg("--asset-root")
            .arg(&package)
            .arg("--verify-assets")
            .status()
            .unwrap();
        assert!(status.success());

        let deleted = delete_corpus_result(&database, &corpus, &detail.summary.result_id).unwrap();
        assert_eq!(deleted.files_deleted, 8);
        assert!(!package.exists());
        assert!(list_corpus_results(&database).unwrap().is_empty());
        fs::remove_file(&database).unwrap();
        let _ = fs::remove_file(database.with_extension("sqlite3-shm"));
        let _ = fs::remove_file(database.with_extension("sqlite3-wal"));
        fs::remove_dir(corpus).unwrap();
        fs::remove_dir(root).unwrap();
    }

    #[test]
    fn corpus_ingest_rejects_cleanup_identity_and_iq_mismatch() {
        let root = temporary_directory("reject");
        let corpus = root.join("corpus");
        let database = root.join("results.sqlite3");
        fs::create_dir_all(&root).unwrap();
        initialize_corpus_store(&database, &corpus).unwrap();

        let mut stale = request();
        stale.preflight.p201_transient_removed = false;
        assert!(ingest_corpus_result(&database, &corpus, stale).is_err());
        let mut wrong_port = request();
        wrong_port.report.points[0].rx_input.front_panel_port = "TRX1".into();
        assert!(ingest_corpus_result(&database, &corpus, wrong_port).is_err());
        let mut wrong_iq = request();
        wrong_iq.iq_base64.replace_range(0..1, "B");
        assert!(ingest_corpus_result(&database, &corpus, wrong_iq).is_err());
        let mut wrong_profile = request();
        wrong_profile.plan.gain_db = Some(49);
        assert!(ingest_corpus_result(&database, &corpus, wrong_profile).is_err());
        assert!(list_corpus_results(&database).unwrap().is_empty());

        fs::remove_file(&database).unwrap();
        let _ = fs::remove_file(database.with_extension("sqlite3-shm"));
        let _ = fs::remove_file(database.with_extension("sqlite3-wal"));
        fs::remove_dir(corpus).unwrap();
        fs::remove_dir(root).unwrap();
    }

    #[test]
    fn corpus_delete_fails_closed_when_package_has_an_unknown_file() {
        let root = temporary_directory("delete-guard");
        let corpus = root.join("corpus");
        let database = root.join("results.sqlite3");
        fs::create_dir_all(&root).unwrap();
        initialize_corpus_store(&database, &corpus).unwrap();
        let detail = ingest_corpus_result(&database, &corpus, request()).unwrap();
        let package = corpus.join(&detail.summary.result_id);
        assert!(ingest_corpus_result(&database, &corpus, request()).is_err());
        assert!(package.join("raw.iq").exists());
        assert_eq!(list_corpus_results(&database).unwrap().len(), 1);
        fs::write(package.join("unexpected"), b"guard").unwrap();
        assert!(delete_corpus_result(&database, &corpus, &detail.summary.result_id).is_err());
        assert!(package.join("raw.iq").exists());
        assert_eq!(list_corpus_results(&database).unwrap().len(), 1);

        fs::remove_file(package.join("unexpected")).unwrap();
        delete_corpus_result(&database, &corpus, &detail.summary.result_id).unwrap();
        fs::remove_file(&database).unwrap();
        let _ = fs::remove_file(database.with_extension("sqlite3-shm"));
        let _ = fs::remove_file(database.with_extension("sqlite3-wal"));
        fs::remove_dir(corpus).unwrap();
        fs::remove_dir(root).unwrap();
    }

    #[test]
    fn utc_and_safe_path_checks_are_strict() {
        assert_eq!(
            validate_utc("2026-09-05T01:02:03.123456Z").unwrap(),
            "2026-09-05"
        );
        assert!(validate_utc("2026-09-05 01:02:03Z").is_err());
        assert!(validate_removed_feature_path(
            "/var/tmp/sdrharness-dev/corpus-fixture/capture-staging"
        )
        .is_ok());
        assert!(validate_removed_feature_path("/var/tmp/sdrharness-dev/../escape").is_err());
        assert!(require_safe_id("../escape", 64, "id").is_err());
    }
}
