import assert from "node:assert/strict";
import test from "node:test";
import {
  makeSessionEvent,
  makeSessionResponse,
  parseSessionCommand,
  SESSION_PROTOCOL_VERSION,
} from "../src/session-protocol.mjs";

function context() {
  return {
    protocol_version: 1,
    request_id: 9,
    session_generation: 3,
    instruction: "查看当前状态",
    state: "idle",
    observation: {
      age_ms: 10,
      health: {
        sdr_online: true,
        can_retune: false,
        can_capture_iq: false,
        fpga_available: false,
        recognizer_available: false,
        dropped_observations: 0,
      },
      candidates: [],
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

function command(type, extra = {}) {
  return {
    protocol_version: SESSION_PROTOCOL_VERSION,
    command_id: 1,
    session_generation: 3,
    type,
    ...extra,
  };
}

test("accepts the Pi-inspired prompting command subset", () => {
  for (const type of ["prompt", "steer", "follow_up"]) {
    const parsed = parseSessionCommand(JSON.stringify(command(type, { context: context() })));
    assert.equal(parsed.type, type);
    assert.equal(parsed.context.instruction, "查看当前状态");
  }
  for (const type of ["open_session", "abort", "clear_queue", "get_state", "close_session"]) {
    assert.equal(parseSessionCommand(JSON.stringify(command(type))).type, type);
  }
});

test("rejects stale context generation", () => {
  const stale = context();
  stale.session_generation = 2;
  assert.throws(
    () => parseSessionCommand(JSON.stringify(command("prompt", { context: stale }))),
    /different session generation/,
  );
});

test("rejects unknown commands and fields", () => {
  assert.throws(() => parseSessionCommand(JSON.stringify(command("bash"))), /unsupported/);
  assert.throws(
    () => parseSessionCommand(JSON.stringify({ ...command("abort"), shell: "id" })),
    /unknown field shell/,
  );
});

test("correlates responses and events", () => {
  const source = command("get_state");
  assert.deepEqual(makeSessionResponse(source, true, { active: false }), {
    protocol_version: 1,
    command_id: 1,
    session_generation: 3,
    type: "response",
    command: "get_state",
    success: true,
    data: { active: false },
  });
  assert.deepEqual(makeSessionEvent(3, "agent_start"), {
    protocol_version: 1,
    session_generation: 3,
    type: "event",
    event: "agent_start",
  });
});

test("bounds error text", () => {
  const response = makeSessionResponse(command("abort"), false, `bad\n${"x".repeat(800)}`);
  assert.equal(response.success, false);
  assert.equal(response.error.includes("\n"), false);
  assert.ok(Buffer.byteLength(response.error, "utf8") <= 512);
});
