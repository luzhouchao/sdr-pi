use sdr_agent_controller::autonomy::{CruiseControl, CruiseStopReason, SweepProgress, SweepVisit};
use sdr_agent_controller::protocol::ProposedAction;
use serde_json::Value;
use std::time::{Duration, Instant};

fn survey(start_hz: u64, stop_hz: u64) -> ProposedAction {
    ProposedAction::SurveyBand {
        start_hz,
        stop_hz,
        step_hz: 100_000,
        sample_rate_hz: 10_000_000,
        rf_bandwidth_hz: 10_000_000,
        dwell_ms: 20,
    }
}

#[test]
fn real_trace_refines_candidates_then_blocks_the_first_empty_local_followup() {
    let trace: Value = serde_json::from_str(include_str!(
        "../../../../docs/evidence/PI_DURABLE_CRUISE_REVIEW_2026-10-27.json"
    ))
    .unwrap();
    let mut progress = SweepProgress::default();
    for step in trace["steps"].as_array().unwrap().iter().take(4) {
        let plan = &step["submitted_plan"]["arguments"];
        let action = survey(
            plan["start_hz"].as_u64().unwrap(),
            plan["stop_hz"].as_u64().unwrap(),
        );
        assert_eq!(progress.check(&action), Ok(()));
        assert_eq!(
            progress.record(SweepVisit {
                start_hz: plan["start_hz"].as_u64().unwrap(),
                stop_hz: plan["stop_hz"].as_u64().unwrap(),
                candidate_count: step["candidate_count"].as_u64().unwrap() as u8,
            }),
            None
        );
    }
    let fifth = &trace["steps"][4]["submitted_plan"]["arguments"];
    assert_eq!(
        progress.check(&survey(
            fifth["start_hz"].as_u64().unwrap(),
            fifth["stop_hz"].as_u64().unwrap()
        )),
        Err(CruiseStopReason::AdjacentSweepRequired)
    );
    // A lawful alternative explores adjacent centers; the third empty result
    // ends the run instead of forcing all eight old model proposals through.
    for (start_hz, stop_hz, expected) in [
        (2_451_250_000, 2_455_000_000, None),
        (
            2_455_000_000,
            2_460_000_000,
            Some(CruiseStopReason::EmptySweepLimit),
        ),
    ] {
        assert_eq!(progress.check(&survey(start_hz, stop_hz)), Ok(()));
        assert_eq!(
            progress.record(SweepVisit {
                start_hz,
                stop_hz,
                candidate_count: 0
            }),
            expected
        );
    }
    assert_eq!(
        progress.check(&survey(2_460_000_000, 2_465_000_000)),
        Err(CruiseStopReason::EmptySweepLimit)
    );
}

#[test]
fn candidate_rechecks_are_finite_even_with_grid_or_action_jitter() {
    let mut progress = SweepProgress::default();
    for _ in 0..3 {
        assert_eq!(
            progress.check(&survey(2_450_000_000, 2_451_000_000)),
            Ok(())
        );
        progress.record(SweepVisit {
            start_hz: 2_450_000_000,
            stop_hz: 2_451_000_000,
            candidate_count: 1,
        });
    }
    assert_eq!(
        progress.check(&survey(2_450_100_000, 2_451_100_000)),
        Err(CruiseStopReason::LocalSweepLimit)
    );
    let inspection = ProposedAction::InspectCandidate {
        candidate_id: "new-id-does-not-reset-history".into(),
        center_hz: 2_450_500_000,
        sample_rate_hz: 2_100_000,
        rf_bandwidth_hz: 200_000,
        dwell_ms: 20,
    };
    assert_eq!(
        progress.check(&inspection),
        Err(CruiseStopReason::LocalSweepLimit)
    );
}

#[test]
fn condensed_history_does_not_reset_older_limits_and_new_run_starts_clean() {
    let now = Instant::now();
    let mut cruise = CruiseControl::default();
    cruise.start(1_048_576, 128, 120, now).unwrap();
    let mut progress = SweepProgress::default();
    for _ in 0..3 {
        progress.record(SweepVisit {
            start_hz: 100_000_000,
            stop_hz: 101_000_000,
            candidate_count: 1,
        });
    }
    for offset in 0..8 {
        let start_hz = 200_000_000 + offset * 2_000_000;
        progress.record(SweepVisit {
            start_hz,
            stop_hz: start_hz + 1_000_000,
            candidate_count: 1,
        });
    }
    let summary = progress.planning_summary(&cruise, now);
    assert!(summary.history_truncated);
    assert_eq!(summary.recent_sweeps.len(), 8);
    assert_eq!(
        progress.check(&survey(100_500_000, 101_500_000)),
        Err(CruiseStopReason::LocalSweepLimit)
    );
    assert_eq!(
        SweepProgress::default().check(&survey(100_500_000, 101_500_000)),
        Ok(())
    );
}

#[test]
fn remaining_budget_summary_and_wire_validation_are_bounded() {
    let now = Instant::now();
    let mut cruise = CruiseControl::default();
    cruise.start(1_048_576, 8, 120, now).unwrap();
    cruise.record_execution(49_152);
    let mut progress = SweepProgress::default();
    progress.record(SweepVisit {
        start_hz: 2_450_000_000,
        stop_hz: 2_460_000_000,
        candidate_count: 1,
    });
    let mut summary = progress.planning_summary(&cruise, now + Duration::from_secs(30));
    assert_eq!(summary.remaining_steps, 7);
    assert_eq!(summary.remaining_ms, 90_000);
    assert_eq!(summary.remaining_iq_bytes, 999_424);
    assert!(summary.valid(70_000_000, 6_000_000_000));
    summary.recent_sweeps[0].stop_hz = 6_000_000_001;
    assert!(!summary.valid(70_000_000, 6_000_000_000));
}

#[test]
fn empty_streak_resets_on_candidates_without_resetting_local_history() {
    let mut progress = SweepProgress::default();
    for (start_hz, candidate_count) in [
        (100_000_000, 0),
        (102_000_000, 0),
        (104_000_000, 1),
        (106_000_000, 0),
    ] {
        assert_eq!(
            progress.record(SweepVisit {
                start_hz,
                stop_hz: start_hz + 1_000_000,
                candidate_count
            }),
            None
        );
    }
    let mut cruise = CruiseControl::default();
    let now = Instant::now();
    cruise.start(100, 8, 120, now).unwrap();
    assert_eq!(
        progress
            .planning_summary(&cruise, now)
            .consecutive_empty_sweeps,
        1
    );
}

#[test]
fn cruise_summary_never_relaxes_frequency_policy_or_frame_limits() {
    use sdr_agent_controller::policy::ControllerPolicy;
    use sdr_agent_controller::protocol::{
        PlanRequest, PlanResponse, SweepObservationSummary, MAX_FRAME_BYTES,
    };
    let mut request: PlanRequest =
        serde_json::from_str(include_str!("../config/request.example.json")).unwrap();
    let now = Instant::now();
    let mut cruise = CruiseControl::default();
    cruise.start(1_048_576, 8, 120, now).unwrap();
    request.cruise = Some(SweepProgress::default().planning_summary(&cruise, now));
    request.observation.health.sdr_online = true;
    request.observation.health.can_retune = true;
    let response: PlanResponse=serde_json::from_value(serde_json::json!({
        "protocol_version":1,"request_id":request.request_id,"session_generation":request.session_generation,
        "status":"ok","planner":{"provider":"test","model":"test"},
        "action":{"kind":"survey_band","start_hz":69000000,"stop_hz":70000000,"step_hz":100000,
            "sample_rate_hz":10000000,"rf_bandwidth_hz":10000000,"dwell_ms":20}
    })).unwrap();
    assert!(ControllerPolicy
        .validate_response(&request, response)
        .is_err());
    assert!(
        serde_json::from_value::<ProposedAction>(serde_json::json!({"kind":"transmit"})).is_err()
    );
    request.instruction = "x".repeat(1024);
    request.observation.latest_sweep = Some(SweepObservationSummary {
        sweep_id: "r".repeat(64),
        sample_rate_hz: 10_000_000,
        rf_bandwidth_hz: 10_000_000,
        fixed_gain_db: 20,
        noise_floor_dbfs: -53.33333,
        points: (0..768)
            .map(|i| (70_000_000 + i * 1_000_000, -53.33333))
            .collect(),
    });
    let mut candidate = sdr_agent_controller::protocol::CandidateSummary {
        id: "candidate".into(),
        center_hz: 433_920_000,
        bandwidth_hz: 1_000_000,
        peak_dbfs: -30.0,
        snr_db: 10.0,
        age_ms: 0,
    };
    request.observation.candidates = (0..32)
        .map(|i| {
            candidate.id = format!("candidate-{i}");
            candidate.clone()
        })
        .collect();
    let summary = request.cruise.as_mut().unwrap();
    summary.recent_sweeps = vec![
        SweepVisit {
            start_hz: 70_000_000,
            stop_hz: 80_000_000,
            candidate_count: 32
        };
        8
    ];
    assert!(ControllerPolicy.validate_request(&request).is_ok());
    assert!(serde_json::to_vec(&request).unwrap().len() < MAX_FRAME_BYTES);
    request.cruise.as_mut().unwrap().local_sweep_limit = 128;
    assert!(ControllerPolicy.validate_request(&request).is_err());
}
