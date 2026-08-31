import assert from "node:assert/strict";
import test from "node:test";
import { RunLease } from "../src/run-lease.mjs";

test("allows one inference owner at a time", () => {
  const lease = new RunLease();
  const release = lease.acquire("planner");
  assert.equal(typeof release, "function");
  assert.deepEqual(lease.state(), { busy: true, owner: "planner" });
  assert.equal(lease.acquire("session"), undefined);
  release();
  assert.deepEqual(lease.state(), { busy: false, owner: undefined });
  assert.equal(typeof lease.acquire("session"), "function");
});

test("release is idempotent", () => {
  const lease = new RunLease();
  const release = lease.acquire("planner");
  release();
  release();
  assert.equal(lease.state().busy, false);
});
