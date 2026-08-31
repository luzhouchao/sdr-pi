import assert from "node:assert/strict";
import test from "node:test";
import { normalizeAction } from "../src/protocol.mjs";
import { parseSessionCommand } from "../src/session-protocol.mjs";
import { SessionRuntime } from "../src/session-runtime.mjs";

class FakeAgent {
  constructor(onPlan, blocking = false) {
    this.onPlan = onPlan;
    this.blocking = blocking;
    this.listeners = new Set();
    this.queues = [];
    this.aborted = false;
    this.resolveRun = undefined;
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async prompt(text) {
    this.emit({ type: "agent_start" });
    this.emit({ type: "message_start", message: userMessage(text) });
    this.onPlan(normalizeAction({ action: "hold", reason: "safe replay" }));
    this.emit({
      type: "message_end",
      message: { role: "assistant", content: [{ type: "text", text: "保持等待" }] },
    });
    if (this.blocking) await new Promise((resolve) => (this.resolveRun = resolve));
    this.emit({ type: "agent_end", messages: [] });
  }

  steer(message) {
    this.queues.push(["steer", message]);
  }

  followUp(message) {
    this.queues.push(["follow_up", message]);
  }

  clearAllQueues() {
    this.queues = [];
  }

  abort() {
    this.aborted = true;
    this.resolveRun?.();
  }

  reset() {
    this.clearAllQueues();
  }

  emit(event) {
    for (const listener of this.listeners) listener(event);
  }
}

function userMessage(text) {
  return { role: "user", content: [{ type: "text", text }] };
}

function context(generation = 3, requestId = 9, instruction = "查看状态") {
  return {
    protocol_version: 1,
    request_id: requestId,
    session_generation: generation,
    instruction,
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

function command(type, id, extra = {}) {
  return parseSessionCommand(
    JSON.stringify({
      protocol_version: 1,
      command_id: id,
      session_generation: 3,
      type,
      ...extra,
    }),
  );
}

function runtime(blocking = false) {
  let fake;
  const instance = new SessionRuntime({
    plannerMeta: { provider: "test", model: "test" },
    createAgent: ({ onPlan }) => (fake = new FakeAgent(onPlan, blocking)),
  });
  return { instance, getFake: () => fake };
}

test("runs a persistent Agent and emits a correlated plan", async () => {
  const { instance } = runtime();
  const events = [];
  assert.equal((await instance.dispatch(command("open_session", 1), (e) => events.push(e))).success, true);
  assert.equal(
    (await instance.dispatch(command("prompt", 2, { context: context() }), (e) => events.push(e))).success,
    true,
  );
  await new Promise((resolve) => setImmediate(resolve));
  const proposed = events.find((event) => event.event === "plan_proposed");
  assert.equal(proposed.data.request_id, 9);
  assert.equal(proposed.data.action.kind, "hold");
  assert.equal(events.some((event) => event.event === "assistant_message"), true);
});

test("uses Pi steering and follow-up queues with a hard limit", async () => {
  const { instance, getFake } = runtime(true);
  const events = [];
  await instance.dispatch(command("open_session", 1), (e) => events.push(e));
  await instance.dispatch(command("prompt", 2, { context: context() }), (e) => events.push(e));
  await new Promise((resolve) => setImmediate(resolve));
  for (let index = 0; index < 4; index += 1) {
    const type = index % 2 === 0 ? "steer" : "follow_up";
    const response = await instance.dispatch(
      command(type, 3 + index, { context: context(3, 10 + index, `queued ${index}`) }),
      (e) => events.push(e),
    );
    assert.equal(response.success, true);
  }
  const overflow = await instance.dispatch(
    command("steer", 8, { context: context(3, 20, "overflow") }),
    (e) => events.push(e),
  );
  assert.equal(overflow.success, false);
  assert.match(overflow.error, /queue limit/);
  assert.equal(getFake().queues.length, 4);
  await instance.dispatch(command("abort", 9), (e) => events.push(e));
  assert.equal(getFake().aborted, true);
  await new Promise((resolve) => setImmediate(resolve));
});

test("rejects stale generation and active close", async () => {
  const { instance } = runtime(true);
  const sink = () => {};
  await instance.dispatch(command("open_session", 1), sink);
  await instance.dispatch(command("prompt", 2, { context: context() }), sink);
  const stale = { ...command("get_state", 3), session_generation: 2 };
  assert.equal((await instance.dispatch(stale, sink)).success, false);
  const close = await instance.dispatch(command("close_session", 4), sink);
  assert.equal(close.success, false);
  assert.match(close.error, /abort/);
  await instance.dispatch(command("abort", 5), sink);
  await new Promise((resolve) => setImmediate(resolve));
});
