//! Engineering replay of one hash-bound received window and its prior inspection.
//! No RF operation, label admission, resampling or model-specific transform here.
use crate::protocol::CandidateSummary;
use crate::recognition_input::{
    build_model_ready_batch, sha256_hex, validate_recognition_target, BatchCaptureMetadata,
    LoadedRecognitionInputProfile, ModelReadyBatch, RecognitionTarget,
};
use crate::sweep::{analyze_ci16_window, validate_completed_sweep, SweepPlan, SweepReport};
use serde::{Deserialize, Serialize};
use std::fs::OpenOptions;
use std::io::Read;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::Path;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReceivedWindow {
    pub schema_version: u16,
    pub candidate_id: String,
    pub request_id: u64,
    pub inspection_plan: SweepPlan,
    pub inspection_report: SweepReport,
    pub inspection_received_at_unix_ms: u64,
    pub capture_plan: SweepPlan,
    pub capture_report: SweepReport,
    pub capture_received_at_unix_ms: u64,
    pub raw_iq_file: String,
    pub raw_iq_sha256: String,
}

pub fn prepare(
    loaded: &LoadedRecognitionInputProfile,
    root: &Path,
    input: &ReceivedWindow,
) -> Result<ModelReadyBatch, String> {
    if input.schema_version != 1
        || !loaded.is_rf_v1()
        || !root.is_absolute()
        || root.canonicalize().map_err(|e| e.to_string())? != root
        || input.raw_iq_file.is_empty()
        || input.raw_iq_file.len() > 96
        || !input
            .raw_iq_file
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
        || input.raw_iq_file == "."
        || input.raw_iq_file == ".."
    {
        return Err("received window input/root".into());
    }
    validate_completed_sweep(&input.inspection_plan, &input.inspection_report)
        .map_err(|e| e.to_string())?;
    let capture_plan = validate_completed_sweep(&input.capture_plan, &input.capture_report)
        .map_err(|e| e.to_string())?;
    if input.inspection_report.backend != "agx_iq_software_aggregate"
        || input.inspection_report.backend_version != 1
        || input.capture_report.backend != "agx_iq_software_aggregate"
        || input.capture_report.backend_version != 1
        || input.inspection_report.points.len() != 1
        || input.capture_report.points.len() != 1
        || input.capture_report.session_generation <= input.inspection_report.session_generation
        || input.capture_received_at_unix_ms < input.inspection_received_at_unix_ms
        || input.capture_plan.settle_ms != u64::from(loaded.profile.rx.settle_ms)
        || input.capture_plan.gain_db != Some(loaded.profile.rx.gain_db)
        || capture_plan.samples_per_point != loaded.total_complex_samples()
    {
        return Err("received window capture plan/time".into());
    }
    let source = &input.inspection_report.points[0];
    let point = &input.capture_report.points[0];
    if point.sequence <= source.sequence {
        return Err("received window source order".into());
    }
    let spectral = &source.spectral;
    let target = RecognitionTarget::from_inspection(
        &CandidateSummary {
            id: input.candidate_id.clone(),
            center_hz: spectral.estimated_center_hz,
            bandwidth_hz: spectral.occupied_bandwidth_hz,
            peak_dbfs: spectral.peak_power_dbfs,
            snr_db: spectral.measured_snr_db,
            age_ms: 0,
        },
        &input.inspection_report,
        input.inspection_received_at_unix_ms,
        input
            .inspection_plan
            .gain_db
            .ok_or("inspection gain missing")?,
    )
    .map_err(|e| e.to_string())?;
    // Evaluate freshness at capture receipt time, never re-date history to inference time.
    validate_recognition_target(loaded, &target, input.capture_received_at_unix_ms)
        .map_err(|e| e.to_string())?;
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(root.join(&input.raw_iq_file))
        .map_err(|e| e.to_string())?;
    let m = file.metadata().map_err(|e| e.to_string())?;
    if !m.is_file()
        || m.nlink() != 1
        || m.uid() != unsafe { libc::geteuid() }
        || m.mode() & 0o077 != 0
        || m.len() != 16384
    {
        return Err("received window private IQ shape".into());
    }
    let mut raw = Vec::new();
    file.by_ref()
        .take(16385)
        .read_to_end(&mut raw)
        .map_err(|e| e.to_string())?;
    if raw.len() != 16384 || sha256_hex(&raw) != input.raw_iq_sha256 {
        return Err("received window raw hash".into());
    }
    let (power, measured, clipped) =
        analyze_ci16_window(&raw, 4096, point.actual_center_hz, point.sample_rate_hz)
            .map_err(|e| e.to_string())?;
    if power != point.band_power_dbfs
        || measured != point.spectral
        || clipped != point.clipped_samples
    {
        return Err("received window same-IQ spectral mismatch".into());
    }
    let capture = BatchCaptureMetadata {
        sdrd_request_id: point.request_id,
        session_generation: point.session_generation,
        sequence: point.sequence,
        center_hz: point.actual_center_hz,
        sample_rate_hz: point
            .sample_rate_hz
            .try_into()
            .map_err(|_| "sample rate width")?,
        rf_bandwidth_hz: point
            .rf_bandwidth_hz
            .try_into()
            .map_err(|_| "bandwidth width")?,
        gain_db: loaded.profile.rx.gain_db,
        samples_captured: point.captured_samples,
        bytes_transferred: raw.len() as u64,
        dropped_samples: point.dropped_samples,
        overflow: point.overflow,
        timeout: point.timeout.clone(),
        health: point.health.clone(),
        rx_input: point.rx_input.clone(),
    };
    build_model_ready_batch(
        loaded,
        &target,
        input.request_id,
        point.session_generation,
        capture,
        &raw,
    )
    .map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::recognition_input::frozen_rf_v1_profile;
    use crate::sweep::{BackendSweep, ReplaySweepAdapter, SweepEngine};
    use std::os::unix::fs::PermissionsExt;

    fn report(center: u64, generation: u64, sequence: u64, raw: &[u8]) -> (SweepPlan, SweepReport) {
        let plan: SweepPlan = serde_json::from_value(serde_json::json!({
            "sweep_id":format!("received-test-{generation}"),"session_generation":generation,
            "frequencies":{"kind":"centers","centers_hz":[center]},"sample_rate_hz":2100000,
            "rf_bandwidth_hz":1500000,"gain_db":50,"settle_ms":100,"frame_samples":4096,
            "aggregate_frames":1,"point_timeout_ms":1000,"detection_threshold_db":6
        }))
        .unwrap();
        let (power, spectral, clipped) = analyze_ci16_window(raw, 4096, center, 2100000).unwrap();
        let point = serde_json::from_value(serde_json::json!({
            "point_index":0,"request_id":5,"session_generation":generation,"requested_center_hz":center,
            "actual_center_hz":center,"sample_rate_hz":2100000,"rf_bandwidth_hz":1500000,"sequence":sequence,
            "dropped_samples":0,"overflow":false,"captured_samples":4096,"band_power_dbfs":power,
            "spectral":spectral,"clipped_samples":clipped,"status_flags":0,"elapsed_us":2000,
            "timeout":{"limit_ms":1000,"elapsed_us":2000,"timed_out":false},
            "health":{"healthy":true,"flags":0,"source":"iio_adapter"},
            "rx_input":{"identity_version":1,"verified":true,"front_panel_port":"RX1","logical_channel":"RX0",
                "phy_channel":"voltage0","scan_i_channel":"voltage0","scan_q_channel":"voltage1","rf_port_select":"A_BALANCED","source":"iio_channel_attr"}
        })).unwrap();
        let report = SweepEngine::new(ReplaySweepAdapter::new([Ok(BackendSweep {
            backend: "agx_iq_software_aggregate".into(),
            backend_version: 1,
            points: vec![point],
            dataset: None,
        })]))
        .run(&plan)
        .unwrap();
        (plan, report)
    }

    #[test]
    fn received_replay_binds_raw_hash_source_time_and_fixed_input() {
        let root = std::env::temp_dir().join(format!("received-window-{}", std::process::id()));
        std::fs::create_dir(&root).unwrap();
        let raw: Vec<u8> = (0..4096)
            .flat_map(|n| {
                let phase = std::f64::consts::TAU * 17.0 * f64::from(n) / 4096.0;
                [(phase.cos() * 400.0) as i16, (phase.sin() * 400.0) as i16]
                    .into_iter()
                    .flat_map(i16::to_le_bytes)
            })
            .collect();
        let path = root.join("raw.iq");
        std::fs::write(&path, &raw).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
        let (inspection_plan, inspection_report) = report(2440000000, 10, 100, &raw);
        let center = inspection_report.points[0].spectral.estimated_center_hz;
        let (capture_plan, capture_report) = report(center, 11, 101, &raw);
        let input = ReceivedWindow {
            schema_version: 1,
            candidate_id: "synthetic-test".into(),
            request_id: 10001,
            inspection_plan,
            inspection_report,
            inspection_received_at_unix_ms: 1000,
            capture_plan,
            capture_report,
            capture_received_at_unix_ms: 2000,
            raw_iq_file: "raw.iq".into(),
            raw_iq_sha256: sha256_hex(&raw),
        };
        let loaded = frozen_rf_v1_profile().unwrap();
        let batch = prepare(&loaded, &root, &input).unwrap();
        assert_eq!(batch.model_bytes.len(), 32768);
        for kind in [
            "hash",
            "time",
            "sequence",
            "input",
            "path",
            "backend",
            "source_input",
            "zero_time",
            "spectral",
        ] {
            let mut bad = input.clone();
            match kind {
                "hash" => bad.raw_iq_sha256 = "0".repeat(64),
                "time" => bad.capture_received_at_unix_ms = 10000,
                "sequence" => bad.capture_report.points[0].sequence = 100,
                "input" => bad.capture_report.points[0].rx_input.front_panel_port = "RX2".into(),
                "backend" => bad.capture_report.backend_version = 2,
                "source_input" => {
                    bad.inspection_report.points[0].rx_input.logical_channel = "RX1".into()
                }
                "zero_time" => bad.inspection_received_at_unix_ms = 0,
                "path" => bad.raw_iq_file = "../raw.iq".into(),
                _ => bad.capture_report.points[0].spectral.peak_power_dbfs += 1.0,
            }
            assert!(prepare(&loaded, &root, &bad).is_err(), "{kind}");
        }
        let mut altered = raw.clone();
        altered[0] ^= 1;
        std::fs::write(&path, &altered).unwrap();
        assert!(prepare(&loaded, &root, &input).is_err());
        std::fs::write(&path, &raw).unwrap();
        let link = root.join("linked.iq");
        std::fs::hard_link(&path, &link).unwrap();
        assert!(prepare(&loaded, &root, &input).is_err());
        std::fs::remove_file(&link).unwrap();
        std::os::unix::fs::symlink(&path, &link).unwrap();
        let mut linked = input.clone();
        linked.raw_iq_file = "linked.iq".into();
        assert!(prepare(&loaded, &root, &linked).is_err());
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
        assert!(prepare(&loaded, &root, &input).is_err());
        std::fs::remove_dir_all(root).unwrap();
    }
}
