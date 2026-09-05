//! S6a archive in the existing application SQLite database. No IQ file access.
use crate::{internal_error, now_ms, open_result_database, ApiError, ApiResult};
use axum::http::StatusCode;
use rusqlite::{params, OptionalExtension};
use sdr_agent_controller::recognition_input::frozen_rf_v1_profile;
use sdr_agent_controller::recognition_result::{
    ClassIdentity, NameStatus, RecognitionObservation, RecognitionResult, MAX_RESULT_BYTES,
};
use serde::{Deserialize, Serialize};
use std::path::Path;

pub const MAX_IMPORT_BYTES: usize = MAX_RESULT_BYTES + 1024;
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Origin {
    ExperimentalReplay,
    SyntheticFixture,
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Import {
    pub schema_version: u16,
    pub session_id: String,
    pub origin: Origin,
    pub result: RecognitionResult,
}
#[derive(Debug, Serialize)]
pub struct Detail {
    pub id: i64,
    pub created_at_ms: u64,
    pub session_id: String,
    pub origin: Origin,
    pub production_result: bool,
    pub iq_retained: bool,
    pub observation: RecognitionObservation,
    pub experimental_prediction: Option<ClassIdentity>,
    pub uncalibrated_probability: Option<f64>,
}
fn bad(message: &str) -> ApiError {
    ApiError(StatusCode::BAD_REQUEST, message.into())
}
fn valid_id(id: i64) -> ApiResult<()> {
    if id <= 0 {
        return Err(bad("识别记录 ID 无效"));
    }
    Ok(())
}
fn validate(input: &Import) -> ApiResult<()> {
    if input.schema_version != 1
        || input.session_id.is_empty()
        || input.session_id.len() > 96
        || !input
            .session_id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
    {
        return Err(bad("识别记录会话或版本无效"));
    }
    let profile = frozen_rf_v1_profile().map_err(internal_error)?;
    match input.origin {
        Origin::ExperimentalReplay => input.result.validate(&profile).map_err(|e| bad(&e))?,
        Origin::SyntheticFixture => {
            // Inert demonstrations can exercise all four UI states, but can
            // neither carry actual model outputs nor claim real decision evidence.
            let result = &input.result;
            result.observation.validate().map_err(|e| bad(&e))?;
            if result.schema_version != 1
                || result.experimental_batch.is_some()
                || result.experimental_prediction.is_some()
                || result.uncalibrated_probability.is_some()
                || !result.observation.candidate_id.starts_with("synthetic-")
                || result
                    .observation
                    .source
                    .as_ref()
                    .is_some_and(|s| !s.sweep_id.starts_with("synthetic-"))
                || result.observation.class.as_ref().is_some_and(|c| {
                    c.name_status != NameStatus::Provisional
                        || c.name.is_some()
                        || c.name_evidence.is_some()
                })
                || result
                    .observation
                    .decision_references
                    .as_ref()
                    .is_some_and(|d| {
                        [&d.calibration, &d.rejection, &d.admission]
                            .iter()
                            .any(|r| r.id != "synthetic-only" || r.sha256 != "0".repeat(64))
                    })
            {
                return Err(bad("合成演示不能携带实测预测或真实准入依据"));
            }
            if let Some(id) = &result.observation.identity {
                if id.profile_sha256 != profile.manifest_sha256
                    || id.model_id != profile.profile.model.model_id
                    || id.checkpoint_sha256 != profile.profile.model.model_sha256
                    || id.profile_id != profile.profile.profile_id
                    || id.preprocess_id != profile.profile.preprocess.preprocess_id
                    || id.preprocess_sha256 != profile.profile.preprocess.spec_sha256
                {
                    return Err(bad("演示模型身份不匹配"));
                }
            }
        }
    }
    if serde_json::to_vec(&input.result)
        .map_err(internal_error)?
        .len()
        > MAX_RESULT_BYTES
    {
        return Err(bad("识别记录超过 64 KiB"));
    }
    Ok(())
}
pub fn initialize(path: &Path) -> ApiResult<()> {
    open_result_database(path)?.execute_batch(
        "CREATE TABLE IF NOT EXISTS recognition_results (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at_ms INTEGER NOT NULL,
          session_id TEXT NOT NULL,
          generation TEXT NOT NULL,
          request_id TEXT NOT NULL,
          candidate_id TEXT NOT NULL,
          payload_json TEXT NOT NULL CHECK(length(CAST(payload_json AS BLOB)) <= 66560),
          UNIQUE(session_id, generation, request_id, candidate_id)
        );
        CREATE INDEX IF NOT EXISTS recognition_created ON recognition_results(created_at_ms DESC,id DESC);"
    ).map_err(internal_error)?;
    Ok(())
}
fn detail(id: i64, created_at_ms: u64, input: Import) -> Detail {
    Detail {
        id,
        created_at_ms,
        session_id: input.session_id,
        origin: input.origin,
        production_result: false,
        iq_retained: false,
        observation: input.result.observation,
        experimental_prediction: input.result.experimental_prediction,
        uncalibrated_probability: input.result.uncalibrated_probability,
    }
}
fn parse_stored(payload: &str) -> ApiResult<Import> {
    if payload.len() > MAX_IMPORT_BYTES {
        return Err(internal_error("stored recognition bound"));
    }
    let input: Import = serde_json::from_str(payload).map_err(internal_error)?;
    validate(&input).map_err(|_| internal_error("stored recognition validation failed"))?;
    Ok(input)
}
pub fn ingest(path: &Path, bytes: &[u8]) -> ApiResult<Detail> {
    if bytes.len() > MAX_IMPORT_BYTES {
        return Err(bad("识别导入超过大小限制"));
    }
    let input: Import = serde_json::from_slice(bytes).map_err(|_| bad("识别导入 JSON 无效"))?;
    validate(&input)?;
    let payload = serde_json::to_string(&input).map_err(internal_error)?;
    let mut connection = open_result_database(path)?;
    let transaction = connection
        .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .map_err(internal_error)?;
    let o = &input.result.observation;
    let existing: Option<(i64, i64, String)> = transaction.query_row(
        "SELECT id, created_at_ms, payload_json FROM recognition_results WHERE session_id=?1 AND generation=?2 AND request_id=?3 AND candidate_id=?4",
        params![input.session_id,o.session_generation.to_string(),o.request_id.to_string(),o.candidate_id],
        |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?))).optional().map_err(internal_error)?;
    if let Some((id, created, old)) = existing {
        if old != payload {
            return Err(ApiError(
                StatusCode::CONFLICT,
                "同一请求已有不同识别记录；不会覆盖历史".into(),
            ));
        }
        return Ok(detail(id, created as u64, parse_stored(&old)?));
    }
    let created = now_ms();
    transaction.execute("INSERT INTO recognition_results (created_at_ms,session_id,generation,request_id,candidate_id,payload_json) VALUES (?1,?2,?3,?4,?5,?6)",params![created as i64,input.session_id,o.session_generation.to_string(),o.request_id.to_string(),o.candidate_id,payload]).map_err(internal_error)?;
    let id = transaction.last_insert_rowid();
    transaction.commit().map_err(internal_error)?;
    Ok(detail(id, created, input))
}
pub fn list(path: &Path, before: i64) -> ApiResult<Vec<Detail>> {
    if before <= 0 {
        return Err(bad("分页游标无效"));
    }
    let connection = open_result_database(path)?;
    let mut query = connection.prepare("SELECT id,created_at_ms,payload_json FROM recognition_results WHERE id < ?1 ORDER BY id DESC LIMIT 50").map_err(internal_error)?;
    let rows = query
        .query_map([before], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, String>(2)?,
            ))
        })
        .map_err(internal_error)?;
    rows.map(|r| {
        let (id, created, payload) = r.map_err(internal_error)?;
        Ok(detail(id, created as u64, parse_stored(&payload)?))
    })
    .collect()
}
pub fn load(path: &Path, id: i64) -> ApiResult<Detail> {
    valid_id(id)?;
    let row: Option<(i64, String)> = open_result_database(path)?
        .query_row(
            "SELECT created_at_ms,payload_json FROM recognition_results WHERE id=?1",
            [id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .map_err(internal_error)?;
    let (created, payload) =
        row.ok_or_else(|| ApiError(StatusCode::NOT_FOUND, "识别记录不存在".into()))?;
    Ok(detail(id, created as u64, parse_stored(&payload)?))
}
pub fn delete(path: &Path, id: i64) -> ApiResult<()> {
    valid_id(id)?;
    // No filesystem deletion and no cascade into captures/corpus. A corrupt
    // record remains manually deletable without parsing its payload.
    let connection = open_result_database(path)?;
    connection
        .execute_batch("PRAGMA secure_delete=ON;")
        .map_err(internal_error)?;
    if connection
        .execute("DELETE FROM recognition_results WHERE id=?1", [id])
        .map_err(internal_error)?
        == 0
    {
        return Err(ApiError(StatusCode::NOT_FOUND, "识别记录不存在".into()));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use sdr_agent_controller::recognition_result::{
        CalibrationStatus, DecisionReferences, RecognitionStatus, ResultReference,
    };
    fn replay() -> Import {
        let audit: serde_json::Value = serde_json::from_str(include_str!(
            "../../../../docs/RF_V1_RUNTIME_PARITY_AUDIT_2026-09-05.json"
        ))
        .unwrap();
        let report = serde_json::from_value(audit["cases"][0]["report"].clone()).unwrap();
        Import {
            schema_version: 1,
            session_id: "s6a-replay".into(),
            origin: Origin::ExperimentalReplay,
            result: RecognitionResult::from_experimental_batch(
                &frozen_rf_v1_profile().unwrap(),
                report,
                1000,
            )
            .unwrap(),
        }
    }
    fn fixture(status: RecognitionStatus) -> Import {
        let mut input = replay();
        input.origin = Origin::SyntheticFixture;
        input.result.experimental_batch = None;
        input.result.experimental_prediction = None;
        input.result.uncalibrated_probability = None;
        let o = &mut input.result.observation;
        o.candidate_id = format!("synthetic-{status:?}");
        o.source.as_mut().unwrap().sweep_id = "synthetic-sweep".into();
        o.status = status;
        if matches!(
            status,
            RecognitionStatus::Classified | RecognitionStatus::Rejected
        ) {
            let reference = ResultReference {
                id: "synthetic-only".into(),
                sha256: "0".repeat(64),
            };
            o.decision_references = Some(DecisionReferences {
                calibration: reference.clone(),
                rejection: reference.clone(),
                admission: reference,
            });
            o.calibration_status = CalibrationStatus::Frozen;
            o.reason = Some("synthetic_low_confidence".into());
        }
        if status == RecognitionStatus::Classified {
            o.reason = None;
            o.class = Some(ClassIdentity {
                numeric_id: 1,
                name: None,
                name_status: NameStatus::Provisional,
                name_evidence: None,
            });
            o.calibrated_confidence = Some(0.75);
        }
        input
    }
    fn database(name: &str) -> std::path::PathBuf {
        let root = std::env::temp_dir().join(format!("s6a-{name}-{}", std::process::id()));
        std::fs::create_dir(&root).unwrap();
        let path = root.join("results.sqlite3");
        crate::initialize_result_database(&path).unwrap();
        initialize(&path).unwrap();
        path
    }
    #[test]
    fn full_record_roundtrip_idempotence_and_manual_delete_preserve_other_tables() {
        let path = database("roundtrip");
        let input = replay();
        let bytes = serde_json::to_vec(&input).unwrap();
        let stored = ingest(&path, &bytes).unwrap();
        assert!(!stored.production_result && !stored.iq_retained);
        assert_eq!(ingest(&path, &bytes).unwrap().id, stored.id);
        let connection = open_result_database(&path).unwrap();
        let payload: String = connection
            .query_row("SELECT payload_json FROM recognition_results", [], |r| {
                r.get(0)
            })
            .unwrap();
        assert_eq!(parse_stored(&payload).unwrap().result, input.result);
        let public = serde_json::to_string(&load(&path, stored.id).unwrap()).unwrap();
        for forbidden in ["experimental_batch", "logits", "tensor", "iq_path"] {
            assert!(!public.contains(&format!("\"{forbidden}\":")));
        }
        let mut changed = replay();
        changed.result.observation.observed_at_unix_ms += 1;
        assert_eq!(
            ingest(&path, &serde_json::to_vec(&changed).unwrap())
                .unwrap_err()
                .0,
            StatusCode::CONFLICT
        );
        assert_eq!(list(&path, i64::MAX).unwrap().len(), 1);
        assert!(list(&path, stored.id).unwrap().is_empty());
        connection.execute_batch("INSERT INTO capture_results (session_id,sweep_id,kind,created_at_ms,point_count,candidate_count,elapsed_ms,gain_db,noise_floor_dbfs,iq_bytes,payload_json) VALUES ('keep-session','keep-sweep','initial',1,1,0,1,20,-80,0,'{}');").unwrap();
        // A sentinel application table survives recognition deletion.
        connection
            .execute_batch(
                "CREATE TABLE sentinel(value TEXT); INSERT INTO sentinel VALUES ('keep');",
            )
            .unwrap();
        delete(&path, stored.id).unwrap();
        assert_eq!(load(&path, stored.id).unwrap_err().0, StatusCode::NOT_FOUND);
        assert_eq!(
            delete(&path, stored.id).unwrap_err().0,
            StatusCode::NOT_FOUND
        );
        assert_eq!(
            connection
                .query_row("SELECT value FROM sentinel", [], |r| r.get::<_, String>(0))
                .unwrap(),
            "keep"
        );
        assert_eq!(
            connection
                .query_row("SELECT count(*) FROM capture_results", [], |r| r
                    .get::<_, i64>(0))
                .unwrap(),
            1
        );
        drop(connection);
        std::fs::remove_dir_all(path.parent().unwrap()).unwrap();
    }
    #[test]
    fn four_inert_states_and_production_forgery_rejected() {
        let path = database("states");
        for status in [
            RecognitionStatus::Classified,
            RecognitionStatus::Rejected,
            RecognitionStatus::Unavailable,
            RecognitionStatus::Error,
        ] {
            let mut input = fixture(status);
            let bytes = serde_json::to_vec(&input).unwrap();
            let stored = ingest(&path, &bytes).unwrap();
            assert_eq!(stored.observation.status, status);
            assert!(!stored.production_result);
            if matches!(
                status,
                RecognitionStatus::Classified | RecognitionStatus::Rejected
            ) {
                input.origin = Origin::ExperimentalReplay;
                assert!(ingest(&path, &serde_json::to_vec(&input).unwrap()).is_err());
            }
        }
        assert_eq!(list(&path, i64::MAX).unwrap().len(), 4);
        std::fs::remove_dir_all(path.parent().unwrap()).unwrap();
    }
    #[test]
    fn tamper_unknown_fields_duplicate_keys_limits_and_corrupt_delete() {
        let path = database("invalid");
        let input = replay();
        let bytes = serde_json::to_vec(&input).unwrap();
        for kind in [
            "logits",
            "identity",
            "origin",
            "path",
            "duplicate",
            "truncated",
            "oversize",
        ] {
            let mut value = serde_json::to_value(&input).unwrap();
            match kind {
                "logits" => {
                    value["result"]["experimental_batch"]["windows"][0]["recognition"]["rf_v1"]
                        ["logits"][0] = 99.into()
                }
                "identity" => {
                    value["result"]["observation"]["identity"]["profile_sha256"] =
                        "a".repeat(64).into()
                }
                "origin" => value["origin"] = "production".into(),
                "path" => value["result"]["iq_path"] = "/private/user-iq".into(),
                _ => {}
            }
            let mut bad = serde_json::to_vec(&value).unwrap();
            if kind == "duplicate" {
                bad = String::from_utf8(bad)
                    .unwrap()
                    .replacen(
                        "\"schema_version\":1",
                        "\"schema_version\":1,\"schema_version\":1",
                        1,
                    )
                    .into_bytes();
            }
            if kind == "truncated" {
                bad.pop();
            }
            if kind == "oversize" {
                bad = vec![b' '; MAX_IMPORT_BYTES + 1];
            }
            assert!(ingest(&path, &bad).is_err(), "{kind}");
        }
        assert!(list(&path, i64::MAX).unwrap().is_empty());
        let id = ingest(&path, &bytes).unwrap().id;
        open_result_database(&path)
            .unwrap()
            .execute(
                "UPDATE recognition_results SET payload_json='{}' WHERE id=?1",
                [id],
            )
            .unwrap();
        assert!(load(&path, id).is_err());
        assert!(list(&path, i64::MAX).is_err());
        delete(&path, id).unwrap();
        assert!(list(&path, i64::MAX).unwrap().is_empty());
        std::fs::remove_dir_all(path.parent().unwrap()).unwrap();
    }
    #[test]
    fn bounded_pagination_keeps_every_record_reachable() {
        let path = database("pages");
        for request_id in 1..=51 {
            let mut input = fixture(RecognitionStatus::Error);
            input.result.observation.request_id = request_id;
            ingest(&path, &serde_json::to_vec(&input).unwrap()).unwrap();
        }
        let first = list(&path, i64::MAX).unwrap();
        assert_eq!(first.len(), 50);
        let second = list(&path, first.last().unwrap().id).unwrap();
        assert_eq!(second.len(), 1);
        assert!(list(&path, second[0].id).unwrap().is_empty());
        std::fs::remove_dir_all(path.parent().unwrap()).unwrap();
    }
    #[test]
    #[ignore = "explicit bounded S6a archive fixture export"]
    fn export_s6a_archive_fixtures() {
        let root = std::path::PathBuf::from(std::env::var("S6A_VALIDATION_DIR").unwrap());
        assert!(
            root.starts_with("/var/tmp/sdrharness-dev") && root.canonicalize().unwrap() == root
        );
        std::fs::write(
            root.join("experimental.json"),
            serde_json::to_vec(&replay()).unwrap(),
        )
        .unwrap();
        for status in [
            RecognitionStatus::Classified,
            RecognitionStatus::Rejected,
            RecognitionStatus::Unavailable,
            RecognitionStatus::Error,
        ] {
            std::fs::write(
                root.join(format!("{status:?}.json")),
                serde_json::to_vec(&fixture(status)).unwrap(),
            )
            .unwrap();
        }
    }
}
