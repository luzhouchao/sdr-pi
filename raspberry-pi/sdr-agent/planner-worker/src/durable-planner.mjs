import { createHash, randomUUID } from "node:crypto";
import { existsSync, statSync } from "node:fs";
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { AssistantMessageEventStream, Type } from "@earendil-works/pi-ai";
import { Harness, GenerationTask, ToolTask, SessionFailed, StorageRequestError, configure, createRegistry, defineDoc, defineExtension, defineTool, hook } from "@earendil-works/pi-durable";
import { compactPlanningContext } from "./context-policy.mjs";
import { formatUpstreamError } from "./planner-failure.mjs";
import { normalizeAction, parseRequest, requireSubmitPlan } from "./protocol.mjs";
import { MAX_SESSION_QUEUE } from "./session-protocol.mjs";
import { PLANNER_SYSTEM_PROMPT } from "./system-prompt.mjs";
import { openDurableStore } from "./durable-store.mjs";

const ctx = BACKGROUND_CONTEXT;
const checkpointWhen = () => true;
const Index = defineDoc({ kind: "sdr.sessions", version: 1, scope: "session",
  initial: () => ({ sessions: {} }), checkpointWhen });
const Business = defineDoc({ kind: "sdr.planning", version: 1, scope: "conversation", history: "latest", fork: "initial",
  initial: () => ({ appSessionId: "", epoch: "", generation: 0, provider: "", attachment: "", requests: {}, bindings: {} }), checkpointWhen });

export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(",")}}`;
  return JSON.stringify(value);
}
export const digest = (value) => createHash("sha256").update(canonical(value)).digest("hex");
const identifier = (value) => typeof value === "string" && !["__proto__", "constructor", "prototype"].includes(value) && /^[A-Za-z0-9_-]{1,128}$/u.test(value);
function envelope(messages) {
  const last = messages.findLast((m) => m.role === "user");
  const text = typeof last?.content === "string" ? last.content : last?.content?.filter((b) => b.type === "text").map((b) => b.text).join("");
  const value = JSON.parse(text);
  if (value.schema !== "sdr-durable-input-v1") throw new Error("missing durable request identity");
  parseRequest(JSON.stringify(value.context));
  return value;
}

// This engine is deliberately independent of the production socket protocol.
// Only a reconciled Controller adapter may attach a session and deliver plans.
export class DurablePlanner {
  static async open(options) {
    const engine = new DurablePlanner(options);
    await engine.#open();
    return engine;
  }

  constructor({ path, models, model, providerIdentity, runLease, deliver, streamAdapter,
    secrets = [], thinkingLevel = "off", contextWindow = 32_768, thresholdPercent = 90, now = Date.now,
    maxBytes = 64 * 1024 * 1024, onReport = () => {}, onProgress = () => {}, beforeDelivery = async () => {} }) {
    if (!runLease || typeof deliver !== "function") throw new Error("Controller delivery and shared RunLease required");
    this.path = path; this.models = models; this.model = model; this.thinkingLevel = thinkingLevel;
    this.provider = digest(providerIdentity); this.runLease = runLease; this.deliver = deliver;
    this.streamAdapter = streamAdapter; this.secrets = secrets; this.contextWindow = contextWindow;
    this.thresholdPercent = thresholdPercent; this.now = now; this.maxBytes = maxBytes;
    this.onReport = onReport; this.beforeDelivery = beforeDelivery;
    this.onProgress = onProgress;
    this.attachments = new Map(); this.release = undefined; this.admissions = 0; this.revision = 0;
    this.joining = undefined; this.failed = false; this.closed = false; this.commands = Promise.resolve();
  }

  async #open() {
    this.store = await openDurableStore(this.path);
    // Cover SDK-internal task/transcript writes as well as business commits.
    const storageCommit = this.store.storage.commit.bind(this.store.storage);
    this.store.storage.commit = async (...args) => {
      try { this.#storageBudget(); return await storageCommit(...args); }
      catch (error) { this.failed = true; throw error; }
    };
    const registry = createRegistry();
    const submitPlan = defineTool({ name: "submit_plan", description: "Submit one structured proposal to the Rust Controller.",
      // No replay:safe. An interrupted tool is never a licence to resend.
      executionMode: "sequential", callers: ["model"],
      parameters: Type.Object({
        action: Type.Union(["hold", "survey_band", "inspect_candidate", "capture_bounded_iq", "run_local_recognition", "stop_session"].map((v) => Type.Literal(v))),
        reason: Type.Optional(Type.String({ maxLength: 256 })),
        candidate_id: Type.Optional(Type.String({ maxLength: 64 })),
        ...Object.fromEntries(["start_hz", "stop_hz", "step_hz", "center_hz", "sample_rate_hz", "rf_bandwidth_hz", "dwell_ms", "samples"].map((k) => [k, Type.Optional(Type.Integer({ minimum: 1 }))])),
      }),
      execute: (args, api, context) => this.#propose(args, api, context),
    });
    this.submitTool = submitPlan;
    registry.install(defineExtension({ name: "sdr-planner", tools: [submitPlan], hooks: [
      hook(GenerationTask, { beforeRequest: async ({ messages }, api) => {
        const input = envelope(messages);
        await this.#commit(async (tx) => {
          const business = await tx.doc(Business, api.conversationId);
          this.#eligible(business, input.key);
          business.bindings[api.taskId] = input.key;
        });
        return { messages: compactPlanningContext([...messages], this.contextWindow, this.thresholdPercent) };
      } }),
      hook(ToolTask, { beforeTool: async (call, api) => {
        try {
          if (call.name !== "submit_plan") throw new Error("tool not allowed");
          await this.#commit(async (tx) => {
            const task = await tx.task(api.taskId);
            const business = await tx.doc(Business, api.conversationId);
            const key = task?.owner ? business.bindings[task.owner] : undefined;
            const request = this.#eligible(business, key);
            if (request.proposal || request.toolCallId) throw new Error("request already crossed tool intent fence");
            request.toolCallId = call.id;
            request.toolTaskId = api.taskId;
          });
          return undefined;
        } catch { return { block: "request invalid, interrupted or reconciliation required" }; }
      } }),
    ] }));
    const guardedModels = new Proxy(this.models, { get: (target, key) => {
      if (key === "streamSimple") return (model, context, options) => this.#stream(model, context, options);
      const value = Reflect.get(target, key); return typeof value === "function" ? value.bind(target) : value;
    } });
    try {
      this.harness = await Harness.open(this.store.storage, { models: guardedModels, registry, now: this.now,
        settings: { compaction: { enabled: false }, retry: { enabled: false, maxRetries: 0, baseDelayMs: 0 },
          stream: { maxRetries: 0, timeoutMs: 30_000 }, steeringMode: "one-at-a-time", followUpMode: "one-at-a-time",
          toolExecution: "sequential", contextRetentionMs: 0, documentRetentionMs: 0, afterFailedRun: "withdraw" },
        onReport: (_error, info) => {
          if (info.type === "session_failed") this.failed = true;
          this.onReport({ type: info.type, task: info.task?.id });
        },
      }, ctx);
      // Open does recovery bookkeeping, but scheduling remains off. Revoke every
      // persisted execution capability before any submit/wait/abort can start it.
      await this.#commit(async (tx) => {
        const index = await tx.doc(Index);
        for (const conversationId of Object.values(index.sessions)) {
          const business = await tx.doc(Business, conversationId);
          business.attachment = "";
          for (const request of Object.values(business.requests)) {
            request.enabled = false;
            if (request.toolCallId || request.proposal) request.reason = "reconciliation_required";
            if (request.proposal?.state === "dispatch_attempted") request.proposal.state = "unknown";
          }
        }
      });
    } catch (error) {
      try { await this.harness?.close(ctx); } finally { await this.store.close(); }
      throw error;
    }
  }

  async #commit(change) {
    this.#healthy();
    this.#storageBudget();
    try { return await this.harness.commit(change, ctx); }
    catch (error) {
      if (error instanceof SessionFailed || error instanceof StorageRequestError || error.code?.startsWith("SQLITE_")) this.failed = true;
      throw error;
    }
  }

  #storageBudget() {
    const bytes = [this.path, `${this.path}-wal`, `${this.path}-shm`].reduce((n, p) => n + (existsSync(p) ? statSync(p).size : 0), 0);
    if (bytes >= this.maxBytes) { this.failed = true; throw new Error("durable storage budget exhausted"); }
  }

  #healthy() { if (this.failed || this.closed) throw new Error("durable engine unavailable"); }
  #eligible(business, key, proposalId) {
    this.#healthy();
    this.#storageBudget();
    const attached = this.attachments.get(business.appSessionId);
    const request = business.requests[key];
    if (!this.release || !attached || attached.token !== business.attachment || attached.closing ||
      attached.epoch !== business.epoch || attached.generation !== business.generation || business.provider !== this.provider ||
      !request?.enabled || request.reason || request.deadline <= this.now() ||
      (proposalId ? request.proposal?.planId !== proposalId : request.proposal)) {
      throw new Error("durable request not eligible");
    }
    return request;
  }

  #command(action) {
    const result = this.commands.then(action);
    this.commands = result.catch(() => {});
    return result;
  }

  attach(identity) { return this.#command(() => this.#attach(identity)); }

  async #attach({ appSessionId, controllerEpoch, sessionGeneration }) {
    this.#healthy();
    if (!identifier(appSessionId) || !identifier(controllerEpoch) || !Number.isSafeInteger(sessionGeneration) || sessionGeneration < 0) throw new Error("invalid Controller identity");
    if (this.attachments.has(appSessionId)) throw new Error("session already attached");
    const index = await this.harness.snapshot(Index, ctx);
    let conversationId = index?.sessions[appSessionId];
    if (!conversationId) {
      if (Object.keys(index?.sessions ?? {}).length >= 16) throw new Error("durable session capacity reached");
      const conversation = await this.harness.createConversation({ ownership: { kind: "ownerless" },
        agent: { model: this.model, thinkingLevel: this.thinkingLevel, instructions: PLANNER_SYSTEM_PROMPT, tools: [this.#tool()] },
        init: async (tx, id) => {
          (await tx.doc(Index)).sessions[appSessionId] = id;
          const business = await tx.doc(Business, id); business.appSessionId = appSessionId;
        },
      }, ctx);
      conversationId = conversation.id;
    }
    const token = randomUUID();
    await this.#commit(async (tx) => {
      const business = await tx.doc(Business, conversationId);
      for (const request of Object.values(business.requests)) {
        request.enabled = false;
        if (business.epoch !== controllerEpoch || business.generation !== sessionGeneration || business.provider !== this.provider) request.reason = "stale_controller_or_provider";
      }
      business.epoch = controllerEpoch; business.generation = sessionGeneration;
      business.provider = this.provider; business.attachment = token;
      // Agent configuration is persisted by Harness, including instructions.
      // Refresh it on EVERY attach, atomically with revoking old requests and
      // before publishing the new attachment. Restart alone keeps old policy.
      await configure(tx, conversationId, {
        model: this.model, thinkingLevel: this.thinkingLevel,
        instructions: PLANNER_SYSTEM_PROMPT, tools: [this.#tool()],
      });
    });
    this.attachments.set(appSessionId, { token, epoch: controllerEpoch, generation: sessionGeneration, conversationId, closing: false });
    return conversationId;
  }

  #tool() { return this.submitTool; }

  submit(appSessionId, context, options) { return this.#command(() => this.#submit(appSessionId, context, options)); }

  async #submit(appSessionId, context, { mode = "prompt", deadline = this.now() + 30_000 } = {}) {
    this.#healthy();
    const attached = this.attachments.get(appSessionId);
    if (!attached || attached.closing) throw new Error("session not attached");
    parseRequest(JSON.stringify(context));
    if (context.session_generation !== attached.generation) throw new Error("stale generation");
    if (!Number.isSafeInteger(deadline) || deadline <= this.now() || deadline > this.now() + 120_000) throw new Error("invalid request deadline");
    if (!["prompt", "steer", "follow_up"].includes(mode)) throw new Error("invalid queue mode");
    const key = `${attached.epoch}:${attached.generation}:${context.request_id}`;
    const content = { schema: "sdr-durable-input-v1", appSessionId, key, context };
    const hash = digest(content);
    return this.#schedule(async () => {
      const conversation = await this.harness.conversation(attached.conversationId, ctx);
      const prior = await this.harness.snapshot(Business, conversation.id, ctx);
      const existing = prior.requests[key];
      if (existing) {
        if (existing.hash !== hash) throw new Error("same request identity has different content");
        const submission = await this.store.storage.submissionByRequest(conversation.id, key, ctx);
        if (submission) return submission.id;
        if (!existing.enabled || existing.reason) throw new Error("request requires reconciliation");
      } else {
        const inspection = await this.harness.inspect(ctx);
        if (mode === "prompt" && inspection.tasks.some((t) => t.record.conversationId === conversation.id)) throw new Error("Agent is busy; use steer or follow_up");
        const pending = await this.store.storage.scanSubmissions({ conversationId: conversation.id, status: "queued" }, MAX_SESSION_QUEUE + 1, undefined, ctx);
        if (pending.items.length >= MAX_SESSION_QUEUE) throw new Error("session queue limit reached");
        if (Object.keys(prior.requests).length >= 128) throw new Error("request capacity reached; archive session");
        await this.#commit(async (tx) => {
          const business = await tx.doc(Business, conversation.id);
          business.requests[key] = { hash, deadline, enabled: true, reason: "", modelAttempts: 0 };
        });
      }
      // Persist the app fence first. A crash in this gap leaves a disabled
      // orphan record on reopen; it cannot turn into a new input automatically.
      const submission = await conversation.submit({ type: "input", content: JSON.stringify(content), requestId: key,
        whenBusy: mode === "prompt" ? "reject" : mode === "steer" ? "steer" : "followUp" }, ctx);
      return submission.id;
    });
  }

  async #schedule(action) {
    if (!this.release) {
      this.release = this.runLease.acquire("durable_session");
      if (!this.release) throw new Error("Planner Worker busy");
    }
    this.admissions++; this.revision++;
    try { return await action(); }
    finally {
      this.admissions--;
      this.#ensureJoin();
    }
  }

  #ensureJoin() {
    if (this.joining) return;
    const pending = this.#join();
    this.joining = pending;
    pending.then(() => {
      if (this.joining === pending) this.joining = undefined;
      // An admission can acquire a fresh lease between the old join releasing
      // its lease and this completion microtask. Join that run as well.
      if (this.release && !this.failed && !this.closed) this.#ensureJoin();
    }, () => { this.failed = true; });
  }

  async #join() {
    while (true) {
      const revision = this.revision;
      await this.harness.waitForIdle(ctx);
      if (this.admissions === 0 && revision === this.revision) {
        this.release?.(); this.release = undefined; return;
      }
    }
  }

  #streamError(output, model, options, error) {
    const message = { role: "assistant", content: [], api: model.api, provider: model.provider, model: model.id,
      usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
      stopReason: options.signal?.aborted ? "aborted" : "error", errorMessage: formatUpstreamError(error, this.secrets), timestamp: this.now() };
    output.push({ type: "error", reason: message.stopReason, error: message }); output.end();
  }

  #providerStream(model, context, options, input) {
    const output = new AssistantMessageEventStream();
    void (async () => {
      try {
        // This guard runs for EVERY physical provider call, including each
        // Spark host-search turn. Adapter loops cannot bypass identity/budget.
        const attached = this.attachments.get(input.appSessionId);
        if (!attached) throw new Error("request attachment missing");
        await this.#commit(async tx => {
          const doc = await tx.doc(Business, attached.conversationId);
          const request = this.#eligible(doc, input.key);
          if (request.toolCallId || request.modelAttempts >= 4 || request.hash !== digest(input)) throw new Error("request interrupted or model attempt budget exhausted");
          request.modelAttempts++;
        });
        if (options.signal?.aborted) throw new Error("request aborted");
        for await (const event of this.models.streamSimple(model, context, { ...options, reasoning: this.thinkingLevel, maxRetries: 0,
          onPayload: options.onPayload ?? (payload => requireSubmitPlan(payload, model.api)) })) {
          if (event.type === "error") event.error.errorMessage = formatUpstreamError(event.error.errorMessage, this.secrets);
          output.push(event);
        }
        output.end();
      } catch (error) { this.#streamError(output, model, options, error); }
    })();
    return output;
  }

  #stream(model, context, options = {}) {
    const output = new AssistantMessageEventStream();
    void (async () => {
      try {
        const input = envelope(context.messages);
        const identity = { appSessionId: input.appSessionId, requestId: input.context.request_id };
        const base = (m, c, o = {}) => this.#providerStream(m, c, o, input);
        const stream = this.streamAdapter ? this.streamAdapter(base, identity)(model, context, options) : base(model, context, options);
        for await (const event of stream) {
          if (event.type === "error") event.error.errorMessage = formatUpstreamError(event.error.errorMessage, this.secrets);
          this.onProgress({ ...identity, event });
          output.push(event);
        }
        output.end();
      } catch (error) { this.#streamError(output, model, options, error); }
    })();
    return output;
  }

  async #propose(args, api, context) {
    const action = normalizeAction(args);
    let proposal;
    await api.commit(async (tx) => {
      const task = await tx.task(api.taskId);
      const business = await tx.doc(Business, api.conversationId);
      const key = task?.owner ? business.bindings[task.owner] : undefined;
      const request = this.#eligible(business, key);
      if (request.toolTaskId !== api.taskId || request.toolCallId !== api.callId) throw new Error("tool intent identity mismatch");
      proposal = { planId: randomUUID(), key, hash: digest(action), action, state: "prepared" };
      request.proposal = proposal;
      await tx.appendEntry(api.conversationId, { kind: "sdr.plan", data: proposal });
    }, context);
    await this.beforeDelivery(proposal);
    await api.commit(async (tx) => {
      const business = await tx.doc(Business, api.conversationId);
      const request = this.#eligible(business, proposal.key, proposal.planId);
      request.proposal.state = "dispatch_attempted";
    }, context);
    const business = await this.harness.snapshot(Business, api.conversationId, ctx);
    this.#eligible(business, proposal.key, proposal.planId);
    if (context.abortSignal?.aborted) throw new Error("delivery gate closed");
    try {
      const ack = await this.deliver({ ...proposal, controllerEpoch: business.epoch, sessionGeneration: business.generation, appSessionId: business.appSessionId, deadlineUnixMs:business.requests[proposal.key].deadline });
      await api.commit(async (tx) => {
        const doc = await tx.doc(Business, api.conversationId);
        const record = doc.requests[proposal.key];
        record.proposal.state = ack?.planId === proposal.planId && ack?.hash === proposal.hash && ["accepted", "rejected"].includes(ack.state) ? ack.state : "unknown";
        record.reason = record.proposal.state === "unknown" ? "reconciliation_required" : "proposal_finalized";
      }, context);
    } catch {
      await this.#commit(async (tx) => {
        const doc = await tx.doc(Business, api.conversationId);
        doc.requests[proposal.key].proposal.state = "unknown";
        doc.requests[proposal.key].reason = "reconciliation_required";
      });
    }
    return { output: [{ type: "text", text: "Proposal recorded; Controller acknowledgement is not execution completion." }], control: { terminate: true } };
  }

  async state(appSessionId) {
    const index = await this.harness.snapshot(Index, ctx);
    const id = index?.sessions[appSessionId];
    return id ? this.harness.snapshot(Business, id, ctx) : undefined;
  }

  async blocked(appSessionId) {
    const a = this.attachments.get(appSessionId);
    if (!a) throw new Error("session not attached");
    const view = await this.harness.inspect(ctx);
    return view.tasks.filter(t => t.record.conversationId === a.conversationId && t.state.kind === "blocked")
      .slice(0, 16).map(t => ({ reason: t.state.reason }));
  }

  async acknowledge(appSessionId, { plan_id, hash, state }) {
    const a = this.attachments.get(appSessionId);
    if (!a || a.closing || !["accepted", "rejected"].includes(state)) throw new Error("invalid acknowledgement attachment");
    await this.#commit(async tx => {
      const business = await tx.doc(Business, a.conversationId);
      const request = Object.values(business.requests).find(r => r.proposal?.planId === plan_id);
      if (!request || request.proposal.hash !== hash) throw new Error("unknown acknowledgement identity");
      if (["accepted", "rejected"].includes(request.proposal.state)) {
        if (request.proposal.state !== state) throw new Error("conflicting acknowledgement decision");
        return;
      }
      if (request.proposal.state !== "unknown") throw new Error("proposal is not awaiting reconciliation");
      request.proposal.state = state;
      request.enabled = false;
      request.reason = "proposal_finalized";
    });
  }

  // Reconciliation records the Controller's answer only. It grants no request
  // eligibility, restores no approval and never schedules or resends a plan.
  async reconcile(appSessionId, { plan_id, hash, decision, execution_state }) {
    const a = this.attachments.get(appSessionId);
    if (!a || a.closing) throw new Error("session not attached");
    if (!["accepted", "rejected", "unknown"].includes(decision) || !["accepted", "pending_approval", "executing", "completed", "failed", "cancelled", "unknown"].includes(execution_state)) throw new Error("invalid Controller status");
    await this.#commit(async tx => {
      const business = await tx.doc(Business, a.conversationId);
      const request = Object.values(business.requests).find(r => r.proposal?.planId === plan_id);
      if (!request || request.proposal.hash !== hash || request.enabled) throw new Error("status has no disabled matching proposal");
      request.proposal.controllerExecution = execution_state;
      request.proposal.state = decision;
      request.reason = decision === "unknown" ? "reconciliation_required" : "reconciliation_complete";
    });
  }

  clearQueue(appSessionId) { return this.#command(() => this.#clearQueue(appSessionId)); }

  async #clearQueue(appSessionId) {
    const a = this.attachments.get(appSessionId); if (!a || a.closing) throw new Error("session not attached");
    return this.#schedule(async () => {
      const page = await this.store.storage.scanSubmissions({ conversationId: a.conversationId, status: "queued" }, MAX_SESSION_QUEUE + 1, undefined, ctx);
      // Revoke before abortSubmission, which may start scheduling.
      await this.#commit(async (tx) => {
        const doc = await tx.doc(Business, a.conversationId);
        for (const input of page.items) {
          const request = doc.requests[input.requestId];
          if (request) { request.enabled = false; request.reason = "queue_withdrawn"; }
        }
      });
      for (const input of page.items) await this.harness.abortSubmission(input.id, ctx, a.conversationId);
      return page.items.length;
    });
  }

  async abort(appSessionId) {
    const a = this.attachments.get(appSessionId); if (!a) return;
    a.closing = true; // synchronous fence: a late tool cannot deliver while the commit waits.
    await this.#schedule(async () => {
      await this.#commit(async (tx) => {
        const doc = await tx.doc(Business, a.conversationId);
        doc.attachment = "";
        for (const request of Object.values(doc.requests)) { request.enabled = false; request.reason ||= "aborted"; }
      });
      await (await this.harness.conversation(a.conversationId, ctx)).abort(ctx, { background: true });
    });
    await this.idle();
    this.attachments.delete(appSessionId);
  }

  recover(appSessionId, requestIds) { return this.#command(() => this.#recover(appSessionId, requestIds)); }

  async #recover(appSessionId, requestIds) {
    const a = this.attachments.get(appSessionId); if (!a || a.closing) throw new Error("session not attached");
    if (!Array.isArray(requestIds) || requestIds.length > MAX_SESSION_QUEUE + 1) throw new Error("invalid recovery request set");
    return this.#schedule(async () => {
      await this.#commit(async (tx) => {
        const doc = await tx.doc(Business, a.conversationId);
        for (const id of requestIds) {
          const key = `${a.epoch}:${a.generation}:${id}`; const request = doc.requests[key];
          if (!request || request.reason || request.toolCallId || request.proposal || request.deadline <= this.now()) throw new Error("recovery requires reconciliation");
          request.enabled = true;
        }
      });
      this.harness.resume();
    });
  }

  closeSession(appSessionId) { return this.#command(() => this.#closeSession(appSessionId)); }

  async #closeSession(appSessionId) {
    const a = this.attachments.get(appSessionId); if (!a) return;
    const live = await this.harness.inspect(ctx);
    if (live.tasks.some((task) => task.record.conversationId === a.conversationId)) throw new Error("abort active run before closing session");
    await this.abort(appSessionId);
  }

  async idle() { while (this.joining) await this.joining; }

  // Process close deliberately does not claim to cancel work. Every reopen
  // revokes persisted capabilities before any scheduler entry point.
  async close() {
    for (const a of this.attachments.values()) a.closing = true;
    try { await this.harness.close(ctx); }
    finally { this.closed = true; this.release?.(); this.release = undefined; await this.store.close(); }
  }
}
