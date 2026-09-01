import assert from "node:assert/strict";
import test from "node:test";
import { validateRuntimeSocketPath } from "../src/runtime-path.mjs";

test("accepts only direct children of dedicated system runtime directories", () => {
  assert.doesNotThrow(() => validateRuntimeSocketPath("/run/sdr-agent/planner.sock"));
  assert.doesNotThrow(() => validateRuntimeSocketPath("/run/sdrharness/session.sock"));
  assert.throws(
    () => validateRuntimeSocketPath("/run/sdrharness/../planner.sock"),
    /directly under/u,
  );
  assert.throws(() => validateRuntimeSocketPath("/run/other/planner.sock"), /directly under/u);
});

test("accepts the current user's dedicated development runtime", () => {
  const uid = process.getuid?.();
  if (uid === undefined) return;
  assert.doesNotThrow(() =>
    validateRuntimeSocketPath(`/run/user/${uid}/sdr-agent/planner.sock`),
  );
  assert.doesNotThrow(() =>
    validateRuntimeSocketPath(`/run/user/${uid}/sdrharness/session.sock`),
  );
});
