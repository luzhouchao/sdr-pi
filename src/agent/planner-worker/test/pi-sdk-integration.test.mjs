import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { planningUpstream } from "../test-support/planning-upstream.mjs";
import { connect } from "node:net";
import { join } from "node:path";
import { createInterface } from "node:readline";
import test from "node:test";

// Exercise main.mjs with the installed Pi SDK and real HTTP/SSE transports.
// The upstream is local and has no hardware or real provider credentials.
async function fixture(t, { api = "openai-completions", spark = false, hang = false, plan } = {}) {
  const tempRoot = process.env.TMPDIR || "/var/tmp/sdrharness-dev";
  mkdirSync(tempRoot, { recursive: true, mode: 0o700 });
  const root = mkdtempSync(join(tempRoot, "pi-sdk-"));
  const socketRoot = `/run/user/${process.getuid()}/sdr-agent`;
  mkdirSync(socketRoot, { recursive: true, mode: 0o700 });
  const suffix = root.split("/").at(-1);
  const plannerPath = `${socketRoot}/${suffix}-plan.sock`;
  const sessionPath = `${socketRoot}/${suffix}-session.sock`;
  const {upstream,requests} = await planningUpstream({api,spark,hang,...(plan ? {plan} : {})});
  const child = spawn(process.execPath, [new URL("../src/main.mjs", import.meta.url).pathname], {
    env: { ...process.env,
      SDR_DURABLE_STATE_DIR: join(root, "durable"),
      SDR_PLANNER_API: api, SDR_PLANNER_BASE_URL: `http://127.0.0.1:${upstream.address().port}/v1`,
      SDR_PLANNER_API_KEY: "sdk-test-key", SDR_PLANNER_API_KEY_FILE: "",
      SDR_PLANNER_PROVIDER: spark ? "spark-local" : "sdk-test", SDR_PLANNER_MODEL: "test-model",
      SDR_PLANNER_PROVIDER_CONFIG: join(root, "absent.json"), SDR_PLANNER_TIMEOUT_MS: "1000",
      SDR_PLANNER_WEB_SEARCH_URL: "", SDR_PLANNER_SOCKET: plannerPath, SDR_SESSION_SOCKET: sessionPath,
    }, stdio: ["ignore", "ignore", "pipe"],
  });
  t.after(async () => {
    if (child.exitCode === null && child.signalCode === null) {
      const exited = once(child, "exit"); child.kill("SIGTERM"); await exited;
    }
    upstream.closeAllConnections();
    await new Promise((resolve) => upstream.close(resolve));
    for (const path of [plannerPath, sessionPath, root]) rmSync(path, { recursive: true, force: true });
  });
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Planner startup deadline")), 5000);
    let log = "";
    child.stderr.on("data", (chunk) => {
      log += chunk;
      if (log.includes("session_ready")) { clearTimeout(timer); resolve(); }
    });
    child.once("exit", () => { clearTimeout(timer); reject(new Error(`Planner exited: ${log}`)); });
  });
  const context = JSON.parse(readFileSync(new URL("../../../../deploy/agx/config/request.json", import.meta.url)));
  return { plannerPath, sessionPath, requests, context };
}

test("durable session carries the monitoring threshold from structured model output", { timeout: 10_000 }, async (t) => {
  const plan={action:"start_task",mission:"监测两轮",target_sweeps:2,max_steps:2,max_seconds:60,max_iq_bytes:65536,min_freq_hz:2445000000,max_freq_hz:2465000000,monitor_threshold_db:15,monitor_interval_secs:5};
  const f=await fixture(t,{plan});
  const c=await client(f.sessionPath,t);
  c.send({protocol_version:2,command_id:1,session_generation:1,type:"open_session",app_session_id:"monitor_test",controller_epoch:"monitor_epoch"});
  assert.equal((await c.next()).success,true);
  c.send({protocol_version:2,command_id:2,session_generation:1,type:"prompt",context:f.context});
  let frame, proposal;
  do { frame=await c.next(); if(frame.event==="plan_proposed") proposal=frame.data; assert.notEqual(frame.event,"agent_error",JSON.stringify(frame)); } while(frame.event!=="agent_end");
  assert.equal(proposal.action.kind,"start_task");
  assert.equal(proposal.action.monitor_threshold_db,15);
  assert.equal(proposal.action.monitor_interval_secs,5);
});

async function client(path, t) {
  const socket = connect(path);
  t.after(() => socket.destroy());
  await once(socket, "connect");
  const lines = createInterface({ input: socket })[Symbol.asyncIterator]();
  let ackId = 1000;
  return {
    socket,
    send: (value) => socket.write(`${JSON.stringify(value)}\n`),
    async next() {
      let timer;
      try {
        const line = await Promise.race([lines.next(), new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error("Planner frame deadline")), 5000);
        })]);
        assert.equal(line.done, false);
        const frame = JSON.parse(line.value);
        if (frame.event === "plan_proposed" && frame.delivery) {
          socket.write(JSON.stringify({protocol_version:2,command_id:ackId++,session_generation:frame.session_generation,
            type:"plan_ack",plan_id:frame.delivery.plan_id,hash:frame.delivery.hash,state:"accepted"})+"\n");
        }
        return frame;
      } finally { clearTimeout(timer); }
    },
  };
}

for (const options of [{}, { spark: true }, { api: "openai-responses" }]) {
  test(`real Pi SDK submits exactly one plan: ${JSON.stringify(options)}`, { timeout: 10_000 }, async (t) => {
    const f = await fixture(t, options);
    const c = await client(f.plannerPath, t);
    c.send(f.context);
    const response = await c.next();
    assert.equal(response.status, "ok", JSON.stringify(response));
    assert.equal(response.action.kind, "hold");
    assert.equal(response.request_id, f.context.request_id);
    assert.equal(f.requests.length, 1, "terminate must prevent another model turn");
    const { payload } = f.requests[0];
    if (options.spark) {
      assert.equal(payload.tools, undefined);
      assert.equal(payload.tool_choice, undefined);
      assert.equal(payload.response_format.type, "json_schema");
      assert.match(payload.messages[0].content, /LOCAL STRUCTURED OUTPUT ADAPTER/);
    } else {
      assert.equal(payload.tools.length, 1);
      assert.equal(payload.tool_choice.type, "function");
    }
  });
}

test("real Pi session emits a correlated plan and can close after settling", { timeout: 10_000 }, async (t) => {
  const f = await fixture(t, { spark: true });
  const c = await client(f.sessionPath, t);
  const send = (type, command_id, extra = {}) => c.send({
    protocol_version: 2, command_id, session_generation: 1, type, ...extra,
  });
  send("open_session", 1, {app_session_id:"sdk_session",controller_epoch:"sdk_epoch"});
  assert.equal((await c.next()).success, true);
  send("prompt", 2, { context: f.context });
  const plans = [];
  let frame;
  do {
    frame = await c.next();
    if (frame.event === "plan_proposed") plans.push(frame.data);
    assert.notEqual(frame.event, "agent_error", JSON.stringify(frame));
  } while (frame.event !== "agent_end");
  assert.equal(plans.length, 1);
  assert.equal(plans[0].request_id, f.context.request_id);
  assert.equal(plans[0].session_generation, 1);
  assert.equal(plans[0].action.kind, "hold");
  send("close_session", 3);
  do { frame = await c.next(); } while (frame.type !== "response" || frame.command_id !== 3);
  assert.equal(frame.success, true);
  assert.equal(frame.data.closed, true);
  assert.equal(f.requests.length, 1);
});

test("real Pi timeout releases inference lease and never submits a plan", { timeout: 10_000 }, async (t) => {
  const f = await fixture(t, { hang: true });
  const c = await client(f.plannerPath, t);
  c.send(f.context);
  const response = await c.next();
  assert.equal(response.status, "unavailable");
  assert.match(JSON.stringify(response), /timed out/);
  assert.equal(response.action, undefined);
  const again = await client(f.plannerPath, t);
  again.send({ ...f.context, request_id: 2 });
  assert.match(JSON.stringify(await again.next()), /timed out/);
  assert.equal(f.requests.length, 2);
});

test("real Pi session abort and disconnect release ownership without a plan", { timeout: 10_000 }, async (t) => {
  const f = await fixture(t, { hang: true });
  const c = await client(f.sessionPath, t);
  let id = 0;
  const send = (type, extra = {}) => c.send({ protocol_version: 2, command_id: ++id, session_generation: 1, type, ...extra });
  send("open_session",{app_session_id:"abort_session",controller_epoch:"abort_epoch"}); assert.equal((await c.next()).success, true);
  send("prompt", { context: f.context });
  let response;
  do { response = await c.next(); } while (response.type !== "response");
  assert.equal(response.success, true);
  for (const type of ["steer", "follow_up"]) {
    send(type, { context: { ...f.context, request_id: id + 1 } });
    do { response = await c.next(); assert.notEqual(response.event, "plan_proposed"); } while (response.type !== "response");
    assert.equal(response.success, true);
  }
  send("abort");
  do { response = await c.next(); assert.notEqual(response.event, "plan_proposed"); } while (response.type !== "response");
  assert.equal(response.success, true);
  c.socket.end();
  await once(c.socket, "close");
  // A one-shot request after disconnect also proves the shared run lease is free.
  const oneShot = await client(f.plannerPath, t);
  oneShot.send(f.context);
  assert.match(JSON.stringify(await oneShot.next()), /timed out/);
});

test("recorded empty-sweep feedback and bounded cruise progress reach the actual SDK payload", {timeout: 10000}, async t => {
  const f = await fixture(t);
  const trace = JSON.parse(readFileSync(new URL("../../../../docs/evidence/PI_DURABLE_CRUISE_REVIEW_2026-10-27.json", import.meta.url)));
  f.context.observation = trace.steps[4].input.observation;
  f.context.cruise = {remaining_steps: 4, remaining_ms: 80000, remaining_iq_bytes: 753664,
    local_sweep_limit: 3, empty_sweep_limit: 3, consecutive_empty_sweeps: 1,
    recent_sweeps: [{start_hz: 2450250000, stop_hz: 2451250000, candidate_count: 0}],
    history_truncated: false};
  const c = await client(f.plannerPath, t);c.send(f.context);
  const response = await c.next();assert.equal(response.status, "ok");
  assert.equal(f.requests.length,1);
  const payload = f.requests[0].payload;
  const user = payload.messages.filter(m => m.role === "user").at(-1);
  const text = typeof user.content === "string" ? user.content : user.content.filter(x => x.type === "text").map(x => x.text).join("");
  const received = JSON.parse(text);
  assert.deepEqual(received.cruise, f.context.cruise);
  assert.deepEqual(received.observation.latest_sweep.points, f.context.observation.latest_sweep.points);
  assert.match(payload.messages[0].content, /NOT independent measured noise/u);
  assert.match(payload.messages[0].content, /choose a disjoint adjacent tuning-center/u);
  assert.doesNotMatch(text, /data_path|metadata_path|logits|thinkingSignature/u);
});
