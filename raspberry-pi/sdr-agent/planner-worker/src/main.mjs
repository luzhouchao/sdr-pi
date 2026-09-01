import { readFileSync, chmodSync, existsSync, lstatSync, unlinkSync } from "node:fs";
import { createServer } from "node:net";
import { join } from "node:path";
import { Agent } from "@earendil-works/pi-agent-core";
import { createModels, createProvider } from "@earendil-works/pi-ai";
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";
import { openAIResponsesApi } from "@earendil-works/pi-ai/api/openai-responses.lazy";
import { Type } from "typebox";
import { loadProviderSelection } from "./provider-config.mjs";
import { validateRuntimeSocketPath } from "./runtime-path.mjs";
import { RunLease } from "./run-lease.mjs";
import { SessionRuntime } from "./session-runtime.mjs";
import { startSessionServer } from "./session-server.mjs";
import {
  MAX_FRAME_BYTES,
  makeErrorResponse,
  makeResponse,
  normalizeAction,
  parseRequest,
  requireSubmitPlan,
} from "./protocol.mjs";

const config = loadConfig();
const defaultPlannerMeta = { provider: config.provider, model: config.model };
const runLease = new RunLease();

prepareSocket(config.socketPath);
const server = createServer((socket) => {
  socket.setTimeout(config.requestTimeoutMs + 2_000);
  socket.setNoDelay(true);
  let frame = Buffer.alloc(0);
  let handled = false;

  socket.on("data", (chunk) => {
    if (handled) return;
    frame = Buffer.concat([frame, chunk]);
    if (frame.length > MAX_FRAME_BYTES + 1) {
      handled = true;
      writeResponse(socket, makeErrorResponse(undefined, defaultPlannerMeta, "error", "request frame exceeds 32 KiB"));
      return;
    }
    const newline = frame.indexOf(0x0a);
    if (newline < 0) return;
    handled = true;
    if (newline !== frame.length - 1) {
      writeResponse(socket, makeErrorResponse(undefined, defaultPlannerMeta, "error", "one request per connection is required"));
      return;
    }
    handleFrame(frame.subarray(0, newline).toString("utf8"))
      .then((response) => writeResponse(socket, response))
      .catch((error) => writeResponse(socket, makeErrorResponse(undefined, defaultPlannerMeta, "error", error)));
  });
  socket.on("timeout", () => socket.destroy());
  socket.on("error", (error) => process.stderr.write(`planner_socket_error=${safeMessage(error)}\n`));
});
server.maxConnections = 8;
server.listen(config.socketPath, () => {
  chmodSync(config.socketPath, 0o660);
  process.stderr.write(`planner_ready socket=${config.socketPath} provider_config=${config.providerConfigPath}\n`);
});

const sessionServer = startSessionServer({
  socketPath: config.sessionSocketPath,
  createRuntime: () =>
    new SessionRuntime({
      plannerMeta: defaultPlannerMeta,
      runLease,
      createAgent: ({ sessionGeneration, onPlan }) =>
        createPlanningAgent({
          sessionGeneration,
          onPlan,
          terminateAfterPlan: false,
        }),
    }),
  onError: (error) => process.stderr.write(`session_socket_error=${safeMessage(error)}\n`),
});
sessionServer.on("listening", () => {
  process.stderr.write(`session_ready socket=${config.sessionSocketPath}\n`);
});

async function handleFrame(frame) {
  let request;
  try {
    request = parseRequest(frame);
  } catch (error) {
    return makeErrorResponse(request, defaultPlannerMeta, "error", error);
  }

  const releaseRun = runLease.acquire("one_shot_planner");
  if (releaseRun === undefined) {
    return makeErrorResponse(request, defaultPlannerMeta, "unavailable", "planner is busy");
  }

  const submittedPlans = [];
  let runtime;
  try {
    runtime = createPlanningAgent({
      sessionGeneration: request.session_generation,
      terminateAfterPlan: true,
      onPlan: (action) => {
        if (submittedPlans.length !== 0) {
          throw new Error("only one plan may be submitted");
        }
        submittedPlans.push(action);
      },
    });
  } catch (error) {
    releaseRun();
    return makeErrorResponse(request, defaultPlannerMeta, "unavailable", error);
  }

  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    runtime.agent.abort();
  }, config.requestTimeoutMs);
  try {
    await runtime.agent.prompt(JSON.stringify(request));
  } catch (error) {
    return makeErrorResponse(request, runtime.plannerMeta, timedOut ? "unavailable" : "error", error);
  } finally {
    clearTimeout(timer);
    releaseRun();
  }
  if (timedOut) {
    return makeErrorResponse(request, runtime.plannerMeta, "unavailable", "planner request timed out");
  }
  if (submittedPlans.length !== 1) {
    return makeErrorResponse(request, runtime.plannerMeta, "error", "model did not submit exactly one plan");
  }
  return makeResponse(request, runtime.plannerMeta, submittedPlans[0]);
}

function createPlanningAgent({ sessionGeneration, onPlan, terminateAfterPlan }) {
  const providerConfig = loadProviderSelection(config);
  const plannerMeta = { provider: providerConfig.provider, model: providerConfig.model };
  const models = createModels();
  const model = {
    id: providerConfig.model,
    name: providerConfig.model,
    api: providerConfig.api,
    provider: providerConfig.provider,
    baseUrl: providerConfig.baseUrl,
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: config.contextWindow,
    maxTokens: config.maxTokens,
    compat: providerConfig.api === "openai-completions"
      ? {
          supportsStore: false,
          supportsDeveloperRole: false,
          supportsReasoningEffort: false,
          supportsUsageInStreaming: false,
          supportsStrictMode: false,
          maxTokensField: "max_tokens",
        }
      : {
          supportsStore: false,
          supportsStrictMode: false,
        },
  };
  const providerApi = providerConfig.api === "openai-responses"
    ? openAIResponsesApi()
    : openAICompletionsApi();
  models.setProvider(
    createProvider({
      id: providerConfig.provider,
      name: "SDR upstream planner",
      baseUrl: providerConfig.baseUrl,
      auth: {
        apiKey: {
          name: "SDR planner API key",
          resolve: async ({ signal }) => {
            signal.throwIfAborted();
            return {
              auth: { apiKey: providerConfig.apiKey },
              source: providerConfig.apiKeySource,
            };
          },
        },
      },
      models: [model],
      api: providerApi,
    }),
  );
  const submitPlan = {
    name: "submit_plan",
    label: "Submit SDR plan",
    description: "Submit exactly one structured SDR action proposal to the deterministic Rust controller.",
    executionMode: "sequential",
    parameters: Type.Object({
      action: Type.Union([
        Type.Literal("hold"),
        Type.Literal("survey_band"),
        Type.Literal("inspect_candidate"),
        Type.Literal("capture_bounded_iq"),
        Type.Literal("run_local_recognition"),
        Type.Literal("stop_session"),
      ]),
      reason: Type.Optional(Type.String({ maxLength: 256 })),
      candidate_id: Type.Optional(Type.String({ maxLength: 64 })),
      start_hz: Type.Optional(Type.Integer({ minimum: 1 })),
      stop_hz: Type.Optional(Type.Integer({ minimum: 1 })),
      step_hz: Type.Optional(Type.Integer({ minimum: 1 })),
      center_hz: Type.Optional(Type.Integer({ minimum: 1 })),
      bandwidth_hz: Type.Optional(Type.Integer({ minimum: 1 })),
      sample_rate_hz: Type.Optional(Type.Integer({ minimum: 1 })),
      rf_bandwidth_hz: Type.Optional(Type.Integer({ minimum: 1 })),
      dwell_ms: Type.Optional(Type.Integer({ minimum: 1 })),
      samples: Type.Optional(Type.Integer({ minimum: 1 })),
    }),
    execute: async (_toolCallId, params) => {
      onPlan(normalizeAction(params));
      return {
        content: [{ type: "text", text: "Plan submitted for deterministic validation." }],
        details: {},
        terminate: terminateAfterPlan,
      };
    },
  };

  const agent = new Agent({
    initialState: {
      systemPrompt: SYSTEM_PROMPT,
      model,
      thinkingLevel: "off",
      tools: [submitPlan],
      messages: [],
    },
    streamFn: models.streamSimple.bind(models),
    onPayload: (payload) => requireSubmitPlan(payload, providerConfig.api),
    toolExecution: "sequential",
    sessionId: `sdr-${sessionGeneration}`,
    beforeToolCall: async ({ toolCall }) => {
      if (toolCall.name !== "submit_plan") {
        return { block: true, reason: "tool is not allowed", terminate: true };
      }
      return undefined;
    },
  });
  return { agent, plannerMeta };
}

function loadConfig() {
  const baseUrl = requiredEnv("SDR_PLANNER_BASE_URL").replace(/\/$/u, "");
  if (!/^https?:\/\//u.test(baseUrl)) throw new Error("SDR_PLANNER_BASE_URL must be HTTP(S)");
  const credentialsDirectory = process.env.CREDENTIALS_DIRECTORY?.trim();
  const apiKeyFile = process.env.SDR_PLANNER_API_KEY_FILE ||
    (credentialsDirectory ? join(credentialsDirectory, "qwen-api-token") : undefined);
  const apiKey = process.env.SDR_PLANNER_API_KEY?.trim() ||
    (apiKeyFile ? readFileSync(apiKeyFile, "utf8").trim() : "");
  return {
    api: process.env.SDR_PLANNER_API || "openai-completions",
    baseUrl,
    apiKey,
    apiKeySource: apiKeyFile ? "credential file" : "environment API key",
    provider: process.env.SDR_PLANNER_PROVIDER || "qwen4090",
    model: process.env.SDR_PLANNER_MODEL || "qwen3.8-27b",
    providerConfigPath: process.env.SDR_PLANNER_PROVIDER_CONFIG ||
      "/var/lib/sdrharness/web-console/provider.json",
    socketPath: process.env.SDR_PLANNER_SOCKET || "/run/sdr-agent/planner.sock",
    sessionSocketPath: process.env.SDR_SESSION_SOCKET || "/run/sdr-agent/session.sock",
    contextWindow: boundedInteger("SDR_PLANNER_CONTEXT_WINDOW", 196_608, 8_192, 1_000_000),
    maxTokens: boundedInteger("SDR_PLANNER_MAX_TOKENS", 1_024, 128, 8_192),
    requestTimeoutMs: boundedInteger("SDR_PLANNER_TIMEOUT_MS", 30_000, 1_000, 120_000),
  };
}

function prepareSocket(socketPath) {
  validateRuntimeSocketPath(socketPath, "planner socket");
  if (!existsSync(socketPath)) return;
  if (!lstatSync(socketPath).isSocket()) {
    throw new Error("refusing to replace a non-socket planner path");
  }
  unlinkSync(socketPath);
}

function writeResponse(socket, response) {
  const frame = `${JSON.stringify(response)}\n`;
  if (Buffer.byteLength(frame, "utf8") > MAX_FRAME_BYTES + 1) {
    socket.end(`${JSON.stringify(makeErrorResponse(response, defaultPlannerMeta, "error", "response frame exceeds 32 KiB"))}\n`);
    return;
  }
  socket.end(frame);
}

function requiredEnv(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function boundedInteger(name, fallback, minimum, maximum) {
  const value = process.env[name] === undefined ? fallback : Number(process.env[name]);
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}`);
  }
  return value;
}

function safeMessage(error) {
  const message = error instanceof Error ? error.message : String(error);
  return message.replace(/[\r\n\u0000-\u001f\u007f]+/gu, " ").slice(0, 512);
}

const SYSTEM_PROMPT = `You are the planning module of a receive-only SDR agent.
The user message is a JSON PlanningContext from a deterministic Rust controller.
Choose exactly one conservative next action and call submit_plan exactly once.
Never claim that an action executed. Never invent candidates or capabilities.
Respect the supplied limits and health flags. When data is stale, capabilities
are missing, the instruction is ambiguous, or safety is uncertain, submit hold.
The Rust controller independently validates every proposal and owns all hardware.`;
