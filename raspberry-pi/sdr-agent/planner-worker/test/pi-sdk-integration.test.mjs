import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { connect } from "node:net";
import { join } from "node:path";
import { createInterface } from "node:readline";
import test from "node:test";

// Exercise main.mjs with the installed Pi SDK and real HTTP/SSE transports.
// The upstream is local and has no hardware or real provider credentials.
async function fixture(t, { api = "openai-completions", spark = false, hang = false } = {}) {
  const tempRoot = process.env.TMPDIR || "/var/tmp/sdrharness-dev";
  mkdirSync(tempRoot, { recursive: true, mode: 0o700 });
  const root = mkdtempSync(join(tempRoot, "pi-sdk-"));
  const socketRoot = `/run/user/${process.getuid()}/sdr-agent`;
  mkdirSync(socketRoot, { recursive: true, mode: 0o700 });
  const suffix = root.split("/").at(-1);
  const plannerPath = `${socketRoot}/${suffix}-plan.sock`;
  const sessionPath = `${socketRoot}/${suffix}-session.sock`;
  const requests = [];
  const upstream = createServer(async (req, res) => {
    let body = "";
    for await (const chunk of req) body += chunk;
    const payload = JSON.parse(body);
    requests.push({ url: req.url, payload });
    if (hang) return;
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    const event = (value) => res.write(`data: ${JSON.stringify(value)}\n\n`);
    const args = JSON.stringify({ action: "hold", reason: "SDK compatibility check" });
    if (api === "openai-responses") {
      const item = { type: "function_call", id: "fc_1", call_id: "call_1", name: "submit_plan", arguments: args };
      event({ type: "response.created", response: { id: "resp_1", model: "test-model", status: "in_progress", output: [] } });
      event({ type: "response.output_item.added", output_index: 0, item: { ...item, arguments: "" } });
      event({ type: "response.function_call_arguments.delta", output_index: 0, item_id: "fc_1", delta: args });
      event({ type: "response.output_item.done", output_index: 0, item });
      event({ type: "response.completed", response: { id: "resp_1", model: "test-model", status: "completed", output: [item], usage: { input_tokens: 10, output_tokens: 10, total_tokens: 20 } } });
    } else {
      event({ id: "chat_1", object: "chat.completion.chunk", model: "test-model", choices: [{ index: 0,
        delta: spark ? { role: "assistant", content: args } : { role: "assistant", tool_calls: [{ index: 0, id: "call_1", type: "function", function: { name: "submit_plan", arguments: args } }] }, finish_reason: null }] });
      event({ id: "chat_1", object: "chat.completion.chunk", model: "test-model", choices: [{ index: 0, delta: {}, finish_reason: spark ? "stop" : "tool_calls" }] });
      res.write("data: [DONE]\n\n");
    }
    res.end();
  });
  upstream.listen(0, "127.0.0.1");
  await once(upstream, "listening");
  const child = spawn(process.execPath, [new URL("../src/main.mjs", import.meta.url).pathname], {
    env: { ...process.env,
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
  const context = JSON.parse(readFileSync(new URL("../../../../jetson-agx/sdrharness/config/request.json", import.meta.url)));
  return { plannerPath, sessionPath, requests, context };
}

async function client(path, t) {
  const socket = connect(path);
  t.after(() => socket.destroy());
  await once(socket, "connect");
  const lines = createInterface({ input: socket })[Symbol.asyncIterator]();
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
        return JSON.parse(line.value);
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
    protocol_version: 1, command_id, session_generation: 1, type, ...extra,
  });
  send("open_session", 1);
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
  do { frame = await c.next(); } while (frame.type !== "response");
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
  const send = (type, extra = {}) => c.send({ protocol_version: 1, command_id: ++id, session_generation: 1, type, ...extra });
  send("open_session"); assert.equal((await c.next()).success, true);
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
