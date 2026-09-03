import assert from "node:assert/strict";
import test from "node:test";
import { normalizeAction } from "../src/protocol.mjs";
import { RunLease } from "../src/run-lease.mjs";
import { parseSessionCommand } from "../src/session-protocol.mjs";
import { SessionRuntime } from "../src/session-runtime.mjs";

class FakeAgent {
  constructor(onPlan, blocking = false, submitPlan = true) {
    this.onPlan = onPlan;
    this.blocking = blocking;
    this.submitPlan = submitPlan;
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
    if (this.submitPlan) {
      this.onPlan(normalizeAction({ action: "hold", reason: "safe replay" }));
    }
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

  async waitForIdle() {}

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

function runtime(blocking = false, runLease = new RunLease(), submitPlan = true) {
  let fake;
  const instance = new SessionRuntime({
    plannerMeta: { provider: "test", model: "test" },
    createAgent: ({ onPlan, onSearchEvent }) => {
      fake = new FakeAgent(onPlan, blocking, submitPlan);
      fake.onSearchEvent = onSearchEvent;
      return fake;
    },
    runLease,
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

test("reports an upstream turn that ends without a next plan", async () => {
  const { instance } = runtime(false, new RunLease(), false);
  const events = [];
  await instance.dispatch(command("open_session", 1), (event) => events.push(event));
  await instance.dispatch(
    command("prompt", 2, { context: context() }),
    (event) => events.push(event),
  );
  await new Promise((resolve) => setImmediate(resolve));
  const error = events.find((event) => event.event === "agent_error");
  assert.match(error.data.error, /没有提交下一步计划/u);
  assert.equal(events.some((event) => event.event === "plan_proposed"), false);
});

test("forwards only real upstream thinking events and preserves streaming whitespace", async () => {
  const { instance, getFake } = runtime(true);
  const events = [];
  await instance.dispatch(command("open_session", 1), (event) => events.push(event));
  await instance.dispatch(
    command("prompt", 2, { context: context() }),
    (event) => events.push(event),
  );
  await new Promise((resolve) => setImmediate(resolve));
  const fake = getFake();
  const assistant = { role: "assistant", content: [] };
  fake.emit({
    type: "message_update",
    message: assistant,
    assistantMessageEvent: { type: "thinking_start", contentIndex: 0 },
  });
  fake.emit({
    type: "message_update",
    message: assistant,
    assistantMessageEvent: {
      type: "thinking_delta",
      contentIndex: 0,
      delta: "先核对候选。\n再检查字节上限。",
    },
  });
  fake.emit({
    type: "message_update",
    message: assistant,
    assistantMessageEvent: {
      type: "thinking_end",
      contentIndex: 0,
      content: "先核对候选。\n再检查字节上限。",
    },
  });
  assert.deepEqual(
    events.filter((event) => event.event.startsWith("thinking_")),
    [
      {
        protocol_version: 1,
        session_generation: 3,
        type: "event",
        event: "thinking_start",
        data: { request_id: 9 },
      },
      {
        protocol_version: 1,
        session_generation: 3,
        type: "event",
        event: "thinking_delta",
        data: { request_id: 9, delta: "先核对候选。\n再检查字节上限。" },
      },
      {
        protocol_version: 1,
        session_generation: 3,
        type: "event",
        event: "thinking_end",
        data: { request_id: 9 },
      },
    ],
  );
  await instance.dispatch(command("abort", 3), (event) => events.push(event));
  await new Promise((resolve) => setImmediate(resolve));
});

test("does not invent thinking events when the upstream emits none", async () => {
  const { instance } = runtime();
  const events = [];
  await instance.dispatch(command("open_session", 1), (event) => events.push(event));
  await instance.dispatch(
    command("prompt", 2, { context: context() }),
    (event) => events.push(event),
  );
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(events.some((event) => event.event.startsWith("thinking_")), false);
});

test("forwards bounded web search lifecycle events with the active request", async () => {
  const { instance, getFake } = runtime(true);
  const events = [];
  await instance.dispatch(command("open_session", 1), (event) => events.push(event));
  await instance.dispatch(
    command("prompt", 2, { context: context() }),
    (event) => events.push(event),
  );
  await new Promise((resolve) => setImmediate(resolve));
  await getFake().onSearchEvent({ phase: "start", query: "current SDR facts" });
  await getFake().onSearchEvent({
    phase: "end",
    query: "current SDR facts",
    count: 1,
    sources: [{ title: "Source", url: "https://example.com" }],
    truncated: false,
  });
  assert.deepEqual(
    events.filter((event) => event.event.startsWith("web_search_")),
    [
      {
        protocol_version: 1,
        session_generation: 3,
        type: "event",
        event: "web_search_start",
        data: { request_id: 9, phase: "start", query: "current SDR facts" },
      },
      {
        protocol_version: 1,
        session_generation: 3,
        type: "event",
        event: "web_search_end",
        data: {
          request_id: 9,
          phase: "end",
          query: "current SDR facts",
          count: 1,
          sources: [{ title: "Source", url: "https://example.com" }],
          truncated: false,
        },
      },
    ],
  );
  await instance.dispatch(command("abort", 3), (event) => events.push(event));
  await new Promise((resolve) => setImmediate(resolve));
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

test("correlates a completed follow-up without reporting the original request missing", async () => {
  const { instance, getFake } = runtime(true);
  const events = [];
  await instance.dispatch(command("open_session", 1), (event) => events.push(event));
  await instance.dispatch(
    command("prompt", 2, { context: context(3, 9, "first") }),
    (event) => events.push(event),
  );
  await new Promise((resolve) => setImmediate(resolve));
  await instance.dispatch(
    command("follow_up", 3, { context: context(3, 10, "second") }),
    (event) => events.push(event),
  );
  const fake = getFake();
  fake.emit({ type: "message_start", message: userMessage(JSON.stringify(context(3, 10, "second"))) });
  fake.onPlan(normalizeAction({ action: "hold", reason: "follow-up complete" }));
  fake.resolveRun();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(
    events.filter((event) => event.event === "plan_proposed").map((event) => event.data.request_id),
    [9, 10],
  );
  assert.equal(events.some((event) => event.event === "agent_error"), false);
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

test("disposing an active run does not emit an undefined generation", async () => {
  const lease = new RunLease();
  const { instance } = runtime(true, lease);
  const events = [];
  await instance.dispatch(command("open_session", 1), (event) => events.push(event));
  await instance.dispatch(command("prompt", 2, { context: context() }), (event) => events.push(event));
  await new Promise((resolve) => setImmediate(resolve));
  await instance.dispose();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(events.every((event) => Number.isSafeInteger(event.session_generation)), true);
  assert.equal(lease.state().busy, false);
});

test("shares one inference lease with the one-shot planner", async () => {
  const lease = new RunLease();
  const releasePlanner = lease.acquire("one_shot_planner");
  const { instance } = runtime(false, lease);
  const sink = () => {};
  await instance.dispatch(command("open_session", 1), sink);
  const blocked = await instance.dispatch(command("prompt", 2, { context: context() }), sink);
  assert.equal(blocked.success, false);
  assert.match(blocked.error, /busy/);
  releasePlanner();
  const accepted = await instance.dispatch(command("prompt", 3, { context: context() }), sink);
  assert.equal(accepted.success, true);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(lease.state().busy, false);
});
