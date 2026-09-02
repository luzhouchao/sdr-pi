export const PROTOCOL_VERSION = 1;
export const MAX_FRAME_BYTES = 32 * 1024;
export const MAX_INSTRUCTION_BYTES = 1024;
export const MAX_CANDIDATES = 32;
export const MAX_SWEEP_POINTS = 768;

const STATES = new Set([
  "idle",
  "surveying",
  "inspecting",
  "recognizing",
  "holding",
  "faulted",
]);

export function parseRequest(frame) {
  if (Buffer.byteLength(frame, "utf8") > MAX_FRAME_BYTES) {
    throw new Error("request frame exceeds 32 KiB");
  }
  const request = JSON.parse(frame);
  requirePlainObject(request, "request");
  requireExactKeys(
    request,
    [
      "protocol_version",
      "request_id",
      "session_generation",
      "instruction",
      "state",
      "observation",
      "limits",
    ],
    "request",
  );
  if (request.protocol_version !== PROTOCOL_VERSION) {
    throw new Error("unsupported protocol version");
  }
  requireSafeInteger(request.request_id, "request_id", 1);
  requireSafeInteger(request.session_generation, "session_generation", 0);
  if (
    typeof request.instruction !== "string" ||
    request.instruction.trim().length === 0 ||
    Buffer.byteLength(request.instruction, "utf8") > MAX_INSTRUCTION_BYTES
  ) {
    throw new Error("instruction must contain 1 to 1024 bytes");
  }
  if (!STATES.has(request.state)) {
    throw new Error("invalid controller state");
  }
  validateObservation(request.observation);
  validateLimits(request.limits);
  return request;
}

export function normalizeAction(params) {
  requirePlainObject(params, "tool arguments");
  if (typeof params.action !== "string") {
    throw new Error("submit_plan.action is required");
  }
  switch (params.action) {
    case "hold":
      return { kind: "hold", reason: normalizeReason(params.reason) };
    case "stop_session":
      return {
        kind: "stop_session",
        reason: normalizeReason(params.reason),
      };
    case "survey_band":
      return {
        kind: "survey_band",
        start_hz: requireInteger(params.start_hz, "start_hz"),
        stop_hz: requireInteger(params.stop_hz, "stop_hz"),
        step_hz: requireInteger(params.step_hz, "step_hz"),
        sample_rate_hz: requireInteger(params.sample_rate_hz, "sample_rate_hz"),
        rf_bandwidth_hz: requireInteger(params.rf_bandwidth_hz, "rf_bandwidth_hz"),
        dwell_ms: requireInteger(params.dwell_ms, "dwell_ms"),
      };
    case "inspect_candidate":
      return {
        kind: "inspect_candidate",
        candidate_id: requireText(params.candidate_id, "candidate_id", 64),
        center_hz: requireInteger(params.center_hz, "center_hz"),
        sample_rate_hz: requireInteger(params.sample_rate_hz, "sample_rate_hz"),
        rf_bandwidth_hz: requireInteger(params.rf_bandwidth_hz, "rf_bandwidth_hz"),
        dwell_ms: requireInteger(params.dwell_ms, "dwell_ms"),
      };
    case "capture_bounded_iq":
      return {
        kind: "capture_bounded_iq",
        candidate_id: requireText(params.candidate_id, "candidate_id", 64),
        center_hz: requireInteger(params.center_hz, "center_hz"),
        sample_rate_hz: requireInteger(params.sample_rate_hz, "sample_rate_hz"),
        rf_bandwidth_hz: requireInteger(params.rf_bandwidth_hz, "rf_bandwidth_hz"),
        samples: requireInteger(params.samples, "samples"),
      };
    case "run_local_recognition":
      return {
        kind: "run_local_recognition",
        candidate_id: requireText(params.candidate_id, "candidate_id", 64),
      };
    default:
      throw new Error(`unknown proposed action: ${params.action}`);
  }
}

export function requireSubmitPlan(payload, api = "openai-completions") {
  if (api === "openai-responses") {
    return {
      ...payload,
      tool_choice: { type: "function", name: "submit_plan" },
    };
  }
  return {
    ...payload,
    tool_choice: {
      type: "function",
      function: { name: "submit_plan" },
    },
  };
}

export function makeResponse(request, planner, action) {
  return {
    protocol_version: PROTOCOL_VERSION,
    request_id: request.request_id,
    session_generation: request.session_generation,
    status: "ok",
    action,
    planner,
  };
}

export function makeErrorResponse(request, planner, status, error) {
  return {
    protocol_version: PROTOCOL_VERSION,
    request_id: Number.isSafeInteger(request?.request_id) ? request.request_id : 0,
    session_generation: Number.isSafeInteger(request?.session_generation)
      ? request.session_generation
      : 0,
    status,
    error: boundedError(error),
    planner,
  };
}

function validateObservation(observation) {
  requirePlainObject(observation, "observation");
  const observationKeys = ["age_ms", "health", "candidates"];
  if (Object.hasOwn(observation, "latest_sweep")) observationKeys.push("latest_sweep");
  if (Object.hasOwn(observation, "recognition")) observationKeys.push("recognition");
  requireExactKeys(observation, observationKeys, "observation");
  if (!Array.isArray(observation.candidates) || observation.candidates.length > MAX_CANDIDATES) {
    throw new Error("observation.candidates must be an array with at most 32 entries");
  }
  requireSafeInteger(observation.age_ms, "observation.age_ms", 0);
  requirePlainObject(observation.health, "observation.health");
  requireExactKeys(
    observation.health,
    [
      "sdr_online",
      "can_retune",
      "can_capture_iq",
      "fpga_available",
      "recognizer_available",
      "dropped_observations",
    ],
    "observation.health",
  );
  for (const field of [
    "sdr_online",
    "can_retune",
    "can_capture_iq",
    "fpga_available",
    "recognizer_available",
  ]) {
    if (typeof observation.health[field] !== "boolean") {
      throw new Error(`observation.health.${field} must be boolean`);
    }
  }
  requireSafeInteger(
    observation.health.dropped_observations,
    "observation.health.dropped_observations",
    0,
  );
  for (const candidate of observation.candidates) {
    requirePlainObject(candidate, "candidate");
    requireExactKeys(
      candidate,
      ["id", "center_hz", "bandwidth_hz", "peak_dbfs", "snr_db", "age_ms"],
      "candidate",
    );
    requireText(candidate.id, "candidate.id", 64);
    requireSafeInteger(candidate.center_hz, "candidate.center_hz", 1);
    requireSafeInteger(candidate.bandwidth_hz, "candidate.bandwidth_hz", 1);
    requireFinite(candidate.peak_dbfs, "candidate.peak_dbfs");
    requireFinite(candidate.snr_db, "candidate.snr_db");
    requireSafeInteger(candidate.age_ms, "candidate.age_ms", 0);
  }
  if (observation.latest_sweep !== undefined) {
    const sweep = observation.latest_sweep;
    requirePlainObject(sweep, "observation.latest_sweep");
    requireExactKeys(
      sweep,
      [
        "sweep_id",
        "sample_rate_hz",
        "rf_bandwidth_hz",
        "fixed_gain_db",
        "noise_floor_dbfs",
        "points",
      ],
      "observation.latest_sweep",
    );
    requireText(sweep.sweep_id, "latest_sweep.sweep_id", 64);
    requireSafeInteger(sweep.sample_rate_hz, "latest_sweep.sample_rate_hz", 1);
    requireSafeInteger(sweep.rf_bandwidth_hz, "latest_sweep.rf_bandwidth_hz", 1);
    requireSafeInteger(sweep.fixed_gain_db, "latest_sweep.fixed_gain_db", 0);
    if (sweep.fixed_gain_db > 60) {
      throw new Error("latest_sweep.fixed_gain_db must not exceed 60");
    }
    requireFinite(sweep.noise_floor_dbfs, "latest_sweep.noise_floor_dbfs");
    if (!Array.isArray(sweep.points) || sweep.points.length === 0
      || sweep.points.length > MAX_SWEEP_POINTS) {
      throw new Error("latest_sweep.points must contain 1 to 768 measured points");
    }
    let previousCenterHz = 0;
    for (const point of sweep.points) {
      if (!Array.isArray(point) || point.length !== 2) {
        throw new Error("each latest_sweep point must be [center_hz, power_dbfs]");
      }
      requireSafeInteger(point[0], "latest_sweep point center_hz", 1);
      requireFinite(point[1], "latest_sweep point power_dbfs");
      if (point[0] <= previousCenterHz) {
        throw new Error("latest_sweep point centers must be ascending and unique");
      }
      previousCenterHz = point[0];
    }
  }
  if (observation.recognition !== undefined) {
    requirePlainObject(observation.recognition, "observation.recognition");
    requireExactKeys(
      observation.recognition,
      ["candidate_id", "label", "confidence"],
      "observation.recognition",
    );
    requireText(observation.recognition.candidate_id, "recognition.candidate_id", 64);
    requireText(observation.recognition.label, "recognition.label", 128);
    requireFinite(observation.recognition.confidence, "recognition.confidence");
  }
}

function validateLimits(limits) {
  requirePlainObject(limits, "limits");
  const fields = [
    "min_freq_hz",
    "max_freq_hz",
    "max_span_hz",
    "max_bandwidth_hz",
    "max_dwell_ms",
    "max_iq_samples",
    "max_iq_bytes",
    "auto_approve_iq_bytes",
    "max_observation_age_ms",
  ];
  requireExactKeys(limits, fields, "limits");
  for (const field of fields) {
    requireSafeInteger(limits[field], `limits.${field}`, 0);
  }
}

function requireExactKeys(value, keys, label) {
  const expected = new Set(keys);
  for (const key of Object.keys(value)) {
    if (!expected.has(key)) {
      throw new Error(`${label} contains unknown field ${key}`);
    }
  }
  for (const key of keys) {
    if (!Object.hasOwn(value, key)) {
      throw new Error(`${label} is missing field ${key}`);
    }
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
  return value;
}

function requireInteger(value, label) {
  return requireSafeInteger(value, label, 1);
}

function requireFinite(value, label) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be finite`);
  }
  return value;
}

function requireText(value, label, maximumBytes) {
  if (
    typeof value !== "string" ||
    value.trim().length === 0 ||
    Buffer.byteLength(value, "utf8") > maximumBytes ||
    [...value].some((character) => /[\u0000-\u001f\u007f]/u.test(character))
  ) {
    throw new Error(`${label} must contain 1 to ${maximumBytes} printable bytes`);
  }
  return value;
}

function normalizeReason(value) {
  const text = requireText(value, "reason", 1_024);
  if (Buffer.byteLength(text, "utf8") <= 256) return text;
  const characters = [...text];
  while (Buffer.byteLength(`${characters.join("")}…`, "utf8") > 256) {
    characters.pop();
  }
  return `${characters.join("")}…`;
}

function boundedError(error) {
  const message = error instanceof Error ? error.message : String(error);
  return message.replace(/[\r\n\u0000-\u001f\u007f]+/gu, " ").slice(0, 512) || "planner error";
}
