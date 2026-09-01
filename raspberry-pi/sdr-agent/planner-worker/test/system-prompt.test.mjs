import assert from "node:assert/strict";
import test from "node:test";
import { PLANNER_SYSTEM_PROMPT } from "../src/system-prompt.mjs";

test("system prompt names live SDR observations and every hard planning boundary", () => {
  for (const required of [
    "observation.health",
    "observation.candidates",
    "limits.min_freq_hz",
    "limits.max_freq_hz",
    "limits.max_span_hz",
    "limits.max_bandwidth_hz",
    "max_dwell_ms",
    "max_iq_samples",
    "max_iq_bytes",
    "auto_approve_iq_bytes",
    "max_observation_age_ms",
    "never\\s+invent a candidate",
    "Never transmit",
  ]) {
    assert.match(PLANNER_SYSTEM_PROMPT, new RegExp(required, "u"));
  }
});
