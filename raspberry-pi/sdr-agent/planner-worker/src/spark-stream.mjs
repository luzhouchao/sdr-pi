import { randomUUID } from "node:crypto";
import { AssistantMessageEventStream } from "@earendil-works/pi-ai";

export function createSparkJsonPlanningStream(baseStream) {
  return (model, context, options = {}) => {
    const stream = new AssistantMessageEventStream();
    void runSparkJsonPlanningStream(stream, baseStream, model, context, options);
    return stream;
  };
}

export function prepareSparkJsonPayload(payload, parameters) {
  const messages = flattenPureTextMessages(payload.messages).map(
    (message, index) => {
      if (
        index !== 0 ||
        message?.role !== "system" ||
        typeof message.content !== "string"
      ) {
        return message;
      }
      return {
        ...message,
        content: `${message.content}\n\n[LOCAL STRUCTURED OUTPUT ADAPTER]\nReturn only the JSON object matching the response schema. The adapter will convert it into the submit_plan tool call.`,
      };
    },
  );
  const next = {
    ...payload,
    messages,
    chat_template_kwargs: {
      ...payload.chat_template_kwargs,
      enable_thinking: false,
    },
    temperature: 0,
    response_format: {
      type: "json_schema",
      json_schema: {
        name: "submit_plan",
        strict: true,
        schema: parameters,
      },
    },
  };
  delete next.tools;
  delete next.tool_choice;
  delete next.parallel_tool_calls;
  return next;
}

async function runSparkJsonPlanningStream(stream, baseStream, model, context, options) {
  const output = makeAssistantMessage(model);
  try {
    const submitPlan = context.tools?.find((tool) => tool.name === "submit_plan");
    if (submitPlan === undefined || context.tools.length !== 1) {
      throw new Error("Spark planner requires exactly one submit_plan tool");
    }
    const inner = baseStream(
      model,
      { ...context, tools: [] },
      {
        ...options,
        onPayload: (payload) => prepareSparkJsonPayload(payload, submitPlan.parameters),
      },
    );
    const result = await inner.result();
    if (result.stopReason === "error" || result.stopReason === "aborted") {
      throw new Error(result.errorMessage || `Spark request ${result.stopReason}`);
    }
    if (result.stopReason === "length") {
      throw new Error("Spark structured plan reached the output token limit");
    }
    const text = result.content
      .filter((block) => block.type === "text")
      .map((block) => block.text)
      .join("")
      .trim();
    const arguments_ = JSON.parse(text);
    if (arguments_ === null || typeof arguments_ !== "object" || Array.isArray(arguments_)) {
      throw new Error("Spark structured plan must be a JSON object");
    }

    output.usage = result.usage;
    output.responseId = result.responseId;
    output.responseModel = result.responseModel;
    stream.push({ type: "start", partial: output });
    const toolCall = {
      type: "toolCall",
      id: `spark-${randomUUID()}`,
      name: "submit_plan",
      arguments: arguments_,
    };
    output.content.push(toolCall);
    stream.push({ type: "toolcall_start", contentIndex: 0, partial: output });
    stream.push({
      type: "toolcall_delta",
      contentIndex: 0,
      delta: text,
      partial: output,
    });
    output.stopReason = "toolUse";
    output.rawStopReason = result.rawStopReason;
    stream.push({
      type: "toolcall_end",
      contentIndex: 0,
      toolCall,
      partial: output,
    });
    stream.push({ type: "done", reason: "toolUse", message: output });
    stream.end();
  } catch (error) {
    output.stopReason = options.signal?.aborted ? "aborted" : "error";
    output.errorMessage = error instanceof Error ? error.message : String(error);
    stream.push({
      type: "error",
      reason: output.stopReason,
      error: output,
    });
    stream.end();
  }
}

function flattenPureTextMessages(messages) {
  if (!Array.isArray(messages)) return [];
  return messages.map((message) => {
    if (
      message === null ||
      typeof message !== "object" ||
      !Array.isArray(message.content) ||
      !message.content.every(
        (part) => part?.type === "text" && typeof part.text === "string",
      )
    ) {
      return message;
    }
    return {
      ...message,
      content: message.content.map((part) => part.text).join("\n"),
    };
  });
}

function makeAssistantMessage(model) {
  return {
    role: "assistant",
    content: [],
    api: model.api,
    provider: model.provider,
    model: model.id,
    usage: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    },
    stopReason: "pending",
    timestamp: Date.now(),
  };
}
