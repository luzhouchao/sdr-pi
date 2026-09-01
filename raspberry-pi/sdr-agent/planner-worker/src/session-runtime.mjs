// Agent interaction semantics intentionally use the public pi-agent-core
// prompt/steer/followUp/abort/subscribe interface instead of reimplementing
// Pi's Agent loop. See THIRD_PARTY_NOTICES.md and docs/TERMINAL_AGENT_CLI_RESEARCH.md.

import { makeResponse, parseRequest } from "./protocol.mjs";
import {
  boundedText,
  makeSessionEvent,
  makeSessionResponse,
  MAX_SESSION_QUEUE,
} from "./session-protocol.mjs";

export class SessionRuntime {
  constructor({ createAgent, plannerMeta, runLease }) {
    this.createAgent = createAgent;
    this.plannerMeta = plannerMeta;
    this.runLease = runLease;
    this.agent = undefined;
    this.unsubscribe = undefined;
    this.sessionGeneration = undefined;
    this.active = false;
    this.queued = 0;
    this.currentContext = undefined;
    this.planSubmittedForRequest = undefined;
    this.emit = () => {};
    this.releaseRun = undefined;
  }

  async dispatch(command, emit) {
    this.emit = emit;
    try {
      switch (command.type) {
        case "open_session":
          return this.#open(command);
        case "prompt":
          return this.#prompt(command);
        case "steer":
          return this.#queue(command, "steer");
        case "follow_up":
          return this.#queue(command, "followUp");
        case "abort":
          return this.#abort(command);
        case "clear_queue":
          return this.#clearQueue(command);
        case "get_state":
          return this.#state(command);
        case "close_session":
          return this.#close(command);
        default:
          return makeSessionResponse(command, false, "unsupported session command");
      }
    } catch (error) {
      return makeSessionResponse(command, false, error);
    }
  }

  async dispose() {
    if (this.agent === undefined) return;
    this.agent.clearAllQueues();
    this.queued = 0;
    this.agent.abort();
    await this.agent.waitForIdle?.();
    this.releaseRun?.();
    this.releaseRun = undefined;
    this.unsubscribe?.();
    this.agent.reset();
    this.agent = undefined;
    this.unsubscribe = undefined;
    this.sessionGeneration = undefined;
    this.currentContext = undefined;
    this.planSubmittedForRequest = undefined;
    this.active = false;
  }

  #open(command) {
    if (this.agent !== undefined) throw new Error("a session is already open");
    this.sessionGeneration = command.session_generation;
    const created = this.createAgent({
      sessionGeneration: command.session_generation,
      onPlan: (action) => this.#submitPlan(action),
    });
    this.agent = created?.agent ?? created;
    this.plannerMeta = created?.plannerMeta ?? this.plannerMeta;
    this.agent.steeringMode = "one-at-a-time";
    this.agent.followUpMode = "one-at-a-time";
    this.unsubscribe = this.agent.subscribe((event) => this.#handleAgentEvent(event));
    return makeSessionResponse(command, true, this.#stateData());
  }

  #prompt(command) {
    this.#requireSession(command);
    if (this.active) throw new Error("Agent is busy; use steer or follow_up");
    this.releaseRun = this.runLease?.acquire("interactive_session");
    if (this.runLease !== undefined && this.releaseRun === undefined) {
      throw new Error("Planner Worker is busy with another inference run");
    }
    this.active = true;
    this.#runPrompt(command.context);
    return makeSessionResponse(command, true, { accepted: true });
  }

  #queue(command, method) {
    this.#requireSession(command);
    if (!this.active) throw new Error(`${command.type} requires an active Agent run`);
    if (this.queued >= MAX_SESSION_QUEUE) {
      throw new Error(`session queue limit of ${MAX_SESSION_QUEUE} reached`);
    }
    this.agent[method](userMessage(command.context));
    this.queued += 1;
    this.emit(makeSessionEvent(this.sessionGeneration, "queue_update", { queued: this.queued }));
    return makeSessionResponse(command, true, { queued: this.queued });
  }

  #abort(command) {
    this.#requireSession(command);
    this.agent.clearAllQueues();
    this.queued = 0;
    this.agent.abort();
    this.emit(makeSessionEvent(this.sessionGeneration, "queue_update", { queued: 0 }));
    return makeSessionResponse(command, true, { abort_requested: this.active });
  }

  #clearQueue(command) {
    this.#requireSession(command);
    this.agent.clearAllQueues();
    const cleared = this.queued;
    this.queued = 0;
    this.emit(makeSessionEvent(this.sessionGeneration, "queue_update", { queued: 0 }));
    return makeSessionResponse(command, true, { cleared });
  }

  #state(command) {
    this.#requireSession(command);
    return makeSessionResponse(command, true, this.#stateData());
  }

  #close(command) {
    this.#requireSession(command);
    if (this.active) throw new Error("abort the active Agent run before closing the session");
    this.unsubscribe?.();
    this.agent.clearAllQueues();
    this.agent.reset();
    this.agent = undefined;
    this.unsubscribe = undefined;
    this.sessionGeneration = undefined;
    this.currentContext = undefined;
    this.planSubmittedForRequest = undefined;
    this.queued = 0;
    return makeSessionResponse(command, true, { closed: true });
  }

  #requireSession(command) {
    if (this.agent === undefined) throw new Error("no session is open");
    if (command.session_generation !== this.sessionGeneration) {
      throw new Error("command belongs to a stale session generation");
    }
  }

  #stateData() {
    return {
      open: this.agent !== undefined,
      active: this.active,
      queued: this.queued,
    };
  }

  #runPrompt(context) {
    const generation = this.sessionGeneration;
    const agent = this.agent;
    const releaseRun = this.releaseRun;
    const emitIfCurrent = (event, data = undefined) => {
      if (this.sessionGeneration === generation && this.agent === agent) {
        this.emit(makeSessionEvent(generation, event, data));
      }
    };
    Promise.resolve()
      .then(() => agent.prompt(JSON.stringify(context)))
      .then(() => {
        if (
          this.sessionGeneration === generation
          && this.agent === agent
          && this.planSubmittedForRequest !== context.request_id
        ) {
          emitIfCurrent("agent_error", {
            error: "上游模型结束了本轮生成，但没有提交下一步计划",
          });
        }
      })
      .catch((error) => {
        emitIfCurrent("agent_error", {
          error: boundedText(error, 512, "Agent run failed"),
        });
      })
      .finally(() => {
        releaseRun?.();
        if (this.releaseRun === releaseRun) this.releaseRun = undefined;
        if (this.sessionGeneration === generation && this.agent === agent && this.active) {
          this.active = false;
          this.queued = 0;
          emitIfCurrent("agent_end");
        }
      });
  }

  #handleAgentEvent(event) {
    switch (event.type) {
      case "agent_start":
        this.active = true;
        this.emit(makeSessionEvent(this.sessionGeneration, "agent_start"));
        break;
      case "message_start":
        if (event.message?.role === "user") {
          const text = extractText(event.message);
          this.currentContext = parseRequest(text);
          if (this.currentContext.session_generation !== this.sessionGeneration) {
            throw new Error("Agent received a stale planning context");
          }
          this.planSubmittedForRequest = undefined;
        }
        break;
      case "message_update":
        this.#handleAssistantMessageUpdate(event);
        break;
      case "message_end":
        if (event.message?.role === "assistant") {
          const text = extractText(event.message);
          if (text) {
            this.emit(
              makeSessionEvent(this.sessionGeneration, "assistant_message", {
                text: boundedText(text, 8_192, ""),
              }),
            );
          }
        }
        break;
      case "tool_execution_start":
        this.emit(
          makeSessionEvent(this.sessionGeneration, "tool_start", {
            name: event.toolName,
          }),
        );
        break;
      case "tool_execution_end":
        this.emit(
          makeSessionEvent(this.sessionGeneration, "tool_end", {
            name: event.toolName,
            is_error: event.isError,
          }),
        );
        break;
      case "agent_end":
        this.active = false;
        this.queued = 0;
        this.emit(makeSessionEvent(this.sessionGeneration, "queue_update", { queued: 0 }));
        this.emit(makeSessionEvent(this.sessionGeneration, "agent_end"));
        break;
      default:
        break;
    }
  }

  #handleAssistantMessageUpdate(event) {
    const update = event.assistantMessageEvent;
    if (event.message?.role !== "assistant" || update === undefined) return;
    const requestId = this.currentContext?.request_id;
    if (!Number.isSafeInteger(requestId)) return;
    switch (update.type) {
      case "thinking_start":
        this.emit(makeSessionEvent(this.sessionGeneration, "thinking_start", {
          request_id: requestId,
        }));
        break;
      case "thinking_delta": {
        if (typeof update.delta !== "string" || update.delta.length === 0) break;
        this.emit(makeSessionEvent(this.sessionGeneration, "thinking_delta", {
          request_id: requestId,
          delta: update.delta,
        }));
        break;
      }
      case "thinking_end":
        this.emit(makeSessionEvent(this.sessionGeneration, "thinking_end", {
          request_id: requestId,
        }));
        break;
      default:
        break;
    }
  }

  #submitPlan(action) {
    if (this.currentContext === undefined) {
      throw new Error("submit_plan has no active planning context");
    }
    if (this.planSubmittedForRequest === this.currentContext.request_id) {
      throw new Error("only one plan may be submitted per planning context");
    }
    this.planSubmittedForRequest = this.currentContext.request_id;
    const response = makeResponse(this.currentContext, this.plannerMeta, action);
    this.emit(makeSessionEvent(this.sessionGeneration, "plan_proposed", response));
  }
}

function userMessage(context) {
  return {
    role: "user",
    content: [{ type: "text", text: JSON.stringify(context) }],
    timestamp: Date.now(),
  };
}

function extractText(message) {
  if (typeof message.content === "string") return message.content;
  if (!Array.isArray(message.content)) return "";
  return message.content
    .filter((content) => content?.type === "text" && typeof content.text === "string")
    .map((content) => content.text)
    .join("\n");
}
