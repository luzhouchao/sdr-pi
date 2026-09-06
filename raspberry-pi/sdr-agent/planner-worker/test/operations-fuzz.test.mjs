import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdirSync, rmSync, readFileSync } from 'node:fs';
import { connect } from 'node:net';
import { once } from 'node:events';
import test from 'node:test';
import { parseRequest } from '../src/protocol.mjs';
import { parseSessionCommand } from '../src/session-protocol.mjs';
import { startSessionServer } from '../src/session-server.mjs';

function corpus(base) {
  let seed = 20260906;
  return Array.from({ length: 256 }, (_, index) => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    const position = seed % base.length;
    switch (index % 4) {
      case 0: return base.slice(0, position);
      case 1: return base.slice(0, position) + '\0' + base.slice(position + 1);
      case 2: return base + '\n{}';
      default: return base.slice(0, position) + String.fromCharCode(seed % 128) + base.slice(position + 1);
    }
  });
}

test('O1a fixed-seed Planner and session parser mutation corpus', () => {
  const base = readFileSync(new URL('../../../../jetson-agx/sdrharness/config/request.json', import.meta.url), 'utf8');
  // Use the tracked PlanningContext and a read-only session command; no provider/executor.
  for (const [name, parser, seed] of [
    ['planner', parseRequest, base],
    ['session', parseSessionCommand, '{"protocol_version":1,"command_id":1,"session_generation":1,"type":"get_state"}'],
  ]) {
    const inputs = corpus(seed);
    assert.deepEqual(inputs, corpus(seed));
    let accepted = 0;
    for (const input of inputs) {
      let result;
      try { result = parser(input); }
      catch (error) { assert(error instanceof Error); continue; }
      assert.equal(result.protocol_version, 1); accepted += 1;
    }
    console.log(JSON.stringify({ o1a_fuzz: name, seed: 20260906, cases: inputs.length, accepted, sha256: createHash('sha256').update(JSON.stringify(inputs)).digest('hex') }));
  }
});

async function serve(context, options = {}) {
  const root = `/run/user/${process.getuid()}/sdr-agent`;
  mkdirSync(root, { recursive: true, mode: 0o700 });
  const socketPath = `${root}/o1a-${process.pid}-${Math.random().toString(16).slice(2)}.sock`;
  let dispatched = 0;
  const server = startSessionServer({ socketPath, frameTimeoutMs: 60, maxPendingFrames: 4,
    createRuntime: () => ({ async dispatch(command) { dispatched += 1; return { success: true, command_id: command.command_id }; }, async dispose() {} }), ...options });
  await once(server, 'listening');
  context.after(async () => { await new Promise(resolve => server.close(resolve)); rmSync(socketPath, { force: true }); });
  async function send(chunks) {
    const socket = connect(socketPath); socket.on('error', () => {});
    await once(socket, 'connect');
    let received = ''; socket.on('data', b => { received += b.toString(); });
    const closed = once(socket, 'close');
    for (const chunk of chunks) socket.write(chunk);
    await closed;
    await new Promise(resolve => setTimeout(resolve, 20));
    return received;
  }
  return { send, count: () => dispatched };
}

test('O1a partial session frame expires and releases ownership', async context => {
  const s = await serve(context);
  assert.match(await s.send(['{"protocol_version":']), /partial frame deadline/);
  assert.match(await s.send(['x'.repeat(32770)]), /exceeds 32 KiB/);
  assert.equal(s.count(), 0);
});

test('O1a session frame flood is bounded before dispatch', async context => {
  const s = await serve(context);
  const frame = '{"protocol_version":1,"command_id":1,"session_generation":1,"type":"get_state"}\n';
  assert.match(await s.send([frame.repeat(100)]), /pending frame limit/);
  assert.equal(s.count(), 0);
});

test('O1a session rejects oversized remainder following a complete frame', async context => {
  const s = await serve(context);
  assert.match(await s.send(['{}\n' + 'x'.repeat(32770)]), /exceeds 32 KiB/);
  assert.equal(s.count(), 0);
});
