import assert from "node:assert/strict";
import test from "node:test";
import { normalizeAction, parseRequest, requireSubmitPlan } from "../src/protocol.mjs";

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

test("drops the retired false FPGA field and rejects a true legacy claim", () => {
  const legacy = request();
  legacy.observation.health.fpga_available = false;
  assert.deepEqual(parseRequest(JSON.stringify(legacy)), request());
  legacy.observation.health.fpga_available = true;
  assert.throws(() => parseRequest(JSON.stringify(legacy)), /retired and must be false/u);
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

test("bounds a multibyte visible reply to the Rust controller byte limit", () => {
  const action = normalizeAction({ action: "hold", reason: "信号".repeat(100) });
  assert.equal(action.kind, "hold");
  assert.ok(Buffer.byteLength(action.reason, "utf8") <= 256);
  assert.match(action.reason, /…$/u);
});

test("normalizes model-selected survey and inspection radio profiles", () => {
  assert.deepEqual(
    normalizeAction({
      action: "survey_band",
      start_hz: 2_400_000_000,
      stop_hz: 2_420_000_000,
      step_hz: 1_000_000,
      sample_rate_hz: 10_000_000,
      rf_bandwidth_hz: 8_000_000,
      dwell_ms: 10,
    }),
    {
      kind: "survey_band",
      start_hz: 2_400_000_000,
      stop_hz: 2_420_000_000,
      step_hz: 1_000_000,
      sample_rate_hz: 10_000_000,
      rf_bandwidth_hz: 8_000_000,
      dwell_ms: 10,
    },
  );
  assert.deepEqual(
    normalizeAction({
      action: "inspect_candidate",
      candidate_id: "candidate-1",
      center_hz: 2_405_000_000,
      sample_rate_hz: 5_000_000,
      rf_bandwidth_hz: 4_000_000,
      dwell_ms: 250,
    }),
    {
      kind: "inspect_candidate",
      candidate_id: "candidate-1",
      center_hz: 2_405_000_000,
      sample_rate_hz: 5_000_000,
      rf_bandwidth_hz: 4_000_000,
      dwell_ms: 250,
    },
  );
});

test("accepts compact measured sweep points in PlanningContext", () => {
  const value = request();
  value.observation.latest_sweep = {
    sweep_id: "request-6",
    sample_rate_hz: 10_000_000,
    rf_bandwidth_hz: 8_000_000,
    fixed_gain_db: 20,
    noise_floor_dbfs: -53,
    points: [[2_400_000_000, -51.2], [2_401_000_000, -28.4]],
  };
  assert.deepEqual(parseRequest(JSON.stringify(value)), value);
});

test("rejects incomplete proposals", () => {
  assert.throws(
    () => normalizeAction({ action: "inspect_candidate", candidate_id: "candidate-1" }),
    /center_hz/u,
  );
});

test("forces the only allowed planning tool without mutating the provider payload", () => {
  const payload = { model: "test", messages: [] };
  assert.deepEqual(requireSubmitPlan(payload), {
    model: "test",
    messages: [],
    tool_choice: {
      type: "function",
      function: { name: "submit_plan" },
    },
  });
  assert.equal(Object.hasOwn(payload, "tool_choice"), false);
});

test("forces submit_plan with the OpenAI Responses tool shape", () => {
  const payload = { model: "test", input: [] };
  assert.deepEqual(requireSubmitPlan(payload, "openai-responses"), {
    model: "test",
    input: [],
    tool_choice: { type: "function", name: "submit_plan" },
  });
  assert.equal(Object.hasOwn(payload, "tool_choice"), false);
});
