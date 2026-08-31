import assert from "node:assert/strict";
import test from "node:test";
import { normalizeAction, parseRequest } from "../src/protocol.mjs";

function request() {
  return {
    protocol_version: 1,
    request_id: 7,
    session_generation: 3,
    instruction: "Inspect the strongest candidate",
    state: "idle",
    observation: {
      age_ms: 100,
      health: {
        sdr_online: true,
        can_retune: false,
        can_capture_iq: false,
        fpga_available: false,
        recognizer_available: true,
        dropped_observations: 0,
      },
      candidates: [
        {
          id: "candidate-1",
          center_hz: 433_920_000,
          bandwidth_hz: 200_000,
          peak_dbfs: -18,
          snr_db: 16,
          age_ms: 100,
        },
      ],
    },
    limits: {
      min_freq_hz: 70_000_000,
      max_freq_hz: 6_000_000_000,
      max_span_hz: 20_000_000,
      max_bandwidth_hz: 10_000_000,
      max_dwell_ms: 5_000,
      max_iq_samples: 1_048_576,
      max_iq_bytes: 4_194_304,
      auto_approve_iq_bytes: 262_144,
      max_observation_age_ms: 2_000,
    },
  };
}

test("accepts a bounded request", () => {
  assert.deepEqual(parseRequest(JSON.stringify(request())), request());
});

test("rejects unknown top-level fields", () => {
  const value = request();
  value.unexpected = true;
  assert.throws(() => parseRequest(JSON.stringify(value)), /unknown field/u);
});

test("rejects oversized instructions", () => {
  const value = request();
  value.instruction = "x".repeat(1025);
  assert.throws(() => parseRequest(JSON.stringify(value)), /1 to 1024 bytes/u);
});

test("rejects unknown nested fields", () => {
  const value = request();
  value.observation.health.shell = "never";
  assert.throws(() => parseRequest(JSON.stringify(value)), /unknown field/u);
});

test("normalizes a capture proposal", () => {
  assert.deepEqual(
    normalizeAction({
      action: "capture_bounded_iq",
      candidate_id: "candidate-1",
      center_hz: 433_920_000,
      sample_rate_hz: 2_100_000,
      rf_bandwidth_hz: 500_000,
      samples: 65_536,
    }),
    {
      kind: "capture_bounded_iq",
      candidate_id: "candidate-1",
      center_hz: 433_920_000,
      sample_rate_hz: 2_100_000,
      rf_bandwidth_hz: 500_000,
      samples: 65_536,
    },
  );
});

test("rejects incomplete proposals", () => {
  assert.throws(
    () => normalizeAction({ action: "inspect_candidate", candidate_id: "candidate-1" }),
    /center_hz/u,
  );
});
