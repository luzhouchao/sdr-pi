//! Versioned metadata derivation in the existing application corpus store.
use super::*;
use sdr_agent_controller::recognition_input::RF_V1_PROFILE_BYTES;
const RF_V1_PROFILE_SHA256: &str =
    "6c1dac991b45e3738e19a6a55a9f3a1b6d3db8510ceef35ee77cdd34e2982dab";
const RF_PREPROCESS: &[u8] =
    include_bytes!("../../../../../jetson-agx/sdrharness/config/amc/rf-preprocess-v1.json");
const RF_PREPROCESS_HASH: &str = "18428d72beb8c0e7e83d24d57a02d5f6b68f3428cb3f096a219a87b67dbc900f";

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RfV1DeriveRequest {
    pub schema_version: u16,
    pub result_id: String,
    pub parent_manifest_sha256: String,
    pub parent_iq_sha256: String,
    pub source_report: SweepReport,
    pub split: EvidenceSplit,
    pub label: EvidenceLabel,
}
#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum EvidenceSplit {
    ReceiveDomain,
    Calibration,
    Acceptance,
}
impl EvidenceSplit {
    fn name(self) -> &'static str {
        match self {
            Self::ReceiveDomain => "receive_domain",
            Self::Calibration => "calibration",
            Self::Acceptance => "acceptance",
        }
    }
}
#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(tag = "provenance", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum EvidenceLabel {
    Unknown {
        reason: UnknownLabelReason,
    },
    IndependentAnnotation {
        category: EvidenceCategory,
        numeric_id: Option<u16>,
        evidence: Box<AnnotationEvidence>,
    },
}
#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum EvidenceCategory {
    KnownClass,
    NoiseIdle,
    OutOfLabelSpace,
    Mixed,
    LowQuality,
    Ambiguous,
}
#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct AnnotationEvidence {
    pub schema_version: u16,
    pub schema_id: String,
    pub annotation_id: String,
    pub method: EvidenceMethod,
    pub reviewer: String,
    pub annotated_at_utc: String,
    pub independent_of_model: bool,
    pub ambiguity: Option<String>,
    pub basis_report: String,
    pub basis_report_sha256: String,
    pub source_sample_id: String,
    pub capture_session_id: String,
    pub capture_day: String,
    pub iq_sha256: String,
    pub request_id: u64,
    pub session_generation: u64,
    pub sequence: u64,
    pub profile_sha256: String,
    pub preprocess_sha256: String,
    pub label_space_sha256: String,
    pub category: EvidenceCategory,
    pub numeric_id: Option<u16>,
}
#[derive(Debug, Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum EvidenceMethod {
    ExternalDecoder,
    InstrumentReference,
    HumanReview,
}

fn read_private_asset(path: &Path, max: u64) -> ApiResult<Vec<u8>> {
    let meta = fs::symlink_metadata(path).map_err(internal_error)?;
    if !meta.is_file()
        || meta.file_type().is_symlink()
        || meta.len() == 0
        || meta.len() > max
        || meta.permissions().mode() & 0o022 != 0
    {
        return bad_request("语料资产类型、权限或字节界限错误");
    }
    fs::read(path).map_err(internal_error)
}
fn bounded_text(value: &str, max: usize) -> bool {
    !value.trim().is_empty()
        && value.len() <= max
        && !value
            .chars()
            .any(|c| c.is_control() && c != '\n' && c != '\t')
}

pub(crate) fn derive_rf_v1(
    database: &Path,
    root: &Path,
    parent_id: &str,
    request: RfV1DeriveRequest,
) -> ApiResult<CorpusResultDetail> {
    require_safe_id(parent_id, 96, "父语料 ID")?;
    require_safe_id(&request.result_id, 96, "派生语料 ID")?;
    if request.schema_version != 1
        || request.result_id == parent_id
        || sha256_hex(RF_V1_PROFILE_BYTES) != RF_V1_PROFILE_SHA256
        || sha256_hex(RF_PREPROCESS) != RF_PREPROCESS_HASH
    {
        return bad_request("RF-v1 派生合同错误");
    }
    let mut connection = open_result_database(database)?;
    // Serializes derivation, immutable group assignment and parent deletion.
    let transaction = connection
        .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .map_err(internal_error)?;
    let parent = load_corpus_result(database, parent_id)?;
    if parent.record["lineage"]["parent_record_id"] != Value::Null
        || parent.manifest["contract"]["input_profile"]["sha256"] != PROFILE_SHA256
    {
        return bad_request("派生必须引用原始 legacy capture 根记录；修订应重新引用同一根记录");
    }
    let directory = root.join(parent_id);
    let metadata = fs::symlink_metadata(&directory).map_err(internal_error)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return bad_request("父语料包不存在或不是受管目录");
    }
    if fs::canonicalize(&directory)
        .map_err(internal_error)?
        .parent()
        != Some(fs::canonicalize(root).map_err(internal_error)?.as_path())
    {
        return bad_request("父包必须属于受管根目录");
    }
    let manifest_bytes = read_private_asset(&directory.join("manifest.json"), 128 * 1024)?;
    let records_bytes = read_private_asset(&directory.join("records.jsonl"), 64 * 1024)?;
    if sha256_hex(&manifest_bytes) != request.parent_manifest_sha256
        || serde_json::from_slice::<Value>(&manifest_bytes).map_err(internal_error)?
            != parent.manifest
        || serde_json::from_slice::<Value>(&records_bytes).map_err(internal_error)? != parent.record
        || sha256_hex(&records_bytes) != parent.manifest["record_index"]["sha256"]
    {
        return bad_request("父包/索引哈希或数据库记录不一致");
    }
    if manifest_bytes != pretty_json(&parent.manifest)?
        || records_bytes != json_line(&parent.record)?
    {
        return bad_request("原始包 JSON 必须匹配入库规范编码，不接受重复键或重写");
    }
    let mut names = HashSet::new();
    for entry in fs::read_dir(&directory).map_err(internal_error)? {
        names.insert(
            entry
                .map_err(internal_error)?
                .file_name()
                .to_string_lossy()
                .into_owned(),
        );
    }
    let mut expected: HashSet<String> = [
        "manifest.json",
        "records.jsonl",
        "capture-plan.json",
        "input-profile.json",
        "preprocess.json",
        "labels.json",
        "raw.iq",
    ]
    .into_iter()
    .map(str::to_owned)
    .collect();
    let original_report = if names.contains("source-report.json") {
        expected.insert("source-report.json".into());
        let bytes = read_private_asset(&directory.join("source-report.json"), 128 * 1024)?;
        let saved: SweepReport = serde_json::from_slice(&bytes).map_err(internal_error)?;
        if saved != request.source_report {
            return bad_request("source report 与原始入库报告不一致");
        }
        Some(bytes)
    } else {
        if !matches!(request.label, EvidenceLabel::Unknown { .. }) {
            return bad_request(
                "历史包未保存原始 request 报告，只能 unknown 派生；不得补造独立关联",
            );
        }
        None
    };
    if names != expected {
        return bad_request("原始父包包含未知文件");
    }
    let descriptors = parent.manifest["assets"]
        .as_array()
        .ok_or_else(|| ApiError(StatusCode::BAD_REQUEST, "父包资产缺失".into()))?;
    let expected_assets: HashSet<_> = expected
        .iter()
        .filter(|n| n.as_str() != "manifest.json" && n.as_str() != "records.jsonl")
        .map(String::as_str)
        .collect();
    let asset_names: HashSet<_> = descriptors
        .iter()
        .filter_map(|a| a["path"].as_str())
        .collect();
    if asset_names != expected_assets
        || asset_names.len() != descriptors.len()
        || parent.manifest["record_index"]["count"] != 1
        || parent.manifest["record_index"]["bytes"] != records_bytes.len() as u64
    {
        return bad_request("父包资产索引不完整或重复");
    }
    let mut asset_ids = HashSet::new();
    for descriptor in descriptors {
        let id = descriptor["asset_id"].as_str().unwrap_or("");
        require_safe_id(id, 128, "父资产 ID")?;
        if !asset_ids.insert(id) {
            return bad_request("父资产 ID 重复");
        }
        let name = descriptor["path"].as_str().unwrap_or("");
        if !expected.contains(name) {
            return bad_request("父资产路径不在允许集合");
        }
        let role = match name {
            "input-profile.json" => "input_profile",
            "preprocess.json" => "preprocess_spec",
            "labels.json" => "label_table",
            "capture-plan.json" => "capture_plan",
            "source-report.json" => "capture_report",
            "raw.iq" => "raw_iq",
            _ => return bad_request("父资产类型错误"),
        };
        if descriptor["role"] != role {
            return bad_request("父资产角色错误");
        }
        let bytes = read_private_asset(&directory.join(name), 128 * 1024)?;
        if descriptor["bytes"].as_u64() != Some(bytes.len() as u64)
            || descriptor["sha256"] != sha256_hex(&bytes)
        {
            return bad_request("父语料资产哈希不一致");
        }
    }
    for (name, expected) in [
        ("input-profile.json", PROFILE_BYTES),
        ("preprocess.json", PREPROCESS_BYTES),
        ("labels.json", LABEL_BYTES),
    ] {
        if read_private_asset(&directory.join(name), 128 * 1024)? != expected {
            return bad_request("父包冻结 profile/preprocess/labels 内容不一致");
        }
    }
    let iq = read_private_asset(&directory.join("raw.iq"), 16384)?;
    if request.parent_iq_sha256 != sha256_hex(&iq)
        || parent.record["window"]["sha256"] != request.parent_iq_sha256
    {
        return bad_request("原始 IQ 内容哈希不一致");
    }
    let plan_bytes = read_private_asset(&directory.join("capture-plan.json"), 128 * 1024)?;
    let plan: Value = serde_json::from_slice(&plan_bytes).map_err(internal_error)?;
    let reconstructed = P201CorpusIngestRequest {
        schema_version: 1,
        capture_session_id: parent.summary.capture_session_id.clone(),
        captured_at_utc: parent.summary.captured_at_utc.clone(),
        label_reason: UnknownLabelReason::NoIndependentLabel,
        plan: serde_json::from_value(plan["sweep"].clone()).map_err(internal_error)?,
        preflight: serde_json::from_value(plan["preflight"].clone()).map_err(internal_error)?,
        report: request.source_report.clone(),
        iq_base64: String::new(),
    };
    let validated = validate_ingest_iq(root, &reconstructed, iq.clone())?;
    if validated.result_id != parent_id {
        return bad_request("capture session/sequence 与父结果不一致");
    }
    let expected_lineage = json!({"source_sample_id":parent_id,"capture_session_id":reconstructed.capture_session_id,"capture_day":validated.capture_day,"parent_record_id":null,"transforms":[]});
    let expected_window = json!({"window_index":0,"sample_offset":0,"samples":4096,"bytes":16384,"sample_format":"ci16_le","layout":"interleaved_iq","endianness":"little","sha256":request.parent_iq_sha256,"storage":{"kind":"managed_asset","asset_id":format!("{parent_id}-iq"),"offset_bytes":0}});
    if parent.record["source"]
        != capture_source(
            &reconstructed,
            parent_id,
            &validated.capture_day,
            &format!("{parent_id}-plan"),
            &sha256_hex(&plan_bytes),
            iq.len(),
        )
        || parent.record["lineage"] != expected_lineage
        || parent.record["window"] != expected_window
        || parent.record["label"]["provenance"] != "unknown"
    {
        return bad_request("父记录的完整 source/lineage/window 必须与已验证 capture 一致");
    }
    let (label, annotation) = validate_label(&request, &parent.record)?;
    let mut record = parent.record.clone();
    record["record_id"] = format!("{}-window-0", request.result_id).into();
    record["split"] = request.split.name().into();
    record["lineage"]["parent_record_id"] = parent.record["record_id"].clone();
    record["lineage"]["transforms"] = json!(["rf_v1_profile_binding_v1"]);
    record["source"]["retention"]["result_id"] = request.result_id.clone().into();
    record["label"] = label;
    let derivation = json!({"schema_version":1,"schema_id":"rf_v1_corpus_derivation_v1",
        "parent_result_id":parent_id,"parent_manifest_sha256":request.parent_manifest_sha256,
        "parent_manifest_utf8":String::from_utf8(manifest_bytes).map_err(internal_error)?,
        "parent_record_sha256":sha256_hex(&records_bytes),"parent_record_utf8":String::from_utf8(records_bytes).map_err(internal_error)?,
        "source_report":request.source_report,"request_correlation":if original_report.is_some(){"original_report_hash_verified"}else{"legacy_reconstructed"},"raw_iq_sha256":request.parent_iq_sha256,
        "transform":"rf_v1_profile_binding_v1","iq_storage":"shared_inode_no_copy",
        "profile_sha256":RF_V1_PROFILE_SHA256,"preprocess_sha256":RF_PREPROCESS_HASH});
    let derivation_bytes = json_line(&derivation)?;
    let mut manifest = parent.manifest.clone();
    manifest["manifest_id"] = request.result_id.clone().into();
    manifest["contract"]["input_profile"] = json!({"id":"rml2018a-d8-rf-v1-epoch010-fp16-runtime-v1","path":"input-profile.json","sha256":RF_V1_PROFILE_SHA256,"admission":"integration_only"});
    manifest["contract"]["preprocessing"] = json!({"id":"rf_preprocess_v1","path":"preprocess.json","sha256":RF_PREPROCESS_HASH,"status":"frozen"});
    manifest["split_policy"]["allowed_splits"] = json!([request.split.name()]);
    let assets = manifest["assets"].as_array_mut().unwrap();
    for a in assets.iter_mut() {
        if a["role"] == "input_profile" {
            *a = asset(
                "rf-v1-profile",
                "input-profile.json",
                "input_profile",
                RF_V1_PROFILE_BYTES,
                "repository_metadata",
                "not_applicable",
            );
        }
        if a["role"] == "preprocess_spec" {
            *a = asset(
                "rf-v1-preprocess",
                "preprocess.json",
                "preprocess_spec",
                RF_PREPROCESS,
                "repository_metadata",
                "not_applicable",
            );
        }
    }
    assets.push(asset(
        "rf-v1-lineage",
        "derivation.json",
        "lineage_evidence",
        &derivation_bytes,
        "application_result",
        "required",
    ));
    let mut files = vec![
        ("input-profile.json", RF_V1_PROFILE_BYTES),
        ("preprocess.json", RF_PREPROCESS),
        ("labels.json", LABEL_BYTES),
        ("capture-plan.json", plan_bytes.as_slice()),
        ("derivation.json", derivation_bytes.as_slice()),
    ];
    if let Some(bytes) = original_report.as_ref() {
        files.push(("source-report.json", bytes));
    }
    if let Some(bytes) = annotation.as_ref() {
        assets.push(asset(
            "independent-evidence",
            "annotation.json",
            "annotation_evidence",
            bytes,
            "application_result",
            "required",
        ));
        files.push(("annotation.json", bytes));
    }
    let rb = json_line(&record)?;
    manifest["record_index"]["bytes"] = (rb.len() as u64).into();
    manifest["record_index"]["sha256"] = sha256_hex(&rb).into();
    if request.split != EvidenceSplit::ReceiveDomain {
        for (kind, value) in [
            (
                "source_sample_id",
                record["lineage"]["source_sample_id"].as_str().unwrap_or(""),
            ),
            (
                "capture_session_id",
                record["lineage"]["capture_session_id"]
                    .as_str()
                    .unwrap_or(""),
            ),
            (
                "capture_day",
                record["lineage"]["capture_day"].as_str().unwrap_or(""),
            ),
            ("raw_iq_sha256", request.parent_iq_sha256.as_str()),
        ] {
            let digest = sha256_hex(value.as_bytes());
            let prior:Option<String>=transaction.query_row("SELECT split FROM p201_corpus_partition_groups WHERE group_kind=?1 AND group_hash=?2",params![kind,digest],|r| r.get(0)).optional().map_err(internal_error)?;
            if prior.as_deref().is_some_and(|s| s != request.split.name()) {
                return Err(ApiError(
                    StatusCode::CONFLICT,
                    "source/session/day/IQ 已属于另一个校准或验收集合".into(),
                ));
            }
            transaction.execute("INSERT OR IGNORE INTO p201_corpus_partition_groups(group_kind,group_hash,split) VALUES (?1,?2,?3)",params![kind,digest,request.split.name()]).map_err(internal_error)?;
        }
    }
    store_package(
        &transaction,
        root,
        &request.result_id,
        &manifest,
        &record,
        &files,
        Some(&directory.join("raw.iq")),
    )?;
    if let Err(error) = transaction.commit() {
        cleanup_package_directory(root, &root.join(&request.result_id), true)?;
        return Err(internal_error(error));
    }
    load_corpus_result(database, &request.result_id)
}

fn validate_label(
    request: &RfV1DeriveRequest,
    parent: &Value,
) -> ApiResult<(Value, Option<Vec<u8>>)> {
    match &request.label {
        EvidenceLabel::Unknown { reason } => {
            if request.split != EvidenceSplit::ReceiveDomain {
                return bad_request("unknown 不进入校准或验收集合");
            }
            Ok((
                json!({"provenance":"unknown","reason":reason.as_str()}),
                None,
            ))
        }
        EvidenceLabel::IndependentAnnotation {
            category,
            numeric_id,
            evidence: e,
        } => {
            require_safe_id(&e.annotation_id, 96, "annotation ID")?;
            require_safe_id(&e.reviewer, 96, "reviewer ID")?;
            validate_utc(&e.annotated_at_utc)?;
            let p = &request.source_report.points[0];
            if e.schema_version != 1
                || e.schema_id != "rf_v1_independent_annotation_v1"
                || !e.independent_of_model
                || !bounded_text(&e.basis_report, 16384)
                || e.basis_report_sha256 != sha256_hex(e.basis_report.as_bytes())
                || e.iq_sha256 != request.parent_iq_sha256
                || parent["lineage"]["source_sample_id"] != e.source_sample_id
                || parent["lineage"]["capture_session_id"] != e.capture_session_id
                || parent["lineage"]["capture_day"] != e.capture_day
                || e.request_id != p.request_id
                || e.session_generation != p.session_generation
                || e.sequence != p.sequence
                || e.profile_sha256 != RF_V1_PROFILE_SHA256
                || e.preprocess_sha256 != RF_PREPROCESS_HASH
                || e.label_space_sha256 != LABEL_SHA256
                || e.category != *category
                || e.numeric_id != *numeric_id
            {
                return bad_request("独立标签证据的来源、依据、哈希或身份不匹配");
            }
            if (*category == EvidenceCategory::KnownClass && !numeric_id.is_some_and(|n| n < 24))
                || (*category != EvidenceCategory::KnownClass && numeric_id.is_some())
            {
                return bad_request("known-class 需要可信数字 ID；OOD/混合/低质量不得强制类别");
            }
            if e.ambiguity.as_ref().is_some_and(|a| !bounded_text(a, 1024))
                || (*category == EvidenceCategory::Ambiguous && e.ambiguity.is_none())
                || (e.ambiguity.is_some() && request.split != EvidenceSplit::ReceiveDomain)
            {
                return bad_request("存在歧义的证据只能进入 receive_domain");
            }
            let bytes = json_line(&serde_json::to_value(e).map_err(internal_error)?)?;
            let labels: Value = serde_json::from_slice(LABEL_BYTES).map_err(internal_error)?;
            let name = numeric_id
                .map(|i| labels["classes"][usize::from(i)].clone())
                .unwrap_or(Value::Null);
            Ok((
                json!({"provenance":"independent_annotation","category":category,"numeric_id":numeric_id,"display_name":name,"display_name_status":if numeric_id.is_some(){"provisional"}else{"absent"},"evidence":{"annotation_id":e.annotation_id,"method":e.method,"annotated_at_utc":e.annotated_at_utc,"evidence_sha256":sha256_hex(&bytes)}}),
                Some(bytes),
            ))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::MetadataExt;
    struct Fixture {
        root: PathBuf,
        db: PathBuf,
        corpus: PathBuf,
        parent: CorpusResultDetail,
        input: P201CorpusIngestRequest,
    }
    impl Fixture {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!(
                "rf-evidence-{}-{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            ));
            fs::create_dir(&root).unwrap();
            let db = root.join("results.sqlite");
            let corpus = root.join("corpus");
            initialize_corpus_store(&db, &corpus).unwrap();
            let input = super::super::tests::request();
            let parent = ingest_corpus_result(&db, &corpus, input.clone()).unwrap();
            Self {
                root,
                db,
                corpus,
                parent,
                input,
            }
        }
        fn request(&self, name: &str) -> RfV1DeriveRequest {
            RfV1DeriveRequest {
                schema_version: 1,
                result_id: name.into(),
                parent_manifest_sha256: sha256_hex(
                    &fs::read(
                        self.corpus
                            .join(&self.parent.summary.result_id)
                            .join("manifest.json"),
                    )
                    .unwrap(),
                ),
                parent_iq_sha256: self.parent.summary.iq_sha256.clone(),
                source_report: self.input.report.clone(),
                split: EvidenceSplit::ReceiveDomain,
                label: EvidenceLabel::Unknown {
                    reason: UnknownLabelReason::NoIndependentLabel,
                },
            }
        }
        fn annotated(
            &self,
            name: &str,
            split: EvidenceSplit,
            category: EvidenceCategory,
        ) -> RfV1DeriveRequest {
            let mut r = self.request(name);
            r.split = split;
            let p = &r.source_report.points[0];
            let numeric_id = (category == EvidenceCategory::KnownClass).then_some(3);
            let basis =
                "SYNTHETIC TEST ONLY: independent instrument report, not real RF labels".to_owned();
            r.label = EvidenceLabel::IndependentAnnotation {
                category,
                numeric_id,
                evidence: Box::new(AnnotationEvidence {
                    schema_version: 1,
                    schema_id: "rf_v1_independent_annotation_v1".into(),
                    annotation_id: "synthetic-evidence".into(),
                    method: EvidenceMethod::InstrumentReference,
                    reviewer: "synthetic-reviewer".into(),
                    annotated_at_utc: "2026-09-06T00:00:00Z".into(),
                    independent_of_model: true,
                    ambiguity: None,
                    basis_report_sha256: sha256_hex(basis.as_bytes()),
                    basis_report: basis,
                    source_sample_id: self.parent.record["lineage"]["source_sample_id"]
                        .as_str()
                        .unwrap()
                        .into(),
                    capture_session_id: self.input.capture_session_id.clone(),
                    capture_day: self.parent.summary.capture_day.clone(),
                    iq_sha256: r.parent_iq_sha256.clone(),
                    request_id: p.request_id,
                    session_generation: p.session_generation,
                    sequence: p.sequence,
                    profile_sha256: RF_V1_PROFILE_SHA256.into(),
                    preprocess_sha256: RF_PREPROCESS_HASH.into(),
                    label_space_sha256: LABEL_SHA256.into(),
                    category,
                    numeric_id,
                }),
            };
            r
        }
        fn derive(&self, r: RfV1DeriveRequest) -> ApiResult<CorpusResultDetail> {
            derive_rf_v1(&self.db, &self.corpus, &self.parent.summary.result_id, r)
        }
        fn check_python(&self, id: &str) {
            let package = self.corpus.join(id);
            let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
            let output = std::process::Command::new("python3")
                .arg(repo.join("jetson-agx/sdrharness/scripts/validate-amc-corpus-manifest.py"))
                .arg("--manifest")
                .arg(package.join("manifest.json"))
                .arg("--asset-root")
                .arg(&package)
                .arg("--verify-assets")
                .output()
                .unwrap();
            assert!(
                output.status.success(),
                "{}",
                String::from_utf8_lossy(&output.stderr)
            );
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.root).unwrap();
        }
    }
    #[test]
    #[ignore = "explicit isolated HTTP fixture export"]
    fn export_synthetic_http_requests() {
        let out =
            PathBuf::from(std::env::var("V1A_VALIDATION_DIR").expect("explicit feature directory"));
        assert!(out.starts_with("/var/tmp/sdrharness-dev") && out.canonicalize().unwrap() == out);
        let f = Fixture::new();
        for (name, value) in [
            (
                "original-request.json",
                serde_json::to_value(&f.input).unwrap(),
            ),
            (
                "unknown-request.json",
                serde_json::to_value(f.request("rf-http-unknown")).unwrap(),
            ),
            (
                "calibration-request.json",
                serde_json::to_value(f.annotated(
                    "rf-http-calibration",
                    EvidenceSplit::Calibration,
                    EvidenceCategory::KnownClass,
                ))
                .unwrap(),
            ),
            (
                "acceptance-request.json",
                serde_json::to_value(f.annotated(
                    "rf-http-acceptance",
                    EvidenceSplit::Acceptance,
                    EvidenceCategory::KnownClass,
                ))
                .unwrap(),
            ),
        ] {
            write_private_file(&out.join(name), &pretty_json(&value).unwrap()).unwrap();
        }
    }

    #[test]
    fn legacy_package_without_original_report_stays_unknown() {
        let f = Fixture::new();
        let dir = f.corpus.join(&f.parent.summary.result_id);
        let mut manifest = f.parent.manifest.clone();
        manifest["assets"]
            .as_array_mut()
            .unwrap()
            .retain(|a| a["role"] != "capture_report");
        fs::remove_file(dir.join("source-report.json")).unwrap();
        fs::write(dir.join("manifest.json"), pretty_json(&manifest).unwrap()).unwrap();
        open_result_database(&f.db)
            .unwrap()
            .execute(
                "UPDATE p201_corpus_results SET manifest_json=?1 WHERE result_id=?2",
                params![
                    serde_json::to_string(&manifest).unwrap(),
                    f.parent.summary.result_id
                ],
            )
            .unwrap();
        let r = f.derive(f.request("legacy-unknown")).unwrap();
        f.check_python(&r.summary.result_id);
        assert!(f
            .derive(f.annotated(
                "legacy-forgery",
                EvidenceSplit::Calibration,
                EvidenceCategory::KnownClass
            ))
            .is_err());
        fs::write(
            dir.join("source-report.json"),
            json_line(&serde_json::to_value(&f.input.report).unwrap()).unwrap(),
        )
        .unwrap();
        assert!(f
            .derive(f.annotated(
                "unpinned-report",
                EvidenceSplit::Calibration,
                EvidenceCategory::KnownClass
            ))
            .is_err());
    }

    #[test]
    fn session_day_and_duplicate_iq_cannot_cross_partitions() {
        for fault in ["session", "day", "iq"] {
            let mut f = Fixture::new();
            f.derive(f.annotated(
                "cal-first",
                EvidenceSplit::Calibration,
                EvidenceCategory::KnownClass,
            ))
            .unwrap();
            f.input.report.points[0].sequence += 1;
            if fault != "session" {
                f.input.capture_session_id = "another-session".into();
            }
            if fault == "iq" {
                f.input.captured_at_utc = "2026-09-04T05:10:11Z".into();
            }
            f.parent = ingest_corpus_result(&f.db, &f.corpus, f.input.clone()).unwrap();
            assert!(
                f.derive(f.annotated(
                    "accept-second",
                    EvidenceSplit::Acceptance,
                    EvidenceCategory::KnownClass
                ))
                .is_err(),
                "{fault}"
            );
        }
    }

    #[test]
    fn derives_unknown_without_iq_copy_and_preserves_parent_and_delete() {
        let f = Fixture::new();
        let original = fs::read(
            f.corpus
                .join(&f.parent.summary.result_id)
                .join("manifest.json"),
        )
        .unwrap();
        let r = f.derive(f.request("rf-unknown")).unwrap();
        f.check_python(&r.summary.result_id);
        assert_eq!(r.record["label"]["provenance"], "unknown");
        assert_eq!(r.summary.preprocess_id, "rf_preprocess_v1");
        let original_iq = f.corpus.join(&f.parent.summary.result_id).join("raw.iq");
        let derived_iq = f.corpus.join(&r.summary.result_id).join("raw.iq");
        assert_eq!(
            fs::metadata(&original_iq).unwrap().ino(),
            fs::metadata(&derived_iq).unwrap().ino()
        );
        assert_eq!(
            fs::read(
                f.corpus
                    .join(&f.parent.summary.result_id)
                    .join("manifest.json")
            )
            .unwrap(),
            original
        );
        delete_corpus_result(&f.db, &f.corpus, &f.parent.summary.result_id).unwrap();
        f.check_python(&r.summary.result_id);
        assert!(derived_iq.exists());
        delete_corpus_result(&f.db, &f.corpus, &r.summary.result_id).unwrap();
        assert!(list_corpus_results(&f.db).unwrap().is_empty());
    }
    #[test]
    fn independent_known_and_ood_evidence_keep_groups_after_delete() {
        for category in [
            EvidenceCategory::KnownClass,
            EvidenceCategory::NoiseIdle,
            EvidenceCategory::OutOfLabelSpace,
            EvidenceCategory::Mixed,
            EvidenceCategory::LowQuality,
        ] {
            let f = Fixture::new();
            let r = f
                .derive(f.annotated("rf-cal", EvidenceSplit::Calibration, category))
                .unwrap();
            f.check_python(&r.summary.result_id);
            assert_eq!(
                r.record["label"]["numeric_id"].is_null(),
                category != EvidenceCategory::KnownClass
            );
            delete_corpus_result(&f.db, &f.corpus, &r.summary.result_id).unwrap();
            assert!(f
                .derive(f.annotated("rf-accept", EvidenceSplit::Acceptance, category))
                .is_err());
            assert_eq!(fs::read_dir(&f.corpus).unwrap().count(), 1);
            let again = f
                .derive(f.annotated("rf-cal2", EvidenceSplit::Calibration, category))
                .unwrap();
            f.check_python(&again.summary.result_id);
        }
    }
    #[test]
    fn annotation_and_lineage_negative_cases_leave_no_package_or_group_claim() {
        let f = Fixture::new();
        for fault in [
            "hash",
            "rx",
            "request",
            "session",
            "source",
            "profile",
            "preprocess",
            "evidence_hash",
            "model",
            "class",
            "ambiguity",
            "unknown_split",
            "oversized",
        ] {
            let mut r = f.annotated(
                "bad",
                EvidenceSplit::Calibration,
                EvidenceCategory::KnownClass,
            );
            match fault {
                "hash" => r.parent_iq_sha256 = "0".repeat(64),
                "rx" => r.source_report.points[0].rx_input.front_panel_port = "RX2".into(),
                "session" => r.source_report.session_generation += 1,
                "unknown_split" => {
                    r.label = EvidenceLabel::Unknown {
                        reason: UnknownLabelReason::NoiseOrIdle,
                    }
                }
                _ => {
                    if let EvidenceLabel::IndependentAnnotation { evidence: e, .. } = &mut r.label {
                        match fault {
                            "request" => e.request_id += 1,
                            "source" => e.capture_day = "2026-09-04".into(),
                            "profile" => e.profile_sha256 = "0".repeat(64),
                            "preprocess" => e.preprocess_sha256 = "0".repeat(64),
                            "evidence_hash" => e.basis_report.push('!'),
                            "model" => e.independent_of_model = false,
                            "class" => e.numeric_id = Some(24),
                            "ambiguity" => e.ambiguity = Some("not independently resolved".into()),
                            "oversized" => e.basis_report = "x".repeat(16385),
                            _ => unreachable!(),
                        }
                    }
                }
            }
            assert!(f.derive(r).is_err(), "{fault}");
            assert_eq!(fs::read_dir(&f.corpus).unwrap().count(), 1, "{fault}");
            let n: u64 = open_result_database(&f.db)
                .unwrap()
                .query_row(
                    "SELECT count(*) FROM p201_corpus_partition_groups",
                    [],
                    |r| r.get(0),
                )
                .unwrap();
            assert_eq!(n, 0);
        }
        let mut value = serde_json::to_value(f.request("bad")).unwrap();
        value["label"] = json!({"provenance":"dataset_ground_truth","numeric_id":3});
        assert!(serde_json::from_value::<RfV1DeriveRequest>(value).is_err());
        let path = f.corpus.join(&f.parent.summary.result_id).join("raw.iq");
        let mut raw = fs::read(&path).unwrap();
        raw[0] ^= 1;
        fs::write(&path, raw).unwrap();
        assert!(f.derive(f.request("bad")).is_err());
    }
    #[test]
    fn reference_validator_rejects_rehashed_evidence_and_source_forgery() {
        let f = Fixture::new();
        let r = f
            .derive(f.annotated(
                "tamper",
                EvidenceSplit::Calibration,
                EvidenceCategory::KnownClass,
            ))
            .unwrap();
        let dir = f.corpus.join(&r.summary.result_id);
        let originals: Vec<_> = fs::read_dir(&dir)
            .unwrap()
            .map(|e| {
                let path = e.unwrap().path();
                let bytes = fs::read(&path).unwrap();
                (path, bytes)
            })
            .collect();
        for fault in [
            "numeric_id",
            "lineage",
            "request",
            "model",
            "method",
            "extra",
            "rx",
            "original_request",
        ] {
            let mut manifest = r.manifest.clone();
            let mut record = r.record.clone();
            let mut d: Value =
                serde_json::from_slice(&fs::read(dir.join("derivation.json")).unwrap()).unwrap();
            let mut e: Value =
                serde_json::from_slice(&fs::read(dir.join("annotation.json")).unwrap()).unwrap();
            match fault {
                "numeric_id" => record["label"]["numeric_id"] = 4.into(),
                "lineage" => record["lineage"]["capture_day"] = "2026-09-04".into(),
                "request" => d["source_report"]["points"][0]["request_id"] = 99.into(),
                "model" => e["independent_of_model"] = false.into(),
                "method" => e["method"] = "model_prediction".into(),
                "extra" => e["model_top1"] = 3.into(),
                "rx" => record["source"]["rx_input"]["front_panel_port"] = "RX2".into(),
                "original_request" => {
                    d["source_report"]["points"][0]["request_id"] = 99.into();
                    fs::write(
                        dir.join("source-report.json"),
                        json_line(&d["source_report"]).unwrap(),
                    )
                    .unwrap();
                }
                _ => unreachable!(),
            }
            let eb = json_line(&e).unwrap();
            record["label"]["evidence"]["evidence_sha256"] = sha256_hex(&eb).into();
            fs::write(dir.join("annotation.json"), eb).unwrap();
            fs::write(dir.join("derivation.json"), json_line(&d).unwrap()).unwrap();
            let rb = json_line(&record).unwrap();
            manifest["record_index"]["sha256"] = sha256_hex(&rb).into();
            manifest["record_index"]["bytes"] = (rb.len() as u64).into();
            fs::write(dir.join("records.jsonl"), rb).unwrap();
            for a in manifest["assets"].as_array_mut().unwrap() {
                let bytes = fs::read(dir.join(a["path"].as_str().unwrap())).unwrap();
                a["sha256"] = sha256_hex(&bytes).into();
                a["bytes"] = (bytes.len() as u64).into();
            }
            fs::write(dir.join("manifest.json"), pretty_json(&manifest).unwrap()).unwrap();
            let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
            let output = std::process::Command::new("python3")
                .arg(repo.join("jetson-agx/sdrharness/scripts/validate-amc-corpus-manifest.py"))
                .arg("--manifest")
                .arg(dir.join("manifest.json"))
                .arg("--asset-root")
                .arg(&dir)
                .arg("--verify-assets")
                .output()
                .unwrap();
            assert!(!output.status.success(), "{fault}");
            for (path, bytes) in &originals {
                fs::write(path, bytes).unwrap();
            }
        }
    }

    #[test]
    fn insert_failure_cleans_new_files_and_does_not_replace_existing() {
        let f = Fixture::new();
        let r = f.request("same");
        f.derive(r.clone()).unwrap();
        let before = fs::read(f.corpus.join("same/manifest.json")).unwrap();
        assert!(f.derive(r).is_err());
        assert_eq!(
            fs::read(f.corpus.join("same/manifest.json")).unwrap(),
            before
        );
        open_result_database(&f.db).unwrap().execute_batch("CREATE TRIGGER injected_failure BEFORE INSERT ON p201_corpus_results BEGIN SELECT RAISE(FAIL,'synthetic database failure'); END;").unwrap();
        assert!(f
            .derive(f.annotated(
                "db-failure",
                EvidenceSplit::Acceptance,
                EvidenceCategory::NoiseIdle
            ))
            .is_err());
        assert!(!f.corpus.join("db-failure").exists());
        assert_eq!(fs::read_dir(&f.corpus).unwrap().count(), 2);
        let n: u64 = open_result_database(&f.db)
            .unwrap()
            .query_row(
                "SELECT count(*) FROM p201_corpus_partition_groups",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(n, 0);
    }
}
