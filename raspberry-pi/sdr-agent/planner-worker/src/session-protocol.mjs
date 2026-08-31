// Command vocabulary is adapted from earendil-works/pi RPC mode at commit
// 853a80d26c90a14c1886f0ebb8ffaae133ca2185 under the MIT License.
// Copyright (c) 2025 Mario Zechner. This implementation is SDR-specific.

import { MAX_FRAME_BYTES, parseRequest } from "./protocol.mjs";

export const SESSION_PROTOCOL_VERSION = 1;
export const MAX_SESSION_QUEUE = 4;

const CONTEXT_COMMANDS = new Set(["prompt", "steer", "follow_up"]);
const SIMPLE_COMMANDS = new Set([
  "open_session",
  "abort",
  "clear_queue",
  "get_state",
  "close_session",
]);

export function parseSessionCommand(frame) {
  if (Buffer.byteLength(frame, "utf8") > MAX_FRAME_BYTES) {
    throw new Error("session command frame exceeds 32 KiB");
  }
  const command = JSON.parse(frame);
  requirePlainObject(command, "session command");
  requireSafeInteger(command.protocol_version, "protocol_version", 1);
  if (command.protocol_version !== SESSION_PROTOCOL_VERSION) {
    throw new Error("unsupported session protocol version");
  }
  requireSafeInteger(command.command_id, "command_id", 1);
  requireSafeInteger(command.session_generation, "session_generation", 0);
  if (typeof command.type !== "string") {
    throw new Error("session command type is required");
  }

  if (CONTEXT_COMMANDS.has(command.type)) {
    requireExactKeys(
      command,
      ["protocol_version", "command_id", "session_generation", "type", "context"],
      "session command",
    );
    requirePlainObject(command.context, "context");
    const context = parseRequest(JSON.stringify(command.context));
    if (context.session_generation !== command.session_generation) {
      throw new Error("context belongs to a different session generation");
    }
    return { ...command, context };
  }

  if (SIMPLE_COMMANDS.has(command.type)) {
    requireExactKeys(
      command,
      ["protocol_version", "command_id", "session_generation", "type"],
      "session command",
    );
    return command;
  }

  throw new Error(`unsupported session command: ${command.type}`);
}

export function makeSessionResponse(command, success, dataOrError) {
  const response = {
    protocol_version: SESSION_PROTOCOL_VERSION,
    command_id: Number.isSafeInteger(command?.command_id) ? command.command_id : 0,
    session_generation: Number.isSafeInteger(command?.session_generation)
      ? command.session_generation
      : 0,
    type: "response",
    command: typeof command?.type === "string" ? command.type : "unknown",
    success,
  };
  if (success) {
    if (dataOrError !== undefined) response.data = dataOrError;
  } else {
    response.error = boundedText(dataOrError, 512, "session command failed");
  }
  return response;
}

export function makeSessionEvent(sessionGeneration, event, data = undefined) {
  requireSafeInteger(sessionGeneration, "session_generation", 0);
  if (typeof event !== "string" || event.length === 0 || event.length > 64) {
    throw new Error("invalid session event name");
  }
  const frame = {
    protocol_version: SESSION_PROTOCOL_VERSION,
    session_generation: sessionGeneration,
    type: "event",
    event,
  };
  if (data !== undefined) frame.data = data;
  return frame;
}

export function boundedText(value, maximumBytes, fallback) {
  const source = value instanceof Error ? value.message : String(value ?? "");
  const cleaned = source.replace(/[\r\n\u0000-\u001f\u007f]+/gu, " ").trim();
  if (!cleaned) return fallback;
  let output = cleaned;
  while (Buffer.byteLength(output, "utf8") > maximumBytes) {
    output = output.slice(0, -1);
  }
  return output || fallback;
}

function requireExactKeys(value, keys, label) {
  const expected = new Set(keys);
  for (const key of Object.keys(value)) {
    if (!expected.has(key)) throw new Error(`${label} contains unknown field ${key}`);
  }
  for (const key of keys) {
    if (!Object.hasOwn(value, key)) throw new Error(`${label} is missing field ${key}`);
  }
}

function requirePlainObject(value, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
}

function requireSafeInteger(value, label, minimum) {
  if (!Number.isSafeInteger(value) || value < minimum) {
    throw new Error(`${label} must be a safe integer >= ${minimum}`);
  }
}
