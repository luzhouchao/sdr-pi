import assert from "node:assert/strict";
import test from "node:test";
import { AssistantMessageEventStream } from "@earendil-works/pi-ai";
import {
  createSparkJsonPlanningStream,
  prepareSparkJsonPayload,
} from "../src/spark-stream.mjs";

const usage = {
  input: 10,
  output: 5,
  cacheRead: 0,
  cacheWrite: 0,
  totalTokens: 15,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
};

test("prepares a constrained local Spark payload without native tools", () => {
  const payload = {
    model: "spark-x2.5-4b",
    messages: [
      { role: "system", content: "system" },
      {
        role: "user",
        content: [
          { type: "text", text: "first" },
          { type: "text", text: "second" },
        ],
      },
    ],
    tools: [{ type: "function" }],
    tool_choice: "auto",
    stream: true,
  };
  const schema = { type: "object", properties: { action: { const: "hold" } } };
  const next = prepareSparkJsonPayload(payload, schema);
  assert.equal(next.messages[1].content, "first\nsecond");
  assert.match(next.messages[0].content, /LOCAL STRUCTURED OUTPUT ADAPTER/u);
  assert.equal(next.temperature, 0);
  assert.equal(next.chat_template_kwargs.enable_thinking, false);
  assert.deepEqual(next.response_format.json_schema.schema, schema);
  assert.equal(Object.hasOwn(next, "tools"), false);
  assert.equal(Object.hasOwn(next, "tool_choice"), false);
  assert.ok(Array.isArray(payload.messages[1].content));
});

test("converts constrained Spark JSON into the sole Agent tool call", async () => {
  let capturedContext;
  let capturedPayload;
  const baseStream = (_model, context, options) => {
    capturedContext = context;
    capturedPayload = options.onPayload({
      model: "spark-x2.5-4b",
      messages: [{ role: "system", content: "system" }],
      tools: [{ type: "function" }],
    });
    return completedTextStream('{"action":"hold","reason":"你好"}');
  };
  const streamFn = createSparkJsonPlanningStream(baseStream);
  const result = await streamFn(
    { api: "openai-completions", provider: "spark-local", id: "spark-x2.5-4b" },
    {
      systemPrompt: "system",
      messages: [],
      tools: [{ name: "submit_plan", parameters: { type: "object" } }],
    },
  ).result();

  assert.deepEqual(capturedContext.tools, []);
  assert.equal(Object.hasOwn(capturedPayload, "tools"), false);
  assert.equal(result.stopReason, "toolUse");
  assert.equal(result.content.length, 1);
  assert.equal(result.content[0].name, "submit_plan");
  assert.deepEqual(result.content[0].arguments, { action: "hold", reason: "你好" });
  assert.deepEqual(result.usage, usage);
});

function completedTextStream(text) {
  const stream = new AssistantMessageEventStream();
  const message = {
    role: "assistant",
    content: [{ type: "text", text }],
    api: "openai-completions",
    provider: "spark-local",
    model: "spark-x2.5-4b",
    usage,
    stopReason: "stop",
    timestamp: Date.now(),
  };
  stream.push({ type: "done", reason: "stop", message });
  stream.end();
  return stream;
}
