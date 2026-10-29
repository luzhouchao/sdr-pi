import { createServer } from "node:http";
import { once } from "node:events";

export async function planningUpstream({api="openai-completions",spark=false,hang=false,plan={ action: "hold", reason: "SDK compatibility check" }}={}) {
  const requests = [];
  const upstream = createServer(async (req, res) => {
    let body = "";
    for await (const chunk of req) body += chunk;
    const payload = JSON.parse(body);
    requests.push({ url: req.url, payload });
    if (hang) return;
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    const event = (value) => res.write(`data: ${JSON.stringify(value)}\n\n`);
    const args = JSON.stringify(plan);
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
  return {upstream,requests};
}
