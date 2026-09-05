// Planner receives only this allowlist, never the internal experimental record.
export function validateRecognition(r, generation, maxAge, candidates, now = Date.now()) {
  const check = (ok) => { if (!ok) throw new Error("invalid recognition observation"); };
  const object = (v, keys) => {
    check(v !== null && typeof v === "object" && !Array.isArray(v));
    check(Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k)));
  };
  const token = (v, max = 64) => typeof v === "string" && v.length > 0 && Buffer.byteLength(v) <= max && /^[A-Za-z0-9_.:-]+$/.test(v);
  const uint = v => Number.isSafeInteger(v) && v >= 0;
  const positive = v => uint(v) && v > 0;
  const hash = v => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
  const ref = v => { object(v, ["id", "sha256"]); check(token(v.id) && hash(v.sha256)); };
  object(r, ["schema_version", "candidate_id", "request_id", "session_generation", "observed_at_unix_ms", "status", "reason", "class", "calibrated_confidence", "calibration_status", "decision_references", "identity", "source", "quality", "timing"]);
  check(Buffer.byteLength(JSON.stringify(r)) <= 4096);
  check(r.schema_version === 1 && token(r.candidate_id) && positive(r.request_id) && positive(r.session_generation) && r.session_generation === generation);
  check(positive(r.observed_at_unix_ms) && r.observed_at_unix_ms <= now && now - r.observed_at_unix_ms <= maxAge);
  check(candidates.some(c => c.id === r.candidate_id));
  check(["classified", "rejected", "unavailable", "error"].includes(r.status));
  check(["uncalibrated", "frozen", "unavailable"].includes(r.calibration_status));
  if (r.reason !== null) check(token(r.reason));
  if (r.identity !== null) {
    const i = r.identity;
    object(i, ["model_id", "checkpoint_sha256", "profile_id", "profile_sha256", "preprocess_id", "preprocess_sha256", "compute", "aggregation"]);
    check(token(i.model_id,128) && token(i.profile_id,128) && token(i.preprocess_id,128));
    check(hash(i.checkpoint_sha256) && hash(i.profile_sha256) && hash(i.preprocess_sha256));
    check(i.compute === "cuda_fp16_autocast" && i.aggregation === "float64_arithmetic_mean_logits_then_softmax");
  }
  if (r.source !== null) {
    const s = r.source;
    object(s, ["sweep_id", "request_id", "session_generation", "sequence", "capture_request_id", "capture_sequence"]);
    check(token(s.sweep_id) && positive(s.request_id) && positive(s.session_generation) && positive(s.sequence) && positive(s.capture_request_id) && positive(s.capture_sequence) && s.capture_sequence > s.sequence);
  }
  if (r.quality !== null) {
    const q = r.quality;
    object(q, ["window_count", "window_agreement", "clipped_samples", "dropped_samples", "overflow", "healthy"]);
    check(q.window_count === 4 && Number.isFinite(q.window_agreement) && q.window_agreement >= 0 && q.window_agreement <= 1 && Number.isInteger(q.window_agreement*4));
    check(uint(q.clipped_samples) && uint(q.dropped_samples) && typeof q.overflow === "boolean" && typeof q.healthy === "boolean");
  }
  if (r.timing !== null) {
    const t = r.timing;
    object(t, ["capture_us", "worker_total_us", "inference_us"]);
    check(uint(t.capture_us) && t.capture_us <= 60000000 && uint(t.worker_total_us) && t.worker_total_us <= 120000000 && uint(t.inference_us) && t.inference_us <= t.worker_total_us);
  }
  if (r.class !== null) {
    const c = r.class;
    object(c, ["numeric_id", "name", "name_status", "name_evidence"]);
    check(uint(c.numeric_id) && c.numeric_id < 24);
    check(c.name === null || token(c.name,128));
    if (c.name_status === "verified") { check(c.name !== null); ref(c.name_evidence); }
    else if (c.name_status === "provisional") check(c.name_evidence === null);
    else { check(c.name_status === "unavailable" && c.name === null && c.name_evidence === null); }
  }
  if (r.calibrated_confidence !== null) check(Number.isFinite(r.calibrated_confidence) && r.calibrated_confidence >= 0 && r.calibrated_confidence <= 1);
  if (r.decision_references !== null) {
    object(r.decision_references, ["calibration", "rejection", "admission"]);
    Object.values(r.decision_references).forEach(ref);
  }
  check((r.calibration_status === "frozen") === (r.decision_references !== null));
  if (["classified", "rejected"].includes(r.status)) {
    check(r.identity !== null && r.source !== null && r.quality !== null && r.timing !== null && r.decision_references !== null);
    if (r.status === "classified") check(r.class !== null && r.calibrated_confidence !== null && r.reason === null && r.quality.healthy && !r.quality.overflow && r.quality.clipped_samples === 0 && r.quality.dropped_samples === 0);
    else check(r.class === null && r.reason !== null);
  } else check(r.class === null && r.calibrated_confidence === null && r.decision_references === null && r.reason !== null);
}
