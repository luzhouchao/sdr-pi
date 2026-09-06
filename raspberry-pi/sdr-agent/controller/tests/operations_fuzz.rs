//! Deterministic, bounded JSON mutations; no executor, IQ, model, or socket access.
use sdr_agent_controller::policy::ControllerPolicy;
use sdr_agent_controller::protocol::{PlanRequest, PlanResponse};
use sdr_agent_controller::recognition_result::RecognitionObservation;
use sha2::{Digest, Sha256};

fn corpus(base: &[u8]) -> Vec<Vec<u8>> {
    let mut seed = 20260906_u32;
    (0..256)
        .map(|index| {
            seed = seed.wrapping_mul(1664525).wrapping_add(1013904223);
            let position = seed as usize % base.len();
            let mut frame = base.to_vec();
            match index % 4 {
                0 => frame.truncate(position),
                1 => frame[position] = 0,
                2 => frame.extend_from_slice(b"\n{}"),
                _ => frame[position] = (seed % 128) as u8,
            }
            frame
        })
        .collect()
}

#[test]
fn seeded_planner_and_recognition_summary_decoders_remain_bounded() {
    let base = include_bytes!("../../../../jetson-agx/sdrharness/config/request.json");
    let response = br#"{"protocol_version":1,"request_id":1,"session_generation":1,"status":"ok","action":{"kind":"hold","reason":"synthetic"},"planner":{"provider":"synthetic","model":"none"}}"#;
    let observation = br#"{"schema_version":1,"candidate_id":"synthetic","request_id":1,"session_generation":1,"observed_at_unix_ms":1,"status":"unavailable","reason":"synthetic","calibration_status":"unavailable"}"#;
    for (kind, seed) in [
        ("planning_context", base.as_slice()),
        ("planner_response", response.as_slice()),
        ("recognition_observation", observation.as_slice()),
    ] {
        let frames = corpus(seed);
        assert_eq!(frames, corpus(seed));
        let mut hash = Sha256::new();
        for frame in &frames {
            hash.update(frame);
            hash.update([0]);
            assert!(frame.len() <= 32768);
            match kind {
                "planning_context" => {
                    if let Ok(request) = serde_json::from_slice::<PlanRequest>(frame) {
                        let _ = ControllerPolicy.validate_request(&request);
                    }
                }
                "planner_response" => {
                    if let Ok(response) = serde_json::from_slice::<PlanResponse>(frame) {
                        let request: PlanRequest = serde_json::from_slice(base).unwrap();
                        let _ = ControllerPolicy.validate_response(&request, response);
                    }
                }
                _ => {
                    if let Ok(observation) = serde_json::from_slice::<RecognitionObservation>(frame)
                    {
                        let _ = observation.validate();
                    }
                }
            }
        }
        println!(
            "o1a_fuzz={kind} seed=20260906 cases=256 sha256={:x}",
            hash.finalize()
        );
    }
}
