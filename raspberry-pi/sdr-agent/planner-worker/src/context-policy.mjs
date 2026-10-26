import { getCurrentSystemMessage } from "@earendil-works/pi-ai";
import { estimateContextTokens } from "@earendil-works/pi-ai/utils/estimate";

export function compactPlanningContext(messages, contextWindow, thresholdPercent = 90) {
  if (!Number.isSafeInteger(contextWindow) || contextWindow < 8_192 || contextWindow > 1_000_000) {
    throw new Error("context window is outside the supported range");
  }
  if (!Number.isSafeInteger(thresholdPercent) || thresholdPercent < 50 || thresholdPercent > 95) {
    throw new Error("compression threshold is outside the supported range");
  }
  const thresholdTokens = Math.floor((contextWindow * thresholdPercent) / 100);
  if (estimateContextTokens(messages).tokens < thresholdTokens) return messages;

  // Each Rust PlanningContext is a complete, freshly validated snapshot. Once
  // the threshold is reached, older planning turns are less authoritative than
  // the newest user context and can be removed without summarizing radio facts.
  const latestUserIndex = messages.findLastIndex((message) => message?.role === "user");
  if (latestUserIndex <= 0) return messages;
  // Pi 1.x carries the prompt and tool declarations in system messages. Replay
  // them before removing old turns so compaction cannot remove planning rules.
  const system = getCurrentSystemMessage(messages);
  const recent = messages.slice(latestUserIndex).filter((message) => message.role !== "system");
  return system === undefined ? recent : [system, ...recent];
}
